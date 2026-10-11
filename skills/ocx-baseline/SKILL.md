---
name: ocx-baseline
description: Adopt, modernize or audit a repo against the OCX project baseline (ocx-sh/conventions copier template). Use when asked to adopt the baseline, bring a repo up to the OCX standard, set up ocx/taskfile/prek/CI conventions, update or upgrade the baseline (copier update), explain what a baseline version changed, or check or audit baseline drift in a repo.
license: Apache-2.0
metadata:
  summary: Adopt, modernize or audit a repo against the OCX baseline
  keywords: ocx,baseline,copier,adopt,modernize,audit
  repository: https://github.com/ocx-sh/conventions
  authors: ocx-sh
---

# OCX baseline

Pick the mode by whether `.copier-answers.yml` exists: absent -> **adopt**; present -> **modernize** or **audit**. Never hand-edit template-owned files; change `ocx-sh/conventions` instead (ownership table: the `ocx-baseline` rule). Run tool commands as `ocx exec -- <cmd>`; write files under `.github/`, `.claude/`, `.codex/`, `.opencode/` through Bash (copier, grim, git), not file-edit tools.

## adopt

1. Work from a clean branch in the target repo; have a clone of `ocx-sh/conventions` (`$CONV`).
2. Choose answers: use the repo's entry in `$CONV/fleet.toml` when present; otherwise inspect the repo (profile `mirror` for upstream mirrors, else `full`; `bazel` if `MODULE.bazel`/`WORKSPACE` exists; `languages` from the lore bundle names; `site` if it ships a docs site; `deep_os` from the current CI matrix) and add a `fleet.toml` entry.
3. `bash $CONV/scripts/adopt.sh <dest> <key>` - renders the template, renames `Taskfile.yml`, removes Dependabot, rewrites `_src_path`.
4. `python3 $CONV/scripts/pin-exact.py <dest>/ocx.toml` - exact pins, D-04 groups, then `ocx lock`.
5. Work through [references/adoption-checklist.md](references/adoption-checklist.md) and hand the user the per-repo delta checklist (what you did, what is left, what needs a decision). Prefer the strongest in-fleet example: [references/best-in-fleet.md](references/best-in-fleet.md).
6. Done when `task setup` and `task verify` are green and `task baseline:check` passes.

## modernize

1. `task copier:update -- --vcs-ref <latest tag>` (latest: `gh release list -R ocx-sh/conventions` or `git ls-remote --tags`). Resolve conflicts in seeded-once files by hand; never in template-owned ones - rerun the update. Then `python3 $CONV/scripts/untrack_grim.py` untracks grim client output; move each repo-owned skill or rule it lists to `agent-config/` and `grim add` it.
2. Read `CHANGELOG.md` of `ocx-sh/conventions` for every version crossed; tell the user what each version changed and why, in one line each.
3. Add the conventions grim bundle to `grimoire.toml` when the owner has published it and it is missing (status flag `bundle-missing`); then `task setup`, `task lock:check`, `task verify`.

## audit

1. `task baseline:check` - structural and ownership findings; each line names the file, tool or task.
2. Drift flags for this repo: in a conventions clone run `python3 drift/check.py --out status.json` (needs `gh`) and read the row for this repo key. Classes: `baseline-behind`, `not-adopted`, `stale-pin`, `setup-ocx-stale`, `ocx-cli-stale`, `pending-updates`, `nightly-red`, `bundle-missing`, `grim-pending`.
3. Report findings with the fix for each; apply only when asked.

## New tools

A tool the repo needs is first packaged via ocx-contrib and pinned in `ocx.toml`. `uvx`/`npx` only as a recorded interim with a comment naming the ocx-contrib issue.
