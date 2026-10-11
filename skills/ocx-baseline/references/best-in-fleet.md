# Best in fleet

Strongest observed example per convention (not a recommendation). Open the named repo (sibling checkout or `ocx-sh/<repo>` on GitHub) and copy its shape when the baseline leaves the choice to the repo.

| Convention | Strongest example | Why |
|---|---|---|
| ocx.toml + lock + setup-ocx in CI | ocx-website, www-setup | all tools from ocx.toml, no other installer in CI; www-setup adds the `ocx lock --check` gate |
| ocx.toml groups | www-setup (platform), grimoire-indexer (Node versions) | commented rationale, wired to `ocx run -g` and setup-ocx `groups:` |
| grim bundles, multi-client | ocx, ocx-website | 3 clients, 8 bundles, lock committed |
| Git hook | ocx | prek, commit-msg gate, native pre-push, documented in the config |
| JS package manager (pnpm via ocx) | ocx-website, find_ocx | `pnpm` + `node` from ocx.toml, lockfile, `packageManager` field |
| Rust build/lint | ocx, grimoire | rustfmt, clippy, deny, taplo, hawkeye, nextest JUnit, cargo-dist |
| Python build/lint | ocx-indexbot | ruff, pyright, bandit, mutmut, coverage in pyproject, `lock:check` |
| Test summary / reports | ocx, ocx-sdk-python | JUnit + step summary; three test tiers + codecov |
| Renovate shape | ocx, rules_ocx | grouped, SHA-pinned, conventional prefixes, themed groups |
| Tiered CI (basic/deep/readiness) | ocx | verify-basic on PR, verify-deep on main/cron, release-readiness GO/NO-GO |
| Tiered test naming | ocx-sdk-python, www-setup | explicit unit/contract/acceptance tiers in CLAUDE.md |
| Workflow hardening | ocx-website | zizmor config, SHA-pinned actions, permissions `{}`, CODEOWNERS |
| Docs site + shared theme | ocx-website (theme source), find_ocx (consumer) | Lighthouse + Bunny deploy + theme patch |
| Lighthouse + a11y | ocx-website, ocx-catalog | minScore 1, budgets, axe e2e |
| AI config shape | ocx-website, ocx-catalog | AGENTS.md canonical, one-line CLAUDE.md pointer, rules/skills committed |
| Publishing grim packages | grimoire-lore, ocx-website | `publish.toml` + CI publish job |
| Bazel with rules_ocx | rules_ocx | the module is its own consumer; use it for every ocx-provided tool |
