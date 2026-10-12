"""src/ -> template/ build (scripts/build_template.py): committed template/ is the build output, banners mark ownership."""

import re
import subprocess
import sys
import tomllib

from conftest import REPO_ROOT

BANNER = "ocx-baseline: template-owned file — change ocx-sh/conventions, then run task copier:update"


def build(out):
    subprocess.run([sys.executable, REPO_ROOT / "scripts" / "build_template.py", out], check=True)
    return {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}


def test_committed_template_is_the_build_output(tmp_path):
    built = build(tmp_path / "t")
    committed = {p.relative_to(REPO_ROOT / "template"): p.read_bytes() for p in (REPO_ROOT / "template").rglob("*") if p.is_file()}
    assert built == committed, "template/ differs from the src/ build; run task template:build"
    assert build(tmp_path / "t2") == built, "build must be deterministic"


def test_banner_marks_template_owned_files_only():
    manifest = tomllib.loads((REPO_ROOT / "MANIFEST.toml").read_text())
    for f in manifest["file"]:
        src = REPO_ROOT / "src" / f["path"]
        text = (src.with_name(src.name + ".jinja") if src.with_name(src.name + ".jinja").is_file() else src).read_text()
        assert BANNER not in text, f"src/{f['path']}: the build adds the banner; remove it from the source"
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from build_template import names
    tpl = REPO_ROOT / "template"
    for f, name in zip(manifest["file"], names(manifest).values()):
        out = tpl / (name + ".jinja") if (tpl / (name + ".jinja")).is_file() else tpl / name
        assert out.is_file(), f"{f['path']} missing from template/"
        if f["path"] != ".copier-answers.yml":  # copier writes its own "never edit" header
            assert (BANNER in out.read_text()) == (f["class"] == "template-owned"), \
                f"{f['path']} ({f['class']}): banner must mark exactly the template-owned files"


def test_tag_ref_regex_accepts_real_tags_only():
    """Version comments and the Renovate preset name a tag only for a tag ref; a describe ref or SHA falls back to the hash."""
    lit = re.search(r"regex_search\('(.+?)'\)", (REPO_ROOT / "src/renovate.json.jinja").read_text()).group(1)
    for wf in ("verify-basic", "verify-deep", "deploy-site"):
        assert f"regex_search('{lit}')" in (REPO_ROOT / f"src/.github/workflows/{wf}.yml.jinja").read_text(), wf
    pat = lit.replace("\\\\", "\\")
    for ref, tag in [("v0.1.1", True), ("v1.0.0-rc.1", True), ("v0.1.0-2-g2b1ec3f", False), ("2b1ec3f", False), ("HEAD", False)]:
        assert bool(re.search(pat, ref)) == tag, ref
