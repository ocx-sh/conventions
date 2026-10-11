#!/usr/bin/env python3
"""C-018 status page: render drift/check.py status.json as a static index.html table (no JS)."""
import argparse
import html
import json
from pathlib import Path

CSS = """
body { font: 14px/1.4 system-ui, sans-serif; margin: 16px; color: #1b1b1b; }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #f4f4f4; }
code { background: #f0f0f0; padding: 0 3px; }
.excluded td { color: #777; }
"""


def esc(value):
    return html.escape("" if value is None else str(value))


def flags_cell(repo):
    items = [f"<li><code>{esc(f['class'])}</code> {esc(f['detail'])}</li>" for f in repo["flags"]]
    if repo["excluded"]:
        items.append(f"<li>excluded: {esc(repo['reason'])}</li>")
    return f"<ul>{''.join(items)}</ul>" if items else "none"


def row(repo):
    cls = ' class="excluded"' if repo["excluded"] else ""
    return (f"<tr{cls}><td>{esc(repo['key'])}</td><td>{esc(repo['repo'])}</td>"
            f"<td>{esc(repo['baseline_version'])}</td><td>{esc(repo['latest_version'])}</td>"
            f"<td>{flags_cell(repo)}</td></tr>")


def render(data):
    rows = "\n".join(row(r) for r in data["repos"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ocx-conventions status</title>
<style>{CSS}</style>
</head>
<body>
<h1>ocx-conventions status</h1>
<p>Generated {esc(data['generated_at'])} · latest baseline {esc(data['latest_version'])}</p>
<table>
<thead><tr><th>key</th><th>repo</th><th>baseline</th><th>latest</th><th>flags</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("status", type=Path, help="status.json from drift/check.py")
    ap.add_argument("-o", "--out", "--output", dest="out", type=Path, required=True, help="index.html to write")
    args = ap.parse_args()
    data = json.loads(args.status.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(data), encoding="utf-8")


if __name__ == "__main__":
    main()
