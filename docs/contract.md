# Baseline interface contract

What an adopting repo can rely on. File ownership (template-owned vs seeded-once) is defined in
[`MANIFEST.toml`](../MANIFEST.toml); `task baseline:check` enforces it. Never hand-edit a
template-owned file: change `ocx-sh/conventions` and run `task copier:update`.

## Answers (`copier.yml`)

| Answer | Type | Notes |
|---|---|---|
| `repo_name` | str | required |
| `profile` | `full` \| `mirror` | `mirror` ignores every answer below |
| `bazel` | bool, default false | full only |
| `languages` | multiselect: bazel, cmake, dotnet, go, jvm, nix, python, rust, shell, swift, typescript | full only; unknown entry fails naming the allowed list |
| `site` | null or `{dir, dist, deploy: bool, path?}` | full only; `path` optional, may be empty |
| `deep_os` | subset of `ubuntu-latest, macos-latest, windows-latest`; default `[ubuntu-latest]` | full only |
| `theme_bundle` | bool, default `site is not none` | full only |

The template uses no `_tasks`, `_migrations` or `_jinja_extensions`: `--trust` is never needed.

## Tasks (`taskfiles/baseline.taskfile.yml`, included flat from the root `taskfile.yml`)

| Task | Behaviour |
|---|---|
| `setup` | `ocx pull` all groups, `grim install`, then `hooks:install`. Idempotent (`status:`-guarded). |
| `hooks:install` | `prek install` for `pre-commit` and `commit-msg`. Idempotent. |
| `lock:check` | `ocx lock --check` plus `grim:check`. |
| `grim:check` | Runs `grim install`, which fails when `grimoire.lock` is missing or stale against `grimoire.toml`; then fails when any committed grim output (client dirs, `.claude/settings.json`, `opencode.json`) differs from what it installed, or when `clients` lacks claude/codex/opencode. A newer upstream digest for a floating tag is not a failure. Installed skills and rules are committed so every agent sees them on a fresh clone; a template-owned `.gitattributes` in each client dir marks them `linguist-generated`. |
| `secrets` | gitleaks over the repo; exit 1 on a finding. |
| `baseline:check` | Re-renders the recorded `_commit` with the recorded answers into a temp dir and diffs the template-owned paths; also checks the ocx.toml, grimoire.toml, root-task, Bazel and pnpm rules below. |
| `release:prepare` | See below. |
| `copier:update` | Wrapper around `uvx --from copier==<COPIER_VERSION> copier update`; extra args pass through (`-- --vcs-ref v0.1.0`). |

The repo-owned root `taskfile.yml` must define `verify`, `ci:lint`, `ci:test`, `ci:build`,
`ci:docs`, `ci:deep`; a missing one fails `baseline:check` naming it. `ci:test` and `ci:deep`
write JUnit XML under `target/reports/junit/`. The `docs` job uploads whatever `ci:docs` leaves under
`target/reports/` as the artifact `docs-reports`, also on failure; follow-up workflows read it by that name. Repo-owned optional hooks: `hooks:pre-commit`
(called by the prek config when defined), `release:bump-files` (called by `release:prepare`).

### `release:prepare`

Inputs: `BUMP` (`auto|patch|minor|major`) or `VERSION=x.y.z`. With a TTY, `task --interactive`
offers the menu; without one, a missing var exits non-zero with the usage line.

- Refuses (exit 1, prints the run URL) when the latest completed `verify-deep` run on the default
  branch (event `schedule` or `workflow_dispatch`) is not `success`.
- Refuses with `no verify-deep run on <branch> yet — dispatch one` when none exists.
- Refuses when `gh` is unauthenticated.
- Otherwise writes `CHANGELOG.md` via git-cliff `--tag v<next>` and runs `verify`. Never tags, never pushes.

## `ocx.toml` and `grimoire.toml`

- Every tool ref is an exact `X.Y.Z` (no `latest`, no major/minor-only tag); `ocx.lock` is tracked and current.
- `[tools]` (default) holds `task` only. Groups: `lint`, `test`, `build`, `docs`, `release`.
  Baseline tools: task, prek, gitleaks, grim, uv (`lint`), git-cliff (`release`).
- `grimoire.toml`: `clients` contains claude, codex, opencode; bundles contain `docs-essentials`,
  `code-docs-essentials`, one `<lang>-essentials` per `languages` entry, and `ocx-theme` when `theme_bundle`.
- With a site: `ci:docs` runs the repo's Lighthouse gate. `packageManager` (pnpm) is allowed only when equal to the ocx pnpm pin.

## Hooks (`.pre-commit-config.yaml`)

`default_install_hook_types: [pre-commit, commit-msg]`. Local hooks: `gitleaks git --staged --redact`
(pre-commit); conventional-commit subject check (commit-msg; types `feat fix docs style refactor perf
test build ci chore revert`, optional scope, optional `!`; anything else exits 1 naming the types);
`task hooks:pre-commit` when the repo defines it. `.gitleaks.toml` extends the defaults
(`useDefault = true`); add path/regex allowlists there.

## Workflows (template-owned)

All: top-level `permissions: {}`, every `uses:` a 40-hex SHA with `# vX`, checkout with
`persist-credentials: false`, no path filters. The setup action is referenced as
`ocx-sh/conventions/.github/actions/setup@<conventions commit>` and moves with the baseline version.

**`verify-basic.yml`** — triggers `pull_request`, `push: main`, `merge_group`, `workflow_dispatch`.

| Job | Runs | Present |
|---|---|---|
| `lint` | setup (`groups: default,lint`) → `task ci:lint`, `task lock:check`, `task baseline:check`, `task secrets`, actionlint, zizmor | always |
| `test` | setup (`default,test`) → `task ci:test`; JUnit to job summary + check annotations (fork-safe `annotate_only`) | full |
| `build` | setup (`default,build`) → `task ci:build`; org secrets, write credential only on a push to `main`, else the read credential | `bazel` |
| `docs` | setup (`default,docs`) → `task ci:docs` | `site` |
| `basic-gate` | `if: always()`; fails unless every needed job succeeded or was skipped by answer. The single required check. | always |

The mirror profile renders `lint` and `basic-gate` only.

No job uses a GitHub environment for cache or telemetry credentials: `BAZEL_CACHE_READ_AUTH`,
`BAZEL_CACHE_WRITE_AUTH` and `OTEL_OTLP_AUTH` are org secrets. The `build` job passes the write
credential only on `github.event_name == 'push' && github.ref == 'refs/heads/main'` and the read
credential everywhere else; OTel export happens only when `OTEL_OTLP_AUTH` is non-empty, so fork PRs
and runs without the secrets stay green. (The `renovate` and `ocx.sh` environments are separate.)

**`verify-deep.yml`** (full) — triggers `schedule` (daily 03:MM UTC, `MM = int(sha256(repo_name)[:4], 16) % 60`),
`workflow_dispatch`, `workflow_call`, and `pull_request: types: [labeled]` gated on label `run-deep`.
Matrix over `deep_os`, runs `task ci:deep` (Bazel repos: `--config=ci` plus `test:deep`). A failed
scheduled run opens or updates one issue labelled `nightly-red` (`issues: write` on that job only);
the next green scheduled run closes it.

**`claude.yml`** (full) — PR review on `pull_request` (opened, synchronize, ready_for_review) plus an
`@claude` responder; secret `CLAUDE_CODE_OAUTH_TOKEN`. Every job skips (green) when the secret is
empty or the PR is from a fork. The responder passes `github_token: ${{ github.token }}` (no OIDC exchange for the
write-capable Claude App token) and an explicit `--allowedTools` allowlist (`gh pr view|diff|comment`, inline comment).

**`deploy-site.yml`** (when `site.deploy`) — triggers `push: main` (site paths) and `workflow_dispatch`
only, environment `ocx.sh`, uses the pinned `ocx-sh/website/.github/actions/deploy` with inputs
`dist` and optional `path` from `site`, secret `BUNNY_STORAGE_KEY`. Never runs on `pull_request`.

## Setup action (`.github/actions/setup`, composite)

| Input | Meaning |
|---|---|
| `groups` | ocx groups to install, e.g. `default,lint` |
| `bazel-cache` | `off` (default) \| `read` \| `write`; write only on `push: main` |
| `cache-read-auth`, `cache-write-auth`, `otel-auth` | secrets passed by the caller |

Installs ocx through setup-ocx (pinned SHA, baseline ocx CLI version, `groups`). When `bazel-cache`
is not `off` and the auth is non-empty it writes `$RUNNER_TEMP/bazel-cache.rc` with `--remote_header`
and exports the `BAZELRC` import; when `otel-auth` is non-empty it exports
`OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.ocx.sh` plus headers. Empty secrets (fork PRs) degrade to no
cache / no telemetry and never fail. A warning-only `if: always()` post step ships test telemetry.

## Bazel fragment (`bazel/baseline.bazelrc`, when `bazel`)

The seeded `.bazelrc` starts with `import %workspace%/bazel/baseline.bazelrc`. The fragment sets:

```
build --remote_cache=https://bazel-cache.ocx.sh/v1
build --remote_upload_local_results=false
build --remote_timeout=30s
build --remote_retries=2
build:ci --remote_download_minimal
build:ci --remote_download_regex=.*/test\.(xml|log)$
build:ci --jobs=auto
test:basic --test_size_filters=small,medium --test_tag_filters=-deep
test:deep            # all sizes
try-import %workspace%/.bazelrc.user
```

`baseline:check` requires an exact-version `bazel_dep(name = "rules_ocx", …)` in `MODULE.bazel` (or
that the module is rules_ocx) and rejects any `http_archive`/`http_file` for a tool the ocx tool map
(`scripts/groups.toml`) already covers. `ci:test` copies JUnit from `bazel-testlogs` to
`target/reports/junit/`.

## Renovate presets

Rendered `renovate.json` extends `github>ocx-sh/conventions//renovate/default#<tag>` (`mirror` profile:
`…//renovate/mirror#<tag>`).

- `default`: `config:recommended`, weekly schedule, semantic commits (`ci(deps)` / `chore(deps)`),
  `helpers:pinGitHubActionDigests`, `minimumReleaseAge: "7 days"`, `ocx-sh/conventions` action refs ignored (they move with copier),
  copier manager on, `ocx.toml` regex manager (datasource `docker`, versioning
  `regex:^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)$`, `postUpgradeTasks: ["ocx lock"]`),
  `bazel-module` manager for `rules_ocx` (`postUpgradeTasks: ["bazel mod deps"]`), pypi regex manager
  for `COPIER_VERSION` / `ZIZMOR_VERSION` (matches only `template/taskfiles/baseline.taskfile.yml` in conventions itself; adopted repos get new pins through `copier update`), and the `ocx-sh/website` deploy action grouped with `@ocx-sh/theme`.
- `mirror`: `default` minus the npm and Bazel groups.

Renovate runs self-hosted from `ocx-sh/conventions` (`renovate.yml`, schedule + dispatch, GitHub App
token, `RENOVATE_REPOSITORIES` = adopted repos in `fleet.toml`; the job runs in environment `renovate`, which holds `RENOVATE_APP_ID` / `RENOVATE_APP_KEY`); remove an adopted repo from the hosted
Renovate app so PRs do not double.
