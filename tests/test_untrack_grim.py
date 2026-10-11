"""D-05 scripts/untrack_grim.py: untrack grim-installed client files, keep and report repo-owned ones."""

import sys

from conftest import REPO_ROOT, git_env_dict, run


def test_untracks_lock_artifacts_and_reports_repo_owned(tmp_path):
    env = git_env_dict()
    files = {"grimoire.lock": '[[skill]]\nname = "a"\n\n[[rule]]\nname = "r"\n',
             ".claude/skills/a/SKILL.md": "x", ".agents/skills/a/SKILL.md": "x", ".claude/rules/r.md": "x",
             ".claude/rules/r/ref.md": "x", ".claude/skills/.gitignore": "*\n!.gitignore\n",
             ".claude/skills/own/SKILL.md": "x", ".claude/rules/house.md": "x"}
    for p, t in files.items():
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).write_text(t)
    run(["git", "init", "-q"], tmp_path, env)
    run(["git", "add", "-f", "."], tmp_path, env)
    r = run([sys.executable, REPO_ROOT / "scripts" / "untrack_grim.py", tmp_path], tmp_path, env, check=False)
    left = set(run(["git", "ls-files"], tmp_path, env).stdout.split())
    assert r.returncode == 1 and ".claude/skills/own" in r.stdout and ".claude/rules/house.md" in r.stdout, r.stdout
    assert left == {"grimoire.lock", ".claude/skills/.gitignore", ".claude/skills/own/SKILL.md", ".claude/rules/house.md"}, left
