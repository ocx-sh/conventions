#!/usr/bin/env python3
"""baseline:check: drift of template-owned files plus the structural baseline contract.

Run by `task baseline:check` with the conventions clone at the repo's recorded `_commit`:
    uv run --no-project --with pyyaml==6.0.3 python <clone>/scripts/baseline_check.py --template <clone> --repo .

Checks: re-render of the recorded commit vs template-owned paths (Q3), C-003 root tasks, C-005 ocx.toml,
C-006 grimoire.toml, C-012 Bazel (D-12), C-014 site Lighthouse, Q7 pnpm pin. Exit 1 lists every failure.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import yaml  # provided by the task wrapper (--with pyyaml)

ROLES = {"lint", "test", "build", "docs", "release"}
BASELINE_TOOLS = [("default", "task"), ("lint", "prek"), ("lint", "gitleaks"), ("lint", "grim"), ("lint", "uv"), ("release", "git-cliff")]
BASELINE_TASKS = ["setup", "hooks:install", "lock:check", "grim:check", "secrets", "baseline:check", "release:prepare", "copier:update"]
ROOT_TASKS = ["verify", "ci:lint", "ci:test", "ci:build", "ci:docs", "ci:deep"]
CLIENTS = {"claude", "codex", "opencode"}
REF = re.compile(r"^[^:\s]+:\d+\.\d+\.\d+([-+_][\w.+-]*)?$")
MIRROR_FLOAT = re.compile(r"^ocx\.sh/(ocx/(cli|mirror):\d+\.\d+|astral-sh/uv:\d+)$")  # toolchain minor; uv major (url_index generator runtime)
FIX = "change ocx-sh/conventions instead, then run task copier:update"
USER_RC = "try-import %workspace%/.bazelrc.user"


def load_toml(path):
    return tomllib.loads(Path(path).read_text())


def conditions(ans):
    full = ans.get("profile", "full") == "full"
    site = ans.get("site") or None
    return {"bazel": full and bool(ans.get("bazel")), "site": full and site is not None,
            "site.deploy": full and site is not None and bool(site.get("deploy")),
            "repo_workflows": full and bool(ans.get("repo_workflows"))}


def owned_paths(manifest, ans):
    profile, cond = ans.get("profile", "full"), conditions(ans)
    return [f["path"] for f in manifest["file"]
            if f["class"] == "template-owned" and profile in f["profiles"] and cond.get(f.get("when"), True)]


def drift(tmpl, repo, ans, manifest, commit, unresolved, fails):
    """Q3: re-render the recorded commit with the recorded answers and diff the template-owned paths."""
    if unresolved:
        fails.append(f"re-render: recorded _commit {commit} is not reachable in the template source, cannot diff template-owned files; "
                     "run task copier:update --vcs-ref <tag>")
        return
    text = (tmpl / "template" / "taskfiles" / "baseline.taskfile.yml").read_text() if (tmpl / "template" / "taskfiles" / "baseline.taskfile.yml").is_file() else ""
    m = re.search(r'^\s+COPIER_VERSION:\s*"([^"]+)"', text, re.M)
    if not m:
        fails.append(f"re-render: no COPIER_VERSION in template/taskfiles/baseline.taskfile.yml at {commit}")
        return
    uv = shutil.which("uv")
    if not uv:
        fails.append("re-render: uv not found on PATH")
        return
    with tempfile.TemporaryDirectory() as td:
        data, out = Path(td) / "answers.yml", Path(td) / "render"
        data.write_text(yaml.safe_dump({k: v for k, v in ans.items() if not k.startswith("_")}))
        cmd = [uv, "tool", "run", "--from", f"copier=={m.group(1)}", "copier", "copy", "--defaults", "--quiet",
               "--vcs-ref", commit, "--data-file", str(data), str(tmpl), str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            fails.append(f"re-render of {commit} failed: {(r.stderr or r.stdout).strip()[-300:]}")
            return
        for rel in owned_paths(manifest, ans):
            if rel == ".copier-answers.yml":  # carries _commit/_src_path, differs by construction
                continue
            want, got = out / rel, repo / rel
            if not want.is_file():
                continue
            if not got.is_file():
                fails.append(f"{rel}: missing; it is template-owned, {FIX}")
            elif got.read_bytes().replace(b"\r\n", b"\n") != want.read_bytes().replace(b"\r\n", b"\n"):
                fails.append(f"{rel}: differs from ocx-sh/conventions@{commit}; it is template-owned, {FIX}")


def run_task(exe, repo, *args):
    try:
        return subprocess.run([exe, *args], cwd=repo, capture_output=True, text=True)
    except OSError as e:
        return subprocess.CompletedProcess(args, 127, "", str(e))


def check_tasks(repo, ans, exe, fails):
    """C-003 (+ C-014): required root tasks resolve, baseline taskfile is included flat, ci:docs runs Lighthouse for a site."""
    r = run_task(exe, repo, "--list-all", "--json")
    if r.returncode:
        fails.append(f"C-003: `{exe} --list-all` failed: {(r.stderr or r.stdout).strip()[-300:]}")
        return
    names = {t["name"] for t in json.loads(r.stdout)["tasks"]}
    for t in ROOT_TASKS:
        if t not in names:
            fails.append(f"C-003: root taskfile.yml does not define task '{t}'")
    for t in BASELINE_TASKS:
        if t not in names:
            fails.append(f"C-003: baseline task '{t}' not reachable; taskfile.yml must include taskfiles/baseline.taskfile.yml with flatten: true")
    if conditions(ans)["site"] and "ci:docs" in names:
        s = run_task(exe, repo, "--summary", "ci:docs")
        if "lighthouse" not in s.stdout.lower():
            fails.append("C-014: task 'ci:docs' must run the site's Lighthouse gate (site:lighthouse or equivalent); it never mentions lighthouse")


def line_of(text, key):
    m = re.search(rf'(?m)^\s*"?{re.escape(key)}"?\s*=', text)
    return text.count("\n", 0, m.start()) + 1 if m else 0


def ocx_tools(cfg):
    out = {("default", k): v for k, v in (cfg.get("tools") or {}).items()}
    for g, body in (cfg.get("group") or {}).items():
        out.update({(g, k): v for k, v in (body.get("tools") or {}).items()})
    return out


def check_ocx(repo, fails, mirror=False):
    """C-005: exact pins, baseline tools, D-04 groups, ocx.lock tracked. Returns the tool map for Q7."""
    p = repo / "ocx.toml"
    if not p.is_file():
        fails.append("C-005: ocx.toml is missing")
        return {}
    text = p.read_text()
    cfg = tomllib.loads(text)
    tools = ocx_tools(cfg)
    for (g, k), ref in tools.items():
        if mirror and isinstance(ref, str) and MIRROR_FLOAT.match(ref):
            continue  # ocx-contrib/CLAUDE.md: the mirror toolchain floats the minor so a plain `ocx update` picks up patches
        if not (isinstance(ref, str) and REF.match(ref)):
            fails.append(f"C-005: ocx.toml:{line_of(text, k)}: tool '{k}' [{g}] must pin an exact X.Y.Z version, got {ref!r}")
    for g, k in BASELINE_TOOLS:
        if (g, k) not in tools:
            fails.append(f"C-005: ocx.toml lacks baseline tool '{k}' in group {g}")
    for g in cfg.get("group") or {}:
        if g not in ROLES:
            fails.append(f"C-005: ocx.toml group '{g}' is outside {sorted(ROLES)}")
    if subprocess.run(["git", "ls-files", "--error-unmatch", "ocx.lock"], cwd=repo, capture_output=True).returncode:
        fails.append("C-005: ocx.lock is not tracked in git (commit it; `task lock:check` verifies it is current)")
    return tools


def check_grim(repo, ans, fails):
    """C-006: clients and bundles."""
    p = repo / "grimoire.toml"
    if not p.is_file():
        fails.append("C-006: grimoire.toml is missing")
        return
    cfg = tomllib.loads(p.read_text())
    for c in sorted(CLIENTS - set((cfg.get("options") or {}).get("clients", []))):
        fails.append(f"C-006: grimoire.toml options.clients lacks '{c}'")
    full = ans.get("profile", "full") == "full"
    want = {"docs-essentials", "code-docs-essentials"}
    if full:
        want |= {f"{lang}-essentials" for lang in ans.get("languages") or []}
        if ans.get("theme_bundle"):
            want.add("ocx-theme")
    have = set(cfg.get("bundles") or {})
    for b in sorted(want - have):
        fails.append(f"C-006: grimoire.toml [bundles] lacks '{b}'")
    if "ocx-theme" in have and "ocx-theme" not in want:
        fails.append("C-006: grimoire.toml [bundles] has 'ocx-theme' but theme_bundle is false")


def http_calls(text):
    """Bodies of every http_archive(...)/http_file(...) call (balanced parentheses)."""
    for m in re.finditer(r"\bhttp_(?:archive|file)\s*\(", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        yield text[m.end():i]


def names_tool(segments, tool):
    """True when a URL path segment is the tool (`bazelisk`), or its release asset (`cmake-3.28.0-linux.tar.gz`, `task_linux_amd64.tar.gz`, `task-x86_64-unknown-linux-gnu`).

    Whole segments only: `bazel-skylib` and `task-runner` are other projects, not the `bazel` and `task` tools.
    """
    pat = re.compile(rf"{re.escape(tool)}(?:[-_.]?v?\d.*|[-_](?:linux|darwin|macos|osx|windows|win|x86_64|aarch64|arm64|amd64)(?![a-z]).*|\.(?:tar|zip|tgz|gz|exe)\b.*)?", re.I)
    return any(pat.fullmatch(seg) for seg in segments)


def check_user_rc(repo, fails):
    """C-012: the repo-owned .bazelrc ends with the user-rc import; the template-owned fragment is read first and no longer carries it."""
    rc = repo / ".bazelrc"
    if not rc.is_file():
        fails.append(f"C-012: .bazelrc is missing; it imports bazel/baseline.bazelrc and ends with `{USER_RC}`")
        return
    lines = [ln.strip() for ln in rc.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines or lines[-1] != USER_RC:
        fails.append(f"C-012: .bazelrc must end with `{USER_RC}`; any flag after it overrides the developer's .bazelrc.user "
                     "and the trusted cache rc the setup action writes there")


def check_bazel(repo, tmpl, ans, fails):
    """C-012 (D-12): rules_ocx at an exact version, no http_archive for a tool ocx already ships."""
    if not conditions(ans)["bazel"]:
        return
    check_user_rc(repo, fails)
    mod = repo / "MODULE.bazel"
    if not mod.is_file():
        fails.append("C-012: MODULE.bazel is missing")
    else:
        t = mod.read_text()
        if not (re.search(r'\bmodule\(\s*name\s*=\s*"rules_ocx"', t)
                or re.search(r'bazel_dep\(\s*name\s*=\s*"rules_ocx"\s*,\s*version\s*=\s*"\d+\.\d+\.\d+"', t)):
            fails.append('C-012: MODULE.bazel needs bazel_dep(name = "rules_ocx", version = "X.Y.Z") with an exact version')
    try:
        repos = load_toml(tmpl / "scripts" / "groups.toml")["repositories"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as e:
        fails.append(f"C-012: cannot read scripts/groups.toml [repositories] from the template: {e}")
        return
    files = subprocess.run(["git", "ls-files", "MODULE.bazel", "WORKSPACE*", "*.bzl", "*.bazel"], cwd=repo, capture_output=True, text=True).stdout.split()
    for f in files:
        try:
            text = (repo / f).read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for body in http_calls(text):
            for url in re.findall(r"https?://[^\s\"']+", body):
                segs = url.split("//", 1)[1].split("?", 1)[0].split("/")[1:]
                for tool in repos:
                    if names_tool(segs, tool):
                        fails.append(f"C-012: {f}: http_archive/http_file {url} names ocx tool '{tool}'; use rules_ocx instead (D-12)")


def check_pnpm(repo, ans, tools, fails):
    """Q7: packageManager (pnpm) equals the ocx pnpm pin when both exist."""
    pin = next((v.split(":", 1)[1] for (g, k), v in tools.items() if k == "pnpm" and isinstance(v, str) and ":" in v), None)
    site = ans.get("site") or {}
    for d in dict.fromkeys([".", site.get("dir") or "."]):
        pj = repo / d / "package.json"
        if not pj.is_file():
            continue
        pm = json.loads(pj.read_text()).get("packageManager", "")
        if pm.startswith("pnpm@") and pin:
            ver = pm[5:].split("+", 1)[0]
            if ver != pin:
                fails.append(f"Q7: {pj.relative_to(repo)} packageManager pnpm@{ver} != ocx.toml pnpm pin {pin}; the ocx pin is the only pin")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", required=True, type=Path, help="conventions checkout at the repo's recorded _commit")
    ap.add_argument("--repo", default=".", type=Path)
    ap.add_argument("--task", default=os.environ.get("TASK_EXE") or "task", help="task executable")
    ap.add_argument("--commit-unresolved", action="store_true", help="the recorded _commit could not be checked out")
    a = ap.parse_args()
    tmpl, repo = a.template.resolve(), a.repo.resolve()
    fails = []
    try:
        ans = yaml.safe_load((repo / ".copier-answers.yml").read_text()) or {}
        manifest = load_toml(tmpl / "MANIFEST.toml")
    except (OSError, yaml.YAMLError, tomllib.TOMLDecodeError) as e:
        sys.exit(f"baseline:check: cannot read .copier-answers.yml or the template MANIFEST.toml: {e}")
    drift(tmpl, repo, ans, manifest, str(ans.get("_commit", "")), a.commit_unresolved, fails)
    check_tasks(repo, ans, a.task, fails)
    tools = check_ocx(repo, fails, mirror=ans.get("profile") == "mirror")
    check_grim(repo, ans, fails)
    check_bazel(repo, tmpl, ans, fails)
    check_pnpm(repo, ans, tools, fails)
    if fails:
        print("baseline:check FAILED", file=sys.stderr)
        for f in fails:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)
    print("baseline:check OK")


if __name__ == "__main__":
    main()
