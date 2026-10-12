"""Slow self-tests (C-022, C-026, S-002, D-05): render fixtures into target/selftest and run the real tasks.

Needs network + ocx. Note: a template rendered from a DIRTY conventions tree records an automatic-commit `_commit`
that `baseline:check` cannot re-render; run these after the template is committed.
"""

import re
import secrets
import shutil
import string
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import FIXTURES, REPO_ROOT, git_env_dict, ocx_lock_committed, ocx_task, render_to, run

pytestmark = pytest.mark.slow

SELFTEST = REPO_ROOT / "target" / "selftest"
GOLDEN = REPO_ROOT / "tests" / "golden" / "update-n1.diff"
SENTINEL = "# ocx-baseline: template-owned file — change ocx-sh/conventions, then run task copier:update"
BASELINE_TASKFILE = "taskfiles/baseline.taskfile.yml"


def fresh(name, subdir=None):
    dest = SELFTEST / (subdir or name)
    shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    return render_to(name, dest)


def tail(r):
    return (r.stdout + r.stderr)[-800:]


def setup_committed(repo):
    """`task setup`, then commit its grim client output as an adopter does (grim:check fails on uncommitted output)."""
    r = ocx_task(repo, "setup")
    env = git_env_dict()
    run(["git", "add", "-A"], repo, env)
    run(["git", "commit", "-qm", "setup", "--allow-empty"], repo, env)
    return r


@pytest.mark.parametrize("name", ["full-bazel-site", "full-python-site", "full-minimal"])
def test_c022_full_fixture_setup_and_verify(name):
    repo = fresh(name)
    r = setup_committed(repo)
    assert r.returncode == 0, f"C-022: `task setup` failed for {name} (rc={r.returncode})\n{tail(r)}"
    r = ocx_task(repo, "verify")
    assert r.returncode == 0, f"C-022: `task verify` failed for {name} (rc={r.returncode})\n{tail(r)}"


def test_c022_mirror_fixture_checks():
    repo = fresh("mirror")
    r = ocx_task(repo, "lock:check", "baseline:check", "secrets")
    assert r.returncode == 0, f"C-022: mirror `task lock:check baseline:check secrets` failed (rc={r.returncode})\n{tail(r)}"


def test_d05_stale_grim_lock_fails_grim_check_and_lint_job():
    repo = fresh("full-minimal", "stale-grim-lock")
    r = setup_committed(repo)
    assert r.returncode == 0, f"D-05: `task setup` failed before the stale-lock edit (rc={r.returncode})\n{tail(r)}"
    r = ocx_task(repo, "grim:check")
    assert r.returncode == 0, f"D-05: grim:check must pass on a fresh install (rc={r.returncode})\n{tail(r)}"

    entry = (FIXTURES / "stale-grim-lock" / "bundle-entry.toml").read_text()
    p = repo / "grimoire.toml"
    text = p.read_text()
    assert "[bundles]" in text, "D-05: rendered grimoire.toml has no [bundles] table"
    p.write_text(text.replace("[bundles]\n", "[bundles]\n" + entry, 1))
    assert "stale-fixture" in tomllib.loads(p.read_text())["bundles"], "D-05: failed to add the stale entry"

    r = ocx_task(repo, "grim:check")
    assert r.returncode != 0, f"D-05: grim:check must fail when grimoire.toml has an entry absent from grimoire.lock\n{tail(r)}"

    wf = yaml.safe_load((repo / ".github/workflows/verify-basic.yml").read_text())
    cmds = [s["run"].strip() for s in wf["jobs"]["lint"]["steps"] if "task lock:check" in s.get("run", "")]
    assert cmds, "C-009: verify-basic lint job has no `task lock:check` step"
    ocx_lock_committed(repo)
    r = run(["ocx", "exec", "--", "sh", "-c", cmds[0]], repo, git_env_dict(), check=False, timeout=900)
    assert r.returncode != 0, f"C-022: the lint job's `{cmds[0]}` must exit non-zero on a stale grim lock\n{tail(r)}"


def planted_creds():
    # Generated per run: a committed fake key trips GitHub push protection.
    up = string.ascii_uppercase + string.digits
    key = "AKIA" + "".join(secrets.choice(up) for _ in range(16))
    sec = "".join(secrets.choice(string.ascii_letters + string.digits + "+/") for _ in range(40))
    return f"AWS_ACCESS_KEY_ID={key}\naws_secret_access_key={sec}\n"


def test_s002_planted_secret_fails_task_secrets():
    repo = fresh("full-minimal", "planted-secret")
    r = ocx_task(repo, "secrets")
    assert r.returncode == 0, f"S-002: `task secrets` must pass on a clean render (rc={r.returncode})\n{tail(r)}"
    (repo / "creds.env").write_text(planted_creds())
    env = git_env_dict()
    run(["git", "add", "creds.env"], repo, env)
    run(["git", "commit", "-qm", "plant secret"], repo, env)
    r = ocx_task(repo, "secrets")
    assert r.returncode != 0, f"S-002: `task secrets` must exit non-zero for the committed planted secret\n{tail(r)}"


def template_owned_diff(a: Path, b: Path, names):
    return [n for n in sorted(names) if not (a / n).is_file() or not (b / n).is_file() or (a / n).read_bytes() != (b / n).read_bytes()]


def test_c026_dogfood_answers_and_render_current(tmp_path):
    answers_file = REPO_ROOT / ".copier-answers.yml"
    assert answers_file.is_file(), "C-026: conventions root .copier-answers.yml is missing (the repo must be rendered from itself)"
    root = yaml.safe_load(answers_file.read_text())
    want = tomllib.loads((REPO_ROOT / "fleet.toml").read_text())["repos"]["conventions"]["answers"]
    got = {k: root.get(k) for k in want}
    if "site" not in want:
        got["site"] = root.get("site")
        want = {**want, "site": None}
    assert got == want, f"C-026: root answers {got} != fleet.toml conventions answers {want}"

    # baseline:check semantics: re-render the RECORDED commit with the recorded answers, then diff template-owned paths.
    data = tmp_path / "answers.yml"
    data.write_text(yaml.safe_dump({k: v for k, v in root.items() if not k.startswith("_")}))
    dest = tmp_path / "re-render"
    run(["uv", "run", "--project", REPO_ROOT, "copier", "copy", "--defaults", "--quiet", "--vcs-ref", str(root["_commit"]),
         "--data-file", data, REPO_ROOT, dest], REPO_ROOT, git_env_dict())
    a = want
    cond = {"bazel": bool(a.get("bazel")), "site": bool(a.get("site")), "site.deploy": bool((a.get("site") or {}).get("deploy"))}
    owned = {f["path"] for f in tomllib.loads((REPO_ROOT / "MANIFEST.toml").read_text())["file"]
             if f["class"] == "template-owned" and "full" in f["profiles"] and cond.get(f.get("when"), True)}
    owned.discard(".copier-answers.yml")  # carries _commit / _src_path, differs by construction
    drift = template_owned_diff(REPO_ROOT, dest, owned)
    assert not drift, f"C-026: conventions root template-owned files differ from a re-render of {root['_commit']}: {drift}"


def test_c022_copier_update_n_to_n1_matches_golden(tmp_path):
    env = git_env_dict()
    clone = tmp_path / "clone"
    run(["git", "clone", "-q", REPO_ROOT, clone], tmp_path, env)  # clone of HEAD; scratch tags live only here
    run(["git", "tag", "vN"], clone, env)

    tpl = clone / "template" / BASELINE_TASKFILE
    assert tpl.is_file(), f"C-022: template/{BASELINE_TASKFILE} is missing from the committed template"
    lines = tpl.read_text().split("\n")
    assert lines[0] == SENTINEL, f"C-022: line 1 of template/{BASELINE_TASKFILE} must be exactly {SENTINEL!r}, got {lines[0]!r}"

    repo = render_to("full-minimal", tmp_path / "rendered", src=clone, vcs_ref="vN")

    lines[0] = "# ocx-baseline: template-owned file (update-n1 sentinel)"
    tpl.write_text("\n".join(lines))
    run(["git", "commit", "-qam", "n1"], clone, env)
    run(["git", "tag", "vN1"], clone, env)

    run(["uv", "run", "--project", REPO_ROOT, "copier", "update", "--defaults", "--quiet", "--vcs-ref", "vN1"], repo, env)

    diff = run(["git", "diff", "-U0", "--no-color", "--", BASELINE_TASKFILE], repo, env).stdout
    diff = "".join(ln for ln in diff.splitlines(True) if not ln.startswith("index "))
    assert diff == GOLDEN.read_text(), f"C-022: copier update diff != tests/golden/update-n1.diff\n{diff}"

    changed = set(run(["git", "diff", "--name-only"], repo, env).stdout.split())
    changed |= set(run(["git", "ls-files", "--others", "--exclude-standard"], repo, env).stdout.split())
    # Files that embed the template commit (D-02 setup pin, C-015 preset ref) move with every update.
    ref_pinned = {".github/workflows/verify-basic.yml", ".github/workflows/verify-deep.yml", ".github/workflows/claude.yml",
                  ".github/workflows/deploy-site.yml", "renovate.json"}
    assert BASELINE_TASKFILE in changed and ".copier-answers.yml" in changed, f"C-022: update must touch the sentinel file and .copier-answers.yml, got {sorted(changed)}"
    extra = changed - {BASELINE_TASKFILE, ".copier-answers.yml"} - ref_pinned
    assert not extra, f"C-022: update touched files beyond the sentinel, answers and ref-pinned files: {sorted(extra)}"
    for f in changed & ref_pinned:
        d = run(["git", "diff", "-U0", "--no-color", "--", f], repo, env).stdout
        body = [ln for ln in d.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
        assert all(("conventions" in ln) for ln in body), f"C-022: {f} changed beyond its template-ref pin: {body}"
