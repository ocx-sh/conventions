"""scripts/adopt-mirror.sh refusals: usage, dirty tree, wrong branch (no network, nothing mutated)."""
import subprocess

from stubs import REPO_ROOT, git

SCRIPT = REPO_ROOT / "scripts" / "adopt-mirror.sh"


def run(*args):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=60)


def repo(tmp_path):
    d = tmp_path / "mirror-x"
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    (d / "a").write_text("a\n")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "init")
    return d


def test_usage():
    assert run().returncode == 2


def test_refuses_dirty_tree(tmp_path):
    d = repo(tmp_path)
    (d / "a").write_text("b\n")
    r = run(str(d))
    assert r.returncode == 1 and "dirty" in r.stderr
    assert (d / "a").read_text() == "b\n"


def test_refuses_off_main(tmp_path):
    d = repo(tmp_path)
    git(d, "checkout", "-q", "-b", "topic")
    r = run(str(d))
    assert r.returncode == 1 and "not on main" in r.stderr
