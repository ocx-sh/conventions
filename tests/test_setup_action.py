"""C-011 setup composite action (.github/actions/setup/action.yml)."""
import os
import re
import subprocess

import pytest
import yaml

from stubs import REPO_ROOT

ACTION = REPO_ROOT / ".github" / "actions" / "setup" / "action.yml"
SHA = re.compile(r"@[0-9a-f]{40}(\s|$)")
EXPR = re.compile(r"\$\{\{.*?\}\}", re.S)


def load():
    assert ACTION.exists(), "C-011 .github/actions/setup/action.yml must exist"
    return yaml.safe_load(ACTION.read_text())


def steps(action):
    return action["runs"]["steps"]


def cond(step):
    return str(step.get("if", ""))


def blob(step):
    return yaml.safe_dump(step)


def cache_steps(action):
    return [s for s in steps(action) if "bazel-cache.rc" in blob(s) or "BAZELRC" in blob(s)]


def otel_steps(action):
    return [s for s in steps(action) if "OTEL_EXPORTER_OTLP_ENDPOINT" in blob(s)]


def test_inputs():
    action = load()
    assert action["runs"]["using"] == "composite", "C-011 action must be composite"
    ins = action["inputs"]
    for name in ("groups", "bazel-cache", "cache-read-auth", "cache-write-auth", "otel-auth"):
        assert name in ins, f"C-011 missing input {name}"
    assert str(ins["bazel-cache"].get("default")) == "off", "C-011 bazel-cache must default to off"


def test_setup_ocx_pinned_with_groups():
    action = load()
    ss = [s for s in steps(action) if "setup-ocx" in str(s.get("uses", ""))]
    assert ss, "C-011 a setup-ocx step is required"
    s = ss[0]
    assert SHA.search(s["uses"] + "\n"), f"C-011 setup-ocx must be pinned by 40-hex SHA: {s['uses']}"
    assert "inputs.groups" in str(s.get("with", {}).get("groups", "")), "C-011 setup-ocx `groups` must be wired to inputs.groups"


def test_cache_rc_step_guards():
    action = load()
    cs = cache_steps(action)
    assert cs, "C-011 a step writing bazel-cache.rc / exporting BAZELRC is required"
    for s in cs:
        c = cond(s)
        assert re.search(r"inputs\.bazel-cache\s*!=\s*'off'", c), f"C-011 cache step needs `inputs.bazel-cache != 'off'` in if: {c!r}"
        assert re.search(r"inputs\.cache-(read|write)-auth\s*!=\s*''", c), f"C-011 cache step needs a non-empty auth check in if: {c!r}"


def test_write_auth_only_on_default_branch_push():
    action = load()
    ws = [s for s in cache_steps(action) if "cache-write-auth" in blob(s)]
    assert ws, "C-011 write auth must be consumed by a cache step"
    for s in ws:
        text = cond(s) + "\n" + str(s.get("run", ""))
        assert "github.event_name == 'push'" in text, f"C-011 write auth only on push: {text!r}"
        assert "default_branch" in text, f"C-011 write auth only on the default branch: {text!r}"


def test_telemetry_step():
    action = load()
    ts = otel_steps(action)
    assert ts, "C-011 a telemetry step exporting OTEL_EXPORTER_OTLP_ENDPOINT is required"
    for s in ts:
        assert re.search(r"inputs\.otel-auth\s*!=\s*''", cond(s)), f"C-011 telemetry needs `inputs.otel-auth != ''` in if: {cond(s)!r}"
        assert "https://otel.ocx.sh" in blob(s), "C-011 telemetry endpoint must be https://otel.ocx.sh"


def test_junit_post_step_is_non_fatal():
    action = load()
    js = [s for s in steps(action) if "junit" in blob(s).lower()]
    assert js, "C-011/C-012 a JUnit telemetry post step is required"
    for s in js:
        assert "always()" in cond(s), f"C-011 JUnit step must run `if: always()`: {cond(s)!r}"
        assert s.get("continue-on-error") in (True, "true") or "::warning" in str(s.get("run", "")), \
            "C-011 JUnit telemetry must be continue-on-error or warning-only"


def _script_env(step, tmp_path):
    """Run a `run:` script with every ${{ expression }} (inputs, secrets, github.*) evaluated empty."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OTEL_", "BAZEL"))}
    runner_tmp = tmp_path / "runner_tmp"
    runner_tmp.mkdir()
    gh_env, gh_path = tmp_path / "github_env", tmp_path / "github_path"
    gh_env.write_text("")
    gh_path.write_text("")
    env.update(RUNNER_TEMP=str(runner_tmp), GITHUB_ENV=str(gh_env), GITHUB_PATH=str(gh_path), CI="true")
    for k, v in (step.get("env") or {}).items():
        env[k] = EXPR.sub("", str(v))
    return env, runner_tmp, gh_env, gh_path


@pytest.mark.parametrize("which", ["cache", "otel"])
def test_empty_secrets_never_fail_or_write(tmp_path, which):
    action = load()
    sel = cache_steps(action) if which == "cache" else otel_steps(action)
    assert sel, f"C-011 {which} step required"
    for i, s in enumerate(sel):
        if "run" not in s:
            continue
        d = tmp_path / f"{which}{i}"
        d.mkdir()
        env, rtmp, gh_env, gh_path = _script_env(s, d)
        script = EXPR.sub("", s["run"])
        r = subprocess.run(["bash", "-e", "-c", script], env=env, cwd=d, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, f"C-011 empty secrets must not fail the job (step {i}): {r.stderr}"
        assert not list(rtmp.iterdir()), "C-011 empty secrets must not write a bazel-cache.rc"
        assert gh_env.read_text() == "" and gh_path.read_text() == "", "C-011 empty secrets must not export anything"
