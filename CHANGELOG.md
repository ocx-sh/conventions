# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-11

### Added

- Add template core, baseline tasks and pin-exact script
- Add template CI workflows and shared setup action
- Add Renovate presets and self-hosted runner
- Add fleet drift checker and daily status page
- Add baseline rule, adopt skill, publish config and adopt script

### Fixed

- Pin rendered Renovate preset to the template commit
- Adopt.sh compares recorded _commit and ref as commit SHAs
- Tolerate a not-yet-locked mirror in grim:check
[0.1.0]: https://github.com/ocx-sh/conventions/tree/v0.1.0

