#!/bin/bash
# ABOUTME: Offline fixture test for resolve-model.sh — no CLI, no network, no keys.
# ABOUTME: Guards the model fallback chain and the effort ladder against silent rot.
# The 2026-10 outage was invisible for three weeks because nothing tested this
# path: the pinned model vanished and every opencode job died in 1.3s.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1 # repo root, not .github/

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
REG="$TMP/registry.txt"

# Shape mirrors real `opencode models --verbose` output: id line, then the JSON blob.
cat >"$REG" <<'EOF'
opencode/deepseek-v4.1-flash-free
{
  "id": "deepseek-v4.1-flash-free",
  "variants": {
    "low": {},
    "high": {},
    "max": {}
  }
}
opencode/glm-5.3-flash-free
{
  "id": "glm-5.3-flash-free",
  "variants": {
    "low": {},
    "high": {}
  }
}
opencode/minimax-m3.1-flash-free
{
  "id": "minimax-m3.1-flash-free",
  "variants": {
    "xhigh": {},
    "max": {}
  }
}
EOF

fails=0
check() {
  if [ "$2" = "$3" ]; then
    echo "PASS $1"
  else
    echo "FAIL $1 (expected '$3', got '$2')"
    fails=$((fails + 1))
  fi
}

out=$(OPENCODE_MODELS_FILE="$REG" \
  OPENCODE_MODEL_CHAIN="opencode/dead-model opencode/deepseek-v4.1-flash-free opencode/big-pickle" \
  bash .github/scripts/resolve-model.sh 2>/dev/null)
check "dead head falls through to the next model" \
  "$(printf '%s\n' "$out" | grep '^MODEL=')" "MODEL=opencode/deepseek-v4.1-flash-free"
check "highest supported effort wins (max)" \
  "$(printf '%s\n' "$out" | grep '^VARIANT=')" "VARIANT=max"

out=$(OPENCODE_MODELS_FILE="$REG" \
  OPENCODE_VARIANT_CHAIN="xhigh high medium low" \
  OPENCODE_MODEL_CHAIN="opencode/deepseek-v4.1-flash-free" \
  bash .github/scripts/resolve-model.sh 2>/dev/null)
check "ladder xhigh->high->medium->low degrades to high" \
  "$(printf '%s\n' "$out" | grep '^VARIANT=')" "VARIANT=high"

out=$(OPENCODE_MODELS_FILE="$REG" \
  OPENCODE_MODEL_CHAIN="opencode/minimax-m3.1-flash-free" \
  bash .github/scripts/resolve-model.sh 2>/dev/null)
check "xhigh used when the model exposes it" \
  "$(printf '%s\n' "$out" | grep '^VARIANT=')" "VARIANT=xhigh"

out=$(OPENCODE_MODELS_FILE="$REG" OPENCODE_MODEL=opencode/big-pickle \
  bash .github/scripts/resolve-model.sh 2>/dev/null)
check "forced model honoured even when absent from the registry" \
  "$(printf '%s\n' "$out" | grep '^MODEL=')" "MODEL=opencode/big-pickle"
check "model with no variants runs at provider default" \
  "$(printf '%s\n' "$out" | grep '^VARIANT=')" "VARIANT="

if OPENCODE_MODELS_FILE="$REG" OPENCODE_MODEL_CHAIN="opencode/dead-a opencode/dead-b" \
  bash .github/scripts/resolve-model.sh >/dev/null 2>&1; then
  echo "FAIL fully dead chain must exit non-zero"
  fails=$((fails + 1))
else
  echo "PASS fully dead chain exits non-zero"
fi

if [ "$fails" = 0 ]; then
  echo "RESOLVE-MODEL-FIXTURE-PASS"
  exit 0
fi
echo "$fails FAILURES"
exit 1
