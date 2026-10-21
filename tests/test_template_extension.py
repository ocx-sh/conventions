"""C-027..C-031 template extension: runner set, repo workflows, trusted Bazel cache, zizmor ignore, release hooks.

Every assertion message starts with the C-ID it pins. Defaults (no new answer set) must render exactly as before; the
pinned-output tests for that live beside the fixtures in test_contract.py.
"""
import re
import subprocess

import pytest
import yaml

from conftest import FIXTURES, REPO_ROOT, render_to

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


# ---------------------------------------------------------------- C-029 bazel_cache_write

WRITE_SECRET = "${{ secrets.BAZEL_CACHE_WRITE_AUTH }}"


def setup_withs(repo, workflow):
    """The `with:` of every main setup step (the ones that install groups) per job."""
    out = {}
    for jname, job in jobs(repo, workflow).items():
        for s in job.get("steps", []):
            if "conventions/.github/actions/setup" in str(s.get("uses", "")) and "groups" in (s.get("with") or {}):
                out[jname] = s["with"]
    return out


def test_c029_trusted_presents_the_write_credential_in_every_ci_job(tmp_path):
    repo = render_to(answers_file(tmp_path, "full-bazel-site", bazel_cache_write="trusted"), tmp_path / "out")
    basic, deep = setup_withs(repo, "verify-basic.yml"), setup_withs(repo, "verify-deep.yml")
    assert set(basic) == {"lint", "test", "build", "docs"} and set(deep) == {"deep"}, f"C-029 jobs found: {sorted(basic)} {sorted(deep)}"
    for where, withs in (("verify-basic", basic), ("verify-deep", deep)):
        for jname, w in withs.items():
            assert w.get("bazel-cache") == "trusted" and w.get("cache-write-auth") == WRITE_SECRET, \
                f"C-029 {where} job {jname} must run the setup action with bazel-cache: trusted and the write secret: {w}"
            assert "cache-read-auth" not in w, f"C-029 {where} job {jname} presents one credential per lane, not also the read one"


def test_c029_trusted_write_secret_carries_no_event_predicate(tmp_path):
    repo = render_to(answers_file(tmp_path, "full-bazel-site", bazel_cache_write="trusted"), tmp_path / "out")
    for wf in ("verify-basic.yml", "verify-deep.yml", "claude.yml"):
        text = (repo / ".github" / "workflows" / wf).read_text()
        for line in (ln for ln in text.splitlines() if "BAZEL_CACHE_WRITE_AUTH" in ln):
            assert line.strip().endswith(WRITE_SECRET) and "github." not in line, f"C-029 {wf}: bare secret expected, got {line.strip()!r}"


@pytest.mark.parametrize("answers", [{}, {"bazel_cache_write": "main"}])
def test_c029_main_is_the_default_and_keeps_push_to_main_only(tmp_path, answers):
    repo = render_to(answers_file(tmp_path, "full-bazel-site", **answers), tmp_path / "out")
    for wf in ("verify-basic.yml", "verify-deep.yml"):
        assert "trusted" not in (repo / ".github" / "workflows" / wf).read_text(), f"C-029 {wf}: mode main must not render trusted"
    assert setup_withs(repo, "verify-deep.yml")["deep"]["bazel-cache"] == "read", "C-029 mode main keeps the read-only deep cache"
    assert "cache-write-auth" not in setup_withs(repo, "verify-basic.yml")["lint"], "C-029 mode main gives the lint job no cache credential"


def test_c029_trusted_without_bazel_renders_no_cache_inputs(tmp_path):
    repo = render_to(answers_file(tmp_path, "full-minimal", bazel_cache_write="trusted"), tmp_path / "out")
    for wf in ("verify-basic.yml", "verify-deep.yml"):
        assert "trusted" not in (repo / ".github" / "workflows" / wf).read_text(), f"C-029 {wf}: no bazel, no cache inputs"


def test_c029_unknown_mode_fails(tmp_path):
    with pytest.raises(subprocess.CalledProcessError) as e:
        render_to(answers_file(tmp_path, "full-bazel-site", bazel_cache_write="everyone"), tmp_path / "out")
    assert "bazel_cache_write" in (e.value.stdout or "") + (e.value.stderr or ""), "C-029 an unknown mode must fail naming bazel_cache_write"


# ---------------------------------------------------------------- C-030 zizmor_ignore

GENERATED = """name: Release
on:
  pull_request:
permissions:
  contents: write
jobs:
  plan:
    runs-on: ubuntu-latest
    container: ghcr.io/foo/bar:latest
    steps:
      - uses: actions/checkout@v4
      - uses: some/action@main
      - run: echo "${{ github.event.pull_request.title }}"
  call:
    uses: ./.github/workflows/other.yml
    secrets: inherit
"""


def zizmor_version():
    text = (REPO_ROOT / "src" / "taskfiles" / "baseline.taskfile.yml").read_text()
    return re.search(r'ZIZMOR_VERSION:\s*"([^"]+)"', text).group(1)


def zizmor(repo):
    return subprocess.run(["uv", "tool", "run", "--from", f"zizmor=={zizmor_version()}", "zizmor", "--no-online-audits",
                           "--config", ".github/zizmor.yml", ".github"], cwd=repo, capture_output=True, text=True, timeout=300)


def with_workflow(repo, name):
    (repo / ".github" / "workflows" / name).write_text(GENERATED)
    return zizmor(repo)


def test_c030_listed_generated_workflow_is_not_reported(tmp_path):
    repo = render_to(answers_file(tmp_path, "full-minimal", zizmor_ignore=[".github/workflows/release.yml"]), tmp_path / "out")
    r = with_workflow(repo, "release.yml")
    assert r.returncode == 0, f"C-030 a workflow listed in zizmor_ignore must produce no finding: {r.stdout[-600:]}{r.stderr[-600:]}"


def test_c030_unlisted_workflow_still_fails(tmp_path):
    repo = render_to(answers_file(tmp_path, "full-minimal"), tmp_path / "out")
    r = with_workflow(repo, "release.yml")
    assert r.returncode != 0, "C-030 without the answer the same workflow must fail zizmor (the ignore is what turns it green)"


def test_c030_only_the_listed_file_is_ignored(tmp_path):
    repo = render_to(answers_file(tmp_path, "full-minimal", zizmor_ignore=[".github/workflows/release.yml"]), tmp_path / "out")
    r = with_workflow(repo, "hand-written.yml")
    assert r.returncode != 0, "C-030 a hand-written workflow must still be audited when another one is listed"


def test_c030_default_renders_no_ignore(tmp_path):
    repo = render_to(answers_file(tmp_path, "full-minimal"), tmp_path / "out")
    assert "ignore" not in (repo / ".github" / "zizmor.yml").read_text(), "C-030 the default policy file carries no ignore list"


@pytest.mark.parametrize("bad", ["release.yml", [".github/workflows/../x.yml"], ["release.yml"], [".github/workflows/a.txt"], [3], {"a": 1}])
def test_c030_malformed_zizmor_ignore_fails(tmp_path, bad):
    with pytest.raises(subprocess.CalledProcessError) as e:
        render_to(answers_file(tmp_path, "full-minimal", zizmor_ignore=bad), tmp_path / "out")
    assert "zizmor_ignore" in (e.value.stdout or "") + (e.value.stderr or ""), f"C-030 {bad!r} must fail naming zizmor_ignore"
