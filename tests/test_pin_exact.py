"""C-025 pin-exact: scripts/pin-exact.py <ocx.toml>.

Contract refinement (recorded here): ocx.lock stores repository + per-platform digests, NOT tag
versions. So pin-exact resolves a floating tag (`latest`, `3`, `0.11`) to the newest exact
`X.Y.Z` tag matching the floating prefix, read from `ocx index list <repository>` (lines
`<repo>  <tag>`; build tags such as `3.53.1_20260819` and floating tags are ignored; versions
compare numerically), then runs `ocx lock`. Tools go to their D-04 group from scripts/groups.toml;
an unknown tool stays in the default table with a stderr warning naming it. Idempotent.
"""
import shutil
import subprocess
import sys
import tomllib

import pytest

from stubs import FIXTURES, REPO_ROOT, stub_env, write_stub

SCRIPT = REPO_ROOT / "scripts" / "pin-exact.py"
FIX = FIXTURES / "pin-exact"

OCX_STUB = r"""
echo "$*" >> "$OCX_STUB_LOG"
case "$1 $2" in
  "index list")
    echo "Package  Tag"
    awk -v repo="${3%%:*}" '$1 == repo' "$OCX_STUB_INDEX"
    ;;
esac
exit 0
"""


@pytest.fixture
def work(tmp_path):
    bindir = tmp_path / "bin"
    write_stub(bindir, "ocx", OCX_STUB)
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copy(FIX / "ocx.floating.toml", proj / "ocx.toml")
    log = tmp_path / "ocx.log"
    log.write_text("")
    env = stub_env(bindir, OCX_STUB_LOG=str(log), OCX_STUB_INDEX=str(FIX / "index.txt"))

    def run():
        return subprocess.run([sys.executable, str(SCRIPT), str(proj / "ocx.toml")],
                              cwd=proj, env=env, capture_output=True, text=True, timeout=60)
    return proj / "ocx.toml", log, run


def refs(path):
    """name -> (group, ref) for every tool in the file."""
    data = tomllib.loads(path.read_text())
    out = {n: ("default", r) for n, r in data.get("tools", {}).items()}
    for g, body in data.get("group", {}).items():
        out.update({n: (g, r) for n, r in body.get("tools", {}).items()})
    return out


def test_floating_rewritten_to_exact(work):
    toml, log, run = work
    r = run()
    assert r.returncode == 0, f"C-025 pin-exact must exit 0: {r.stderr}"
    got = refs(toml)
    expect = {
        "actionlint": "ocx.sh/actionlint/actionlint:1.7.12",  # `1`, not 2.0.0, not the build tag
        "git-cliff": "ocx.sh/git-cliff/git-cliff:2.14.2",
        "lychee": "ocx.sh/lychee/lychee:0.24.2",  # numeric compare (0.9.0 < 0.24.2), not 1.0.0
        "prek": "ocx.sh/prek/prek:0.5.5",  # `latest` -> newest exact
        "shellcheck": "ocx.sh/shellcheck/shellcheck:0.11.0",  # `0.11` prefix, not 0.12.0
        "task": "ocx.sh/go-task/task:3.54.0",  # `3`, not 4.0.0, not the build tag
        "elvish": "ocx.sh/elvish/elvish:0.21.0",
    }
    for name, ref in expect.items():
        assert name in got and got[name][1] == ref, f"C-025 {name}: want {ref}, got {got.get(name)}"


def test_already_exact_unchanged(work):
    toml, _, run = work
    assert run().returncode == 0, "C-025 pin-exact must exit 0"
    assert refs(toml)["gitleaks"][1] == "ocx.sh/gitleaks/gitleaks:8.30.1", \
        "C-025 an already-exact pin must not be bumped to a newer index version"


def test_runs_ocx_lock(work):
    _, log, run = work
    run()
    calls = [ln.split() for ln in log.read_text().splitlines()]
    assert ["lock"] in [c[:1] for c in calls], f"C-025 pin-exact must run `ocx lock` afterwards: {calls}"
    assert any(c[:2] == ["index", "list"] for c in calls), "C-025 floating tags resolve via `ocx index list`"


def test_tools_moved_to_d04_groups(work):
    toml, _, run = work
    run()
    got = refs(toml)
    for name, group in [("prek", "lint"), ("gitleaks", "lint"), ("actionlint", "lint"),
                        ("lychee", "lint"), ("shellcheck", "lint"), ("git-cliff", "release"),
                        ("task", "default")]:
        assert got[name][0] == group, f"C-025/D-04 {name} must live in group {group}, found {got[name][0]}"


def test_unknown_tool_stays_default_with_warning(work):
    toml, _, run = work
    r = run()
    assert refs(toml)["elvish"][0] == "default", "C-025 unknown tool must stay in the default [tools] table"
    assert "elvish" in r.stderr, f"C-025 unknown tool must be named in a stderr warning, got: {r.stderr!r}"


def test_comments_and_platform_groups_preserved(work):
    toml, _, run = work
    assert run().returncode == 0, "C-025 pin-exact must exit 0"
    text = toml.read_text()
    for needle in ("# Fleet-style ocx.toml", "# floating major", "# fish is UNIX-ONLY",
                   "[group.unix.tools]"):
        assert needle in text, f"C-025 pin-exact must preserve {needle!r}"
    assert refs(toml)["fish"][0] == "unix", "C-025 platform group tool must stay in its platform group"


def test_idempotent(work):
    toml, log, run = work
    assert run().returncode == 0
    first = toml.read_bytes()
    r2 = run()
    assert r2.returncode == 0, f"C-025 second run must succeed: {r2.stderr}"
    assert toml.read_bytes() == first, "C-025 second run must be byte-identical (idempotent)"


def test_groups_map_covers_d04():
    data = tomllib.loads((REPO_ROOT / "scripts" / "groups.toml").read_text())
    assert data["groups"]["task"] == "default" and data["groups"]["git-cliff"] == "release", \
        "C-025/D-04 groups.toml must map task->default and git-cliff->release"
    assert set(data["groups"].values()) <= {"default", "lint", "test", "build", "docs", "release"}, \
        "C-025/D-04 groups.toml may only use the D-04 groups"
    assert set(data["repositories"]) >= set(data["groups"]), "C-025 every mapped tool needs a repository"
