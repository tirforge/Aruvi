#!/bin/bash
# ABOUTME: gh with exactly one bounded retry on transient failures.
# ABOUTME: Reads-only contract: use for gh READS (api get, pr checks, pr view).
# Usage: gh-retry.sh <gh args...>
# A 5xx never says whether a write landed, so writes retried blindly can
# double-post. Callers needing write retries must verify-then-retry
# themselves; this helper intentionally stays read-safe and dumb.
set -uo pipefail

DELAY="${GH_RETRY_DELAY:-15}"
TMP="$(mktemp "${TMPDIR:-/tmp}/gh-retry.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

if gh "$@" 2>"$TMP"; then
  exit 0
fi
ERR="$(cat "$TMP")"
printf '%s\n' "$ERR" >&2

case "$ERR" in
  *"HTTP 502"*|*"HTTP 503"*|*"HTTP 504"*|*"connection reset"*|\
  *"Connection refused"*|*"timed out"*|*"Timeout"*|*"Temporary failure"*|\
  *"Could not resolve host"*|*"rate limit"*|*"socket hang up"*|*"EOF"*)
    echo "gh-retry: transient failure suspected — one retry in ${DELAY}s..." >&2
    sleep "$DELAY"
    RC=0
    gh "$@" || RC=$?
    rm -f "$TMP"
    trap - EXIT
    exit "$RC"
    ;;
  *)
    exit 1
    ;;
esac
