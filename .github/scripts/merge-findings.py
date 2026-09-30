"""Merge combo harvest into one deduped finding list.

The fixer used to get three raw reports with the same bug flagged two or
three times (opencode + rabbit + sonar) — double work and contradictory
advice. This folds blocks that point at the same file:line into ONE entry
with sources tagged, so each location is fixed once.

Grouping key is (file, line) only — never message text: two different bugs
on one line stay separate entries, and a wrong grouping is visible (both
bodies sit under one header) rather than silently dropped.

Usage: merge-findings.py <findings_dir>
Reads opencode.md, rabbit-main.md, rabbit-inline.md, sonar.md.
Writes merged.md. Exit 0 always (merge must never fail a run).
"""
import re
import sys
from collections import OrderedDict
from pathlib import Path

LOC = re.compile(
    r"`?([\w./-]+\.(?:py|ts|tsx|js|jsx|kt|java|go|yml|yaml|toml|gradle|xml))"
    r"(?::(\d+))?`?"
)
SOURCES = [
    ("opencode", "opencode.md"),
    ("rabbit", "rabbit-main.md"),
    ("rabbit-inline", "rabbit-inline.md"),
    ("sonar", "sonar.md"),
]
CLEAN_MARKERS = ("CLEAN", "no open Sonar")


def main() -> None:
    d = Path(sys.argv[1])
    grouped: "OrderedDict[tuple[str, str], list[tuple[str, str]]]" = OrderedDict()
    general: list[tuple[str, str]] = []
    for name, fn in SOURCES:
        p = d / fn
        if not p.exists():
            continue
        for block in [b.strip() for b in p.read_text().split("\n---\n")]:
            if not block or any(m in block for m in CLEAN_MARKERS):
                continue
            m = LOC.search(block)
            if m is None:
                general.append((name, block))
            else:
                grouped.setdefault((m.group(1), m.group(2) or "?"), []).append(
                    (name, block)
                )
    out: list[str] = []
    dupes = sum(len(v) - 1 for v in grouped.values())
    for (f, ln), items in grouped.items():
        names = sorted({n for n, _ in items})
        out.append(f"## `{f}:{ln}` (sources: {', '.join(names)})")
        for n, b in items:
            out.append(f"### via {n}\n{b}")
    if general:
        out.append("## General (no file:line)")
        for n, b in general:
            out.append(f"### via {n}\n{b}")
    if not out:
        out.append("CLEAN: nothing to fix across all three signals.")
    (d / "merged.md").write_text("\n\n---\n\n".join(out) + "\n")
    print(
        f"merge-findings: {len(grouped)} location(s), "
        f"{len(general)} general, {dupes} duplicate(s) folded"
    )


if __name__ == "__main__":
    main()
