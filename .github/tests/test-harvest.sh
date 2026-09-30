#!/bin/bash
# ABOUTME: Fixture test for the harvest -> redact -> merge chain. No network.
# Fails (exit 1) on any drift: extraction filters, redaction, or merge grouping.
set -euo pipefail

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FIXTURE=".github/tests/fixtures"

FIXTURE_DIR="$FIXTURE" bash .github/scripts/harvest-findings.sh dummy/repo 1 dummy_key "$T/out" > /dev/null
python3 .github/scripts/redact-secrets.py "$T/out" > /dev/null
python3 .github/scripts/merge-findings.py "$T/out"

diff -u "$FIXTURE/expected-merged.md" "$T/out/merged.md" && echo HARVEST-FIXTURE-PASS
