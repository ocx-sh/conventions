"""C-015 Renovate presets and C-016 Renovate runner workflow."""
import json
import re
import shutil
import subprocess
import tomllib

import pytest
import yaml

from stubs import FIXTURES, REPO_ROOT

RENOVATE_VERSION = "44.151.0"  # newest renovate at authoring time (npm view renovate version)
DEFAULT = REPO_ROOT / "renovate" / "default.json"
MIRROR = REPO_ROOT / "renovate" / "mirror.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "renovate.yml"
SHA_USES = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")

needs_npx = pytest.mark.skipif(shutil.which("npx") is None, reason="npx not installed")


def load(path, code="C-015"):
    assert path.exists(), f"{code} {path.relative_to(REPO_ROOT)} must exist"
    return json.loads(path.read_text())


def walk(node):
    """Yield every (key, value) pair in a nested JSON structure."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def py_re(js):
    # No re.M: Renovate matchStrings are not multiline, so `^` only anchors at the start of the file.
    return re.compile(js.replace("(?<", "(?P<").replace("(?P<=", "(?<=").replace("(?P<!", "(?<!"))


def managers(cfg):
    return cfg.get("customManagers", [])


def ocx_manager(cfg):
    for m in managers(cfg):
        pats = m.get("managerFilePatterns", m.get("fileMatch", []))
        if any(re.search(p.strip("/"), "ocx.toml") for p in pats):
            return m
    return None


def manager_enabled(cfg, name):
    return name in cfg.get("enabledManagers", []) or cfg.get(name, {}).get("enabled") is True


def validate(tmp_path, source):
    d = tmp_path / source.stem
    d.mkdir()
    shutil.copy(source, d / "renovate.json")
    r = subprocess.run(["npx", "--yes", "--package", f"renovate@{RENOVATE_VERSION}", "renovate-config-validator", "--strict"],
                       cwd=d, capture_output=True, text=True, timeout=600)
    return r, r.stdout + r.stderr


@needs_npx
@pytest.mark.parametrize("source", [DEFAULT, MIRROR, FIXTURES / "renovate" / "renovate.json"], ids=lambda p: p.parent.name + "/" + p.name)
def test_renovate_config_validator(tmp_path, source):
    assert source.exists(), f"C-015 {source.name} must exist"
    r, out = validate(tmp_path, source)
    assert r.returncode == 0 and "validated successfully" in out, f"C-015 renovate-config-validator --strict failed for {source.name}: {out[-1500:]}"


def test_fixture_extends_line():
    cfg = load(FIXTURES / "renovate" / "renovate.json")
    assert cfg == {"extends": ["github>ocx-sh/conventions//renovate/default#v0.1.0"]}, "C-015 rendered renovate.json shape"


def test_rendered_renovate_json_extends_preset(render):
    repo = render("full-minimal")
    p = repo / "renovate.json"
    assert p.exists(), "C-015 template-owned renovate.json must render"
    ext = json.loads(p.read_text())["extends"]
    assert len(ext) == 1 and re.fullmatch(r"github>ocx-sh/conventions//renovate/default#\S+", ext[0]), f"C-015 rendered extends: {ext}"
    mirror = json.loads((render("mirror") / "renovate.json").read_text())["extends"]
    assert re.fullmatch(r"github>ocx-sh/conventions//renovate/mirror#\S+", mirror[0]), f"C-015 mirror profile extends mirror preset: {mirror}"


def test_default_basics():
    cfg = load(DEFAULT)
    text = json.dumps(cfg)
    assert "config:recommended" in cfg.get("extends", []), "C-015 default must extend config:recommended"
    assert "helpers:pinGitHubActionDigests" in cfg.get("extends", []), "C-015 default must extend helpers:pinGitHubActionDigests"
    assert "schedule" in cfg and re.search(r"week|monday|tuesday|wednesday|thursday|friday|saturday|sunday", json.dumps(cfg["schedule"]).lower()), "C-015 weekly schedule"
    assert "ci(deps)" in text and "chore(deps)" in text, "C-015 semantic commits ci(deps)/chore(deps)"
    assert manager_enabled(cfg, "copier"), "C-015 copier manager must be enabled"
    assert manager_enabled(cfg, "bazel-module"), "C-015 bazel-module manager must be enabled"


def test_default_ignores_conventions_actions():
    cfg = load(DEFAULT)
    by_deps = any(s.startswith("ocx-sh/conventions") for s in cfg.get("ignoreDeps", []))
    by_rule = any(
        r.get("enabled") is False and "github-actions" in r.get("matchManagers", ["github-actions"])
        and any(s.startswith("ocx-sh/conventions") for k in ("matchPackageNames", "matchDepNames") for s in r.get(k, []))
        for r in cfg.get("packageRules", [])
    )
    assert by_deps or by_rule, "C-015/D-02 default must ignore ocx-sh/conventions action refs in github-actions"


def test_default_ocx_toml_regex_manager():
    cfg = load(DEFAULT)
    m = ocx_manager(cfg)
    assert m and m.get("customType") == "regex", "C-015 custom regex manager over ocx.toml required"
    assert m.get("datasourceTemplate", m.get("datasource")) == "docker", "C-015 ocx.toml manager uses the docker datasource"
    ver = m.get("versioningTemplate", m.get("versioning", ""))
    assert ver.startswith("regex:"), f"C-015 ocx.toml manager needs regex versioning: {ver!r}"
    vre = py_re(ver[len("regex:"):])
    assert vre.fullmatch("0.11.0") and not vre.fullmatch("0.11.0_20260819"), \
        "C-015 versioning regex must accept X.Y.Z and reject build-timestamped tags"
    texts = [t for t in strings(cfg) if "ocx lock" in t]
    assert any(t == "ocx lock" or t.startswith("ocx lock") for t in texts), "C-015 postUpgradeTasks must run `ocx lock`"
    assert any(k == "postUpgradeTasks" for k, _ in walk(cfg)), "C-015 postUpgradeTasks must be declared"


def test_regex_manager_extracts_exact_pins():
    m = ocx_manager(load(DEFAULT))
    assert m, "C-015 custom regex manager over ocx.toml required"
    content = (FIXTURES / "pin-exact" / "ocx.exact.toml").read_text()
    found = []
    for ms in m["matchStrings"]:
        for hit in py_re(ms).finditer(content):
            g = hit.groupdict()
            found.append((g.get("depName"), g.get("currentValue")))
    for dep, ver in [("ocx.sh/go-task/task", "3.53.1"), ("ocx.sh/prek/prek", "0.5.5"),
                     ("ocx.sh/gitleaks/gitleaks", "8.30.1"), ("ocx.sh/grimoire/cli", "0.14.3"),
                     ("ocx.sh/git-cliff/git-cliff", "2.14.2")]:
        assert (dep, ver) in found, f"C-015 regex manager must extract {dep} {ver}; got {found}"
    xyz = re.compile(r"\d+\.\d+\.\d+")
    for dep, ver in found:
        if dep == "ocx.sh/shellcheck/shellcheck":
            assert not (ver and xyz.fullmatch(ver)), f"C-015 build-timestamped tag must not look like an X.Y.Z pin: {ver!r}"


def test_default_other_managers():
    cfg = load(DEFAULT)
    text = json.dumps(cfg)
    assert "rules_ocx" in text and "bazel mod deps" in text, "C-015/D-12 bazel-module rule for rules_ocx with `bazel mod deps`"
    pv = [m for m in managers(cfg) if "COPIER_VERSION" in json.dumps(m) and "ZIZMOR_VERSION" in json.dumps(m)]
    assert pv and pv[0].get("datasourceTemplate", pv[0].get("datasource")) == "pypi", \
        "C-015/D-01 regex manager for COPIER_VERSION/ZIZMOR_VERSION with the pypi datasource"
    grouped = [r for r in cfg.get("packageRules", []) if r.get("groupName") and "ocx-sh/website" in json.dumps(r) and "@ocx-sh/theme" in json.dumps(r)]
    assert grouped, "C-015 ocx-sh/website deploy action must be grouped with @ocx-sh/theme"


PRESETS = pytest.mark.parametrize("path", [DEFAULT, MIRROR], ids=lambda p: p.stem)


def extract(manager, content):
    return [(h.groupdict().get("depName"), h.groupdict().get("currentValue"))
            for ms in manager["matchStrings"] for h in py_re(ms).finditer(content)]


def glob_re(glob):
    return re.compile("".join(".*" if t == "**" else "[^/]*" if t == "*" else re.escape(t) for t in re.split(r"(\*\*|\*)", glob)) + r"\Z")


@PRESETS
def test_copier_zizmor_manager_extracts_real_taskfile(path):
    cfg = load(path)
    m = next((m for m in managers(cfg) if "COPIER_VERSION" in json.dumps(m)), None)
    assert m, "C-015/D-01 regex manager for COPIER_VERSION/ZIZMOR_VERSION required"
    for rel in ("template/taskfiles/baseline.taskfile.yml", "taskfiles/baseline.taskfile.yml"):
        assert any(re.search(pat.strip("/"), rel) for pat in m["managerFilePatterns"]), f"C-015 manager must target {rel}"
    tf = REPO_ROOT / "template" / "taskfiles" / "baseline.taskfile.yml"
    want = yaml.safe_load(tf.read_text())["vars"]
    found = set(extract(m, tf.read_text()))
    assert {("COPIER", want["COPIER_VERSION"]), ("ZIZMOR", want["ZIZMOR_VERSION"])} <= found, \
        f"C-015 manager must extract both versions from the real baseline taskfile (non-multiline); got {found}"


@PRESETS
def test_ocx_lock_rule_matches_extracted_dep_names(path):
    cfg = load(path)
    m = ocx_manager(cfg)
    rule = next((r for r in cfg["packageRules"] if "ocx lock" in json.dumps(r.get("postUpgradeTasks", {}))), None)
    assert rule, "C-015 a packageRule must run `ocx lock`"
    assert "custom.regex" in rule.get("matchManagers", []), "C-015 ocx lock rule must target the custom.regex manager"
    # packageNameTemplate rewrites packageName to ghcr.io/..., so only depName selectors can match.
    assert "matchPackageNames" not in rule and rule.get("matchDepNames"), "C-015 ocx lock rule must select by matchDepNames"
    deps = [d for d, _ in extract(m, (FIXTURES / "pin-exact" / "ocx.exact.toml").read_text())]
    assert deps and all(any(glob_re(g).match(d) for g in rule["matchDepNames"]) for d in deps), \
        f"C-015 ocx lock selector {rule['matchDepNames']} must match extracted depNames {deps}"


@PRESETS
def test_template_owned_workflows_excluded_from_github_actions(path):
    cfg = load(path)
    manifest = tomllib.loads((REPO_ROOT / "MANIFEST.toml").read_text())["file"]
    owned = [f["path"] for f in manifest if f["class"] == "template-owned" and f["path"].startswith(".github/workflows/")]
    assert owned, "MANIFEST.toml must list template-owned workflows"
    off = [r for r in cfg["packageRules"] if r.get("enabled") is False and "github-actions" in r.get("matchManagers", []) and r.get("matchFileNames")]
    covered = lambda f: any(glob_re(g).match(f) for r in off for g in r["matchFileNames"])
    assert all(covered(f) for f in owned), f"C-015/D-02 template-owned workflows must be disabled for github-actions: {[f for f in owned if not covered(f)]}"
    assert not covered(".github/workflows/publish.yml"), "C-015 repo-owned workflows stay Renovate-managed"


def test_mirror_has_no_npm_or_bazel():
    cfg = load(MIRROR)
    text = json.dumps(cfg)
    for bad in ("bazel", "npm", "@ocx-sh/theme", "renovate/default"):
        assert bad not in text, f"C-015 mirror preset must not contain {bad!r}"
    assert "config:recommended" in cfg.get("extends", []) and manager_enabled(cfg, "copier"), \
        "C-015 mirror keeps config:recommended and the copier manager"
    assert ocx_manager(cfg), "C-015 mirror keeps the ocx.toml regex manager"


# ---- C-016 runner workflow ----

def load_wf():
    assert WORKFLOW.exists(), "C-016 .github/workflows/renovate.yml must exist"
    return yaml.safe_load(WORKFLOW.read_text())


def all_steps(wf):
    return [s for j in wf["jobs"].values() for s in j.get("steps", [])]


def test_runner_triggers_and_permissions():
    wf = load_wf()
    on = wf.get("on", wf.get(True))
    assert {"schedule", "workflow_dispatch"} <= set(on), f"C-016 triggers must include schedule + workflow_dispatch: {on}"
    assert wf.get("permissions") == {}, "C-016 top-level `permissions: {}`"


def test_runner_app_token_and_skip():
    wf = load_wf()
    steps = all_steps(wf)
    tok = [s for s in steps if str(s.get("uses", "")).startswith("actions/create-github-app-token@")]
    assert tok and SHA_USES.match(tok[0]["uses"]), f"C-016 create-github-app-token must be pinned by 40-hex SHA: {[s.get('uses') for s in tok]}"
    skip = [s for s in steps if "RENOVATE_APP_ID" in json.dumps(s) and "::notice" in str(s.get("run", "")) and "exit 0" in str(s.get("run", ""))]
    assert skip, "C-016 a step must emit a notice and exit 0 when RENOVATE_APP_ID is empty"


def test_runner_repositories_from_fleet_toml():
    assert WORKFLOW.exists(), "C-016 .github/workflows/renovate.yml must exist"
    text = WORKFLOW.read_text()
    assert "RENOVATE_REPOSITORIES" in text, "C-016 RENOVATE_REPOSITORIES must be set"
    assert "fleet.toml" in text and "adopted" in text, "C-016 RENOVATE_REPOSITORIES must derive from fleet.toml adopted=true"
    assert "ocx lock" in text, "C-016/D-03 allowedCommands must include `ocx lock`"
    fleet = tomllib.loads((REPO_ROOT / "fleet.toml").read_text())
    assert all("adopted" in v for v in fleet["repos"].values()), "C-016 fleet.toml needs an `adopted` flag on every repo"


def test_runner_token_scoped_per_owner_with_explicit_permissions():
    wf = load_wf()
    tok = next(s for s in all_steps(wf) if str(s.get("uses", "")).startswith("actions/create-github-app-token@"))["with"]
    assert "matrix.owner" in tok.get("owner", "") and "matrix.names" in tok.get("repositories", ""), \
        f"C-016 token must be scoped to the matrix owner and its repositories: {tok}"
    perms = {k: v for k, v in tok.items() if k.startswith("permission-")}
    assert perms == {"permission-contents": "write", "permission-pull-requests": "write", "permission-workflows": "write",
                     "permission-issues": "write", "permission-metadata": "read"}, f"C-016 explicit token permissions: {perms}"


def test_runner_installs_copier_and_allows_only_postupgrade_commands():
    wf = load_wf()
    text = WORKFLOW.read_text()
    assert any("uv tool install" in str(s.get("run", "")) and "copier" in str(s.get("run", "")) for s in all_steps(wf)), "C-016 copier must be installed in the job"
    assert "uvx" not in text.split("RENOVATE_ALLOWED_COMMANDS")[1].splitlines()[0], "C-016 allowedCommands must not carry a dead uvx entry"
