#!/usr/bin/env python3
"""untrack_grim.py [repo] — stop committing grim client output (D-05); stages `git rm --cached`, never commits.

Untracks every file under the gitignored client dirs that belongs to an artifact in grimoire.lock. Tracked files
under those dirs that grimoire.lock does not name are repo-owned: they are listed, left tracked, and belong in
agent-config/ as path sources (`grim add ./agent-config/<name>`). Exit 0 clean, 1 repo-owned files remain.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

DIRS = (".claude/skills", ".claude/rules", ".opencode/skills", ".opencode/rules", ".agents/skills")

repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
if not (repo / "grimoire.lock").is_file():
    sys.exit("untrack_grim: no grimoire.lock; run task setup first")
lock = tomllib.loads((repo / "grimoire.lock").read_text())
names = {a["name"] for kind in ("skill", "rule", "agent") for a in lock.get(kind, [])}
tracked = subprocess.run(["git", "-C", repo, "ls-files", "-z", "--", *DIRS], capture_output=True, text=True, check=True).stdout
grim, owned = [], []
for path in filter(None, tracked.split("\0")):
    d = next(d for d in DIRS if path.startswith(d + "/"))
    top = path[len(d) + 1:].split("/")[0]
    if top == ".gitignore":
        continue
    (grim if top.removesuffix(".md") in names else owned).append(path)
for i in range(0, len(grim), 500):
    subprocess.run(["git", "-C", repo, "rm", "-q", "--cached", "--", *grim[i:i + 500]], check=True)
print(f"untrack_grim: {len(grim)} grim-installed files untracked")
if owned:
    print("untrack_grim: repo-owned files under grim client dirs (move to agent-config/, then grim add):")
    print("\n".join(sorted({p if p.count("/") < 3 else "/".join(p.split("/")[:3]) for p in owned})))
    sys.exit(1)
