"""PR hygiene: nudge stale PRs, auto-close stale BOT PRs only.

Reads open PRs (JSON from `gh pr list`) and prints actions, one per line:
  NUDGE <pr> <days>   — human or bot PR idle longer than the nudge threshold
  CLOSE <pr> <days>   — bot-authored PR idle longer than the close threshold
  OK <pr>             — fresh, or already nudged (has the hygiene label)

Policy (deliberate asymmetry): humans are never auto-closed — a nudge plus
a label is the most the bot does. Bot PRs (dependabot, opencode fix PRs)
that nobody looked at for a month are dead weight; close them with a note.

Usage: pr-hygiene.py <prs.json> [--nudge-days 7] [--close-days 30]
"""
import json
import sys
from datetime import datetime, timezone

NUDGE_LABEL = "hygiene-nudged"


def parse_args(argv):
    nudge_days, close_days, path = 7, 30, None
    it = iter(argv)
    for a in it:
        if a == "--nudge-days":
            nudge_days = int(next(it))
        elif a == "--close-days":
            close_days = int(next(it))
        elif path is None:
            path = a
        else:
            raise SystemExit(f"unexpected arg: {a}")
    if path is None:
        raise SystemExit("usage: pr-hygiene.py <prs.json>")
    return path, nudge_days, close_days


def main() -> None:
    path, nudge_days, close_days = parse_args(sys.argv[1:])
    prs = json.loads(open(path).read())
    if isinstance(prs, dict):
        prs = [prs]
    now = datetime.now(timezone.utc)
    for pr in prs:
        num = pr["number"]
        updated = datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00"))
        days = (now - updated).days
        labels = [lbl["name"] for lbl in pr.get("labels", [])]
        bot = pr.get("author", {}).get("login", "").endswith("[bot]")
        if days >= close_days and bot:
            print(f"CLOSE {num} {days}")
        elif days >= nudge_days and NUDGE_LABEL not in labels:
            print(f"NUDGE {num} {days}")
        else:
            print(f"OK {num}")


if __name__ == "__main__":
    main()
