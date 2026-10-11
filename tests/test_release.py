"""C-004 release:prepare (template/taskfiles/baseline.taskfile.yml), exercised on a rendered full-minimal repo.

gh, git-cliff and ocx are stubs on PATH; `ocx exec -- <cmd>` execs <cmd> from PATH so the stubs win.
`verify` in the rendered root taskfile is replaced by `echo ok`.
"""
import json
import subprocess

import pytest
import yaml

from stubs import git, stub_env, write_stub

OCX = r"""
echo "ocx $*" >> "$STUB_LOG"
if [ "$1" = exec ]; then
  shift
  while [ $# -gt 0 ] && [ "$1" != "--" ]; do shift; done
  [ "$1" = "--" ] && shift
  exec "$@"
fi
exit 0
"""
GH = r"""
echo "gh $*" >> "$STUB_LOG"
case "$1 $2" in
  "auth status") exit "${GH_AUTH_RC:-0}" ;;
  "run list")
    if [ -n "${GH_RUN_404:-}" ]; then
      echo "could not find any workflows named verify-deep.yml: HTTP 404: workflow verify-deep.yml not found on the default branch (https://api.github.com/repos/o/r/actions/workflows/verify-deep.yml/runs)" >&2
      exit 1
    fi
    cat "$GH_RUNS_FILE" ;;
  "repo view") echo main ;;
esac
exit 0
"""
CLIFF = r"""
echo "git-cliff $*" >> "$STUB_LOG"
args=" $* "
if [[ "$args" == *" --bumped-version "* ]]; then
  case "$args" in
    *"--bump minor"*) echo v0.2.0 ;; *"--bump major"*) echo v1.0.0 ;; *) echo v0.1.1 ;;
  esac
  exit 0
fi
tag=""; out=""
while [ $# -gt 0 ]; do
  case "$1" in --tag) tag="$2"; shift ;; -o|--output) out="$2"; shift ;; esac
  shift
done
[ -n "$out" ] && printf '# Changelog\n\n## [%s]\n\n- stub entry\n' "$tag" > "$out"
exit 0
"""
RUN_URL = "https://github.com/ocx-sh/conventions-test/actions/runs/4242"


@pytest.fixture
def rel(render, tmp_path):
    repo = render("full-minimal")
    tf = repo / "taskfile.yml"
    assert tf.exists(), "C-004 rendered full-minimal must contain the seeded root taskfile.yml"
    doc = yaml.safe_load(tf.read_text())
    doc.setdefault("tasks", {})["verify"] = {"cmds": ["echo ok > verify.ran"]}
    tf.write_text(yaml.safe_dump(doc, sort_keys=False))
    for msg in ("feat: first thing", "fix: second thing", "feat: third thing"):
        git(repo, "commit", "--allow-empty", "-q", "-m", msg)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore: stub verify")
    bindir = tmp_path / "stubs"
    for n, b in (("ocx", OCX), ("gh", GH), ("git-cliff", CLIFF)):
        write_stub(bindir, n, b)
    runs, log = tmp_path / "runs.json", tmp_path / "calls.log"
    log.write_text("")
    runs.write_text(json.dumps([{"conclusion": "success", "url": RUN_URL, "event": "schedule"}]))
    env = stub_env(bindir, STUB_LOG=str(log), GH_RUNS_FILE=str(runs), GH_AUTH_RC="0")

    def go(*args, runs_json=None, auth_rc=None, **extra_env):
        if runs_json is not None:
            runs.write_text(runs_json)
        e = dict(env, **extra_env)
        if auth_rc is not None:
            e["GH_AUTH_RC"] = str(auth_rc)
        r = subprocess.run(["task", "release:prepare", *args], cwd=repo, env=e, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=120)
        return r, r.stdout + r.stderr

    return repo, log, go


def test_bump_minor_writes_changelog_and_never_tags(rel):
    repo, log, go = rel
    r, out = go("BUMP=minor")
    assert r.returncode == 0, f"C-004 BUMP=minor must succeed: {out}"
    cl = repo / "CHANGELOG.md"
    assert cl.exists() and "0.2.0" in cl.read_text(), "C-004 CHANGELOG.md must carry the bumped version"
    assert (repo / "verify.ran").exists(), "C-004 release:prepare must run `verify`"
    assert git(repo, "tag", "--list").stdout.strip() == "", "C-004 must never create a tag"


def test_version_override_wins(rel):
    repo, log, go = rel
    r, out = go("VERSION=1.2.3")
    assert r.returncode == 0, f"C-004 VERSION=1.2.3 must succeed: {out}"
    assert "1.2.3" in (repo / "CHANGELOG.md").read_text(), "C-004 VERSION must win and reach git-cliff --tag"
    assert "--tag v1.2.3" in log.read_text(), "C-004 git-cliff must be called with --tag v<VERSION>"


def test_no_var_no_tty_prints_usage(rel):
    _, _, go = rel
    r, out = go()
    assert r.returncode != 0, "C-004 neither BUMP nor VERSION and no TTY must exit non-zero"
    assert "BUMP" in out and "VERSION" in out and "usage" in out.lower(), \
        f"C-004 usage line must name BUMP and VERSION: {out}"


def test_red_nightly_refuses_with_run_url(rel):
    repo, _, go = rel
    bad = json.dumps([{"conclusion": "failure", "url": RUN_URL, "event": "schedule"}])
    r, out = go("BUMP=minor", runs_json=bad)
    assert r.returncode != 0, "C-004 a failed latest verify-deep run must block release:prepare"
    assert RUN_URL in out, f"C-004 refusal must print the run URL: {out}"
    assert not (repo / "CHANGELOG.md").exists(), "C-004 refusal must not write CHANGELOG.md"


def test_no_runs_refuses(rel):
    _, _, go = rel
    r, out = go("BUMP=minor", runs_json="[]")
    assert r.returncode != 0, "C-004 no verify-deep run must block release:prepare"
    assert "no verify-deep run on main yet" in out, f"C-004 wrong message: {out}"


def test_unauthenticated_gh_refuses(rel):
    repo, _, go = rel
    r, out = go("BUMP=minor", auth_rc=1)
    assert r.returncode != 0, "C-004 unauthenticated gh must block release:prepare"
    assert not (repo / "CHANGELOG.md").exists(), "C-004 refusal must not write CHANGELOG.md"


def test_workflow_missing_on_default_branch_reads_as_no_run(rel):
    repo, _, go = rel
    r, out = go("BUMP=minor", GH_RUN_404="1")
    assert r.returncode != 0, f"C-004 a 404 from gh run list must exit non-zero: {out}"
    assert "no verify-deep run on main yet — dispatch one" in out, f"C-004 a 404 must print the never-ran message: {out}"
    assert not (repo / "CHANGELOG.md").exists(), "C-004 refusal must not write CHANGELOG.md"
