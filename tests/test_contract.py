"""Contract tests: every assertion message starts with the C-ID it pins, so a red run names the unimplemented contract.

Fast tests render fixtures once per session (copier on the dirty working tree). Tests marked `slow` run task/ocx and need network.
"""

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import FIXTURES, REPO_ROOT, git_env_dict, ocx_lock_committed, ocx_task, render_to, run

ALL = ["full-bazel-site", "full-python-site", "full-minimal", "mirror"]
FULL = ["full-bazel-site", "full-python-site", "full-minimal"]
LANGS = ["bazel", "cmake", "dotnet", "go", "jvm", "nix", "python", "rust", "shell", "swift", "typescript"]
OS_ALL = ["ubuntu-latest", "macos-latest", "windows-latest"]
SENTINEL = "# ocx-baseline: template-owned file — change ocx-sh/conventions, then run task copier:update"
ROLES = ["lint", "test", "build", "docs", "release"]
SHA = r"[0-9a-f]{40}"


# ---------------------------------------------------------------- helpers

def answers(name):
    return yaml.safe_load((FIXTURES / "answers" / f"{name}.yml").read_text())


def manifest():
    return tomllib.loads((REPO_ROOT / "MANIFEST.toml").read_text())


def expected_files(name, cls=None):
    """Rendered path set the MANIFEST promises for this answers file (profile + `when`)."""
    a = answers(name)
    profile = a.get("profile", "full")
    site = a.get("site") or None
    cond = {"bazel": bool(a.get("bazel")) and profile == "full", "site": site is not None,
            "site.deploy": site is not None and bool(site.get("deploy"))}
    out = set()
    for f in manifest()["file"]:
        if profile not in f["profiles"]:
            continue
        if "when" in f and not cond[f["when"]]:
            continue
        if cls and f["class"] != cls:
            continue
        out.add(f["path"])
    return out


def rendered_files(repo):
    return {p.relative_to(repo).as_posix() for p in repo.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(repo).parts}


@pytest.fixture(scope="session")
def rendered(tmp_path_factory):
    """rendered(name) -> read-only rendered+committed repo, cached for the session. Mutating tests use the `render` fixture."""
    cache = {}

    def get(name):
        if name not in cache:
            cache[name] = render_to(name, tmp_path_factory.mktemp("r") / name)
        return cache[name]

    return get


def need(cid, repo, rel):
    p = repo / rel
    assert p.is_file(), f"{cid}: {rel} is not rendered in {repo.name}"
    return p


def load_yaml(cid, repo, rel):
    return yaml.safe_load(need(cid, repo, rel).read_text())


def load_toml(cid, repo, rel):
    return tomllib.loads(need(cid, repo, rel).read_text())


def triggers(wf):
    on = wf.get("on", wf.get(True))  # pyyaml reads the key `on` as boolean True
    if isinstance(on, str):
        return {on: {}}
    if isinstance(on, list):
        return {k: {} for k in on}
    return {k: (v or {}) for k, v in on.items()}


def workflow_names(repo):
    d = repo / ".github" / "workflows"
    return sorted(p.name for p in d.glob("*.yml")) if d.is_dir() else []


def steps(job):
    return job.get("steps", [])


def job_runs(job):
    return "\n".join(s.get("run", "") for s in steps(job))


def repo_ocx_toml_text(repo):
    return (repo / "ocx.toml").read_text()


# ---------------------------------------------------------------- C-001

def test_c001_copier_has_no_unsafe_features():
    cfg = yaml.safe_load((REPO_ROOT / "copier.yml").read_text())
    bad = {"_tasks", "_migrations", "_jinja_extensions"} & set(cfg)
    assert not bad, f"C-001: copier.yml must not use {sorted(bad)} (--trust must never be needed)"
    assert cfg.get("_subdirectory") == "template", "C-001: copier.yml must set _subdirectory: template"
    assert (REPO_ROOT / "template" / "{{ _copier_conf.answers_file }}.jinja").is_file(), \
        "C-001: template/{{ _copier_conf.answers_file }}.jinja (copier's required answers-file name) is missing"


def test_c001_skip_if_exists_matches_seeded_once():
    cfg = yaml.safe_load((REPO_ROOT / "copier.yml").read_text())
    seeded = {f["path"] for f in manifest()["file"] if f["class"] == "seeded-once"}
    assert set(cfg.get("_skip_if_exists", [])) == seeded, "C-001: _skip_if_exists must equal the seeded-once paths of MANIFEST.toml"


def test_c001_unknown_language_fails_naming_allowed_list(tmp_path):
    with pytest.raises(subprocess.CalledProcessError) as e:
        render_to("bad-language", tmp_path / "x")
    out = (e.value.stdout or "") + (e.value.stderr or "")
    missing = [lang for lang in ["cobol", *LANGS] if lang not in out]
    assert not missing, f"C-001: unknown-language error must name the offending entry and the allowed list; missing {missing}"


def test_c001_mirror_renders_no_bazel_site_or_deep_files(rendered):
    files = rendered_files(rendered("mirror"))
    bad = sorted(f for f in files if f.startswith("bazel/") or f in {".bazelrc", "MODULE.bazel"}
                 or Path(f).name in {"deploy-site.yml", "verify-deep.yml"} or f.startswith("site/"))
    assert not bad, f"C-001: profile mirror must ignore bazel/site/deep_os answers, but rendered {bad}"


# ---------------------------------------------------------------- C-002

@pytest.mark.parametrize("name", ALL)
def test_c002_rendered_tree_equals_manifest(rendered, name):
    got, want = rendered_files(rendered(name)), expected_files(name)
    assert got == want, f"C-002: rendered tree != MANIFEST for {name}; extra={sorted(got - want)} missing={sorted(want - got)}"


# ---------------------------------------------------------------- C-003

BASELINE_TASKS = ["setup", "hooks:install", "lock:check", "grim:check", "secrets", "baseline:check",
                  "release:prepare", "copier:update"]
ROOT_TASKS = ["verify", "ci:lint", "ci:test", "ci:build", "ci:docs", "ci:deep"]


@pytest.mark.parametrize("name", ALL)
def test_c003_baseline_taskfile_interface(rendered, name):
    repo = rendered(name)
    tasks = load_yaml("C-003", repo, "taskfiles/baseline.taskfile.yml").get("tasks", {})
    missing = [t for t in BASELINE_TASKS if t not in tasks]
    assert not missing, f"C-003: taskfiles/baseline.taskfile.yml lacks tasks {missing}"


@pytest.mark.parametrize("name", ALL)
def test_c003_root_taskfile_includes_baseline_flat_and_defines_ci(rendered, name):
    repo = rendered(name)
    root = load_yaml("C-003", repo, "taskfile.yml")
    inc = [v for v in (root.get("includes") or {}).values()
           if isinstance(v, dict) and str(v.get("taskfile", "")).endswith("baseline.taskfile.yml")]
    assert inc and all(v.get("flatten") is True for v in inc), \
        "C-003: root taskfile.yml must include taskfiles/baseline.taskfile.yml with flatten: true"
    missing = [t for t in ROOT_TASKS if t not in (root.get("tasks") or {})]
    assert not missing, f"C-003: root taskfile.yml lacks tasks {missing}"


def test_c003_template_first_line_sentinel(rendered):
    # The update-n1 self-test (C-022) rewrites exactly this line, so the template must honour it.
    first = need("C-003", rendered("full-minimal"), "taskfiles/baseline.taskfile.yml").read_text().split("\n", 1)[0]
    assert first == SENTINEL, f"C-003: line 1 of taskfiles/baseline.taskfile.yml must be exactly {SENTINEL!r}, got {first!r}"



@pytest.mark.slow
def test_c003_missing_ci_task_fails_baseline_check(render):
    repo = render("full-minimal")
    path = need("C-003", repo, "taskfile.yml")
    data = yaml.safe_load(path.read_text())
    assert "ci:docs" in data["tasks"], "C-003: root taskfile.yml must define ci:docs"
    del data["tasks"]["ci:docs"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    r = ocx_task(repo, "baseline:check")
    assert r.returncode != 0 and "ci:docs" in r.stdout + r.stderr, \
        f"C-003: baseline:check must fail naming ci:docs (rc={r.returncode})\n{(r.stdout + r.stderr)[-600:]}"


# ---------------------------------------------------------------- C-005

REF = re.compile(r"^ocx\.sh/[^:]+:\d+\.\d+\.\d+$")


def ocx_tools(cfg):
    tools = {("default", k): v for k, v in (cfg.get("tools") or {}).items()}
    for g, body in (cfg.get("group") or {}).items():
        tools.update({(g, k): v for k, v in (body.get("tools") or {}).items()})
    return tools


@pytest.mark.parametrize("name", ALL)
def test_c005_ocx_toml_pins_and_baseline_tools(rendered, name):
    cfg = load_toml("C-005", rendered(name), "ocx.toml")
    tools = ocx_tools(cfg)
    bad = {f"{g}/{k}": v for (g, k), v in tools.items() if not (isinstance(v, str) and REF.match(v))}
    assert not bad, f"C-005: every tool ref must be an exact X.Y.Z version, offenders: {bad}"
    want = [("default", "task"), ("lint", "prek"), ("lint", "gitleaks"), ("lint", "grim"), ("lint", "uv"), ("release", "git-cliff")]
    assert not [w for w in want if w not in tools], f"C-005: baseline tools missing: {[w for w in want if w not in tools]}"
    groups = set(cfg.get("group") or {})
    assert groups <= set(ROLES), f"C-005: groups {sorted(groups - set(ROLES))} are outside {ROLES}"


@pytest.mark.parametrize("name", FULL)
def test_c005_every_group_a_workflow_requests_is_declared(rendered, name):
    repo = rendered(name)
    declared = {"default"} | set(load_toml("C-005", repo, "ocx.toml").get("group") or {})
    for fname, raw in all_workflows(repo):
        for m in re.finditer(r"^\s*groups:\s*(\S+)\s*$", raw, re.M):
            missing = set(m.group(1).split(",")) - declared
            assert not missing, f"C-005: {fname} requests ocx groups {sorted(missing)} that ocx.toml does not declare (ocx exits 64: unknown group)"


def _mutate_ocx_toml(repo, fn):
    p = need("C-005", repo, "ocx.toml")
    p.write_text(fn(p.read_text()))


def _break_pin(t):
    new = re.sub(r"(gitleaks/gitleaks):\d+\.\d+\.\d+", r"\1:latest", t)
    assert new != t, "C-005: rendered ocx.toml has no gitleaks ref to break"
    return new


def _drop_gitleaks(t):
    new = re.sub(r"(?m)^gitleaks\s*=.*\n", "", t)
    assert new != t, "C-005: rendered ocx.toml has no gitleaks line to drop"
    return new


@pytest.mark.slow
@pytest.mark.parametrize("label,fn,needle", [
    ("latest-pin", _break_pin, "gitleaks"),
    ("no-gitleaks", _drop_gitleaks, "gitleaks"),
    ("unknown-group", lambda t: t + '\n[group.misc.tools]\nfoo = "ocx.sh/foo/foo:1.0.0"\n', "misc"),
])
def test_c005_violation_fails_baseline_check(render, label, fn, needle):
    repo = render("full-minimal")
    _mutate_ocx_toml(repo, fn)
    r = ocx_task(repo, "baseline:check", locked=False)  # ocx.lock is stale after the edit, so skip `ocx exec`
    assert r.returncode != 0 and needle in r.stdout + r.stderr, \
        f"C-005: baseline:check must fail naming {needle!r} for {label} (rc={r.returncode})\n{(r.stdout + r.stderr)[-600:]}"


# ---------------------------------------------------------------- C-006

# Lore ships <lang>-essentials for all eleven copier languages (grimoire-lore/bundles/*.toml), plus
# docs-essentials and code-docs-essentials. `ocx-theme` is not a lore bundle (OCX theme repo), asserted by name only.
def expected_bundles(name):
    a = answers(name)
    want = {"docs-essentials", "code-docs-essentials"}
    want |= {f"{lang}-essentials" for lang in a.get("languages", [])}
    if a.get("theme_bundle"):
        want.add("ocx-theme")
    return want


@pytest.mark.parametrize("name", FULL)
def test_c006_grimoire_toml_clients_and_bundles(rendered, name):
    cfg = load_toml("C-006", rendered(name), "grimoire.toml")
    clients = set((cfg.get("options") or {}).get("clients", []))
    assert {"claude", "codex", "opencode"} <= clients, f"C-006: clients must contain claude, codex, opencode, got {sorted(clients)}"
    bundles = set(cfg.get("bundles") or {})
    missing = expected_bundles(name) - bundles
    assert not missing, f"C-006: grimoire.toml [bundles] lacks {sorted(missing)}"
    if not answers(name).get("theme_bundle"):
        assert "ocx-theme" not in bundles, "C-006: ocx-theme must be present iff theme_bundle"


def test_c006_mirror_has_clients_and_core_bundles(rendered):
    cfg = load_toml("C-006", rendered("mirror"), "grimoire.toml")
    assert {"claude", "codex", "opencode"} <= set((cfg.get("options") or {}).get("clients", [])), "C-006: mirror clients must contain claude, codex, opencode"
    assert {"docs-essentials", "code-docs-essentials"} <= set(cfg.get("bundles") or {}), "C-006: mirror bundles must contain docs-essentials, code-docs-essentials"


@pytest.mark.slow
def test_c006_removing_codex_fails_baseline_check(render):
    repo = render("full-minimal")
    p = need("C-006", repo, "grimoire.toml")
    t = re.sub(r',?\s*"codex"', "", p.read_text(), count=1)
    p.write_text(t)
    assert "codex" not in (tomllib.loads(t).get("options") or {}).get("clients", []), "C-006: could not remove codex from rendered clients"
    r = ocx_task(repo, "baseline:check")
    assert r.returncode != 0 and "codex" in r.stdout + r.stderr, \
        f"C-006: baseline:check must fail naming codex (rc={r.returncode})\n{(r.stdout + r.stderr)[-600:]}"


# ---------------------------------------------------------------- C-007 / C-008

def prek_hooks(repo):
    cfg = load_yaml("C-007", repo, ".pre-commit-config.yaml")
    return cfg, [h for r in cfg.get("repos", []) for h in r.get("hooks", [])]


def hook_argv(hook):
    import shlex
    return shlex.split(hook["entry"]) + [str(a) for a in hook.get("args", [])]


@pytest.mark.parametrize("name", ALL)
def test_c007_prek_config(rendered, name):
    cfg, hooks = prek_hooks(rendered(name))
    assert cfg.get("default_install_hook_types") == ["pre-commit", "commit-msg"], \
        f"C-007: default_install_hook_types must be [pre-commit, commit-msg], got {cfg.get('default_install_hook_types')}"
    gl = [h for h in hooks if "gitleaks" in " ".join(hook_argv(h))]
    assert gl and "--staged" in hook_argv(gl[0]) and "--redact" in hook_argv(gl[0]), \
        "C-007: a local hook must run `gitleaks git --staged --redact`"
    assert [h for h in hooks if "commit-msg" in h.get("stages", [])], "C-007: a hook with stages: [commit-msg] (conventional subject check) is missing"
    shells = [h["id"] for h in hooks if hook_argv(h)[0] in ("sh", "bash", "zsh", "dash", "cmd", "powershell", "pwsh")]
    assert not shells, f"C-007 (Q9): hook entries must be shell-free so they run on Windows; shell entries: {shells}"


TYPES = "feat fix docs style refactor perf test build ci chore revert".split()


@pytest.mark.parametrize("subject,ok", [("bad subject", False), ("feat(x): y", True)])
def test_c007_commit_msg_hook_enforces_conventional_subject(rendered, tmp_path, subject, ok):
    repo = rendered("full-minimal")
    _, hooks = prek_hooks(repo)
    cm = [h for h in hooks if "commit-msg" in h.get("stages", [])]
    assert cm, "C-007: a hook with stages: [commit-msg] is missing"
    ocx_lock_committed(repo)  # the entry is `ocx exec -- task hooks:commit-msg`
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(subject + "\n")
    r = run([*hook_argv(cm[0]), msg], repo, git_env_dict(), check=False, timeout=120)  # prek passes the message file as the last arg
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0, f"C-007: subject {subject!r} must pass, rc={r.returncode}\n{out[-400:]}"
    else:
        assert r.returncode == 1, f"C-007: subject {subject!r} must exit 1, rc={r.returncode}\n{out[-400:]}"
        assert all(t in out for t in TYPES), f"C-007: rejection must name the allowed types {TYPES}\n{out[-400:]}"


def test_c007_commit_msg_hook_accepts_message_path_with_spaces(rendered, tmp_path):
    repo = rendered("full-minimal")
    _, hooks = prek_hooks(repo)
    cm = [h for h in hooks if "commit-msg" in h.get("stages", [])]
    ocx_lock_committed(repo)
    msg = tmp_path / "with space" / "COMMIT_EDITMSG"
    msg.parent.mkdir()
    msg.write_text("feat: y\n")  # an unreadable file reads as an empty subject, which the hook rejects
    r = run([*hook_argv(cm[0]), msg], repo, git_env_dict(), check=False, timeout=120)
    assert r.returncode == 0, f"C-007: a message path with spaces must be read, rc={r.returncode}\n{(r.stdout + r.stderr)[-400:]}"


def test_c009_workflows_lint_scans_whole_github_dir(rendered):
    text = need("C-009", rendered("full-minimal"), "taskfiles/baseline.taskfile.yml").read_text()
    line = next(ln for ln in text.splitlines() if "zizmor --" in ln)
    assert line.rstrip().endswith(" .github") and "--no-online-audits" in line, f"C-009: zizmor must scan .github (workflows and actions), offline: {line!r}"


@pytest.mark.parametrize("name", ALL)
def test_c008_gitleaks_config(rendered, name):
    cfg = load_toml("C-008", rendered(name), ".gitleaks.toml")
    assert (cfg.get("extend") or {}).get("useDefault") is True, "C-008: .gitleaks.toml needs [extend] useDefault = true"
    assert isinstance(cfg.get("allowlist"), dict), "C-008: .gitleaks.toml needs an [allowlist] table"


# ---------------------------------------------------------------- workflows (C-009 C-010 C-013 C-014, D-02)

USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)(.*)$", re.M)
PINNED = re.compile(rf"^[\w.-]+/[\w.-]+(/[^@\s]+)?@{SHA}$")


def all_workflows(repo):
    return [(n, (repo / ".github" / "workflows" / n).read_text()) for n in workflow_names(repo)]


@pytest.mark.parametrize("name", ALL)
def test_c009_all_workflows_hardened(rendered, name):
    repo = rendered(name)
    wfs = all_workflows(repo)
    assert wfs, f"C-009: no workflows rendered for {name}"
    for fname, raw in wfs:
        data = yaml.safe_load(raw)
        assert data.get("permissions") == {}, f"C-009: {fname} must set top-level `permissions: {{}}`"
        for ref, rest in USES.findall(raw):
            if ref.startswith("./"):
                continue
            assert PINNED.match(ref), f"C-009: {fname} `uses: {ref}` must be owner/repo@<40-hex>"
            assert re.match(r"\s*#\s*v\d", rest), f"C-009: {fname} `uses: {ref}` needs a trailing `# vX` comment"
        for jname, job in (data.get("jobs") or {}).items():
            for s in steps(job):
                if str(s.get("uses", "")).startswith("actions/checkout@"):
                    pc = (s.get("with") or {}).get("persist-credentials")
                    assert str(pc).lower() == "false", f"C-009: {fname} job {jname} checkout needs persist-credentials: false"


@pytest.mark.parametrize("name", ALL)
def test_c009_verify_basic_shape(rendered, name):
    a = answers(name)
    full = a.get("profile", "full") == "full"
    wf = load_yaml("C-009", rendered(name), ".github/workflows/verify-basic.yml")
    trig = triggers(wf)
    assert {"pull_request", "push", "merge_group", "workflow_dispatch"} <= set(trig), f"C-009: verify-basic triggers incomplete: {sorted(trig)}"
    assert trig["push"].get("branches") == ["main"], "C-009: verify-basic push trigger must be branches: [main]"
    assert not [k for v in trig.values() for k in v if k in ("paths", "paths-ignore")], "C-009: verify-basic must have no path filters"
    jobs = wf["jobs"]
    want = {"lint", "basic-gate"}
    if full:
        want |= {"test"} | ({"build"} if a.get("bazel") else set()) | ({"docs"} if a.get("site") else set())
    assert set(jobs) == want, f"C-009: verify-basic jobs {sorted(jobs)} != expected {sorted(want)}"
    gate = jobs["basic-gate"]
    assert "always()" in str(gate.get("if")), "C-009: basic-gate needs `if: always()`"
    assert set(gate.get("needs", [])) == want - {"basic-gate"}, "C-009: basic-gate must need every other job"
    for role in want - {"basic-gate"}:
        job = jobs[role]
        setup = [s for s in steps(job) if "conventions/.github/actions/setup" in str(s.get("uses", ""))]
        assert setup and (setup[0].get("with") or {}).get("groups") == f"default,{role}", f"C-009: job {role} needs the setup action with groups: default,{role}"
        assert f"task ci:{role}" in job_runs(job), f"C-009: job {role} must run `task ci:{role}`"
    for cmd in ["task lock:check", "task baseline:check", "task secrets", "actionlint", "zizmor"]:
        assert cmd in job_runs(jobs["lint"]), f"C-009: lint job must run `{cmd}`"
    lint_checkout = [s for s in steps(jobs["lint"]) if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert lint_checkout and (lint_checkout[0].get("with") or {}).get("fetch-depth") == 0, \
        "C-009: lint checkout needs fetch-depth: 0 (task secrets scans git history)"


def nightly_minute(repo_name):
    return int(hashlib.sha256(repo_name.encode()).hexdigest()[:4], 16) % 60


@pytest.mark.parametrize("name", FULL)
def test_c010_verify_deep_shape(rendered, name):
    a = answers(name)
    wf = load_yaml("C-010", rendered(name), ".github/workflows/verify-deep.yml")
    trig = triggers(wf)
    assert {"schedule", "workflow_dispatch", "workflow_call", "pull_request"} <= set(trig), f"C-010: verify-deep triggers incomplete: {sorted(trig)}"
    assert trig["schedule"] == [{"cron": f"{nightly_minute(a['repo_name'])} 3 * * *"}], \
        f"C-010: cron must be '{nightly_minute(a['repo_name'])} 3 * * *', got {trig['schedule']}"
    assert trig["pull_request"].get("types") == ["labeled"], "C-010: pull_request types must be [labeled]"
    assert not [k for v in trig.values() if isinstance(v, dict) for k in v if k in ("paths", "paths-ignore")], "C-010: no path filters"
    oses = [j["strategy"]["matrix"]["os"] for j in wf["jobs"].values() if "os" in ((j.get("strategy") or {}).get("matrix") or {})]
    assert oses and all(sorted(o) == sorted(a["deep_os"]) for o in oses), f"C-010: matrix os {oses} != deep_os {a['deep_os']}"
    assert "task ci:deep" in "\n".join(job_runs(j) for j in wf["jobs"].values()), "C-010: verify-deep must run `task ci:deep`"


@pytest.mark.parametrize("name", ALL)
def test_c014_deploy_site_iff_site_deploy(rendered, name):
    a = answers(name)
    repo = rendered(name)
    deploy = bool((a.get("site") or {}).get("deploy"))
    present = (repo / ".github/workflows/deploy-site.yml").is_file()
    assert present == deploy, f"C-014: deploy-site.yml present={present}, expected {deploy} (site.deploy)"
    if not deploy:
        return
    raw = (repo / ".github/workflows/deploy-site.yml").read_text()
    wf = yaml.safe_load(raw)
    trig = triggers(wf)
    assert set(trig) == {"push", "workflow_dispatch"}, f"C-014: deploy-site triggers must be push + workflow_dispatch only, got {sorted(trig)}"
    assert trig["push"].get("branches") == ["main"], "C-014: deploy-site push trigger must be branches: [main]"
    assert re.search(rf"ocx-sh/website/\.github/actions/deploy@{SHA}", raw), "C-014: must use ocx-sh/website/.github/actions/deploy@<40-hex>"
    envs = [j.get("environment") for j in wf["jobs"].values()]
    assert any((e == "ocx.sh") or (isinstance(e, dict) and e.get("name") == "ocx.sh") for e in envs), "C-014: a job must use environment ocx.sh"
    assert a["site"]["dist"] in raw, "C-014: deploy inputs must carry site.dist"
    if a["site"].get("path"):
        assert a["site"]["path"] in raw, "C-014: deploy inputs must carry site.path"
    assert "BUNNY_STORAGE_KEY" in raw, "C-014: deploy must pass secrets.BUNNY_STORAGE_KEY"
    want = [f"{a['site']['dir']}/**", "ocx.toml", "ocx.lock", *a["site"].get("paths", [])]
    assert trig["push"].get("paths") == want, f"C-014: deploy-site push paths {trig['push'].get('paths')} != {want}"


def test_c014_site_paths_extend_deploy_triggers(render):
    repo = render("full-python-site", extra_data={
        "site": "{dir: site, dist: site/dist, deploy: true, path: /x, paths: ['docs/**']}"})
    trig = triggers(yaml.safe_load((repo / ".github/workflows/deploy-site.yml").read_text()))
    assert trig["push"]["paths"] == ["site/**", "ocx.toml", "ocx.lock", "docs/**"], \
        f"C-014: site.paths must extend the deploy-site push paths, got {trig['push']['paths']}"


def test_c001_site_paths_must_be_list_of_strings(render):
    with pytest.raises(subprocess.CalledProcessError):
        render("full-python-site", extra_data={"site": "{dir: site, dist: site/dist, deploy: true, paths: docs}"})


@pytest.mark.parametrize("name", FULL)
def test_c013_claude_workflow(rendered, name):
    repo = rendered(name)
    raw = need("C-013", repo, ".github/workflows/claude.yml").read_text()
    trig = triggers(yaml.safe_load(raw))
    assert set(trig["pull_request"].get("types", [])) == {"opened", "synchronize", "ready_for_review"}, "C-013: pull_request types must be opened, synchronize, ready_for_review"
    assert {"issue_comment", "pull_request_review_comment"} <= set(trig), "C-013: @claude responder triggers missing"
    assert "secrets.CLAUDE_CODE_OAUTH_TOKEN" in raw, "C-013: must reference secrets.CLAUDE_CODE_OAUTH_TOKEN"
    jobs = yaml.safe_load(raw)["jobs"]
    for jname, job in jobs.items():
        assert "environment" not in job, f"C-013: claude.yml job {jname} must not use an environment (CLAUDE_CODE_OAUTH_TOKEN is an org secret)"
    review = jobs["review"]
    assert "!endsWith(github.actor, '[bot]')" in review["if"], \
        "C-013: review job must skip bot actors (!endsWith(github.actor, '[bot]'))"
    action = [s for s in steps(review) if "claude-code-action" in str(s.get("uses", ""))][0]["with"]
    assert action.get("prompt", "").strip(), "C-013: review job needs a `prompt:` (agent mode never reviews without one)"
    assert "--allowedTools" in action.get("claude_args", "") and "gh pr comment" in action["claude_args"], \
        "C-013: review job claude_args must allow the PR comment tools"


def test_c013_responder_is_least_privilege(rendered):
    job = yaml.safe_load(need("C-013", rendered("full-minimal"), ".github/workflows/claude.yml").read_text())["jobs"]["respond"]
    action = [s for s in steps(job) if "claude-code-action" in str(s.get("uses", ""))][0]["with"]
    assert action.get("github_token") == "${{ github.token }}", "C-013: responder must pass the job token, not exchange OIDC for the write-capable App token"
    args = action.get("claude_args", "")
    assert "--allowedTools" in args and "gh pr comment" in args and "Bash(gh pr view" in args and "create_inline_comment" in args, \
        "C-013: responder needs an explicit read-only/comment --allowedTools allowlist"
    assert "id-token" not in job["permissions"], "C-013: responder with an explicit token needs no id-token: write"


def _issue_job(rendered, name):
    return yaml.safe_load(need("C-013", rendered(name), ".github/workflows/claude.yml").read_text())["jobs"]["issue"]


@pytest.mark.parametrize("name", ALL)
def test_c013_issue_handler_is_branch_only(rendered, name):
    job = _issue_job(rendered, name)
    action = [s for s in steps(job) if "claude-code-action" in str(s.get("uses", ""))][0]["with"]
    args = action["claude_args"]
    assert action["github_token"] == "${{ github.token }}" and action["branch_prefix"] == "claude/", \
        "C-013: issue handler must use the job token and the claude/ branch prefix"
    assert "git " not in args.replace("gh issue", "") and "Bash(git" not in args and "gh pr create" not in args and "ocx-mirror" not in args, \
        "C-013: issue handler must allow no shell git, gh pr create or ocx-mirror"
    assert "mcp__github_file_ops__commit_files" in args, "C-013: issue handler commits through the API tool"
    assert job["permissions"] == {"contents": "write", "issues": "write", "pull-requests": "read"}, "C-013: issue handler permissions"
    assert "id-token" not in job["permissions"], "C-013: issue handler needs no id-token"
    sl = steps(job)
    pre = next(i for i, s in enumerate(sl) if s.get("id") == "precheck")
    for sname in ("Checkout", "Handle @claude"):
        i = next(i for i, s in enumerate(sl) if s.get("name") == sname)
        assert i > pre and sl[i].get("if") == "steps.precheck.outputs.ok == 'true'", \
            f"C-013: issue handler step {sname!r} must follow the precheck and be gated on its ok output"
    assert "!github.event.issue.pull_request" in job["if"], "C-013: issue handler must skip PR comments"
    resp = yaml.safe_load(need("C-013", rendered(name), ".github/workflows/claude.yml").read_text())["jobs"]["respond"]
    assert "github.event.issue.pull_request" in resp["if"], "C-013: PR responder must not also fire on plain issues"


def _precheck(rendered, tmp_path, issue, comments, trigger):
    """Run the rendered pre-check script against a fake `gh` that serves a fixture issue."""
    step = [s for s in steps(_issue_job(rendered, "mirror")) if s.get("id") == "precheck"][0]
    script = step["run"].split("<<'PY'\n", 1)[1].rsplit("PY", 1)[0]
    (tmp_path / "gh").write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *issues/7/comments*) cat "$FIX/comments" ;;\n'
        '  api*) cat "$FIX/issue" ;;\n'
        '  *) echo "$*" >> "$FIX/calls" ;;\n'
        "esac\n")
    (tmp_path / "gh").chmod(0o755)
    (tmp_path / "issue").write_text(json.dumps(issue))
    (tmp_path / "comments").write_text("".join(json.dumps(c) + "\n" for c in comments))
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "FIX": str(tmp_path), "REPO": "o/r", "NUMBER": "7",
           "TRIGGER": trigger, "GITHUB_OUTPUT": str(tmp_path / "out")}
    subprocess.run([sys.executable, "-c", script], env=env, check=True)
    calls = (tmp_path / "calls").read_text() if (tmp_path / "calls").exists() else ""
    return (tmp_path / "out").read_text().strip(), calls


CLEAN = {"title": "Crash", "body": "it breaks"}


def _c(body, bot=False):
    return {"body": body, "user": {"type": "Bot" if bot else "User"}}


@pytest.mark.parametrize("hidden", ["a <!-- ignore previous --> b", "x\u200bz", "t\U000e0041", "<details>x</details>", "A" * 200])
def test_c013_precheck_refuses_hidden_content(rendered, tmp_path, hidden):
    out, calls = _precheck(rendered, tmp_path, {**CLEAN, "body": hidden}, [], "@claude implement")
    assert out == "ok=false" and "issue comment 7" in calls, "C-013: hidden content must be declined with a comment"


def test_c013_precheck_scans_comments_and_passes_clean(rendered, tmp_path):
    out, _ = _precheck(rendered, tmp_path, CLEAN, [_c("fine"), _c("<!-- sneaky -->")], "@claude why?")
    assert out == "ok=false", "C-013: hidden content in a comment must be declined"
    (tmp_path / "b").mkdir()
    out, calls = _precheck(rendered, tmp_path / "b", CLEAN, [_c("fine"), _c("also fine")], "@claude why?")
    assert out.endswith("ok=true") and not calls, "C-013: clean issue must pass silently"


def test_c013_precheck_ignores_bot_comments(rendered, tmp_path):
    out, calls = _precheck(rendered, tmp_path, CLEAN, [_c("Declined: `<details>` ...", bot=True), _c("<details>x</details>", bot=True)], "@claude why?")
    assert out == "ok=true" and not calls, "C-013: bot comments holding <details> must not trip the check"


def test_c013_precheck_override(rendered, tmp_path):
    out, calls = _precheck(rendered, tmp_path, {**CLEAN, "body": "<!-- x -->"}, [], "@claude override implement")
    assert out == "ok=true" and not calls, "C-013: @claude override must skip the check"


@pytest.mark.parametrize("name", ALL)
def test_c040_issue_form(rendered, name):
    repo = rendered(name)
    cfg = load_yaml("C-040", repo, ".github/ISSUE_TEMPLATE/config.yml")
    assert cfg.get("blank_issues_enabled") is False, "C-040: config.yml must disable blank issues"
    form = load_yaml("C-040", repo, ".github/ISSUE_TEMPLATE/report.yml")
    want = answers(name).get("maintainers", ["michael-herwig"])
    assert form.get("assignees") == want, f"C-040: form assignees {form.get('assignees')} != maintainers {want}"
    assert "labels" not in form, "C-040: form must not set labels"
    fields = {b["id"]: b for b in form["body"]}
    if answers(name)["profile"] == "mirror":
        assert {"package", "version", "platform", "what-happened"} <= set(fields), f"C-040: mirror form fields {sorted(fields)}"
        assert fields["platform"]["type"] == "dropdown", "C-040: mirror form needs a platform dropdown"
    else:
        assert {"summary", "steps", "expected", "actual"} <= set(fields), f"C-040: full form fields {sorted(fields)}"


@pytest.mark.parametrize("name", ALL)
def test_c040_issues_workflow(rendered, name):
    raw = need("C-040", rendered(name), ".github/workflows/issues.yml").read_text()
    wf = yaml.safe_load(raw)
    trig = triggers(wf)
    assert trig["issues"].get("types") == ["opened"], "C-040: issues trigger must be types [opened]"
    assert "issue" in trig["workflow_dispatch"]["inputs"], "C-040: workflow_dispatch needs the `issue` input"
    assert wf["permissions"] == {}, "C-040: top-level permissions must be {}"
    job = wf["jobs"]["ping"]
    cond = job["if"]
    assert "OWNER" in cond and "MEMBER" in cond and "COLLABORATOR" in cond and "!endsWith(github.actor, '[bot]')" in cond, \
        "C-040: ping job must skip OWNER/MEMBER/COLLABORATOR authors and bots"
    assert "227748867204972545" in raw and "allowed_mentions" in raw, "C-040: payload must mention the maintainer and restrict allowed_mentions"
    assert "secrets.OCX_ISSUES_HOOK" in raw, "C-040: must read secrets.OCX_ISSUES_HOOK"
    assert "environment" not in job, "C-040: ping job must not use an environment"
    run_text = job_runs(job)
    assert "${{" not in run_text, "C-040: event text must reach `run:` only through env vars, never ${{ }} interpolation"


def test_c040_empty_maintainers_rejected(render):
    with pytest.raises(subprocess.CalledProcessError):
        render("full-minimal", extra_data={"maintainers": "[]"})


def test_c009_bazel_write_credential_only_on_push_to_main(rendered):
    repo = rendered("full-bazel-site")
    push_main = "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    build = yaml.safe_load(need("C-009", repo, ".github/workflows/verify-basic.yml").read_text())["jobs"]["build"]
    setup = [s for s in steps(build) if "BAZEL_CACHE_WRITE_AUTH" in yaml.safe_dump(s)]
    assert setup, "C-009: build must pass the cache credentials to the setup action"
    with_ = setup[0]["with"]
    assert push_main in with_["cache-write-auth"] and "secrets.BAZEL_CACHE_WRITE_AUTH" in with_["cache-write-auth"], \
        f"C-009: the write credential is passed only on a push to main: {with_['cache-write-auth']!r}"
    assert push_main in with_["cache-read-auth"] and "!(" in with_["cache-read-auth"], \
        f"C-009: the read credential is passed everywhere except a push to main: {with_['cache-read-auth']!r}"
    for fname, text in all_workflows(repo):
        for jname, job in (yaml.safe_load(text).get("jobs") or {}).items():
            if "BAZEL_CACHE" in yaml.safe_dump(job) or "OTEL_OTLP_AUTH" in yaml.safe_dump(job):
                assert "environment" not in job, f"C-009: {fname} job {jname} reads org secrets, so it must not use an environment"
                assert "OTEL_AUTH" not in yaml.safe_dump(job), f"C-011: {fname} job {jname} still reads OTEL_AUTH, renamed OTEL_OTLP_AUTH"
            if "BAZEL_CACHE_WRITE_AUTH" in yaml.safe_dump(job):
                assert push_main in yaml.safe_dump(job).replace("\n", " "), f"C-009: {fname} job {jname} reads BAZEL_CACHE_WRITE_AUTH outside a push to main"


def test_checkout_pin_is_uniform(rendered):
    pins = set()
    for name in ("full-bazel-site", "mirror"):
        for _, text in all_workflows(rendered(name)):
            pins |= set(re.findall(r"actions/checkout@(\S+ # v\S+)", text))
    pins |= set(re.findall(r"actions/checkout@(\S+ # v\S+)", "".join(p.read_text() for p in (REPO_ROOT / ".github" / "workflows").glob("*.yml"))))
    assert pins == {"3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"}, f"template and repo workflows must share one actions/checkout pin: {pins}"


def expected_setup_sha(repo):
    """D-02: workflows pin the setup action at copier's `_copier_conf.vcs_ref_hash`.

    For a CLEAN template tree that is `git rev-parse HEAD`. For a DIRTY tree (copier --vcs-ref HEAD) copier commits the
    changes into a temp clone, so the hash is that automatic commit, which `_commit` (written to .copier-answers.yml)
    abbreviates. Either way the pin must be consistent with `_commit`.
    """
    head = run(["git", "-C", REPO_ROOT, "rev-parse", "HEAD"], REPO_ROOT).stdout.strip()
    dirty = bool(run(["git", "-C", REPO_ROOT, "status", "--porcelain", "--untracked-files=no"], REPO_ROOT).stdout.strip()) or \
        bool(run(["git", "-C", REPO_ROOT, "ls-files", "--others", "--exclude-standard"], REPO_ROOT).stdout.strip())
    commit = str(yaml.safe_load((repo / ".copier-answers.yml").read_text())["_commit"])
    return (head, commit, dirty)


@pytest.mark.parametrize("name", ALL)
def test_d02_setup_action_pinned_to_template_commit(rendered, name):
    repo = rendered(name)
    head, commit, dirty = expected_setup_sha(repo)
    found = []
    for fname, raw in all_workflows(repo):
        found += [(fname, m) for m in re.findall(r"ocx-sh/conventions/\.github/actions/setup@(\S+)", raw)]
    assert found, "D-02: no workflow references ocx-sh/conventions/.github/actions/setup"
    for fname, sha in found:
        assert re.fullmatch(SHA, sha), f"D-02: {fname} setup pin {sha!r} is not a 40-hex SHA"
        if dirty:
            assert sha.startswith(commit), f"D-02: {fname} setup pin {sha} does not match recorded _commit {commit}"
        else:
            assert sha == head, f"D-02: {fname} setup pin {sha} != template HEAD {head}"


# ---------------------------------------------------------------- C-012

BAZEL_FLAGS = [
    "build --remote_cache=https://bazel-cache.ocx.sh/v1",
    "build --remote_upload_local_results=false",
    "build --remote_timeout=30s",
    "build --remote_retries=2",
    "build:ci --remote_download_minimal",
    r"build:ci --remote_download_regex=.*/test\.(xml|log)$",
    "build:ci --jobs=auto",
    "test:basic --test_size_filters=small,medium --test_tag_filters=-deep",
]


def test_c012_bazel_fragment_and_module(rendered):
    repo = rendered("full-bazel-site")
    lines = [ln.strip() for ln in need("C-012", repo, "bazel/baseline.bazelrc").read_text().splitlines()]
    missing = [f for f in BAZEL_FLAGS if f not in lines]
    assert not missing, f"C-012: bazel/baseline.bazelrc lacks lines {missing}"
    assert any(ln.startswith("test:deep") for ln in lines), "C-012: bazel/baseline.bazelrc needs a test:deep line"
    rc = [ln.strip() for ln in need("C-012", repo, ".bazelrc").read_text().splitlines()]
    assert "import %workspace%/bazel/baseline.bazelrc" in rc, "C-012: .bazelrc must import %workspace%/bazel/baseline.bazelrc"
    # Contract text puts try-import in the fragment, the brief on .bazelrc; accept either file.
    assert "try-import %workspace%/.bazelrc.user" in rc + lines, "C-012: try-import %workspace%/.bazelrc.user missing"
    mod = need("C-012", repo, "MODULE.bazel").read_text()
    assert re.search(r'bazel_dep\(\s*name\s*=\s*"rules_ocx"\s*,\s*version\s*=\s*"\d+\.\d+\.\d+"', mod), \
        'C-012: MODULE.bazel needs bazel_dep(name = "rules_ocx", version = "X.Y.Z") with an exact version'


@pytest.mark.parametrize("name", ["full-minimal", "full-python-site", "mirror"])
def test_c012_no_bazel_files_without_bazel(rendered, name):
    files = rendered_files(rendered(name))
    assert not ({".bazelrc", "MODULE.bazel", "bazel/baseline.bazelrc"} & files), f"C-012: {name} has bazel: false but rendered bazel files"


@pytest.mark.slow
def test_c012_http_archive_of_ocx_tool_fails_baseline_check(render):
    repo = render("full-bazel-site")
    p = need("C-012", repo, "MODULE.bazel")
    p.write_text(p.read_text() + '\nhttp_archive(name = "gitleaks", urls = ["https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz"])\n')
    r = ocx_task(repo, "baseline:check")
    assert r.returncode != 0 and "gitleaks" in r.stdout + r.stderr, \
        f"C-012: baseline:check must fail on http_archive gitleaks (rc={r.returncode})\n{(r.stdout + r.stderr)[-600:]}"


def test_c012_http_archive_of_a_lookalike_is_not_an_ocx_tool(render):
    """`bazel-skylib` and `task-runner` share a prefix with the `bazel` and `task` tools but are other projects."""
    repo = render("full-bazel-site")
    p = need("C-012", repo, "MODULE.bazel")
    p.write_text(p.read_text()
                 + '\nhttp_archive(name = "bazel_skylib", urls = ["https://github.com/bazelbuild/bazel-skylib/releases/download/1.5.0/bazel-skylib-1.5.0.tar.gz"])\n'
                 + 'http_archive(name = "runner", urls = ["https://example.com/task-runner/task-runner-1.0.tar.gz"])\n')
    r = run([sys.executable, REPO_ROOT / "scripts" / "baseline_check.py", "--template", REPO_ROOT, "--repo", repo, "--commit-unresolved"],
            repo, git_env_dict(), check=False, timeout=300)
    assert "C-012" not in r.stdout + r.stderr, f"C-012: a lookalike http_archive must not name an ocx tool\n{(r.stdout + r.stderr)[-600:]}"


@pytest.mark.parametrize("segment,named", [
    ("task_linux_amd64.tar.gz", True), ("task_darwin_arm64.tar.gz", True), ("task_amd64_linux.tar.gz", True),
    ("task-x86_64-unknown-linux-gnu.tar.gz", True), ("task-aarch64.zip", True), ("task_windows_amd64.zip", True),
    ("task-runner-1.0.tar.gz", False), ("task-linuxish.tar.gz", False), ("bazel-skylib-1.5.0.tar.gz", False),
])
def test_c012_names_tool_matches_os_and_arch_suffixed_assets(segment, named):
    import importlib.util
    spec = importlib.util.spec_from_file_location("baseline_check", REPO_ROOT / "scripts" / "baseline_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tool = "bazel" if segment.startswith("bazel") else "task"
    assert mod.names_tool(["example.com", "x", segment], tool) is named, f"C-012: names_tool({segment!r}, {tool!r}) should be {named}"


# ---------------------------------------------------------------- C-023

# Recon inventory (research_ocx-fleet-baseline-recon.md): 22 canonical checkouts, ocx-contrib (mirror root),
# grimoire-components (GitLab, excluded), plus this repo.
INVENTORY = ("find_ocx grimoire grimoire-index grimoire-indexer grimoire-lore grimoire-vscode index ocx ocx-catalog ocx-indexbot "
             "ocx-marketing ocx-mcp ocx-mirror ocx-mirror-sdk ocx-sdk-python ocx-website rules_ocx rust-oci-client setup-grimoire "
             "setup-ocx vscode-ocx www-setup ocx-contrib grimoire-components ocx-conventions").split()


def test_c023_fleet_toml_covers_inventory():
    fleet = tomllib.loads((REPO_ROOT / "fleet.toml").read_text())
    repos = fleet.get("repos", {})
    by_path = {r.get("path"): r for r in repos.values()}
    missing = [p for p in INVENTORY if p not in by_path]
    assert not missing, f"C-023: fleet.toml lacks recon-inventory repos {missing}"
    for key, r in repos.items():
        need_keys = ["repo", "adopted", "excluded"] + ([] if r.get("excluded") else ["iteration"])
        absent = [k for k in need_keys if k not in r]
        assert not absent, f"C-023: fleet.toml repos.{key} lacks {absent}"
        if r.get("excluded"):
            assert r.get("reason"), f"C-023: excluded repos.{key} needs a reason"
