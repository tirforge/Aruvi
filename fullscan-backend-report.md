# Full-scan backend report — 2026-10-01

Scope: `backend/` tree only. Vendored/build output excluded
(`backend/app/static/vendor/`, `backend/app/static/assets/`).

- Dirs scanned: `backend/app`, `backend/app/routers`, `backend/tests`
- Files: 41 Python files (36 under `backend/app`, 2 runners, 5 tests incl. conftest)
- Method: full read of every non-vendored backend file by three parallel
  audit agents (auth/security, streaming/caching, routers/services),
  then line-level verification of each candidate fix against current source.

## Verdict: NOT CLEAN — 13 minimal fixes applied (see Fix PR below)

Every item below was verified in current source before fixing
(`file:line` = location at time of audit).

### Fixed

1. `backend/app/streaming.py:157-160,285-286` — `CacheManager.remove()` dropped
   `ChunkCache.clear()`'s freed-byte count (missing `return`), so the TTL-evict
   log branch (`if freed:`) was dead. Now returns `int`.
2. `backend/app/utils.py:6-12` — `bearer_token_matches(auth_header, ...)` called
   `auth_header.encode()` with no `None` guard → 500 if a caller passes a missing
   header. Now returns `False` on falsy input.
3. `backend/app/patch.py:60` — `msg.from_user.is_self` with no `None` guard;
   channel posts (`from_user=None`) raise `AttributeError`. Now guarded.
4. `backend/app/routers/folders.py:331-360,414-440` — `delete_folder` /
   `batch_delete_folders` mutated `File`/`Folder` rows filtered only by
   `folder_id` (recursive CTE likewise unscoped). Added `user_id` scoping to the
   CTE anchor/recursive step and to all `update`/`delete` statements
   (defense-in-depth; today cross-user linkage should not exist, but nothing in
   the schema prevents it).
5. `backend/app/routers/files.py:278,485` + `backend/app/routers/folders.py:378,458`
   — batch delete/move endpoints accepted unbounded ID lists (huge `IN()` =
   DoS/memory). Now capped at 500 with HTTP 400.
6. `backend/app/schemas.py:211` — `BatchMoveRequest.ids` unbounded. Now
   `max_length=500`.
7. `backend/app/schemas.py:49-60,98-100` — folder/file names accepted
   empty/huge/control-char strings. Added `min_length=1, max_length=255` on
   folder names and `max_length=255` on `FileUpdate.file_name`.
8. `backend/app/schemas.py:137-140` — `WatchProgressUpdate.position/duration`
   accepted negatives; negative `duration` forces spurious `completed=True`.
   Added `ge=0`.
9. `backend/app/disk_cache.py:171-172` — `put()` swallowed `OSError` (ENOSPC /
   perms) silently, cache just stops working. Now logs a warning.
10. `backend/app/gdrive.py:286` — GDrive staging tmp name
    `f"{msg.id}_{int(time.time())}.tmp"` predictable; concurrent uploads for the
    same message in the same second collide. Added `secrets.token_hex(8)`.
11. `backend/app/routers/setup.py:99,128,130` — raw Telegram/Pyrogram exceptions
    echoed into HTTP 400/403 responses (info disclosure: api_hash/phone
    internals). Now generic messages, full error stays in server logs.
12. `backend/app/routers/auth.py:71` — `POST /auth/refresh` had no rate limit
    (vs `10/min` on generate-code, `80/min` on verify-code). Added
    `30/minute` (slowapi needs the `Request` param — added).
13. `backend/app/routers/tv.py:148` + `backend/app/routers/grab.py:82-83` —
    `tv_search q` (`min_length=1`, no max) and `SelectRequest.group_username` /
    `file_name` (unbounded) allow oversized `%huge%` ILIKE scans / payloads.
    Capped at 200/64/255 chars.

### Checked and deliberately NOT changed (needs product call / larger rework)

- `auth.py:117` token-in-query (`?token=`): client-compat surface; rotating to
  header-only would break web/TV clients. Left for a versioned API change.
- `bot.py:91-93` AUTH_USERS ⇒ admin promotion, `bot.py:98-99` first-/start
  becomes admin: operator-config semantics, not safe to "fix" unilaterally.
- `models.py:40` plaintext `gdrive_token`, `LoginCode.code` plaintext: needs a
  data-migration + KMS/envelope-encryption decision, not a one-line patch.
- `gdrive.py:47` in-memory OAuth nonce store (multi-worker callback fails):
  needs shared store (Redis/DB); out of minimal-fix scope.
- `streaming.py` prefetch/backpressure tuning, `telegram.py` warmup fan-out,
  `grabber.py` group auto-join semantics: behavior/performance trade-offs,
  left untouched.
- No hardcoded API keys/tokens/JWT secrets found in scanned files (all via
  env/`settings`); only a contact email in `legal.py` (left as-is).

## Verification

- `python3 -m compileall -q backend/app backend/tests` — must pass (see PR checks)
- Existing pytest suite + CI (CodeQL, opencode-review, Sonar) run on the PR

Fix PR: <pending — filled in after `gh pr create`>
