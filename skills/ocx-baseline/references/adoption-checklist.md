# Adoption checklist

Per-repo delta after `scripts/adopt.sh` and `scripts/pin-exact.py`. Copy, tick, and give the user the result with each open item.

## Wire (repo-owned `taskfile.yml`)
- [ ] `verify`, `ci:lint`, `ci:test`, `ci:build`, `ci:docs`, `ci:deep` exist (stub with an explicit `echo "n/a"` where a repo has no such stage; `baseline:check` only checks presence)
- [ ] `ci:test` and `ci:deep` write JUnit XML to `target/reports/junit/`
- [ ] repo-specific version-file edits go in an optional `release:bump-files` task
- [ ] old task names the repo's docs or CI used are aliased or updated

## Migrate CI
- [ ] existing lint/test/build jobs moved behind `ci:*` tasks and called from the template `verify-basic.yml` (do not edit that file)
- [ ] superseded workflows deleted (old verify/lint/test/ci workflows, Dependabot, hand-rolled setup steps); keep release/publish/deploy workflows untouched
- [ ] every remaining workflow action pinned by 40-hex SHA with a `# vX.Y.Z` comment; `task workflows:lint` clean

## Tools and hooks
- [ ] every tool the repo needs comes from `ocx.toml` at an exact version in the right group; `ocx.lock` committed; no other installer in CI
- [ ] a tool missing from the ocx index -> ocx-contrib issue + recorded `uvx`/`npx` interim, never a silent install step
- [ ] pnpm via ocx, no corepack; `packageManager` equals the ocx pin
- [ ] `.gitleaks.toml` allowlists reviewed; `task secrets` green; old hook managers removed

## grim
- [ ] `grimoire.toml` clients include claude, codex, opencode
- [ ] bundles: `docs-essentials`, `code-docs-essentials`, one `<lang>-essentials` per language, `ocx-theme` for sites; floating tags only as the lore convention allows
- [ ] `AGENTS.md` canonical, `CLAUDE.md` a pointer; `task grim:check` green
- [ ] `task setup` output committed (grim client dirs, `.claude/settings.json`, `opencode.json`); each hand-written skill or rule in a client dir moved to `agent-config/` and declared with `grim add ./agent-config/<name>`

## Bazel and sites (when answered)
- [ ] `MODULE.bazel` has an exact `bazel_dep(name = "rules_ocx", ...)`; ocx tools come through it, not `http_archive`
- [ ] `.bazelrc` imports `bazel/baseline.bazelrc`
- [ ] `ci:docs` runs the Lighthouse gate; site deploy uses the template workflow (no production deploy while adopting)

## Verify
- [ ] `task setup` green, `task verify` green, `task baseline:check` passes, `task lock:check` passes
- [ ] list what is left for the owner (decisions, secrets, repo settings, required checks) at the end of the report
