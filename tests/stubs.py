"""Shared helpers: executable stub tools in a tmp dir prepended to PATH."""
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
}


def write_stub(bindir: Path, name: str, body: str) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    p = bindir / name
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def stub_env(bindir: Path, **extra: str) -> dict:
    env = dict(os.environ, **GIT_ENV)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env.update(extra)
    return env


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
        cwd=cwd, capture_output=True, text=True, check=check, env=dict(os.environ, **GIT_ENV),
    )
