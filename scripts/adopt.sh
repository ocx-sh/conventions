#!/usr/bin/env bash
# adopt.sh <dest> <fleet-key> — adopt the OCX baseline (C-024). Stages changes in <dest>, never commits.
# Env: CONVENTIONS_SRC (template path/URL), CONVENTIONS_REF (default: latest v* tag), FLEET_TOML (answers).
# Exit: 0 ok / already adopted at this ref, 1 refused or failed, 2 usage.
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: adopt.sh <dest> <fleet-key>" >&2; exit 2; }
dest=$1 key=$2
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
src=${CONVENTIONS_SRC:-https://github.com/ocx-sh/conventions.git}
fleet=${FLEET_TOML:-$root/fleet.toml}
upstream=https://github.com/ocx-sh/conventions.git

die() { echo "adopt: $*" >&2; exit 1; }

git -C "$dest" rev-parse --git-dir >/dev/null 2>&1 || die "$dest is not a git repository"
[ -z "$(git -C "$dest" status --porcelain)" ] || die "$dest has uncommitted changes; commit or stash first"

ref=${CONVENTIONS_REF:-$(git ls-remote --tags --refs --sort=-v:refname "$src" 'v*' | sed -n '1s|.*refs/tags/||p')}
[ -n "$ref" ] || die "no v* tag found in $src; set CONVENTIONS_REF"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$fleet" "$key" >"$tmp/data.json" <<'PY' || die "fleet key '$key' not found (or unreadable) in $fleet"
import json, sys, tomllib
with open(sys.argv[1], "rb") as f:
    r = tomllib.load(f)["repos"][sys.argv[2]]
    print(json.dumps({"repo_owner": r["repo"].split("/")[0], **r["answers"]}))
PY

cd "$dest"
if [ -f .copier-answers.yml ]; then
  rec=$(sed -n 's/^_commit: *//p' .copier-answers.yml)
  if [ "$rec" != "$ref" ]; then
    # copier records `git describe` output, so compare resolved commits, not strings.
    git clone -q --no-checkout "$src" "$tmp/src" 2>/dev/null || die "cannot clone $src to compare $rec with $ref"
    a=$(git -C "$tmp/src" rev-parse -q --verify "$rec^{commit}" 2>/dev/null || true)
    b=$(git -C "$tmp/src" rev-parse -q --verify "$ref^{commit}" 2>/dev/null || git -C "$tmp/src" rev-parse -q --verify "origin/$ref^{commit}" 2>/dev/null || true)
    { [ -n "$a" ] && [ "$a" = "$b" ]; } || die "already adopted at a different ref; use 'copier update' to move to $ref"
  fi
  echo "adopt: $dest already adopted at $ref; nothing to do"
  exit 0
fi

# Seeds skip existing files, so the rename and the AGENTS.md move must precede copier.
if git ls-files --error-unmatch Taskfile.yml >/dev/null 2>&1; then git mv Taskfile.yml taskfile.yml; fi
# CLAUDE.md with any content other than exactly `@AGENTS.md` carries real guidance (even one line): move it to
# AGENTS.md, or append it to the existing one. A pointer line is stripped first so AGENTS.md never imports itself.
if [ -f CLAUDE.md ] && [ ! -L CLAUDE.md ]; then
  body=$(grep -vxE '[[:space:]]*@AGENTS\.md[[:space:]]*' CLAUDE.md || true)
  if [ -n "$(printf %s "$body" | tr -d '[:space:]')" ]; then
    if [ -e AGENTS.md ]; then
      { printf '\n## Imported from CLAUDE.md\n\n'; printf '%s\n' "$body"; } >>AGENTS.md
    else
      git mv CLAUDE.md AGENTS.md
      printf '%s\n' "$body" >AGENTS.md
    fi
    git add AGENTS.md
  fi
fi

if command -v uvx >/dev/null 2>&1; then copier=(uvx --from copier==9.18.2 copier); else copier=(copier); fi
"${copier[@]}" copy --defaults --overwrite --vcs-ref "$ref" --data-file "$tmp/data.json" "$src" .

sed "s|^_src_path:.*|_src_path: $upstream|" .copier-answers.yml >"$tmp/answers" && cat "$tmp/answers" >.copier-answers.yml

paths=$(python3 - "$src/MANIFEST.toml" <<'PY'
import sys, tomllib
try:
    with open(sys.argv[1], "rb") as f:
        print("\n".join(tomllib.load(f)["removed_by_adoption"]["paths"]))
except OSError:
    print(".github/dependabot.yml")
PY
)
while IFS= read -r p; do
  # ls-files matches the index case-sensitively: the renamed taskfile.yml is not mistaken for Taskfile.yml.
  [ -z "$p" ] || [ -z "$(git ls-files -- "$p")" ] || git rm -q -- "$p"
done <<<"$paths"

# ocx.toml is seeded-once, so a repo that already has one lacks the baseline tools and groups (task, lint, release).
# Render a fresh copy and append what is missing; the repo's own pins (e.g. a mirror's `:0.6` toolchain) stay.
# The caller then runs `ocx lock` (relock, never delete the lock) and `task setup`.
if [ -f ocx.toml ] && git cat-file -e HEAD:ocx.toml 2>/dev/null; then
  "${copier[@]}" copy --defaults --overwrite --skip-tasks --vcs-ref "$ref" --data-file "$tmp/data.json" "$src" "$tmp/render" >/dev/null 2>&1 || true
  [ ! -f "$tmp/render/ocx.toml" ] || python3 - "$tmp/render/ocx.toml" ocx.toml <<'PY'
import re, sys, tomllib
want, have = (open(p).read() for p in sys.argv[1:3])
w, h = tomllib.loads(want), tomllib.loads(have)
def tools(d): return {("default", k): v for k, v in d.get("tools", {}).items()} | {(g, k): v for g, b in d.get("group", {}).items() for k, v in b.get("tools", {}).items()}
wt, ht = tools(w), tools(h)
out = have.rstrip("\n") + "\n"
for (g, k), v in wt.items():
    if (g, k) in ht: continue
    line = f'{k} = "{v}"\n'
    hdr = "[tools]" if g == "default" else f"[group.{g}.tools]"
    if re.search(rf"^{re.escape(hdr)}\s*$", out, re.M):
        out = re.sub(rf"^({re.escape(hdr)}\s*\n)", lambda m: m.group(1) + line, out, count=1, flags=re.M)
    else:
        out += f"\n{hdr}\n{line}"
open(sys.argv[2], "w").write(out)
PY
fi
