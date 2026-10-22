"""Stale-issue digest (scripts/issue_watch.py): 7-day threshold, maintainer reply resets, outsiders only, pagination merge."""
import json
import subprocess
import sys

from stubs import REPO_ROOT

NOW = "2026-10-26T12:00:00Z"


def issue(n, created, assoc="NONE", login="stranger", comments=0):
    return {"number": n, "title": f"issue {n}", "created_at": created, "author_association": assoc, "user": {"login": login},
            "comments": comments, "html_url": f"https://github.com/ocx-contrib/mirror-x/issues/{n}",
            "repository_url": "https://api.github.com/repos/ocx-contrib/mirror-x"}


def comment(created, assoc):
    return {"created_at": created, "author_association": assoc}


def run(tmp_path, pages, comments=None):
    (tmp_path / "remote.json").write_text(json.dumps({"pages": pages, "comments": comments or {}}))
    r = subprocess.run([sys.executable, REPO_ROOT / "scripts" / "issue_watch.py", "--offline", tmp_path, "--now", NOW],
                       capture_output=True, text=True, check=True)
    return r.stdout


def listed(out):
    return [] if "no overdue" in out else json.loads(out)["embeds"][0]["description"].splitlines()


def test_threshold_six_days_skipped_seven_listed(tmp_path):
    out = run(tmp_path, [{"items": [issue(1, "2026-10-20T12:00:01Z"), issue(2, "2026-10-19T12:00:00Z")]}])
    rows = listed(out)
    assert len(rows) == 1 and "#2" in rows[0] and "(7d)" in rows[0]


def test_empty_digest_posts_nothing(tmp_path):
    assert run(tmp_path, [{"items": [issue(1, "2026-10-25T00:00:00Z")]}]).strip() == "no overdue issues"


def test_maintainer_reply_resets_but_outsider_reply_does_not(tmp_path):
    a, b = issue(1, "2026-10-01T00:00:00Z", comments=1), issue(2, "2026-10-01T00:00:00Z", comments=1)
    out = run(tmp_path, [{"items": [a, b]}], {a["html_url"]: [[comment("2026-10-24T00:00:00Z", "MEMBER")]],
                                              b["html_url"]: [[comment("2026-10-24T00:00:00Z", "NONE")]]})
    rows = listed(out)
    assert len(rows) == 1 and "#2" in rows[0]


def test_maintainer_and_bot_authored_excluded(tmp_path):
    old = "2026-09-01T00:00:00Z"
    out = run(tmp_path, [{"items": [issue(1, old, "OWNER", "michael-herwig"), issue(2, old, "NONE", "renovate[bot]"),
                                    issue(3, old, "COLLABORATOR")]}])
    assert listed(out) == []


def test_pages_merge_and_mention_is_pinned(tmp_path):
    old = "2026-09-01T00:00:00Z"
    body = json.loads(run(tmp_path, [{"items": [issue(1, old)]}, {"items": [issue(2, old)]}]))
    assert len(body["embeds"][0]["description"].splitlines()) == 2
    assert body["allowed_mentions"] == {"parse": [], "users": ["227748867204972545"]} and "<@227748867204972545>" in body["content"]
