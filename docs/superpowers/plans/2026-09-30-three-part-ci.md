# Three-Part CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `.github/workflows/ci.yml` into three path-filtered workflows (backend, frontend, android) and add Kotlin to CodeQL.

**Architecture:** Copy the existing `backend` and `frontend` job blocks verbatim into two new files with `paths` triggers; add a third file with Gradle assemble+lint for the `mobile`/`tv` flavors; one-line CodeQL matrix edit; delete `ci.yml`; update branch protection.

**Tech Stack:** GitHub Actions, Gradle (Android), CodeQL, Python `yaml`, actionlint, `ci_selfcheck.py`.

**Spec:** `docs/superpowers/specs/2026-09-30-three-part-ci-design.md`

## Global Constraints

- Backend job content stays byte-identical (setup-python 3.11, pip cache on `backend/requirements.txt`, `compileall -q app`, non-blocking pytest with `JWT_SECRET: ci-dummy-secret` + sqlite `DATABASE_URL`).
- Frontend job content stays byte-identical (setup-node 22, npm cache on `frontend/package-lock.json`, eslint `--max-warnings 0`, `tsc --noEmit`, `npm test`, `vite build`).
- Android uses JDK 17, assembles `assembleMobileDebug` + `assembleTvDebug`, lints with default `abortOnError` (errors fail, warnings pass), no secrets.
- Sonar Kotlin/Jacoco is out of scope; Android unit tests are out of scope (none exist).
- Never push with a job token expectation — push with the user's `GH_TOKEN`/auth so CI runs as real runs.

## Review Focus

- A PR touching only `*.md`/root files triggers zero of the three workflows, so required checks stay "Expected" forever — a reasonable person expects merge to still work; mitigation is Task 6's docs-only probe + documented admin unblock.
- A PR touching `docker-compose.yml`/`Dockerfile` must trigger backend CI — pinned by the backend `paths` list including both files.
- `android/local.properties` absent in CI must not fail the build — the Gradle task test in Task 3 pins `assembleMobileDebug` success with defaults (localhost URL fallback).
- Pre-existing Android lint warnings must not fail the PR — the lint task test pins warnings-pass/errors-fail via default `abortOnError`.
- CodeQL `java-kotlin` must analyze without a manual build step — pinned by checking the CodeQL run for the java-kotlin matrix leg going green on the branch PR.

---

### Task 1: Create `ci-backend.yml`

**Files:**
- Create: `.github/workflows/ci-backend.yml`
- Test: `python3 -c "import yaml"` parse + `actionlint` + `.github/scripts/ci_selfcheck.py`

**Interfaces:**
- Consumes: job block `backend` from `.github/workflows/ci.yml:8-36` (copy verbatim).
- Produces: check name `CI Backend / backend` consumed by Task 6 (branch protection).

- [ ] **Step 1: Create the workflow file**

```yaml
name: CI Backend

on:
  push:
    paths:
      - "backend/**"
      - "docker-compose.yml"
      - "Dockerfile"
      - ".github/workflows/ci-backend.yml"
  pull_request:
    paths:
      - "backend/**"
      - "docker-compose.yml"
      - "Dockerfile"
      - ".github/workflows/ci-backend.yml"

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v7

      - name: Set up Python 3.11
        uses: actions/setup-python@v7
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: backend/requirements.txt

      - name: Install dependencies
        run: pip install -r requirements.txt pytest pytest-asyncio

      - name: Compile check (matches AGENTS.md rule)
        run: python -m compileall -q app

      # Unit tests are informational for now (some suites need live
      # Telegram creds); failures here don't block the PR.
      - name: Unit tests (non-blocking)
        run: python -m pytest tests/test_fixes.py tests/test_cast_remux.py -q
        continue-on-error: true
        env:
          JWT_SECRET: ci-dummy-secret
          DATABASE_URL: sqlite+aiosqlite:///./ci_test.db
```

Write with the Write tool to `.github/workflows/ci-backend.yml`.

- [ ] **Step 2: Verify it parses and diff the job against the original**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci-backend.yml'))" && echo PARSE-OK
```
Expected: `PARSE-OK`.

Then confirm the job block is verbatim:
```bash
diff <(sed -n '/^jobs:/,$p' .github/workflows/ci.yml | sed -n '/^  backend:/,/^  frontend:/p' | head -n -1) <(sed -n '/^jobs:/,$p' .github/workflows/ci-backend.yml) && echo JOBS-IDENTICAL
```
(Only the `name:` and `on:` headers may differ; the `jobs:` subtree must be identical.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci-backend.yml
git commit -m "Add CI Backend workflow (split from ci.yml, path-filtered)"
```

### Task 2: Create `ci-frontend.yml`

**Files:**
- Create: `.github/workflows/ci-frontend.yml`
- Test: yaml parse + diff against original `frontend` job.

**Interfaces:**
- Consumes: job block `frontend` from `.github/workflows/ci.yml:38-66` (copy verbatim).
- Produces: check name `CI Frontend / frontend` consumed by Task 6.

- [ ] **Step 1: Create the workflow file**

```yaml
name: CI Frontend

on:
  push:
    paths:
      - "frontend/**"
      - ".github/workflows/ci-frontend.yml"
  pull_request:
    paths:
      - "frontend/**"
      - ".github/workflows/ci-frontend.yml"

jobs:
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v7

      - name: Set up Node 22
        uses: actions/setup-node@v7
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: Lint
        run: npx eslint . --ext ts,tsx --max-warnings 0

      - name: Typecheck
        run: npx tsc --noEmit

      - name: Unit tests
        run: npm test

      - name: Build
        run: npx vite build
```

- [ ] **Step 2: Verify parse + verbatim job**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci-frontend.yml'))" && echo PARSE-OK
diff <(sed -n '/^  frontend:/,$p' .github/workflows/ci.yml) <(sed -n '/^jobs:/,$p' .github/workflows/ci-frontend.yml | sed -n '/^  frontend:/,$p') && echo JOBS-IDENTICAL
```
Expected: `PARSE-OK` and `JOBS-IDENTICAL`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci-frontend.yml
git commit -m "Add CI Frontend workflow (split from ci.yml, path-filtered)"
```

### Task 3: Create `ci-android.yml`

**Files:**
- Create: `.github/workflows/ci-android.yml`
- Test: yaml parse + local Gradle smoke (if SDK present) + live CI run in Task 5.

**Interfaces:**
- Consumes: action versions from `build-apk.yml`.
- Produces: check name `CI Android / build` consumed by Task 6.

- [ ] **Step 1: Note the mirrored versions (already verified 2026-09-30)**

`build-apk.yml` uses `actions/setup-java@v4` (distribution `temurin`, version `17`) and `android-actions/setup-android@v4` — the file in Step 2 already pins these exact versions. `android/app/build.gradle.kts:22-36` confirms flavors `tv` + `mobile`, so task names `assembleMobileDebug`/`assembleTvDebug`/`lintMobileDebug`/`lintTvDebug` are valid. No guessing involved; proceed to Step 2.

- [ ] **Step 2: Create the workflow file**

```yaml
name: CI Android

on:
  push:
    paths:
      - "android/**"
      - ".github/workflows/ci-android.yml"
  pull_request:
    paths:
      - "android/**"
      - ".github/workflows/ci-android.yml"

jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: android
    steps:
      - uses: actions/checkout@v7

      - name: Set up JDK 17
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"

      - name: Set up Android SDK
        uses: android-actions/setup-android@v4

      - name: Assemble mobile + TV debug
        run: ./gradlew :app:assembleMobileDebug :app:assembleTvDebug --no-daemon

      - name: Lint mobile + TV debug
        run: ./gradlew :app:lintMobileDebug :app:lintTvDebug --no-daemon
```

If the executor finds `build-apk.yml` has since changed versions, match the newer pins instead and note the change in the commit message.

- [ ] **Step 3: Verify parse + local Gradle sanity (if Android SDK available)**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci-android.yml'))" && echo PARSE-OK
```
Expected: `PARSE-OK`.

If a local Android SDK + JDK 17 exists, also run `./gradlew :app:assembleMobileDebug --no-daemon -x lint` as a smoke test. If no SDK is available locally, skip with a note in the commit message body (`Local SDK absent; verified via CI run in Task 5`) — the CI run in Task 5 is the real test.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci-android.yml
git commit -m "Add CI Android workflow (assemble+lint mobile/tv per PR)"
```

### Task 4: Delete `ci.yml`, extend CodeQL matrix

**Files:**
- Delete: `.github/workflows/ci.yml`
- Modify: `.github/workflows/codeql.yml:20` (one line)
- Test: `ci_selfcheck.py` must stay ALL GREEN (it scans workflow files generically).

**Interfaces:**
- Consumes: the three new files from Tasks 1–3.
- Produces: final workflow set consumed by Task 5 verification.

- [ ] **Step 1: Delete `ci.yml` and edit the CodeQL matrix**

Run:
```bash
git rm .github/workflows/ci.yml
```

Edit `.github/workflows/codeql.yml` line 20:
```diff
-        language: [python, javascript-typescript]
+        language: [python, javascript-typescript, java-kotlin]
```

- [ ] **Step 2: Run the repo's own CI guardrails**

Run:
```bash
python3 .github/scripts/ci_selfcheck.py 2>&1 | tail -3
```
Expected: `ALL GREEN` (or current green baseline — any failure names the exact file/line to fix before proceeding).

Run actionlint if installed:
```bash
actionlint .github/workflows/ci-backend.yml .github/workflows/ci-frontend.yml .github/workflows/ci-android.yml .github/workflows/codeql.yml 2>&1 | tail -5
```
Expected: no output (clean). If `actionlint` is not installed, skip with a note — `ci_selfcheck.py` + yaml parse already cover syntax.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/codeql.yml
git commit -m "Remove ci.yml, add java-kotlin to CodeQL matrix"
```

### Task 5: Push and verify live runs

**Files:** none (verification only).

**Interfaces:**
- Consumes: branch with Tasks 1–4 commits.
- Produces: green workflow runs proving path-filtering + job contents.

- [ ] **Step 1: Push with user credentials (NOT a job token)**

Run:
```bash
source ~/.bashrc >/dev/null 2>&1
git fetch origin fix/sonar-minor-batch -q
git rebase origin/fix/sonar-minor-batch   # resolve like previous combo-fix races: rebase, never merge
git push origin fix/sonar-minor-batch
```
Expected: push accepted; if rejected (combo-fix race again), fetch + rebase + retry.

- [ ] **Step 2: Confirm the three workflows trigger on the branch PR**

Check runs for PR #58:
```bash
gh run list --branch fix/sonar-minor-batch --limit 10 --json name,conclusion,status
```
Expected: `CI Backend`, `CI Frontend`, `CI Android` runs exist with `conclusion: success`. All three trigger because the branch diff touches all three areas (workflow files themselves are in each file's `paths`). Also confirm the `CodeQL` run shows a green `java-kotlin` matrix leg (pins the Review Focus CodeQL line).

- [ ] **Step 3: Prove path-filtering skips correctly**

Push a docs-only commit (e.g. append a blank line + timestamp to a scratch comment in the spec doc, or an empty commit touching only `docs/`):
```bash
git commit --allow-empty -m "Probe: docs-only change must skip all three CI workflows" && git push origin fix/sonar-minor-batch
sleep 90
gh run list --branch fix/sonar-minor-batch --limit 5 --json name,status
```
Expected: NO new `CI Backend` / `CI Frontend` / `CI Android` runs for the probe commit. Then revert the probe:
```bash
git reset --hard HEAD~1 && git push --force-with-lease origin fix/sonar-minor-batch
```
This pins the Review Focus edge: docs-only PRs skip CI (accepted limitation, unblocked via admin merge when needed).

### Task 6: Update branch protection to the three new checks

**Files:** none (settings change).

**Interfaces:**
- Consumes: check names `CI Backend / backend`, `CI Frontend / frontend`, `CI Android / build` from Tasks 1–3.
- Produces: `main` protection requiring exactly the three new checks.

- [ ] **Step 1: Try the API first**

Run:
```bash
gh api repos/tirforge/Aruvi/branches/main/protection/required_status_checks --jq '.contexts'
```
Expected: shows current contexts (should include `backend`/`frontend` or `CI / backend`-style names).

Then set the new contexts:
```bash
gh api repos/tirforge/Aruvi/branches/main/protection/required_status_checks -X PATCH -f strict=true -f contexts='["CI Backend / backend","CI Frontend / frontend","CI Android / build"]' --jq '.contexts'
```
Expected: the three new contexts echoed back. If the PATCH returns `403` (token lacks admin), go to Step 2.

- [ ] **Step 2 (fallback): manual 30-second update**

If Step 1 fails with 403, hand the owner this exact click path: GitHub → repo Settings → Branches → edit `main` rule → uncheck the two old `CI / backend`-style contexts → check `CI Backend / backend`, `CI Frontend / frontend`, `CI Android / build` → Save. Record in the final report that protection is pending owner action.

- [ ] **Step 3: Verify protection sees green on the next PR**

After merge of the split PR, confirm on `main` that the three checks report. No commit in this task.
