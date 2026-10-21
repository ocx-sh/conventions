"""C-027..C-031 template extension: runner set, repo workflows, trusted Bazel cache, zizmor ignore, release hooks.

Every assertion message starts with the C-ID it pins. Defaults (no new answer set) must render exactly as before; the
pinned-output tests for that live beside the fixtures in test_contract.py.
"""
import subprocess

import pytest
import yaml

from conftest import FIXTURES, render_to

RUNNERS = ["ubuntu-latest", "ubuntu-24.04-arm", "macos-latest", "macos-15-intel", "macos-26", "windows-latest", "windows-11-arm"]


def answers_file(tmp_path, base, **override):
    """A copy of fixture `base` with `override` merged in; the Path goes to render_to."""
    data = yaml.safe_load((FIXTURES / "answers" / f"{base}.yml").read_text())
    data.update(override)
    p = tmp_path / "answers.yml"
    p.write_text(yaml.safe_dump(data))
    return p


def jobs(repo, workflow):
    return yaml.safe_load((repo / ".github" / "workflows" / workflow).read_text())["jobs"]


# ---------------------------------------------------------------- C-027 runner set

def test_c027_every_supported_runner_renders_into_the_deep_matrix(tmp_path):
    repo = render_to(answers_file(tmp_path, "full-minimal", deep_os=RUNNERS), tmp_path / "out")
    assert jobs(repo, "verify-deep.yml")["deep"]["strategy"]["matrix"]["os"] == RUNNERS, \
        "C-027: deep_os must accept ubuntu-24.04-arm, macos-15-intel, macos-26 and windows-11-arm"


def test_c027_unknown_runner_fails_naming_the_allowed_list(tmp_path):
    with pytest.raises(subprocess.CalledProcessError) as e:
        render_to(answers_file(tmp_path, "full-minimal", deep_os=["macos-13"]), tmp_path / "out")
    out = (e.value.stdout or "") + (e.value.stderr or "")
    missing = [r for r in ["macos-13", *RUNNERS] if r not in out]
    assert not missing, f"C-027: an unknown runner must be named with the allowed list; missing {missing}"
