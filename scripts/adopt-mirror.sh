#!/usr/bin/env bash
# adopt-mirror.sh <mirror-dir> — one-shot adoption of the OCX baseline (profile mirror) in an ocx-contrib mirror repo.
# Sequence: clean+main+synced check -> adopt.sh at latest tag -> relock keeping the pre-adoption cli/mirror pins ->
# task setup -> gates -> generate ci --check for EVERY spec -> commit -> push main -> protect-main ruleset.
# Run it from an up-to-date checkout of conventions origin/main, never from a stale feature branch:
#   git -C <worktree> fetch -q && git -C <worktree> checkout -q --detach origin/main && <worktree>/scripts/adopt-mirror.sh <dir>
# Env: CONVENTIONS_REF / CONVENTIONS_SRC / FLEET_TOML pass through to adopt.sh.
# Exit: 0 adopted (or already adopted), 1 failed (tree restored if nothing was pushed), 2 usage.
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: adopt-mirror.sh <mirror-dir>" >&2; exit 2; }
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
dest=$(cd "$1" && pwd)
key=$(basename "$dest")
pushed=0 orig=""

rollback() {
  [ "$pushed" = 0 ] && [ -n "$orig" ] && [ -z "${ADOPT_MIRROR_KEEP:-}" ] || return 0  # KEEP=1 leaves the failed tree for debugging
  # Tree was clean at start, so every untracked non-ignored path is adopt's; ignored state (.ocx) is untouched.
  git -C "$dest" reset -q --hard "$orig" && git -C "$dest" clean -qfd
}
fail() { echo "adopt-mirror: $key: $*" >&2; rollback; exit 1; }
trap 'fail "unexpected failure at line $LINENO"' ERR

cd "$dest"
git rev-parse --git-dir >/dev/null 2>&1 || { echo "adopt-mirror: $dest is not a git repository" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "adopt-mirror: $key: working tree is dirty" >&2; exit 1; }
[ "$(git branch --show-current)" = main ] || { echo "adopt-mirror: $key: not on main" >&2; exit 1; }
git pull -q --ff-only origin main || { echo "adopt-mirror: $key: git pull --ff-only failed" >&2; exit 1; }
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "adopt-mirror: $key: main is ahead of origin/main" >&2; exit 1; }
[ ! -f .copier-answers.yml ] || { echo "adopt-mirror: $key: already adopted; nothing to do"; exit 0; }
orig=$(git rev-parse HEAD)
repo=$(git remote get-url origin | sed -E 's#.*github\.com[:/]##; s#\.git$##')
specs=(*/mirror.yml)
[ -e "${specs[0]}" ] || fail "no */mirror.yml spec found"
# allow_manual_edits specs carry a deliberately hand-edited workflow, so --check always drifts on them
spec_args=(); for s in "${specs[@]}"; do grep -qx 'allow_manual_edits: true' "$s" || spec_args+=(--spec "$s"); done

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cp ocx.lock "$tmp/ocx.lock.orig" || fail "no ocx.lock"

"$root/scripts/adopt.sh" "$dest" "$key" >"$tmp/adopt.log" 2>&1 || fail "adopt.sh failed: $(tail -n1 "$tmp/adopt.log")"

# `ocx lock` re-resolves the floating :0.6 toolchain; keep the digests the mirror ran on, so generate ci stays stable.
ocx lock --no-pull >"$tmp/lock.log" 2>&1 || fail "ocx lock failed: $(tail -n1 "$tmp/lock.log")"
python3 - "$tmp/ocx.lock.orig" ocx.lock <<'PY' || fail "could not splice the old cli/mirror lock pins"
import re, sys, tomllib
split = lambda t: re.split(r"(?m)^(?=\[\[tool\]\]$)", t)
old = {(b["name"], b["group"]): blk for blk in split(open(sys.argv[1]).read())[1:] for b in [tomllib.loads(blk)["tool"][0]]}
parts = split(open(sys.argv[2]).read())
out = [parts[0]]
for blk in parts[1:]:
    t = tomllib.loads(blk)["tool"][0]
    keep = old.get((t["name"], t["group"])) if t["group"] == "default" and t["name"] in ("cli", "mirror") else None
    out.append((keep or blk).rstrip("\n") + "\n\n")
text = "".join(out).rstrip("\n") + "\n"
tomllib.loads(text)
open(sys.argv[2], "w").write(text)
PY
grep -qx 'lock_version = 3' ocx.lock || fail "lock_version is not 3"
ocx lock --check >/dev/null 2>&1 || fail "ocx lock --check failed after splice"
ocx pull >"$tmp/pull.log" 2>&1 || fail "ocx pull failed: $(tail -n1 "$tmp/pull.log")"

ocx exec -- task setup >"$tmp/setup.log" 2>&1 || fail "task setup failed: $(tail -n1 "$tmp/setup.log")"
git add -A  # grim:check reads untracked client files as drift; staged is fine
for g in lock:check baseline:check secrets workflows:lint; do
  ocx exec -- task "$g" >"$tmp/gate.log" 2>&1 || fail "gate $g failed: $(tail -n1 "$tmp/gate.log")"
done
[ ${#spec_args[@]} -eq 0 ] || ocx exec -- ocx-mirror package pipeline generate ci --check "${spec_args[@]}" >"$tmp/gen.log" 2>&1 \
  || fail "generate ci --check drifts: $(tail -n1 "$tmp/gen.log")"

ref=$(sed -n 's/^_commit: *//p' .copier-answers.yml)
git commit -q -m "chore: adopt ocx-sh/conventions baseline $ref" >"$tmp/commit.log" 2>&1 || fail "commit failed: $(tail -n1 "$tmp/commit.log")"
git push -q origin main >"$tmp/push.log" 2>&1 || fail "push failed: $(tail -n1 "$tmp/push.log")"
pushed=1

if env -u GITHUB_TOKEN gh api "repos/$repo/rulesets" --jq '.[].name' | grep -qx protect-main; then
  echo "adopt-mirror: $key: ruleset protect-main already present"
else
  env -u GITHUB_TOKEN gh api -X POST "repos/$repo/rulesets" --input "$root/scripts/mirror-ruleset.json" >/dev/null \
    || { echo "adopt-mirror: $key: pushed, but applying the ruleset failed" >&2; exit 1; }
fi
echo "adopt-mirror: $key: adopted at $ref, pushed $(git rev-parse --short HEAD)"
