"""C-017 drift checker and C-018 status page. Offline input format: tests/fixtures/drift/README.md."""
import base64
import json
import re
import shutil
import subprocess
import sys

import jsonschema
import pytest

from stubs import FIXTURES, REPO_ROOT

CHECK = REPO_ROOT / "drift" / "check.py"
RENDER = REPO_ROOT / "drift" / "render.py"
SCHEMA = REPO_ROOT / "drift" / "schema.json"
OFFLINE = FIXTURES / "drift"

CLASS_REPO = {
    "baseline-behind": "behind",
    "not-adopted": "not-adopted",
    "stale-pin": "stale-pin",
    "setup-ocx-stale": "setup-stale",
    "ocx-cli-stale": "cli-stale",
    "pending-updates": "pending",
    "nightly-red": "red",
    "bundle-missing": "no-bundle",
    "grim-pending": "grim-pending",
}
EXCLUDE_REASON = "upstream fork; baseline files would leak upstream (D-10)"


def check(offline, out):
    return subprocess.run([sys.executable, str(CHECK), "--offline", str(offline), "--out", str(out)],
                          capture_output=True, text=True, timeout=120)


@pytest.fixture(scope="module")
def status(tmp_path_factory):
    out = tmp_path_factory.mktemp("drift") / "status.json"
    r = check(OFFLINE, out)
    data = json.loads(out.read_text()) if out.exists() else None
    return r, data, out


def repo_flags(data, key):
    row = next((x for x in data["repos"] if x["key"] == key), None)
    assert row is not None, f"C-017 status.json must contain repo {key}"
    return row, [f["class"] for f in row["flags"]]


def test_exit_zero_and_schema_valid(status):
    r, data, _ = status
    assert r.returncode == 0, f"C-017 exit must be 0 even with flags: {r.stderr}"
    assert data is not None, "C-017 --out must write status.json"
    jsonschema.validate(data, json.loads(SCHEMA.read_text()))
    assert data["latest_version"] == "v0.2.0", "C-017 latest_version comes from remote facts"


def test_one_row_per_fleet_repo(status):
    _, data, _ = status
    assert data is not None, "C-017 status.json missing"
    assert {x["key"] for x in data["repos"]} == set(CLASS_REPO.values()) | {"clean", "excluded"}, \
        "C-017 one status row per fleet.toml repo, excluded included"


@pytest.mark.parametrize("cls", sorted(CLASS_REPO))
def test_drift_class(status, cls):
    _, data, _ = status
    assert data is not None, f"C-017 status.json missing ({cls})"
    row, classes = repo_flags(data, CLASS_REPO[cls])
    assert classes == [cls], f"C-017 repo {CLASS_REPO[cls]} must raise exactly [{cls}], got {classes}"
    assert all(f["detail"] for f in row["flags"]), f"C-017 flag {cls} needs a detail"


def test_clean_repo_has_no_flags(status):
    _, data, _ = status
    assert data is not None, "C-017 status.json missing"
    row, classes = repo_flags(data, "clean")
    assert classes == [] and row["baseline_version"] == "v0.2.0" and row["adopted"], \
        f"C-017 clean repo: no flags and baseline_version v0.2.0, got {classes} / {row['baseline_version']}"


def test_baseline_versions_and_excluded(status):
    _, data, _ = status
    assert data is not None, "C-017 status.json missing"
    assert repo_flags(data, "behind")[0]["baseline_version"] == "v0.1.0", "C-017 baseline_version is the recorded _commit"
    assert repo_flags(data, "not-adopted")[0]["baseline_version"] is None, "C-017 not-adopted has no baseline_version"
    ex, classes = repo_flags(data, "excluded")
    assert ex["excluded"] and ex["reason"] == EXCLUDE_REASON and classes == [], \
        f"C-017 excluded repo carries its reason and no flags: {ex}"


def test_malformed_fleet_toml_exits_2(status, tmp_path):
    assert status[0].returncode == 0, "C-017 control: the unmodified fixture must exit 0"
    bad = tmp_path / "bad"
    shutil.copytree(OFFLINE, bad)
    (bad / "fleet.toml").write_text("[repos.x\nrepo = \n")
    r = check(bad, tmp_path / "s.json")
    assert r.returncode == 2, f"C-017 invalid input must exit 2, got {r.returncode}: {r.stderr}"
    assert "fleet.toml" in r.stderr, f"C-017 invalid input must name fleet.toml on stderr: {r.stderr!r}"


def test_render_one_row_per_repo(status, tmp_path):
    _, data, out = status
    assert data is not None, "C-018 needs status.json from the checker"
    page = tmp_path / "index.html"
    r = subprocess.run([sys.executable, str(RENDER), str(out), "-o", str(page)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and page.exists(), f"C-018 render.py must write index.html: {r.stderr}"
    html = page.read_text()
    rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.S)
    body_rows = [x for x in rows if "<td" in x]
    assert len(body_rows) == len(data["repos"]), f"C-018 one <tr> per repo: {len(body_rows)} vs {len(data['repos'])}"
    for repo in data["repos"]:
        row = next((x for x in body_rows if repo["repo"] in x), None)
        assert row, f"C-018 row for {repo['repo']} missing"
        for f in repo["flags"]:
            assert f["class"] in row, f"C-018 row for {repo['repo']} must show flag {f['class']}"
    ex = next(x for x in body_rows if "ocx-sh/excluded" in x)
    assert "upstream fork" in ex, "C-018 excluded row must show the reason text"
    assert "v0.1.0" in next(x for x in body_rows if "ocx-sh/behind" in x), "C-018 row shows the baseline version"


# ---- online mode (fetch_remote) with `gh` and `ocx` stubbed on PATH -------------------------------------------------

STUB_PY = '''
import json, os, sys
argv = " ".join(sys.argv[2:])
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(os.path.basename(sys.argv[1]) + " " + argv + "\\n")
for rule in json.load(open(os.environ["STUB_MAP"])):
    if all(m in argv for m in rule["match"]):
        sys.stdout.write(rule.get("out", ""))
        sys.stderr.write(rule.get("err", ""))
        sys.exit(rule.get("rc", 0))
sys.stderr.write("gh: Not Found (HTTP 404)\\n")
sys.exit(1)
'''
NOT_FOUND = "gh: Not Found (HTTP 404)"
FORBIDDEN = "gh: API rate limit exceeded (HTTP 403)"
ACTION = "steps:\n  - # v1.0.0\n    uses: ocx-sh/setup-ocx@abc\n    with:\n      version: 0.5.0\n"


def b64(text):
    return base64.b64encode(text.encode()).decode()


def api(path, out, **kw):
    return {"match": [f"repos/{path}"], "out": out, **kw}


def online(tmp_path, fleet, rules):
    """Run check.py online against stub gh/ocx; returns (status rows by key, call log lines)."""
    from stubs import stub_env, write_stub
    d = tmp_path / "stubs"
    d.mkdir()
    (d / "stub.py").write_text(STUB_PY)
    (d / "map.json").write_text(json.dumps(rules))
    log = d / "log"
    for tool in ("gh", "ocx"):
        write_stub(d / "bin", tool, f'exec {sys.executable} {d / "stub.py"} "$0" "$@"\n')
    env = stub_env(d / "bin", STUB_MAP=str(d / "map.json"), STUB_LOG=str(log))
    (tmp_path / "fleet.toml").write_text(fleet)
    out = tmp_path / "status.json"
    r = subprocess.run([sys.executable, str(CHECK), "--fleet", str(tmp_path / "fleet.toml"), "--out", str(out)],
                       capture_output=True, text=True, env=env, timeout=120, check=False)
    assert r.returncode == 0, r.stderr
    rows = {x["key"]: x for x in json.loads(out.read_text())["repos"]}
    return rows, log.read_text().splitlines() if log.exists() else []


def fleet_of(*keys):
    return "schema = 1\n" + "".join(
        f'[repos.{k}]\nrepo = "ocx-sh/{k}"\nadopted = true\nexcluded = false\n[repos.{k}.answers]\nprofile = "minimal"\n'
        for k in keys)


BASE = [
    api("ocx-sh/conventions/tags", "v0.2.0\nv0.1.0"),
    api("ocx-sh/setup-ocx/releases/latest", "v1.4.0"),
    api("ocx-sh/ocx/releases/latest", "v0.6.5"),
]


def test_online_404_is_not_adopted_but_403_is_unreachable(tmp_path):
    rules = [api("ocx-sh/locked/contents", "", rc=1, err=FORBIDDEN), *BASE]  # ocx-sh/absent: stub default 404
    rows, _ = online(tmp_path, fleet_of("absent", "locked"), rules)
    assert [f["class"] for f in rows["absent"]["flags"]] == ["not-adopted"]
    flags = rows["locked"]["flags"]
    assert [f["class"] for f in flags] == ["unreachable"] and "403" in flags[0]["detail"]
    assert rows["locked"]["adopted"] is False


def test_online_pending_updates_counts_renovate_head_branches_only(tmp_path):
    prs = json.dumps([{"headRefName": "renovate/ocx"}, {"headRefName": "renovate/grim"},
                      {"headRefName": "feat/x"}, {"headRefName": "dependabot/y"}])
    rules = [api("ocx-sh/r/contents/.copier-answers.yml", b64("_commit: v0.2.0\n")),
             {"match": ["pr", "list", "-R ocx-sh/r", "headRefName"], "out": prs}, *BASE]
    rows, log = online(tmp_path, fleet_of("r"), rules)
    assert [(f["class"], f["detail"]) for f in rows["r"]["flags"]] == [("pending-updates", "2 open Renovate PR(s)")]
    assert not any("--author" in line for line in log)


def test_online_versions_derive_from_conventions_setup_action_at_commit(tmp_path):
    rules = [api("ocx-sh/conventions/contents/.github/actions/setup/action.yml?ref=v0.1.0", b64(ACTION)),
             api("ocx-sh/r/contents/.copier-answers.yml", b64("_commit: v0.1.0\n")),
             {"match": ["repos/ocx-sh/r/contents/.github/workflows", ".[].name"], "out": "ci.yml"},
             api("ocx-sh/r/contents/.github/workflows/ci.yml", b64("uses: ocx-sh/conventions/.github/actions/setup@sha # v0.1.0\n")),
             *BASE]
    rows, _ = online(tmp_path, fleet_of("r"), rules)
    flags = {f["class"]: f["detail"] for f in rows["r"]["flags"]}
    assert flags["setup-ocx-stale"] == "v1.0.0 < v1.4.0" and flags["ocx-cli-stale"] == "0.5.0 < 0.6.5", flags


def test_online_setup_versions_fall_back_to_workflow_scrape(tmp_path):
    wf = "- uses: ocx-sh/setup-ocx@abc # v1.1.0\n  with:\n    version: 0.4.0\n"
    rules = [api("ocx-sh/r/contents/.copier-answers.yml", b64("_commit: v0.2.0\n")),  # no action.yml at ref: 404
             {"match": ["repos/ocx-sh/r/contents/.github/workflows", ".[].name"], "out": "ci.yml"},
             api("ocx-sh/r/contents/.github/workflows/ci.yml", b64(wf)), *BASE]
    rows, _ = online(tmp_path, fleet_of("r"), rules)
    assert {f["class"]: f["detail"] for f in rows["r"]["flags"]} == {
        "setup-ocx-stale": "v1.1.0 < v1.4.0", "ocx-cli-stale": "0.4.0 < 0.6.5"}


def test_online_stale_pin_uses_refreshed_ocx_index(tmp_path):
    toml = '[tools]\nfoo = "ocx.sh/org/foo:1.0.0"\n'
    rules = [api("ocx-sh/r/contents/.copier-answers.yml", b64("_commit: v0.2.0\n")),
             api("ocx-sh/r/contents/ocx.toml", b64(toml)),
             {"match": ["index", "list", "ocx.sh/org/foo"], "out": json.dumps({"ocx.sh/org/foo": ["1", "1.0.0", "1.2.0", "1.2"]})},
             *BASE]
    rows, log = online(tmp_path, fleet_of("r"), rules)
    assert [(f["class"], f["detail"]) for f in rows["r"]["flags"]] == [("stale-pin", "foo 1.0.0 < 1.2.0")]
    calls = [line for line in log if line.startswith("ocx ")]
    assert calls[0].endswith("index update ocx.sh/org/foo") and "index list" in calls[1]
