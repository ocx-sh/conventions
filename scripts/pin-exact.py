#!/usr/bin/env python3
"""pin-exact.py <ocx.toml>: pin floating ocx tool tags to the newest exact X.Y.Z, sort tools into
their D-04 groups (scripts/groups.toml), then run `ocx lock`. Line-based rewrite so comments,
blank lines and unknown tables (platform groups) survive. Idempotent."""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ENTRY = re.compile(r'^(\s*)([A-Za-z0-9_.-]+)(\s*=\s*)"([^"]*)"(.*)$')
HEADER = re.compile(r"^\s*\[+\s*([^\]]+?)\s*\]+")
EXACT = re.compile(r"^\d+\.\d+\.\d+")
PLAIN = re.compile(r"^\d+\.\d+\.\d+$")
groups = tomllib.loads((Path(__file__).parent / "groups.toml").read_text())["groups"]
index_cache: dict[str, list[tuple[int, ...]]] = {}


def die(msg: str) -> None:
    sys.exit(f"pin-exact: {msg}")


def versions(repo: str) -> list[tuple[int, ...]]:
    if repo not in index_cache:
        r = subprocess.run(["ocx", "index", "list", repo], capture_output=True, text=True)
        if r.returncode:
            die(f"`ocx index list {repo}` failed: {r.stderr.strip()}")
        tags = [ln.split()[-1] for ln in r.stdout.splitlines() if ln.split()]
        index_cache[repo] = [tuple(map(int, t.split("."))) for t in tags if PLAIN.match(t)]
    return index_cache[repo]


def pin(name: str, ref: str) -> str:
    repo, _, tag = ref.partition(":")
    if EXACT.match(tag):
        return ref
    prefix = () if tag in ("", "latest") else tuple(map(int, tag.split(".")))
    if not all(p.isdigit() for p in ([] if not prefix else tag.split("."))):
        die(f"{name}: cannot interpret tag {tag!r} in {ref!r}")
    hits = [v for v in versions(repo) if v[: len(prefix)] == prefix]
    if not hits:
        die(f"{name}: no exact X.Y.Z tag matching {tag or 'latest'!r} in `ocx index list {repo}`")
    return f"{repo}:{'.'.join(map(str, max(hits)))}"


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: pin-exact.py <ocx.toml>")
    path = Path(sys.argv[1])
    lines = path.read_text().splitlines(keepends=True)
    out: list[str] = []
    moved: dict[str, list[str]] = {}
    section = ""
    for ln in lines:
        h = HEADER.match(ln)
        if h:
            section = h.group(1)
        m = ENTRY.match(ln)
        if not h and m and (section == "tools" or re.fullmatch(r"group\.[^.]+\.tools", section)):
            name = m.group(2)
            ln = f'{m.group(1)}{name}{m.group(3)}"{pin(name, m.group(4))}"{m.group(5)}\n'
            if section == "tools":
                if name not in groups:
                    print(f"pin-exact: warning: tool {name!r} not in groups.toml, left in [tools]", file=sys.stderr)
                elif groups[name] != "default":
                    block = [ln]  # entry plus the comment lines directly above it
                    while out and out[-1].lstrip().startswith("#"):
                        block.insert(0, out.pop())
                    moved.setdefault(groups[name], []).extend(block)
                    continue
        out.append(ln)
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    for g, block in moved.items():
        head = f"[group.{g}.tools]"
        at = next((i for i, ln in enumerate(out) if ln.strip() == head), None)
        if at is None:
            out += (["\n"] if out and out[-1].strip() else []) + [head + "\n"] + block
            continue
        end = at + 1
        while end < len(out) and not HEADER.match(out[end]):
            end += 1
        while out[end - 1].strip() == "":
            end -= 1
        out[end:end] = block
    path.write_text("".join(out))
    r = subprocess.run(["ocx", "lock"], cwd=path.parent)
    sys.exit(r.returncode)


main()
