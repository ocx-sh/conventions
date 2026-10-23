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
| `deep_os` | subset of `ubuntu-latest, ubuntu-24.04-arm, macos-latest, macos-15-intel, macos-26, windows-latest, windows-11-arm`; default `[ubuntu-latest]` | full only |
| `theme_bundle` | bool, default `site is not none` | full only |
| `bazel_cache_write` | `main` (default) \| `trusted` | full with `bazel`; `trusted` makes every job that runs a `ci:*` task (lint, test, build, docs, deep) present the write secret on every event that carries it |
| `zizmor_ignore` | list of `.github/workflows/<name>.yml`, default `[]` | full only; workflows another tool generates (cargo-dist's `release.yml`): zizmor reports nothing for them. Hand-written workflows are fixed, not listed |
| `submodules` | bool, default false | full only; adds `submodules: recursive` to every checkout in `verify-basic` and `verify-deep`, for a repo that vendors git submodules (ocx, grimoire, ocx-mirror) |
| `repo_workflows` | `false` (default) or `{secrets: [NAME, ...]}`; names are letters, digits, underscores, not starting with a digit or `GITHUB_` | full only; adds the `repo` job to `verify-basic` and `verify-deep` and seeds `basic-repo.yml` and `deep-repo.yml` |

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
(called by the prek config when defined), `hooks:repo-commit-msg` (replaces the conventional-subject check),
`release:bump-files`, `release:gate`, `release:validate`, `release:verify` (called by `release:prepare`, below).

### `release:prepare`

Inputs: `BUMP` (`auto|patch|minor|major`) or `VERSION=x.y.z`. With a TTY, `task --interactive`
offers the menu; without one, a missing var exits non-zero with the usage line.

- Refuses (exit 1, prints the run URL) when the latest completed `verify-deep` run on the default
  branch (event `schedule` or `workflow_dispatch`) is not `success`.
- Refuses with `no verify-deep run on <branch> yet — dispatch one` when none exists.
- Refuses when `gh` is unauthenticated.
- Otherwise writes `CHANGELOG.md` via git-cliff `--tag v<next>` and runs `verify`. Never tags, never pushes.

Optional repo-owned hooks, each detected by name in `task --list-all`:

| Hook | Effect |
|---|---|
| `release:gate` | Replaces the verify-deep and `gh` checks above. A non-zero exit refuses the release before anything is written. |
| `release:bump-files` | Called with `VERSION=x.y.z` before git-cliff (version files). |
| `release:validate` | Called with `VERSION=x.y.z` after git-cliff wrote `CHANGELOG.md`; non-zero stops before `verify`. |
| `release:verify` | Replaces `verify` as the last step. |

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
`task hooks:pre-commit` when the repo defines it. A repo-owned `hooks:repo-commit-msg` task, when defined, judges the
commit message instead of the conventional check (it receives the message file as `{{.CLI_ARGS}}`); it is for a repo
whose subjects that check refuses or that gates a commit on more than its subject. `.gitleaks.toml` extends the defaults
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
| `repo` | `uses: ./.github/workflows/basic-repo.yml` with `permissions: contents: read` and each `repo_workflows.secrets` name mapped explicitly (never `secrets: inherit`) | `repo_workflows` |
| `basic-gate` | `if: always()`; fails unless every needed job succeeded or was skipped by answer. The single required check. | always |

The mirror profile renders `lint` and `basic-gate` only.

No job uses a GitHub environment for cache or telemetry credentials: `BAZEL_CACHE_READ_AUTH`,
`BAZEL_CACHE_WRITE_AUTH` and `OTEL_OTLP_AUTH` are org secrets. The `build` job passes the write
credential only on `github.event_name == 'push' && github.ref == 'refs/heads/main'` and the read
credential everywhere else; OTel export happens only when `OTEL_OTLP_AUTH` is non-empty, so fork PRs
and runs without the secrets stay green. (The `renovate` and `ocx.sh` environments are separate.)

With `bazel_cache_write = trusted`, `lint`, `test`, `build`, `docs` and the deep matrix instead call the setup action
with `bazel-cache: trusted` and `cache-write-auth: ${{ secrets.BAZEL_CACHE_WRITE_AUTH }}`, no event predicate and no read
credential (one credential per lane). The answer is the repo's statement that those jobs run no untrusted code with the
secret; a fork PR still carries no secret, so it reads uncached. Each such job ends with an `if: always()` step that removes
`$RUNNER_TEMP/bazel-cache-helper` and `$RUNNER_TEMP/bazel-cache.rc` (a composite action has no `post:` hook, and a self-hosted
runner keeps `$RUNNER_TEMP` between jobs).

Every checkout in `verify-basic.yml` and `verify-deep.yml` uses `persist-credentials: false`; with `submodules = true` it also uses
`submodules: recursive`, which a repo that vendors submodules (ocx, grimoire, ocx-mirror) needs to build anything.

**`verify-deep.yml`** (full) — triggers `schedule` (daily 03:MM UTC, `MM = int(sha256(repo_name)[:4], 16) % 60`),
`workflow_dispatch`, `workflow_call`, and `pull_request: types: [labeled]` gated on label `run-deep`.
Matrix over `deep_os`, runs `task ci:deep` (Bazel repos: `--config=ci` plus `test:deep`). A failed
scheduled run opens or updates one issue labelled `nightly-red` (`issues: write` on that job only);
the next green scheduled run closes it. With `repo_workflows` a `repo` job (same `run-deep` gate as `deep`) calls
`./.github/workflows/deep-repo.yml` with the same secret mapping, and `nightly-red` waits for it: a red `repo`
job reddens the night, a cancelled one leaves the issue as it is.

A caller (`uses: ./.github/workflows/verify-deep.yml`) passes secrets by name, never `secrets: inherit`. `on.workflow_call.secrets`
declares, all `required: false`, every secret the file reads: `OTEL_OTLP_AUTH`, the cache secret of the mode
(`BAZEL_CACHE_READ_AUTH` for a Bazel repo, `BAZEL_CACHE_WRITE_AUTH` with `bazel_cache_write = trusted`, none without
`bazel`) and each `repo_workflows.secrets` entry. The block is the whole `secrets` object, so a secret the file reads but
does not declare would arrive empty in a called run.

**`basic-repo.yml`, `deep-repo.yml`** (seeded once, only with `repo_workflows`) — `workflow_call` stubs the repo owns
from the first render: top-level `permissions: {}`, one trivial job, and every listed secret declared under
`on.workflow_call.secrets` (`required: false`, so a fork PR that receives no secrets still calls them). A called workflow
sees only the secrets it declares: when the answer gains a secret, add it to both files by hand.

**`claude.yml`** (full) — PR review on `pull_request` (opened, synchronize, ready_for_review) plus an
`@claude` responder; secret `CLAUDE_CODE_OAUTH_TOKEN`. Every job skips (green) when the secret is
empty or the PR is from a fork. The responder passes `github_token: ${{ github.token }}` (no OIDC exchange for the
write-capable Claude App token) and an explicit `--allowedTools` allowlist (`gh pr view|diff|comment`, inline comment).

**`deploy-site.yml`** (when `site.deploy`) — triggers `push: main` (site paths) and `workflow_dispatch`
only, environment `ocx.sh`, uses the pinned `ocx-sh/website/.github/actions/deploy` with inputs
`dist` and optional `path` from `site`, secret `BUNNY_STORAGE_KEY`. Never runs on `pull_request`.

**`.github/zizmor.yml`** (template-owned) — hash-pin policy for every `uses:`; `self-repository` off. Each `zizmor_ignore`
entry becomes an `ignore:` line (the workflow's file name) under every audit of the pinned `ZIZMOR_VERSION`, because zizmor
has no path exclusion. A `ZIZMOR_VERSION` bump that adds an audit must add its id to `src/.github/zizmor.yml.jinja`.

## Setup action (`.github/actions/setup`, composite)

| Input | Meaning |
|---|---|
| `groups` | ocx groups to install, e.g. `default,lint` |
| `bazel-cache` | `off` (default) \| `read` \| `write` \| `trusted`; `write` only on `push: main`, `trusted` on every event that carries `cache-write-auth` |
| `cache-read-auth`, `cache-write-auth`, `otel-auth` | secrets passed by the caller |

Installs ocx through setup-ocx (pinned SHA, baseline ocx CLI version, `groups`). When `bazel-cache`
is not `off` and the auth is non-empty it writes `$RUNNER_TEMP/bazel-cache.rc` with `--remote_header`
and exports the `BAZELRC` import; when `otel-auth` is non-empty it exports
`OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.ocx.sh` plus headers. Empty secrets (fork PRs) degrade to no
cache / no telemetry and never fail. A warning-only `if: always()` post step ships test telemetry.

Mode `trusted` ignores `cache-read-auth`. With `cache-write-auth` set (and a non-Windows runner) it writes, owner-only,
`$RUNNER_TEMP/bazel-cache-helper` (mode 0700, a `/bin/sh` script that answers Bazel's credential request with the
`<header>=<value>` pair) and `$RUNNER_TEMP/bazel-cache.rc` (mode 0600), exactly the two lines of
[`tests/golden/trusted-cache.rc`](../tests/golden/trusted-cache.rc), and imports the rc through `.bazelrc.user`. A malformed
credential fails the step without echoing it; an empty one writes nothing.

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
```

The fragment imports no user rc, so it cannot be read ahead of the repo's own flags. The seeded `.bazelrc` ends with
`try-import %workspace%/.bazelrc.user`; keep that line last in a repo-owned `.bazelrc`, because the setup action's trusted cache
rc arrives through `.bazelrc.user` and is silently ignored without it. `baseline:check` fails a `.bazelrc` whose last effective
line is anything else, so an adopter whose `.bazelrc` only imported the fragment sees it red at its next update.

`baseline:check` requires an exact-version `bazel_dep(name = "rules_ocx", …)` in `MODULE.bazel` (or
that the module is rules_ocx) and rejects any `http_archive`/`http_file` for a tool the ocx tool map
(`scripts/groups.toml`) already covers. `ci:test` copies JUnit from `bazel-testlogs` to
`target/reports/junit/`.

## Renovate presets

Rendered `renovate.json` extends `github>ocx-sh/conventions//renovate/default#<tag>` (`mirror` profile:
`…//renovate/mirror#<tag>`), then `local>{repo_owner}/{repo_name}//.github/renovate-local`, so repo-local rules
win. `repo_owner` is a copier answer (default `ocx-sh`); `scripts/adopt.sh` derives it from the fleet entry's `repo`.
`.github/renovate-local.json` is seeded once (both profiles) with only a description; the adopting repo owns it afterwards.
Ecosystem norms live in the presets, never in adopters: put only repo-specific rules in the local file.

- `default`: `config:recommended`, weekly schedule, semantic commits (`ci(deps)` / `chore(deps)`),
  `helpers:pinGitHubActionDigests`, `minimumReleaseAge: "7 days"`, `ocx-sh/conventions` action refs ignored (they move with copier),
  copier manager on, `ocx.toml` regex manager (datasource `docker`, versioning
  `regex:^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)$`, `postUpgradeTasks: ["ocx lock"]`),
  `bazel-module` manager for `rules_ocx` (`postUpgradeTasks: ["bazel mod deps"]`), pypi regex manager
  for `COPIER_VERSION` / `ZIZMOR_VERSION` (matches only `template/taskfiles/baseline.taskfile.yml` in conventions itself; adopted repos get new pins through `copier update`), and the `ocx-sh/website` deploy action grouped with `@ocx-sh/theme`.
- Ecosystem norms (`packageRules` on `matchCategories` with `matchUpdateTypes` minor, patch, digest, pin, pinDigest; majors stay
  separate PRs): `ci` grouped as "github actions (non-major)", `js` as "npm (non-major)" with `lockFileMaintenance`,
  `rust` as "cargo (non-major)", `python` as "python (non-major)", and `docker:pinDigests`. The group rules precede the
  `enabled: false` rules for `ocx-sh/conventions` refs and template-owned workflows, and the `ocx site theme` group follows the npm group.
- `mirror`: `default` minus the npm and Bazel groups, and only the `ci` group.

Renovate runs self-hosted from `ocx-sh/conventions` (`renovate.yml`, schedule + dispatch, GitHub App
token incl. `vulnerability-alerts: read` (the App needs the "Dependabot alerts: read" permission), `RENOVATE_REPOSITORIES` = adopted repos in `fleet.toml`; the job runs in environment `renovate`, which holds `RENOVATE_APP_ID` / `RENOVATE_APP_KEY`); remove an adopted repo from the hosted
Renovate app so PRs do not double.
