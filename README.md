# conventions

OCX fleet baseline for `ocx-sh` repositories. Status: v0.1 in progress.

- `copier.yml` + `template/`: the copier template (profiles `full` and `mirror`); ownership in `MANIFEST.toml`
- `renovate/`: shared Renovate presets
- `.github/actions/setup`: composite setup action (ocx, Bazel cache, telemetry)
- `drift/`: drift checker and status page over `fleet.toml`
- `docs/contract.md`: the task, workflow and preset interface adopters rely on
