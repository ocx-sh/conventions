# conventions

The OCX project baseline for `ocx-sh` repositories: a [copier](https://copier.readthedocs.io) template that gives
every repo the same tools (`ocx.toml`), AI config (`grimoire.toml`), tasks, CI workflows, git hooks and
Renovate preset, plus a drift checker that tracks the fleet (`fleet.toml`, daily status page).

This repo is rendered from its own template (`full`, languages python + shell), so `task verify` here
exercises the baseline end to end.

## Bootstrap

```sh
ocx exec -- task setup    # pulls every tool, installs grim client files, arms git hooks (idempotent)
ocx exec -- task verify   # the gate CI runs
```

`ocx` missing: install it with `ocx self setup` (see the ocx docs).

## Adopt

Existing repo listed in `fleet.toml` (stages changes, never commits; needs a clean tree):

```sh
scripts/adopt.sh <repo-dir> <fleet-key>
```

New repo:

```sh
uvx --from copier==9.18.2 copier copy gh:ocx-sh/conventions <dir>
```

## Update

```sh
ocx exec -- task copier:update -- --vcs-ref <tag>
```

`task baseline:check` fails when a template-owned file was hand-edited or the ocx.toml, grimoire.toml
or root-task contract is broken.

## Profiles

- `full`: tools, tasks, hooks, `verify-basic` and `verify-deep` workflows, Claude workflow, optional Bazel and site.
- `mirror`: the subset for mirror repos (tools, hooks, Renovate preset, lock checks); verify runs `ci:lint` only.

## Ownership

[`MANIFEST.toml`](MANIFEST.toml) classifies every rendered path:

- template-owned: rewritten on each update. Change this repo, never the copy.
- seeded-once: written on first copy (`taskfile.yml`, `ocx.toml`, `grimoire.toml`, `AGENTS.md`, `.gitleaks.toml`); the adopting repo owns it afterwards.

The task, workflow and preset interface adopters rely on is in [`docs/contract.md`](docs/contract.md).

## Layout

`template/` and `copier.yml` (the template), `renovate/` (shared presets and the self-hosted runner),
`.github/actions/setup` (composite setup action), `drift/` (checker), `scripts/` (`adopt.sh`,
`baseline_check.py`), `skills/` and `rules/` (grim-published AI config), `tests/` (pytest self-tests; `-m slow` renders fixtures).

## Owner acts

- Renovate: create the Renovate GitHub App, install it on the fleet repos, create an environment `renovate` here (deployment branches: `main` only) and set `RENOVATE_APP_ID` and `RENOVATE_APP_KEY` as its secrets, not as repo secrets.
- Org secrets: set `BAZEL_CACHE_READ_AUTH`, `BAZEL_CACHE_WRITE_AUTH`, `OTEL_OTLP_AUTH` and `CLAUDE_CODE_OAUTH_TOKEN` at org level (no `ci` / `ci-write` environments); the template passes the write credential only on a push to `main`.
- Pages: enable GitHub Pages (source: GitHub Actions) so `status.yml` can publish the drift status page.
- Tag `v0.1.0` and push: adopters pin template and setup action by commit, and `release:prepare` never tags or pushes.
