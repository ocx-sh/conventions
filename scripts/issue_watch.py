#!/usr/bin/env python3
"""Weekly stale-issue digest: open outsider issues in both orgs with no maintainer comment for >= 7 days -> one Discord post.

issue_watch.py [--offline DIR] [--now ISO8601] [--days 7]
Remote facts come through gh_pages(); --offline reads DIR/remote.json ({"pages": [search pages], "comments": {html_url: [pages]}})
and prints the payload instead of posting. Posting needs OCX_ISSUES_HOOK; nothing is posted when no issue is overdue.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

QUERY = "org:ocx-contrib org:ocx-sh is:issue is:open"  # one search ORs repeated org: qualifiers (verified)
MAINTAINER = {"OWNER", "MEMBER", "COLLABORATOR"}
PING = "227748867204972545"


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def gh_pages(*args):
    r = subprocess.run(["gh", "api", "--paginate", "--slurp", *args], capture_output=True, text=True, check=False)
    if r.returncode:
        sys.exit(f"issue_watch.py: gh api failed: {r.stderr.strip()[-200:]}")
    return json.loads(r.stdout)


def fetch(issue):
    """Comment pages for one issue."""
    return gh_pages(issue["comments_url"])


def flat(pages, key=None):
    return [x for p in pages for x in (p[key] if key else p)]


def outsider(i):
    return i["author_association"] not in MAINTAINER and not (i["user"]["login"].endswith("[bot]") or i["user"].get("type") == "Bot")


def last_touch(issue, comments):
    """Latest maintainer comment, else the issue's creation."""
    times = [ts(c["created_at"]) for c in comments if c["author_association"] in MAINTAINER]
    return max(times, default=ts(issue["created_at"]))


def overdue(issues, comments_of, now, days):
    out = []
    for i in issues:
        if not outsider(i):
            continue
        since = last_touch(i, comments_of(i) if i["comments"] else [])
        if now - since >= timedelta(days=days):
            out.append((i, (now - since).days))
    return sorted(out, key=lambda t: -t[1])


def payload(rows):
    lines = [f"[{i['repository_url'].split('repos/')[1]}#{i['number']}]({i['html_url']}) {i['title'][:80]} ({d}d)" for i, d in rows]
    desc = "\n".join(lines)
    if len(desc) > 4000:  # embed description cap is 4096
        desc = desc[:4000].rsplit("\n", 1)[0] + "\n..."
    return {"content": f"<@{PING}> {len(rows)} issue(s) without a maintainer reply",
            "embeds": [{"title": "Stale issues", "description": desc}],
            "allowed_mentions": {"parse": [], "users": [PING]}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now")
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    now = ts(a.now) if a.now else datetime.now(timezone.utc)
    if a.offline:
        try:
            remote = json.loads((Path(a.offline) / "remote.json").read_text())
        except (OSError, ValueError) as e:
            sys.exit(f"issue_watch.py: invalid remote.json in {a.offline}: {e!r}")
        issues = flat(remote["pages"], "items")
        comments_of = lambda i: flat(remote["comments"].get(i["html_url"], []))
    else:
        # ponytail: search caps at 1000 results and github.token sees public repos only; split the query or use the renovate app token past that
        issues = flat(gh_pages("search/issues", "-X", "GET", "-f", f"q={QUERY}", "-f", "per_page=100"), "items")
        comments_of = lambda i: flat(fetch(i))
    rows = overdue(issues, comments_of, now, a.days)
    if not rows:
        print("no overdue issues")
        return
    body = payload(rows)
    if a.offline:
        print(json.dumps(body, indent=2))
        return
    hook = os.environ.get("OCX_ISSUES_HOOK")
    if not hook:
        sys.exit("issue_watch.py: OCX_ISSUES_HOOK is empty")
    req = urllib.request.Request(hook, json.dumps(body).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).close()
    print(f"posted {len(rows)} issue(s)")


if __name__ == "__main__":
    main()
