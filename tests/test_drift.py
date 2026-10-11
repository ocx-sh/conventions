"""C-017 drift checker and C-018 status page. Offline input format: tests/fixtures/drift/README.md."""
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
