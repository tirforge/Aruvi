#!/bin/bash
# ABOUTME: Pick the first AVAILABLE model from a fallback chain, plus the highest effort it supports.
# ABOUTME: Prints MODEL=<id> and VARIANT=<v> lines ready for $GITHUB_OUTPUT.
# Why: the pipeline sat dead for three weeks (2026-10) because every workflow
# pinned ONE model id the provider had silently dropped — "Model not found" in
# 1.3s, red fullscan every Sunday, nobody watching. Now the chain degrades to
# the next model instead of failing the whole run, and the effort level is
# resolved per model so a model without `xhigh` never gets an invalid flag.
#
# Effort ladder (highest first, first one the model supports wins):
#   xhigh -> max -> high -> medium -> low -> minimal
# A model exposing NO variants runs at its provider default (empty VARIANT).
#
# Env: OPENCODE_MODEL          force this model, skip the chain (caller override)
#      OPENCODE_MODEL_CHAIN    space-separated models, first available wins
#      OPENCODE_VARIANT_CHAIN  override the effort ladder above
#      OPENCODE_MODELS_FILE    read a captured `opencode models --verbose` dump
#                              instead of calling the CLI (offline fixture tests)
# Exit: 1 only when nothing in the chain resolves — fail loud, never silently
#       fall back to a model we already know is gone.
set -uo pipefail

CHAIN="${OPENCODE_MODEL_CHAIN:-opencode/deepseek-v4.1-flash-free opencode/glm-5.3-flash-free opencode/minimax-m3.1-flash-free opencode/big-pickle}"
VARIANTS="${OPENCODE_VARIANT_CHAIN:-xhigh max high medium low minimal}"

TMP=""
cleanup() { [ -n "$TMP" ] && rm -f "$TMP"; }
trap cleanup EXIT

if [ -n "${OPENCODE_MODELS_FILE:-}" ] && [ -r "$OPENCODE_MODELS_FILE" ]; then
  REGISTRY="$OPENCODE_MODELS_FILE"
else
  export PATH="$HOME/.opencode/bin:$PATH"
  if ! command -v opencode >/dev/null 2>&1; then
    # Official installer — the same one the pinned opencode action uses internally.
    curl -fsSL https://opencode.ai/install | bash >/dev/null 2>&1 || true
    export PATH="$HOME/.opencode/bin:$PATH"
  fi
  if ! command -v opencode >/dev/null 2>&1; then
    echo "::error::opencode CLI unavailable — cannot resolve a model." >&2
    exit 1
  fi
  TMP="$(mktemp "${TMPDIR:-/tmp}/opencode-models.XXXXXX")"
  # The CLI's registry is the authoritative list: models.dev can advertise an id
  # that `--model` still rejects, which is exactly how the last outage hid.
  opencode models --verbose >"$TMP" 2>/dev/null || true
  REGISTRY="$TMP"
fi

OPENCODE_MODEL="${OPENCODE_MODEL:-}" \
OPENCODE_VARIANT_CHAIN="$VARIANTS" \
python3 - "$REGISTRY" "$CHAIN" <<'PY'
import json
import os
import re
import sys

registry_path, chain = sys.argv[1], sys.argv[2].split()
text = open(registry_path, encoding="utf-8", errors="replace").read()

models = {}
for name, blob in re.findall(r'^(opencode/[\w.\-]+)\n(\{.*?\n\})\s*$', text, re.M | re.S):
    try:
        models[name] = json.loads(blob)
    except json.JSONDecodeError:
        continue

ladder = os.environ.get("OPENCODE_VARIANT_CHAIN", "xhigh max high medium low minimal").split()


def variant_for(name):
    """Highest effort this model actually exposes; "" = provider default."""
    variants = list((models.get(name, {}).get("variants") or {}).keys())
    for effort in ladder:
        if effort in variants:
            return effort
    return ""


forced = os.environ.get("OPENCODE_MODEL", "").strip()
if forced:
    # Explicit override wins even if the registry cannot see it (private gateways).
    print(f"MODEL={forced}")
    print(f"VARIANT={variant_for(forced)}")
    sys.exit(0)

if not models:
    print("::error::could not parse the opencode model registry", file=sys.stderr)
    sys.exit(1)

for candidate in chain:
    if candidate not in models:
        print(f"skip (not in registry): {candidate}", file=sys.stderr)
        continue
    print(f"MODEL={candidate}")
    print(f"VARIANT={variant_for(candidate)}")
    sys.exit(0)

print("::error::no candidate model is available: " + " ".join(chain), file=sys.stderr)
sys.exit(1)
PY
