"""Redact credential-shaped literals from review-harvest markdown.

Reads every *.md under a directory (default: findings/) and replaces
high-confidence secret patterns with <REDACTED> so step summaries and
uploaded artifacts never leak tokens a model echoed back.

Conservative by design: only token-shaped literals and private-key blocks
are scrubbed. Finding metadata (file:line, rule, message) is untouched —
a hardcoded-secret finding still reads clearly, minus the value.

Usage: redact-secrets.py [dir]
Exit 0 always (redaction must never fail a run); prints redaction count.
"""
import re
import sys
from pathlib import Path

PATTERNS = [
    # GitHub tokens
    r"ghp_[A-Za-z0-9]{8,}",
    r"github_pat_[A-Za-z0-9_]{8,}",
    r"gho_[A-Za-z0-9]{8,}",
    r"ghu_[A-Za-z0-9]{8,}",
    r"ghs_[A-Za-z0-9]{8,}",
    r"ghr_[A-Za-z0-9]{8,}",
    # Slack / AWS / generic provider keys
    r"xox[baprs]-[A-Za-z0-9-]{8,}",
    r"AKIA[0-9A-Z]{16}",
    r"sk-ant-[A-Za-z0-9-_]{8,}",
    r"sk-[A-Za-z0-9-_]{20,}",
    # Private key blocks (multiline)
    r"-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA )?PRIVATE KEY-----",
]
RX = re.compile("|".join(f"(?:{p})" for p in PATTERNS))


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "findings")
    total = 0
    if target.is_dir():
        files = sorted(target.glob("*.md"))
    elif target.is_file():
        files = [target]
    else:
        print(f"redact-secrets: {target} not found, nothing to scrub")
        return
    for f in files:
        text = f.read_text(errors="replace")
        scrubbed, n = RX.subn("<REDACTED>", text)
        if n:
            f.write_text(scrubbed)
            total += n
    print(f"redact-secrets: scrubbed {total} credential-shaped literal(s)")


if __name__ == "__main__":
    main()
