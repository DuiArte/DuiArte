#!/usr/bin/env python3
"""Regenerate the "Recent activity" section of the profile README from the latest
commits on DuiArte/ltcma.

Sources, in order:
  1. a local clone, if env LTCMA_REPO points to one (fast, used when run locally);
  2. the public GitHub API otherwise (used by the daily Action). An optional
     GH_TOKEN / GITHUB_TOKEN raises the rate limit but is not required.

Automated refresh commits and trivial maintenance are filtered out, and commits
are de-duplicated by scope prefix (the text before the first ":") so a burst of
"backtests: ..." commits collapses to a single, most-recent line. The result is
written between the ACTIVITY:START / ACTIVITY:END markers in README.md; the file
is rewritten only if the section actually changed.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

OWNER = os.environ.get("ACTIVITY_OWNER", "DuiArte")
REPO = os.environ.get("ACTIVITY_REPO", "ltcma")
N_SHOW = int(os.environ.get("ACTIVITY_COUNT", "6"))

HERE = os.path.dirname(os.path.abspath(__file__))
README = os.path.join(os.path.dirname(HERE), "README.md")
START, END = "<!-- ACTIVITY:START -->", "<!-- ACTIVITY:END -->"

# commits whose message matches these are noise, not showcase activity
SKIP = re.compile(
    r"^(daily refresh|auto-refresh|merge |wip\b)"
    r"|portfolio tracker update"
    r"|portfolio: snapshot"
    r"|restore exec|exec bit|filesystem paths|mode change|^fixup|typo",
    re.IGNORECASE,
)


def from_local(path):
    out = subprocess.check_output(
        ["git", "-C", path, "log", "-60", "--pretty=format:%cI%x09%s"],
        text=True)
    rows = []
    for line in out.splitlines():
        iso, _, msg = line.partition("\t")
        rows.append((iso, msg))
    return rows


def from_api():
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/commits?per_page=60"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{OWNER}-profile-readme",
    })
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    rows = []
    for c in data:
        commit = c.get("commit", {})
        iso = commit.get("committer", {}).get("date") or commit.get("author", {}).get("date")
        msg = (commit.get("message") or "").splitlines()[0]
        rows.append((iso, msg))
    return rows


def relative(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ""
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    for size, unit in ((86400 * 365, "year"), (86400 * 30, "month"),
                       (86400 * 7, "week"), (86400, "day"),
                       (3600, "hour"), (60, "minute")):
        n = int(secs // size)
        if n >= 1:
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"


def curate(rows):
    seen, out = set(), []
    for iso, msg in rows:
        msg = msg.strip()
        if not msg or SKIP.search(msg):
            continue
        scope = msg.split(":", 1)[0].lower() if ":" in msg else msg.lower()
        if scope in seen:
            continue
        seen.add(scope)
        out.append((iso, msg))
        if len(out) >= N_SHOW:
            break
    return out


def main():
    local = os.environ.get("LTCMA_REPO")
    try:
        rows = from_local(local) if local and os.path.isdir(os.path.join(local, ".git")) else from_api()
    except Exception as exc:  # never hard-fail the Action over a transient error
        print(f"update_profile_readme: could not fetch commits ({exc})", file=sys.stderr)
        return 0

    items = curate(rows)
    if not items:
        print("update_profile_readme: no commits after filtering; leaving README as-is")
        return 0

    bullets = "\n".join(f"- **{msg}** &mdash; {relative(iso)}" for iso, msg in items)
    section = (f"{START}\n{bullets}\n\n"
               f"_Auto-updated daily from [{OWNER}/{REPO}](https://github.com/{OWNER}/{REPO})._\n{END}")

    text = open(README, encoding="utf-8").read()
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), section, text, flags=re.DOTALL)
    if new == text:
        print("update_profile_readme: activity unchanged")
        return 0
    open(README, "w", encoding="utf-8").write(new)
    print(f"update_profile_readme: wrote {len(items)} activity lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
