# Fullscan report — `frontend` (run 4)

## Scope

- Dirs scanned: `frontend/src` (all `.tsx`/`.ts`/`.css`), `frontend/scripts`,
  `frontend/public` (minus `public/vendor/`), plus root configs
  (`index.html`, `vite.config.ts`, `tailwind.config.js`, `postcss.config.js`,
  `tsconfig*.json`, `.eslintrc.cjs`, `package.json`).
- Out of scope and untouched: `public/vendor/movi-player-0.4.0-element.js`
  (vendored), binary image/font assets, `node_modules`, all other top-level dirs.
- File count: **44 tracked files** under `frontend/` (33 excluding vendored
  bundle, binary images and font assets); **24 source files** under
  `frontend/src` — all read in full.
- Checks performed: auth/token handling, injection/XSS (`dangerouslySetInnerHTML`,
  `innerHTML`, `eval`, `postMessage` — zero hits), secrets in code (none),
  `target="_blank"` hygiene, token-in-URL construction, race conditions
  (refresh queue, poll loops, double-submit guards), error-handling gaps,
  dead code, `tsc --noEmit`, `eslint --max-warnings 0`, `vite build`,
  `node --check` on the script, plus a behavioral fixture test of the script.

## Verdict: 14 findings — all fixed (see PR `opencode fullscan: frontend fixes`)

1. `frontend/src/components/MediaPlayer.tsx:278` — stream URL interpolated a
   `null` access token literally (`…?token=null`) when logged out/expired;
   token also unencoded. Fixed with `?? ''` + `encodeURIComponent`.
2. `frontend/src/components/MediaPlayer.tsx:288` — same null/encoding issue
   for the reactive image URL. Fixed the same way.
3. `frontend/src/components/MediaPlayer.tsx:314` — token-rotation re-source
   built the fresh URL from the raw reactive token (unencoded). Fixed with
   `encodeURIComponent`.
4. `frontend/src/components/MediaPlayer.tsx:665` — attaching subtitles
   re-sourced the player with the frozen mount-time token, so an attach after
   a mid-playback rotation replayed a stale token and 401'd. Fixed by building
   the video src from the current token at attach time.
5. `frontend/src/components/MediaPlayer.tsx:175` — `.srt` extension check was
   case-sensitive (`.SRT` uploads skipped conversion and broke as VTT) while
   the `.sub` guard right above already used `toLowerCase()`. Fixed.
6. `frontend/src/components/GlobalContextMenu.tsx:229,249` — "Play in VLC" and
   "Copy Stream URL" always appended `?token=`, producing a malformed
   `?token=…?token=…` URL for grabbed files whose `stream_url` already carries
   a download token (the player already handled this separator correctly).
   Fixed with `?`/`&` selection + `encodeURIComponent` on the minted token.
7. `frontend/src/components/FileBrowser.tsx:107,766` — failed files/recent/
   continue-watching fetches fell through to the misleading "No files found"
   empty state with no retry. Fixed with an error panel + Retry button.
8. `frontend/src/components/FileBrowser.tsx:274` — paste (cut/move) failure
   was `console.error`-only, no user feedback. Fixed with an error toast.
9. `frontend/src/components/FileBrowser.tsx:440` — global keyboard shortcuts
   fired while a `<select>` or `contentEditable` element was focused. Fixed by
   extending the focus guard.
10. `frontend/src/components/Sidebar.tsx:18,117` — storage-stats failure left
    the shimmer skeleton up forever. Fixed with a "Storage unavailable"
    fallback.
11. `frontend/src/components/AdminPanel.tsx:129,130,185,217` — stats failure
    rendered a blank area; users failure rendered the misleading "No users
    found". Fixed with explicit error messages for both.
12. `frontend/src/components/MoveFileModal.tsx:181` — `<div>` nested inside
    `<button>` (invalid HTML). Fixed with `<span>`.
13. `frontend/src/lib/api.ts:28,785,797` — `useSyncExternalStore` lacked the
    server-snapshot arg; `formatFileSize` passed negative values through;
    `formatDuration` formatted negatives as `-1:-05`. Fixed (server snapshot
    `() => ''`, negative guards).
14. `frontend/src/components/RenameModal.tsx:44,79` (pre-fix lines) — two
    unused `eslint-disable` directives; these were the only 2 baseline lint
    errors. Removed.
15. `frontend/scripts/gzip-assets.mjs` — skipped files left stale `.gz`
    artifacts that the backend prefers over fresh content (stale bytes served
    indefinitely); `walk` crashed postbuild on a missing dir or dangling
    symlink. Fixed with stale-`.gz` cleanup on every skip path and
    try/catch around `readdirSync`/`statSync`.

## Verification

- `npx tsc --noEmit` → clean (was already clean).
- `npx eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0`
  → clean (2 pre-existing errors fixed).
- `npx vite build` → success (1540 modules, built in ~2s).
- `node --check scripts/gzip-assets.mjs` → OK, plus a fixture test proving:
  compressible output round-trips, stale `.gz` removed for small and
  incompressible inputs, missing out-dir exits 0.
- No dependency changes; no files touched outside `frontend/`
  (a verification run of the repo's own postbuild script briefly rewrote
  `backend/app/static` `.gz` bytes — all reverted, `git status` confirms only
  the 9 `frontend/` source files changed).

## Explicitly checked and left alone (no bug)

- Refresh-token interceptor queue/timeout/multi-tab races, login long-poll
  loop (`pollCodeRef` snapshot), `AuthImage` bearer-leak origin guard + abort
  + 5 MB cap, drag-drop payload validation, move-into-descendant guard,
  per-row admin pending states, delete/paste double-submit guards, focus
  restoration, toast dedupe/cap, search highlight regex escaping,
  `__BACKEND_URL__` placeholder handling, `emptyOutDir: false` (deliberate —
  flipping it would wipe backend-served files).
