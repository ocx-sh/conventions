"""C-024 scripts/adopt.sh <dest> <fleet-key>, driven against a stub copier template (tests/fixtures/stub-template).

Env contract: CONVENTIONS_SRC (template path/URL; default https://github.com/ocx-sh/conventions.git),
CONVENTIONS_REF (default: latest tag), FLEET_TOML (default: the conventions fleet.toml).
"""
import shutil
import subprocess

import pytest

from stubs import FIXTURES, REPO_ROOT, git, stub_env

ADOPT = REPO_ROOT / "scripts" / "adopt.sh"
BIG_CLAUDE = "# Project\n\nLots of guidance.\n\n## Rules\n\n- one\n- two\n"
TASKFILE = 'version: "3"\ntasks:\n  mine:\n    cmds: [echo mine]\n'


@pytest.fixture
def template(tmp_path):
    t = tmp_path / "template-src"
    shutil.copytree(FIXTURES / "stub-template", t)
    git(t, "init", "-q", "-b", "main")
    git(t, "add", "-A")
    git(t, "commit", "-q", "-m", "init")
    git(t, "tag", "v0.1.0")
    return t


@pytest.fixture
def dest(tmp_path):
    d = tmp_path / "demo"
    (d / ".github").mkdir(parents=True)
    (d / ".github" / "dependabot.yml").write_text("version: 2\nupdates: []\n")
    (d / "Taskfile.yml").write_text(TASKFILE)
    (d / "CLAUDE.md").write_text(BIG_CLAUDE)
    (d / "README.md").write_text("demo\n")
    git(d, "init", "-q", "-b", "main")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "init")
    return d


@pytest.fixture
def adopt(template, dest, tmp_path):
    env = stub_env(tmp_path / "nobin", CONVENTIONS_SRC=str(template), CONVENTIONS_REF="v0.1.0",
                   FLEET_TOML=str(FIXTURES / "adopt" / "fleet.toml"))

    def run(key="demo"):
        assert ADOPT.exists(), "C-024 scripts/adopt.sh must exist"
        return subprocess.run(["bash", str(ADOPT), str(dest), key], env=env, capture_output=True, text=True, timeout=600)
    return run


def state(d):
    return git(d, "status", "--porcelain").stdout, sorted(p.name for p in d.rglob("*") if ".git" not in p.parts)


def test_adopt_succeeds_and_removes_dependabot(adopt, dest):
    r = adopt()
    assert r.returncode == 0, f"C-024 adopt must succeed: {r.stderr}"
    assert not (dest / ".github" / "dependabot.yml").exists(), "C-024 must delete .github/dependabot.yml"


def test_taskfile_renamed_via_git_mv(adopt, dest):
    assert adopt().returncode == 0, "C-024 adopt must succeed"
    tracked = git(dest, "ls-files").stdout.split()
    assert "taskfile.yml" in tracked and "Taskfile.yml" not in tracked, f"C-024 Taskfile.yml must be renamed in the index: {tracked}"
    assert (dest / "taskfile.yml").read_text() == TASKFILE, "C-024 repo-owned taskfile content must survive the rename"
    diff = git(dest, "diff", "--cached", "-M", "--name-status", "HEAD").stdout
    assert any(ln.startswith("R") and "Taskfile.yml" in ln and "taskfile.yml" in ln for ln in diff.splitlines()), \
        f"C-024 rename must be recorded as a git rename (git mv): {diff!r}"


def test_src_path_rewritten(adopt, dest):
    assert adopt().returncode == 0, "C-024 adopt must succeed"
    answers = (dest / ".copier-answers.yml").read_text()
    assert "_src_path: https://github.com/ocx-sh/conventions.git" in answers, f"C-024 _src_path must be rewritten: {answers}"
    assert "_commit: v0.1.0" in answers and "repo_name: demo" in answers, f"C-024 answers keep _commit and fleet answers: {answers}"


def test_full_claude_md_becomes_agents_md(adopt, dest):
    assert adopt().returncode == 0, "C-024 adopt must succeed"
    assert (dest / "AGENTS.md").read_text() == BIG_CLAUDE, "C-024 full-size CLAUDE.md must become AGENTS.md"
    assert (dest / "CLAUDE.md").read_text().strip() == "@AGENTS.md", "C-024 CLAUDE.md must be the one-line pointer"
    assert "AGENTS.md" in git(dest, "ls-files").stdout.split(), "C-024 AGENTS.md must be tracked (git mv)"
    diff = git(dest, "diff", "--cached", "-M", "-C", "--name-status", "HEAD").stdout
    assert any(ln.startswith(("R", "C")) and "CLAUDE.md" in ln and "AGENTS.md" in ln for ln in diff.splitlines()), \
        f"C-024 CLAUDE.md -> AGENTS.md must be recorded as a git move: {diff!r}"


def test_existing_agents_md_is_not_overwritten(adopt, dest):
    (dest / "AGENTS.md").write_text("mine\n")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "agents")
    assert adopt().returncode == 0, "C-024 adopt must succeed"
    text = (dest / "AGENTS.md").read_text()
    assert text.startswith("mine\n"), "C-024 an existing AGENTS.md keeps its own content"
    assert "## Imported from CLAUDE.md" in text and BIG_CLAUDE in text, "C-024 CLAUDE.md content must be appended to the existing AGENTS.md, not lost"
    assert (dest / "CLAUDE.md").read_text().strip() == "@AGENTS.md", "C-024 CLAUDE.md must be the one-line pointer"
    assert git(dest, "diff", "--cached", "--name-only", "HEAD").stdout.split().count("AGENTS.md") == 1, "C-024 the AGENTS.md edit must be staged"


def test_pointer_only_claude_md_adds_nothing_to_existing_agents_md(adopt, dest):
    (dest / "AGENTS.md").write_text("mine\n")
    (dest / "CLAUDE.md").write_text("@AGENTS.md\n")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "agents")
    assert adopt().returncode == 0, "C-024 adopt must succeed"
    assert (dest / "AGENTS.md").read_text() == "mine\n", "C-024 a pointer-only CLAUDE.md must not be imported"


def test_dirty_dest_refused_without_changes(adopt, dest):
    (dest / "scratch.txt").write_text("dirty\n")
    before = state(dest)
    r = adopt()
    assert r.returncode != 0, "C-024 dirty dest must be refused"
    assert state(dest) == before and (dest / ".github" / "dependabot.yml").exists(), "C-024 refusal must change nothing"


def test_unknown_fleet_key_refused(adopt, dest):
    before = state(dest)
    r = adopt("nope")
    assert r.returncode != 0 and state(dest) == before, "C-024 unknown fleet key must fail without changes"


def test_second_run_is_noop(adopt, dest):
    assert adopt().returncode == 0, "C-024 first adopt must succeed"
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "chore: adopt baseline")
    r = adopt()
    assert r.returncode == 0, f"C-024 second run on an adopted repo must succeed: {r.stderr}"
    assert git(dest, "status", "--porcelain").stdout == "", "C-024 second run must leave no diff"
