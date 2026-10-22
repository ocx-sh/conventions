# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-10-22

### Fixed

- Let mirror profile float the ocx toolchain minor, skip ocx-mirror-generated workflows in lint, allowlist the discord user id (#17)

## [0.2.0] - 2026-10-22

### Added

- Upload docs-job reports as the docs-reports artifact
- Renovate ecosystem norms and repo-local overrides
- Issue form and outsider-issue Discord ping for both profiles (#10)
- @claude on issues, branch-only, mirror profile too (#11) *(claude)*
- Auto-merge copier updates and weekly stale-issue digest (#12)
- Track 100 ocx-contrib mirror repos at iteration 3 (#13) *(fleet)*

### Documentation

- Document Renovate norms and renovate-local.json

### Fixed

- Reuse the v7.0.2 upload-artifact pin and name docs-reports in the contract
- Give the Renovate token vulnerability-alerts read *(ci)*
- Unshallow before re-rendering the dogfood _commit; refresh dogfood render (#14) *(test)*
- D-02 accepts a describe-style _commit on a dirty tree (release:prepare runs verify after writing the changelog) (#15) *(test)*

## [0.1.1] - 2026-10-12

### Fixed

- Put ocx group tools on PATH for the Renovate runner
- Commit grim client output instead of gitignoring it

## [0.1.0] - 2026-10-11

### Added

- Add template core, baseline tasks and pin-exact script
- Add template CI workflows and shared setup action
- Add Renovate presets and self-hosted runner
- Add fleet drift checker and daily status page
- Add baseline rule, adopt skill, publish config and adopt script
- Use org secrets for cache and telemetry, drop the ci environments
- Build template/ from src/ with ownership banners; gitignore grim client output

### Documentation

- Add README and changelog

### Fixed

- Pin rendered Renovate preset to the template commit
- Adopt.sh compares recorded _commit and ref as commit SHAs
- Tolerate a not-yet-locked mirror in grim:check
- Let grim:check reinstall committed client files on a fresh clone
- Renovate preset selectors and per-owner scoped runner
- Harden drift checker online mode and status workflow
- Harden template workflows (lint history, claude review prompt, bot skip, ci env, site paths)
- Declare the test group, shell-free hooks, release 404, lookalike archives, adopt import, split publish repos
- Drop OCX_GLOBAL from the test subprocess env
- Give python repos uv in the CI test group
- Environments for write credentials, release cooldown, private-repo drift probe, adopt and checker edge cases
- Pin the dogfood render to a pushed baseline commit
- Reach uv through its ocx group in the repo's own ci tasks
- Give the CI test group grim for the grim artifact tests
[0.2.1]: https://github.com/ocx-sh/conventions/compare/v0.2.0..v0.2.1
[0.2.0]: https://github.com/ocx-sh/conventions/compare/v0.1.1..v0.2.0
[0.1.1]: https://github.com/ocx-sh/conventions/compare/v0.1.0..v0.1.1
[0.1.0]: https://github.com/ocx-sh/conventions/tree/v0.1.0

