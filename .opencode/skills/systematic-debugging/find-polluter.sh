#!/usr/bin/env bash
# Bisection script to find which test creates unwanted files/state
# Usage: ./find-polluter.sh <file_or_dir_to_check> <test_pattern>
# Example: ./find-polluter.sh '.git' 'src/**/*.test.ts'

set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 <file_to_check> <test_pattern>"
  echo "Example: $0 '.git' 'src/**/*.test.ts'"
  exit 1
fi

POLLUTION_CHECK="$1"
TEST_PATTERN="$2"
# Per-run log for the test output (overridable for parallel runs).
LOG_FILE="${POLLUTER_LOG:-/tmp/find-polluter.log}"

echo "🔍 Searching for test that creates: $POLLUTION_CHECK"
echo "Test pattern: $TEST_PATTERN"
echo ""

# Derive a -name match plus a literal directory filter from the glob:
# -name handles '*' portably, and grep -F keeps '**' semantics (any depth)
# without relying on find -path, where '**/' cannot match zero levels
# (src/**/*.test.ts would otherwise skip src/top.test.ts).
NAME_PAT=$(basename "$TEST_PATTERN")
DIR_PAT=$(dirname "$TEST_PATTERN")
DIR_PAT=${DIR_PAT%/\*\*}
TEST_FILES=$(find . -name "$NAME_PAT" | grep -F "$DIR_PAT" | sort -u || true)
if [ -z "$TEST_FILES" ]; then
  TOTAL=0
else
  TOTAL=$(printf '%s\n' "$TEST_FILES" | wc -l | tr -d ' ')
fi

echo "Found $TOTAL test files"
echo ""

COUNT=0
# Pipe into while (not for-in over $TEST_FILES): filenames with spaces,
# tabs, or glob characters would otherwise split or expand.
printf '%s\n' "$TEST_FILES" | while IFS= read -r TEST_FILE; do
  COUNT=$((COUNT + 1))

  # Skip if pollution already exists
  if [ -e "$POLLUTION_CHECK" ]; then
    echo "⚠️  Pollution already exists before test $COUNT/$TOTAL"
    echo "   Skipping: $TEST_FILE"
    continue
  fi

  echo "[$COUNT/$TOTAL] Testing: $TEST_FILE"

  # Run the test. The -- ends npm's own flags so a test path starting
  # with '-' can't inject options; output goes to a log file instead of
  # /dev/null so a polluting run can be inspected afterwards.
  npm test -- "$TEST_FILE" > "$LOG_FILE" 2>&1 || true

  # Check if pollution appeared
  if [ -e "$POLLUTION_CHECK" ]; then
    echo ""
    echo "🎯 FOUND POLLUTER!"
    echo "   Test: $TEST_FILE"
    echo "   Created: $POLLUTION_CHECK"
    echo ""
    echo "Pollution details:"
    ls -la -- "$POLLUTION_CHECK"
    echo ""
    echo "To investigate:"
    echo "  npm test -- \"$TEST_FILE\"    # Run just this test"
    echo "  cat -- \"$TEST_FILE\"         # Review test code"
    exit 1
  fi
done

echo ""
echo "✅ No polluter found - all tests clean!"
exit 0
