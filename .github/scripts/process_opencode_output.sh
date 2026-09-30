#!/bin/bash
# ABOUTME: Processes opencode run JSONL output and extracts the last text response.
# ABOUTME: Ported from nagyv/gitlab-opencode (MIT) scripts/process_opencode_output.sh
# Usage: process_opencode_output.sh <input.jsonl> [output.out]
# Prints extracted text to stdout; optionally also writes to output file.
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <input.jsonl> [output.out]" >&2
  exit 2
fi

INPUT="$1"
if [ ! -f "$INPUT" ]; then
  echo "Input file not found: $INPUT" >&2
  exit 1
fi

# Filter for text parts, take the last one, extract text field.
# Fallback chain: jq -> python3 -> raw line (never crash, never empty-exit).
TEXT=""
if command -v jq >/dev/null 2>&1; then
  TEXT=$(grep -E '"type":[ ]*"text"' "$INPUT" | tail -1 | jq -r '.part.text // empty' || true)
elif command -v python3 >/dev/null 2>&1; then
  TEXT=$(grep -E '"type":[ ]*"text"' "$INPUT" | tail -1 | python3 -c 'import json,sys; raw=sys.stdin.read().strip(); print(json.loads(raw).get("part",{}).get("text","") if raw else "")' || true)
else
  TEXT=$(grep -E '"type":[ ]*"text"' "$INPUT" | tail -1 || true)
fi

if [ "$#" -ge 2 ]; then
  printf '%s\n' "$TEXT" > "$2"
fi
printf '%s\n' "$TEXT"
