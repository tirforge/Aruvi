#!/bin/bash
# ABOUTME: Harvest review-combo signals into a findings dir (opencode + rabbit + sonar).
# ABOUTME: Single source of truth: called by review-combo.yml AND test-harvest.sh (fixture mode).
# Usage: harvest-findings.sh <repo> <pr> <sonar_project_key> <outdir>
# Env: SONAR_TOKEN (optional; empty on dependabot runs -> API 401 -> CLEAN fallback),
#      FIXTURE_DIR (optional: copy canned API payloads instead of calling GitHub/Sonar).
set -euo pipefail

REPO="$1"; PR="$2"; KEY="$3"; OUT="$4"
RETRY=".github/scripts/gh-retry.sh"
mkdir -p "$OUT"

if [ -n "${FIXTURE_DIR:-}" ]; then
  cp "$FIXTURE_DIR/issues-raw.json" "$OUT/issues-raw.json"
  cp "$FIXTURE_DIR/pull-raw.json" "$OUT/pull-raw.json"
  cp "$FIXTURE_DIR/sonar.json" "$OUT/sonar.json"
else
  # Fetch-then-filter with guards: --paginate can emit page arrays that
  # break --jq object filters, and any API hiccup under bash -e kills the
  # whole step. So: fetch raw (never fail), then filter locally with
  # null-safe recursion handling flat or paged shapes. gh-retry gives one
  # bounded retry on transient blips (reads only — writes never retried
  # blind, a 5xx can't say if it landed).
  bash "$RETRY" api "repos/$REPO/issues/$PR/comments" --paginate > "$OUT/issues-raw.json" \
    || echo '[]' > "$OUT/issues-raw.json"
  bash "$RETRY" api "repos/$REPO/pulls/$PR/comments" --paginate > "$OUT/pull-raw.json" \
    || echo '[]' > "$OUT/pull-raw.json"
  # Download to a file first, then parse — never pipe a download straight
  # into an interpreter.
  # Auth: public SonarCloud projects answer anonymously with 200. Passing
  # `-u ":"` when the token is empty sends an EMPTY credential, which Sonar
  # rejects with 401 — that used to fall back to "CLEAN" and mask every real
  # finding on any run without a token. Omit -u entirely when there is none.
  SONAR_URL="https://sonarcloud.io/api/issues/search?componentKeys=$KEY&pullRequest=$PR&resolved=false&ps=100"
  if [ -n "${SONAR_TOKEN:-}" ]; then
    CURL_AUTH=(-u "$SONAR_TOKEN:")
  else
    CURL_AUTH=()
  fi
  # A genuine failure is NOT "clean": write a marker the reporter treats as
  # unknown, so the run never claims the repo is clean without having looked.
  if ! curl -sf ${CURL_AUTH[@]+"${CURL_AUTH[@]}"} -o "$OUT/sonar.json" "$SONAR_URL"; then
    echo '{"__unavailable__":true}' > "$OUT/sonar.json"
  fi
fi

# 1+2+3. Extraction is python3 (not jq): one implementation, no drift
# between local/test/runner envs, and it handles --paginate's page arrays
# via full-depth recursion. Order = document order, same as the old jq.
OUTDIR="$OUT" python3 - <<'PYEOF'
import json, os
d = os.environ['OUTDIR']
def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)
issues = json.load(open(d + '/issues-raw.json'))
pulls = json.load(open(d + '/pull-raw.json'))
# Bots get a [bot] suffix from the API: the opencode action posts through
# GITHUB_TOKEN, so its login is 'github-actions[bot]'. Matching bare
# 'github-actions' silently dropped EVERY opencode finding (proven against a
# live PR: opencode.md was 0 bytes while the bot had posted real findings).
GH_ACTIONS = ('github-actions[bot]', 'github-actions')
RABBIT = ('coderabbitai[bot]', 'coderabbitai')
ga = [o['body'] for o in walk(issues)
      if o.get('user', {}).get('login') in GH_ACTIONS and 'body' in o]
rb = [o['body'] for o in walk(issues)
      if o.get('user', {}).get('login') in RABBIT and 'body' in o]
inl = []
for o in walk(pulls):
    if o.get('user', {}).get('login') in RABBIT and 'path' in o:
        lines = ','.join(str(x) for x in (o.get('line'), o.get('original_line'))
                         if x is not None)
        inl.append(f"`{o.get('path', '?')}:{lines}` {o.get('body', '')}")
open(d + '/opencode.md', 'w').write('\n---\n'.join(ga))
open(d + '/rabbit-main.md', 'w').write('\n---\n'.join(rb))
open(d + '/rabbit-inline.md', 'w').write('\n---\n'.join(inl))
raw = open(d + '/sonar.json').read().strip() or '{"__unavailable__":true}'
try:
    j = json.loads(raw)
except json.JSONDecodeError:
    j = {"__unavailable__": True}
if j.get('__unavailable__'):
    sonar = 'UNKNOWN: Sonar API unreachable — Sonar findings were NOT verified.'
else:
    sonar = '\n---\n'.join(
        f"[{i.get('severity','?')}] {i['component'].split(':')[-1]}:{i.get('line','?')} "
        f"{i.get('rule','?')} \u2014 {i.get('message','')}" for i in j.get('issues', []))
open(d + '/sonar.md', 'w').write(sonar or 'CLEAN: no open Sonar issues.')
PYEOF
wc -c "$OUT"/*.md
