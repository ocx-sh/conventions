#!/usr/bin/env python3
"""Generate template/ (what copier reads) from src/ and MANIFEST.toml. Never edit template/ by hand.

Each [[file]] is read from src/<path> (src/<path>.jinja when copier renders it). Its profiles/when become copier's
conditional names ({% if <cond> %}name{% endif %}), and template-owned files get the ownership banner as line 1.
Usage: build_template.py [OUT_DIR]   (default: template/; task template:check builds into a temp dir and diffs)
"""

import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNER = "ocx-baseline: template-owned file — change ocx-sh/conventions, then run task copier:update"
ANSWERS = ".copier-answers.yml"  # copier requires this name as {{ _copier_conf.answers_file }}; copier writes its own header
WHEN = {None: "profile == 'full'", "bazel": "profile == 'full' and bazel", "site": "profile == 'full' and site",
        "site.deploy": "profile == 'full' and site and site.deploy", "repo_workflows": "profile == 'full' and repo_workflows"}


def condition(f):
    if f.get("when") is None and set(f["profiles"]) == {"full", "mirror"}:
        return None
    assert f["profiles"] == ["full"], f"{f['path']}: profiles {f['profiles']} has no copier condition"
    return WHEN[f.get("when")]


def banner(path, text):
    """Insert the banner where it renders as line 1: after leading whitespace-stripping {%- / {#- lines."""
    if path.endswith(".json"):
        body = text.rstrip()
        assert body.endswith("}"), f"{path}: JSON banner needs a top-level object"
        return body[:-1] + ', "description": "' + BANNER + '"}' + text[len(body):]
    line = f"<!-- {BANNER} -->\n" if path.endswith(".md") else f"# {BANNER}\n"
    lines = text.splitlines(True)
    i = 0
    while i < len(lines) and lines[i].startswith(("{%-", "{#-")):
        i += 1
    return "".join(lines[:i]) + line + "".join(lines[i:])


def names(manifest):
    """Copier name per path: the condition wraps the shallowest component that holds only files of that condition."""
    conds = {f["path"]: condition(f) for f in manifest["file"]}
    out = {}
    for path, cond in conds.items():
        parts = path.split("/")
        if path == ANSWERS:
            parts = ["{{ _copier_conf.answers_file }}"]
        elif cond:
            for i in range(len(parts)):
                prefix = "/".join(parts[:i + 1])
                if all(c == cond for p, c in conds.items() if p == prefix or p.startswith(prefix + "/")):
                    parts[i] = f"{{% if {cond} %}}{parts[i]}{{% endif %}}"
                    break
        out[path] = "/".join(parts)
    return out


def build(out):
    manifest = tomllib.loads((ROOT / "MANIFEST.toml").read_text())
    shutil.rmtree(out, ignore_errors=True)
    for f, name in zip(manifest["file"], names(manifest).values()):
        src = ROOT / "src" / (f["path"] + ".jinja")
        jinja = src.is_file()
        src = src if jinja else ROOT / "src" / f["path"]
        text = src.read_text()
        if f["class"] == "template-owned" and f["path"] != ANSWERS:
            text = banner(f["path"], text)
        dst = out / (name + (".jinja" if jinja else ""))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text)
        shutil.copymode(src, dst)
    listed = {f["path"] + s for f in manifest["file"] for s in ("", ".jinja")}
    stray = sorted(str(p.relative_to(ROOT / "src")) for p in (ROOT / "src").rglob("*") if p.is_file()
                   and str(p.relative_to(ROOT / "src")) not in listed)
    if stray:
        sys.exit(f"src/ files missing from MANIFEST.toml: {stray}")


if __name__ == "__main__":
    build(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "template")
