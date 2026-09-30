"""Monthly review-combo scorecard: runs vs outcomes, no artifact downloads.

Inputs (JSON files from gh):
  runs.json — `gh run list --workflow review-combo.yml --json conclusion,headBranch,createdAt`
Prints a markdown table body + one-line verdict. The workflow posts it as a
comment on the pinned scorecard issue (or creates it the first month).

Metrics (deliberately cheap):
  - runs in window, green rate, failure rate
  - distinct PR heads touched (loop pressure: high runs-per-PR = churn)
  - [combo-fix] commits in window (from git log — fixes actually shipped)
Usage: scorecard.py <runs.json> <fix_commit_count> <month_label>
"""
import json
import sys
from collections import Counter


def main() -> None:
    runs_path, fix_count, label = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    runs = json.load(open(runs_path))
    if isinstance(runs, dict):
        runs = [runs]
    total = len(runs)
    by_conclusion = Counter(r.get("conclusion", "?") for r in runs)
    heads = len({r.get("headBranch", "?") for r in runs})
    green = by_conclusion.get("success", 0)
    rate = (100.0 * green / total) if total else 0.0
    per_pr = (total / heads) if heads else 0.0
    verdict = (
        "healthy ✅" if rate >= 80 and per_pr <= 3
        else "watch ⚠️" if rate >= 50 else "needs attention ❌"
    )
    print(f"## 📊 review-combo scorecard — {label} ({verdict})")
    print("")
    print(f"| metric | value |")
    print(f"|---|---|")
    print(f"| combo runs | {total} |")
    print(f"| green rate | {rate:.0f}% ({green}/{total}) |")
    print(f"| PR heads touched | {heads} |")
    print(f"| runs per PR (loop pressure) | {per_pr:.1f} |")
    print(f"| [combo-fix] commits shipped | {fix_count} |")
    for conc, n in sorted(by_conclusion.items()):
        print(f"| runs: {conc} | {n} |")


if __name__ == "__main__":
    main()
