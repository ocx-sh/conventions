---
paths:
  - ".copier-answers.yml"
  - "taskfile.yml"
  - "taskfiles/**"
  - "ocx.toml"
  - "ocx.lock"
  - "grimoire.toml"
  - "renovate.json"
  - "cliff.toml"
  - ".pre-commit-config.yaml"
  - ".github/**"
  - "bazel/**"
  - "MODULE.bazel"
summary: OCX project baseline - target state, file ownership, task interface
keywords: ocx,baseline,copier,conventions,taskfile
repository: https://github.com/ocx-sh/conventions
---

# OCX project baseline

This repo follows the `ocx-sh/conventions` copier template; `.copier-answers.yml` records the baseline version. Adopt, upgrade or audit it with the `ocx-baseline` skill.

## Never hand-edit template-owned files

Change `ocx-sh/conventions`, release a tag, then run `task copier:update` (copier update) here. A local edit fails `task baseline:check` and is overwritten by the next update.

| Class | Files |
|---|---|
| template-owned | `taskfiles/baseline.taskfile.yml`, `.pre-commit-config.yaml`, `cliff.toml`, `renovate.json`, `CLAUDE.md`, `.github/zizmor.yml`, `.github/workflows/{verify-basic,verify-deep,claude,deploy-site}.yml`, `bazel/baseline.bazelrc`, `.gitignore` in `.claude/{skills,rules}`, `.opencode/{skills,rules}`, `.agents/skills` - each starts with an `ocx-baseline: template-owned file` banner |
| seeded-once | `taskfile.yml`, `ocx.toml`, `grimoire.toml`, `AGENTS.md`, `.gitleaks.toml`, `.bazelrc`, `MODULE.bazel` - repo-owned after the first copy |
| repo-owned | everything else; repo-owned skills and rules live in `agent-config/` as grim path sources, never in the gitignored client dirs |

## Target state

| Area | Rule |
|---|---|
| Distribution | copier only; `.copier-answers.yml` is the version marker; Renovate opens the update PRs |
| Tasks | lowercase `taskfile.yml`; run as `ocx exec -- task <name>` |
| Tools | ocx for every tool: exact pins, committed `ocx.lock`, groups by role (`lint`/`test`/`build`/`docs`/`release`); pnpm via ocx, no corepack |
| Hooks | prek (pre-commit, commit-msg) running linters and gitleaks; Renovate, never Dependabot |
| CI | `verify-basic` on PR/main, `verify-deep` nightly and as gate of `release:prepare`; every action pinned by SHA |
| Build | Bazel (full profile) uses `rules_ocx` for ocx-provided tools, `bazel-cache.ocx.sh`, telemetry to `otel.ocx.sh` |
| AI config | grim with claude, codex, opencode; AGENTS.md canonical, CLAUDE.md a pointer |
| Sites | `@ocx-sh/theme`, Lighthouse gate, shared Bunny deploy action |

## Task interface

Baseline tasks (template-owned): `setup`, `hooks:install`, `lock:check`, `grim:check`, `secrets`, `baseline:check`, `release:prepare` (inputs `BUMP` or `VERSION`; needs a green `verify-deep`), `copier:update`.

The repo-owned root `taskfile.yml` must define `verify`, `ci:lint`, `ci:test`, `ci:build`, `ci:docs`, `ci:deep`; `baseline:check` names a missing one. `ci:test` and `ci:deep` write JUnit XML to `target/reports/junit/`.

## New tools

A tool a repo needs is first packaged via ocx-contrib and added to `ocx.toml` at an exact version. `uvx`/`npx` only as a recorded interim: leave a comment naming the ocx-contrib issue.
