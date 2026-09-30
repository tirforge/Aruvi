# Design: three-part CI (backend / frontend / android)

Date: 2026-09-30 | Status: approved, pending implementation plan
Context: PR #58 discussion. Today `ci.yml` runs backend+frontend as two
jobs in one workflow; `android/` has no per-PR CI (`build-apk.yml` is
release/manual only); Sonar + CodeQL don't scan Kotlin.

## Intent (agreed)

Split CI into three standalone, path-filtered workflows so each area
gets isolated signal and Android stops merging silently. No behavior
change to backend/frontend steps; Android gains assemble+lint per PR;
CodeQL gains java-kotlin. Sonar Kotlin deferred (needs Jacoco +
`sonar-project.properties` reconfig — separate task).

## Layout (approved §1)

- DELETE `.github/workflows/ci.yml`.
- CREATE `ci-backend.yml` (name `CI Backend`):
  `push` + `pull_request`, paths: `backend/**`, `docker-compose.yml`,
  `Dockerfile`, `.github/workflows/ci-backend.yml`.
- CREATE `ci-frontend.yml` (name `CI Frontend`):
  `push` + `pull_request`, paths: `frontend/**`,
  `.github/workflows/ci-frontend.yml`.
- CREATE `ci-android.yml` (name `CI Android`):
  `push` + `pull_request`, paths: `android/**`,
  `.github/workflows/ci-android.yml`.
- Untouched: `ruff.yml`, `gitleaks.yml`, `sonar.yml`, `codeql.yml`
  (matrix edit only), `codecov.yml`, `ci-selfcheck.yml`,
  `review-combo.yml`, `opencode-fullscan.yml`, `build-apk.yml`,
  `merge-agent.yml`, `desktop-apps.yml`, `docker-publish.yml`.

## Job contents (approved §2)

- Backend job `backend` (setup-python 3.11, pip cache): `pip install -r
  requirements.txt pytest pytest-asyncio`, `compileall -q app`,
  non-blocking pytest (`continue-on-error: true`, same suites + env).
- Frontend job `frontend` (setup-node 22, npm cache): `npm ci`,
  eslint `--max-warnings 0`, `tsc --noEmit`, `npm test` (vitest run),
  `vite build`.
- Android job `build` (JDK 17 temurin, `setup-android`,
  gradle cache): `./gradlew :app:assembleMobileDebug
  :app:assembleTvDebug` then `./gradlew :app:lintMobileDebug
  :app:lintTvDebug` (default abortOnError — errors fail, warnings pass).
  No secrets needed (debug keystore auto-generated; server URL defaults
  to localhost when `local.properties` absent).

## Names, gates, CodeQL (approved §3)

- New check names: `CI Backend / backend`, `CI Frontend / frontend`,
  `CI Android / build`. Old `CI / *` names disappear with `ci.yml`.
- Branch protection (`main`, currently requires `backend` +
  `frontend`): replace with the three new checks. Attempt via API
  first; if token lacks admin, owner updates in
  Settings → Branches (30-sec click path, exact contexts provided at
  implementation time).
- CodeQL matrix: `[python, javascript-typescript]` →
  `[python, javascript-typescript, java-kotlin]` (one line).
  `review-combo.yml` waiter matches `CodeQL` + `analyze*` — unaffected.
- `merge-agent` enforces protection (no `--admin`) — unaffected.

## Verification

- `python3 -c yaml.safe_load` on all touched workflows.
- `.github/scripts/ci_selfcheck.py` → ALL GREEN.
- Push to feature branch; confirm all three workflows trigger on a
  touch-PR and path-filtering skips unrelated areas.
- Confirm branch protection shows the three new required checks green.
- Full test suite run per AGENTS.md (backend compileall, frontend
  tsc+eslint+build) — implementation must not break existing gates.

## Out of scope

- Sonar Kotlin/Jacoco, Android unit tests (none exist), detekt,
  reusable-workflow refactor, release APK flow changes.
