"""C-005 mirror exception: only ocx.sh/ocx/{cli,mirror} (minor) and astral-sh/uv (major) may float, and only under profile mirror."""
import importlib.util
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("bc", Path(__file__).parent.parent / "scripts" / "baseline_check.py")
bc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bc)

TOML = '[tools]\ntask = "ocx.sh/go-task/task:3.53.1"\ncli = "ocx.sh/ocx/cli:0.6"\nother = "ocx.sh/x/y:1.2"\nuv = "ocx.sh/astral-sh/uv:0"\n'


def pins(tmp_path, mirror):
    (tmp_path / "ocx.toml").write_text(TOML)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    fails = []
    bc.check_ocx(tmp_path, fails, mirror=mirror)
    return [f for f in fails if "must pin" in f]


def test_mirror_floats_only_ocx_toolchain(tmp_path):
    f = pins(tmp_path, True)
    assert len(f) == 1 and "'other'" in f[0]


def test_full_profile_rejects_float(tmp_path):
    assert len(pins(tmp_path, False)) == 3
