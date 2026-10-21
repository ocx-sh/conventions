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


# ---------------------------------------------------------------- C-028 repo-owned workflows

SECRETS = ["BAZEL_CACHE_WRITE_AUTH", "OTHER_TOKEN"]


def repo_answers(tmp_path, base="full-bazel-site", **override):
    return answers_file(tmp_path, base, repo_workflows={"secrets": SECRETS}, **override)


def test_c028_basic_and_deep_call_the_repo_workflows_with_named_secrets(tmp_path):
    repo = render_to(repo_answers(tmp_path), tmp_path / "out")
    for wf, called in (("verify-basic.yml", "basic-repo.yml"), ("verify-deep.yml", "deep-repo.yml")):
        job = jobs(repo, wf)["repo"]
        assert job["uses"] == f"./.github/workflows/{called}", f"C-028: {wf} job `repo` must call {called}: {job}"
        assert job["permissions"] == {"contents": "read"}, f"C-028: {wf} job `repo` must be read-only: {job}"
        assert job["secrets"] == {s: "${{ secrets." + s + " }}" for s in SECRETS}, \
            f"C-028: {wf} must map each secret by name (never `secrets: inherit`): {job['secrets']}"


def test_c028_gate_and_nightly_red_wait_for_the_repo_job(tmp_path):
    repo = render_to(repo_answers(tmp_path), tmp_path / "out")
    assert "repo" in jobs(repo, "verify-basic.yml")["basic-gate"]["needs"], "C-028: basic-gate must need `repo`"
    red = jobs(repo, "verify-deep.yml")["nightly-red"]
    assert red["needs"] == ["deep", "repo"], f"C-028: nightly-red must need deep and repo: {red['needs']}"
    assert red["steps"][0]["env"]["REPO_RESULT"] == "${{ needs.repo.result }}", "C-028: nightly-red must read the repo job's result"


def test_c028_stubs_declare_every_listed_secret(tmp_path):
    repo = render_to(repo_answers(tmp_path), tmp_path / "out")
    for name in ("basic-repo.yml", "deep-repo.yml"):
        wf = yaml.safe_load((repo / ".github" / "workflows" / name).read_text())
        on = wf.get("on", wf.get(True))
        assert set(on["workflow_call"]["secrets"]) == set(SECRETS), f"C-028: {name} must declare {SECRETS} under workflow_call.secrets"
        assert wf["permissions"] == {}, f"C-028: {name} must set top-level `permissions: {{}}`"


def test_c028_no_secrets_renders_no_secrets_block(tmp_path):
    repo = render_to(answers_file(tmp_path, "full-minimal", repo_workflows={"secrets": []}), tmp_path / "out")
    assert "secrets" not in jobs(repo, "verify-basic.yml")["repo"], "C-028: an empty secrets list must render no `secrets:` key"
    on = yaml.safe_load((repo / ".github/workflows/basic-repo.yml").read_text())
    assert on.get("on", on.get(True)) == {"workflow_call": None}, "C-028: a stub with no secrets declares a bare workflow_call"


def test_c028_stubs_are_seeded_once(tmp_path):
    repo = render_to(repo_answers(tmp_path), tmp_path / "out")
    for name in ("basic-repo.yml", "deep-repo.yml"):
        first = (repo / ".github" / "workflows" / name).read_text().splitlines()[0]
        assert "ocx-baseline: template-owned" not in first, f"C-028: {name} is repo-owned and must carry no ownership banner"


@pytest.mark.parametrize("bad", [True, {}, {"secrets": "A"}, {"secrets": ["lower-case-dash"]}, {"secrets": ["1A"]},
                                 {"secrets": ["GITHUB_TOKEN"]}, {"secrets": ["A"], "extra": 1}, ["A"], "A"])
def test_c028_malformed_repo_workflows_fails(tmp_path, bad):
    with pytest.raises(subprocess.CalledProcessError) as e:
        render_to(answers_file(tmp_path, "full-minimal", repo_workflows=bad), tmp_path / "out")
    assert "repo_workflows" in (e.value.stdout or "") + (e.value.stderr or ""), \
        f"C-028: {bad!r} must fail naming repo_workflows"


def test_c028_mirror_profile_ignores_repo_workflows(tmp_path):
    repo = render_to(answers_file(tmp_path, "mirror", repo_workflows={"secrets": ["A"]}), tmp_path / "out")
    assert not (repo / ".github/workflows/basic-repo.yml").exists(), "C-028: profile mirror must not render repo workflows"
