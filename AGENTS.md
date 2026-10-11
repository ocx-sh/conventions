# conventions

The OCX fleet baseline: a copier template (`full` and `mirror` profiles), shared Renovate presets, a composite setup action and a drift checker over `fleet.toml`. Maintainers of `ocx-sh` repositories adopt and update from it.

## Purpose

Own the tool, task, workflow and preset interface adopting repos rely on (`docs/contract.md`). Out of scope: any repo's product code.

## Setup

```sh
ocx exec -- task setup
```

Pulls every tool from `ocx.toml`, installs the grim client directories and arms the git hooks. Re-running it is a no-op.

## Verify

```sh
ocx exec -- task verify
```

The same gate CI runs. `ci:lint`, `ci:test` and `ci:deep` run the pytest self-tests (`-m slow` renders fixtures and needs network); `ci:build` and `ci:docs` are no-ops.

## Layout

- `template/`, `copier.yml`, `MANIFEST.toml`: the template and its ownership classes
- `renovate/`, `.github/actions/setup`: shared presets and the setup action
- `drift/`, `fleet.toml`, `scripts/`: fleet tracking, `adopt.sh`, `baseline_check.py`
- `skills/`, `rules/`: grim-published AI config
- `tests/`: pytest self-tests (`slow` tier renders fixtures into `target/selftest/`)

## Baseline

This repo follows the [ocx-sh/conventions](https://github.com/ocx-sh/conventions) baseline, rendered by copier (`.copier-answers.yml`).
Template-owned files (`taskfiles/baseline.taskfile.yml`, `.pre-commit-config.yaml`, `cliff.toml`, `renovate.json`, `CLAUDE.md`, `.github/workflows/verify-*.yml`, ...) must never be hand-edited: change ocx-sh/conventions, then run `ocx exec -- task copier:update`. `task baseline:check` fails on drift.
