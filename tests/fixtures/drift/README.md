# Offline drift fixture (C-017)

`python3 drift/check.py --offline tests/fixtures/drift [--out status.json]` reads, instead of `gh api`:
- `fleet.toml`: same schema as the real fleet.toml (`[repos.<key>]` repo/adopted/excluded/reason + `.answers`).
- `remote.json`: `latest_version` (newest conventions tag), `newest_setup_ocx`, `newest_ocx`, `index`
  (newest exact version per `ocx.sh/<org>/<pkg>`), and `repos.<key>` with the remote facts per repo:
  `answers` (raw `.copier-answers.yml` text or null; `_commit:` is the baseline version), `ocx_toml`,
  `grimoire_toml` (raw text or null), `setup_ocx_ref`, `ocx_cli`, `renovate_prs` (open count), `nightly`
  (last scheduled verify-deep conclusion or null), `grim_floating_pending` (bool).
Each drift class is raised by exactly one repo (key `behind`, `stale-pin`, `setup-stale`, `cli-stale`,
`pending`, `red`, `no-bundle`, `grim-pending`, `not-adopted`); `clean` has no flags; `excluded` is skipped
with its reason. Expected bundles come from the fleet.toml answers (docs-essentials, code-docs-essentials,
`<lang>-essentials`, `ocx-theme` when theme_bundle). Output: `status.json` per `drift/schema.json`.
