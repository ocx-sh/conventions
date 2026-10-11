"""C-019/C-020 grim artifacts validate; C-021 publishing config. Nothing is ever published for real."""
import re
import subprocess
import tomllib

import pytest
import yaml

from stubs import REPO_ROOT

RULE = REPO_ROOT / "rules" / "ocx-baseline.md"
SKILL = REPO_ROOT / "skills" / "ocx-baseline"
PUBLISH_TOML = REPO_ROOT / "publish.toml"
PUBLISH_YML = REPO_ROOT / ".github" / "workflows" / "publish.yml"
AUTH_FAILURE = re.compile(r"unauthori[sz]ed|denied|credential|login|authenticat|dns|connect|network|resolve", re.I)


def grim(*args, timeout=180):
    return subprocess.run(["grim", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout)


def test_rule_builds():
    assert RULE.exists(), "C-019 rules/ocx-baseline.md must exist"
    r = grim("build", str(RULE))
    assert r.returncode == 0, f"C-019 `grim build rules/ocx-baseline.md` must exit 0: {r.stdout}{r.stderr}"


def test_rule_content():
    assert RULE.exists(), "C-019 rules/ocx-baseline.md must exist"
    text = RULE.read_text()
    for needle in (".copier-answers.yml", "copier update", "ocx-contrib", "baseline:check"):
        assert needle in text, f"C-019 rule must mention {needle!r}"


def test_skill_builds():
    assert (SKILL / "SKILL.md").exists(), "C-020 skills/ocx-baseline/SKILL.md must exist"
    r = grim("build", str(SKILL))
    assert r.returncode == 0, f"C-020 `grim build skills/ocx-baseline` must exit 0: {r.stdout}{r.stderr}"


def test_skill_modes():
    p = SKILL / "SKILL.md"
    assert p.exists(), "C-020 skills/ocx-baseline/SKILL.md must exist"
    text = p.read_text()
    for mode in ("adopt", "modernize", "audit"):
        assert re.search(rf"\b{mode}\b", text, re.I), f"C-020 skill must describe mode {mode}"
    assert "scripts/adopt.sh" in text and "ocx-contrib" in text, "C-020 skill names the adopt script and the ocx-contrib-first rule"


def test_publish_toml_prefix():
    assert PUBLISH_TOML.exists(), "C-021 publish.toml must exist"
    assert tomllib.loads(PUBLISH_TOML.read_text()).get("repository_prefix") == "ocx-sh/conventions", \
        "C-021 publish.toml repository_prefix must be ocx-sh/conventions"


def test_publish_dry_run():
    assert PUBLISH_TOML.exists(), "C-021 publish.toml must exist"
    r = grim("publish", "--dry-run", "--version", "0.0.0")
    out = r.stdout + r.stderr
    if r.returncode != 0 and AUTH_FAILURE.search(out):
        pytest.skip(f"C-021 dry-run needs registry access here; only the grim build steps are asserted: {out[-300:]}")
    assert r.returncode == 0, f"C-021 `grim publish --dry-run --version 0.0.0` must exit 0: {out}"


def test_publish_workflow_only_on_version_tags():
    assert PUBLISH_YML.exists(), "C-021 .github/workflows/publish.yml must exist"
    wf = yaml.safe_load(PUBLISH_YML.read_text())
    on = wf.get("on", wf.get(True))
    assert isinstance(on, dict) and set(on) == {"push"}, f"C-021 publish.yml must trigger only on push: {on}"
    assert set(on["push"]) == {"tags"} and on["push"]["tags"] == ["v*"], f"C-021 publish.yml must trigger only on push tags ['v*']: {on['push']}"
