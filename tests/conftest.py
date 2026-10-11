"""Shared test API: render fixture answers files with the pinned copier into scratch git repos."""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"

GIT_ISOLATION = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_COUNT": "4",
    "GIT_CONFIG_KEY_0": "commit.gpgsign",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "user.name",
    "GIT_CONFIG_VALUE_1": "t",
    "GIT_CONFIG_KEY_2": "user.email",
    "GIT_CONFIG_VALUE_2": "t@t",
    "GIT_CONFIG_KEY_3": "tag.gpgsign",
    "GIT_CONFIG_VALUE_3": "false",
}


def git_env_dict() -> dict:
    return {**os.environ, **GIT_ISOLATION}


def run(cmd, cwd, env=None, check=True, timeout=900):
    """subprocess.run with captured text output; raises CalledProcessError (stdout/stderr attached) when check."""
    return subprocess.run(
        [str(c) for c in cmd], cwd=cwd, env=env, check=check, timeout=timeout,
        capture_output=True, text=True,
    )


def render_to(answers_name, dest, extra_data=None, src=None, vcs_ref="HEAD"):
    """copier copy `src` (default REPO_ROOT) into dest, then commit the result. Raises CalledProcessError on copier failure."""
    src = Path(src) if src else REPO_ROOT
    dest = Path(dest)
    answers = FIXTURES / "answers" / f"{answers_name}.yml"
    cmd = ["uv", "run", "--project", REPO_ROOT, "copier", "copy", "--defaults", "--quiet",
           "--vcs-ref", vcs_ref, "--data-file", answers]
    for k, v in (extra_data or {}).items():
        cmd += ["--data", f"{k}={v}"]
    cmd += [src, dest]
    # copier renders the dirty working tree of a local git template when vcs_ref is HEAD
    run(cmd, cwd=REPO_ROOT, env=git_env_dict())
    env = git_env_dict()
    run(["git", "init", "-q", "-b", "main"], dest, env)
    run(["git", "add", "-A"], dest, env)
    run(["git", "commit", "-qm", "init"], dest, env)
    return dest


def ocx_lock_committed(repo):
    """Rendered repos carry no ocx.lock; create and commit one so `ocx exec` works (needs network)."""
    if not (Path(repo) / "ocx.lock").exists():
        env = git_env_dict()
        run(["ocx", "lock"], repo, env, timeout=1800)
        run(["git", "add", "ocx.lock"], repo, env)
        run(["git", "commit", "-qm", "lock"], repo, env)


def ocx_task(repo, *args, locked=True, timeout=1800):
    """`ocx exec -- task <args>` in repo (no check). locked=False runs host `task` directly (for tests that make ocx.lock stale)."""
    if locked:
        ocx_lock_committed(repo)
        cmd = ["ocx", "exec", "--", "task", *args]
    else:
        cmd = ["task", *args]
    return run(cmd, repo, git_env_dict(), check=False, timeout=timeout)


@pytest.fixture
def git_env():
    return git_env_dict()


@pytest.fixture
def render(tmp_path):
    def _render(answers_name: str, dest: Path | None = None, extra_data: dict | None = None) -> Path:
        dest = Path(dest) if dest else tmp_path / answers_name
        return render_to(answers_name, dest, extra_data)

    return _render
