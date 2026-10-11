#!/usr/bin/env python3
"""C-017 drift checker: fleet.toml + remote facts -> status.json (drift/schema.json). Exit 0 unless input is invalid (2).

check.py [--offline DIR] [--fleet fleet.toml] [--out status.json]
All remote facts come through fetch_remote(); --offline reads DIR/remote.json (same shape) instead of `gh api`.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

CONVENTIONS = "ocx-sh/conventions"
RED = {"failure", "timed_out", "startup_failure"}
REF = re.compile(r"^(ocx\.sh/[^:\s]+):(\d+\.\d+\.\d+)")


def vt(s):
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(map(int, m.groups())) if m else None


def older(a, b):
    """True when version a is parseably older than b; unparseable never flags."""
    return bool(vt(a) and vt(b) and vt(a) < vt(b))


# ---- remote facts -------------------------------------------------------------------------

class Unreachable(Exception):
    """A repo fact could not be fetched for a reason other than 'absent' (403, rate limit, network)."""


def run(*args):
    """-> (returncode, stdout, stderr); a missing binary or timeout is (-1, '', reason). Never raises."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", repr(e)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def gh(*args):
    """stdout of a command or None on any failure; never raises. For facts whose absence is not a repo problem."""
    rc, out, _ = run(*args)
    return out if rc == 0 else None


def gh_strict(*args):
    """stdout, or None on HTTP 404 (absent); raises Unreachable on any other failure (403, rate limit, network)."""
    rc, out, err = run(*args)
    if rc == 0:
        return out
    if "HTTP 404" in err:
        return None
    raise Unreachable(((err.splitlines() or [f"exit {rc}"])[-1])[:200])


def contents(repo, path):
    out = gh_strict("gh", "api", f"repos/{repo}/contents/{path}", "--jq", ".content")
    try:
        return base64.b64decode(out).decode() if out else None
    except ValueError:
        return None


def workflows(repo):
    names = (gh_strict("gh", "api", f"repos/{repo}/contents/.github/workflows", "--jq", ".[].name") or "").split()
    return "\n".join(contents(repo, f".github/workflows/{n}") or "" for n in names if n.endswith((".yml", ".yaml")))


def commit_of(answers):
    m = re.search(r"^_commit:\s*[\"']?(\S+?)[\"']?\s*$", answers or "", re.M)
    return m.group(1) if m else None


def scrape(text):
    """-> (setup-ocx version, ocx CLI version) from workflow or composite-action text; None when absent."""
    ref = (re.search(r"ocx-sh/setup-ocx@\S+[ \t]+#\s*(v?\d+\.\d+\.\d+)", text)  # comment after uses:
           or re.search(r"#\s*(v?\d+\.\d+\.\d+)[ \t]*\n\s*uses:\s*ocx-sh/setup-ocx@", text)  # comment above uses:
           or re.search(r"ocx-sh/setup-ocx@(v\d+\.\d+\.\d+)", text))
    cli = re.search(r"\bversion:\s*[\"']?(\d+\.\d+\.\d+)[\"']?", text) if "setup-ocx" in text else None
    return ref and ref.group(1), cli and cli.group(1)


def renovate_prs(repo):
    out = gh_strict("gh", "pr", "list", "-R", repo, "--state", "open", "--limit", "200", "--json", "headRefName")
    try:
        return sum(str(p["headRefName"]).startswith("renovate/") for p in json.loads(out or "[]"))
    except (ValueError, TypeError, KeyError):
        raise Unreachable("unparseable PR list") from None


def fetch_repo(repo):
    try:
        return _fetch_repo(repo)
    except Unreachable as e:
        return {"unreachable": str(e)}


def _fetch_repo(repo):
    answers = contents(repo, ".copier-answers.yml")
    base = commit_of(answers)
    # Adopted repos call the conventions composite setup action, so its pins at the recorded _commit are authoritative;
    # workflow text is the fallback (non-adopted repos, or a tag that no longer resolves).
    action = contents(CONVENTIONS, f".github/actions/setup/action.yml?ref={base}") if base else None
    a, w = scrape(action or ""), scrape(workflows(repo))
    run_ = gh("gh", "run", "list", "-R", repo, "--workflow", "verify-deep.yml", "--event", "schedule", "--limit", "1",
              "--json", "conclusion", "--jq", ".[0].conclusion")
    return {
        "answers": answers,
        "ocx_toml": contents(repo, "ocx.toml"),
        "grimoire_toml": contents(repo, "grimoire.toml"),
        "setup_ocx_ref": a[0] or w[0],
        "ocx_cli": a[1] or w[1],
        "renovate_prs": renovate_prs(repo),
        "nightly": run_ or None,
        # ponytail: never flags online. Upgrade path: install grim on the status runner, write the repo's
        # grimoire.toml + grimoire.lock to a temp dir, run `grim --format json status --check --config <toml>`
        # and flag any item whose `update_available` is non-null.
        "grim_floating_pending": False,
    }


def newest_tag(out):
    tags = [t for t in (out or "").split() if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    return max(tags, key=vt, default=None)


def fetch_remote(fleet):
    repos = {}
    for key, r in fleet.items():
        if not r["excluded"] and "*" not in r["repo"]:  # ponytail: mirror-* globs are not enumerated; rollout is iteration 3
            repos[key] = fetch_repo(r["repo"])
    pkgs = {m.group(1) for f in repos.values() for m in map(REF.match, ref_strings(f.get("ocx_toml"))) if m}
    index = {}
    for p in sorted(pkgs):
        gh("ocx", "index", "update", p)  # the runner's local index starts empty; a failed refresh just leaves it stale
        out = gh("ocx", "--format", "json", "index", "list", p)
        try:
            vs = [v for v in json.loads(out)[p] if re.fullmatch(r"\d+\.\d+\.\d+", v)]
            index[p] = max(vs, key=vt) if vs else None
        except (TypeError, ValueError, KeyError):
            index[p] = None
    ocx = gh("gh", "api", "repos/ocx-sh/ocx/releases/latest", "--jq", ".tag_name")
    return {
        "latest_version": newest_tag(gh("gh", "api", f"repos/{CONVENTIONS}/tags", "--jq", ".[].name")),
        "newest_setup_ocx": gh("gh", "api", "repos/ocx-sh/setup-ocx/releases/latest", "--jq", ".tag_name"),
        "newest_ocx": ocx and ocx.lstrip("v"),
        "index": index,
        "repos": repos,
    }


# ---- classification -----------------------------------------------------------------------

def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def ref_strings(text):
    try:
        return list(strings(tomllib.loads(text or "")))
    except tomllib.TOMLDecodeError:
        return []


def expected_bundles(answers):
    if answers.get("profile") != "full":
        return []
    out = ["docs-essentials", "code-docs-essentials"]
    out += [f"{lang}-essentials" for lang in answers.get("languages", []) if lang != "bazel"]  # ponytail: only bazel lacks a <lang>-essentials bundle
    return out + (["ocx-theme"] if answers.get("theme_bundle") else [])


def present_bundles(text):
    try:
        b = tomllib.loads(text or "").get("bundles", {})
    except tomllib.TOMLDecodeError:
        return set()
    return set(b) | {v.rsplit("/", 1)[-1].split(":")[0] for v in strings(b)}


def classify(r, rf, remote):
    """-> (baseline_version, [(class, detail)]) for one adopted-or-not, non-excluded repo."""
    if rf.get("unreachable"):
        return None, [("unreachable", rf["unreachable"])]
    if not rf.get("answers"):
        return None, [("not-adopted", "no .copier-answers.yml on the default branch")]
    base = commit_of(rf["answers"])
    latest = remote["latest_version"]
    flags = []
    if base != latest and not (vt(base) and vt(latest) and vt(base) >= vt(latest)):
        flags.append(("baseline-behind", f"recorded {base or 'unknown'}, latest {latest}"))
    stale = [f"{m.group(1).rsplit('/', 1)[-1]} {m.group(2)} < {remote['index'][m.group(1)]}"
             for m in map(REF.match, ref_strings(rf.get("ocx_toml")))
             if m and older(m.group(2), (remote.get("index") or {}).get(m.group(1)))]
    if stale:
        flags.append(("stale-pin", "; ".join(stale)))
    if older(rf.get("setup_ocx_ref"), remote.get("newest_setup_ocx")):
        flags.append(("setup-ocx-stale", f"{rf['setup_ocx_ref']} < {remote['newest_setup_ocx']}"))
    if older(rf.get("ocx_cli"), remote.get("newest_ocx")):
        flags.append(("ocx-cli-stale", f"{rf['ocx_cli']} < {remote['newest_ocx']}"))
    if rf.get("renovate_prs", 0) > 0:
        flags.append(("pending-updates", f"{rf['renovate_prs']} open Renovate PR(s)"))
    if rf.get("nightly") in RED:
        flags.append(("nightly-red", f"last scheduled verify-deep: {rf['nightly']}"))
    missing = [b for b in expected_bundles(r["answers"]) if b not in present_bundles(rf.get("grimoire_toml"))]
    if missing:
        flags.append(("bundle-missing", "missing: " + ", ".join(missing)))
    if rf.get("grim_floating_pending"):
        flags.append(("grim-pending", "a floating tag has a newer upstream digest"))
    return base, flags


def build(fleet, remote):
    rows = []
    for key, r in fleet.items():
        row = {"key": key, "repo": r["repo"], "baseline_version": None, "latest_version": remote["latest_version"],
               "adopted": False, "excluded": r["excluded"], "reason": r["reason"] if r["excluded"] else None, "flags": []}
        if not r["excluded"]:
            base, flags = classify(r, (remote.get("repos") or {}).get(key) or {}, remote)
            row.update(baseline_version=base, adopted=bool(((remote.get("repos") or {}).get(key) or {}).get("answers")),
                       flags=[{"class": c, "detail": d} for c, d in flags])
        rows.append(row)
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latest_version": remote["latest_version"], "repos": rows}


def load_fleet(path):
    try:
        data = tomllib.loads(Path(path).read_text())
        out = {}
        for key, r in data["repos"].items():
            out[key] = {"repo": r["repo"], "excluded": bool(r.get("excluded")), "reason": r.get("reason"),
                        "answers": r.get("answers", {})}
        return out
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError, AttributeError) as e:
        sys.exit(f"check.py: invalid fleet file {path}: {e!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--fleet")
    ap.add_argument("--out", default="status.json")
    a = ap.parse_args()
    fleet_path = a.fleet or (Path(a.offline) / "fleet.toml" if a.offline else "fleet.toml")
    fleet = load_fleet(fleet_path)
    if a.offline:
        try:
            remote = json.loads((Path(a.offline) / "remote.json").read_text())
        except (OSError, ValueError) as e:
            sys.exit(f"check.py: invalid remote.json in {a.offline}: {e!r}")
    else:
        remote = fetch_remote(fleet)
    remote["latest_version"] = remote.get("latest_version") or "unknown"
    Path(a.out).write_text(json.dumps(build(fleet, remote), indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            sys.exit(2)
        raise
