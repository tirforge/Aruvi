# fullscan frontend report — run 23 (2026-10-11)

## Scope

- Dirs scanned: `frontend/src` (App, main, lib, components), `frontend/scripts`,
  `frontend/public` (listing only — `public/vendor/` is vendored, untouched),
  plus root configs (`package.json`, `vite.config.ts`, `tsconfig*.json`,
  `.eslintrc.cjs`, `index.html`, `tailwind/postcss`).
- Files in `frontend/`: 46 total; 21 TS/TSX/MJS source files audited line by line.
- Baseline: branch `opencode/fullscan-frontend-22` (PR #72), which already fixed
  split-deploy URL resolution in MediaPlayer, subtitle size cap + case-insensitive
  `.srt`, `encodeURIComponent` on tokens, GrabbedModal focus/Escape, context-menu
  toasts/timer/separator, paste-failure toast, nested-button HTML, `formatFileSize`
  negatives, `formatDuration` non-positive, and removed dead `plyr.d.ts`.
  This run looked only for what is still broken on top of that branch.

## Checked and found clean

- No `dangerouslySetInnerHTML`, `innerHTML`, `eval`, or `new Function` in `src`.
- Auth flows: token refresh interceptor (queue, timeout, multi-tab recovery),
  login-code polling (snapshot ref, sequential long-poll, terminal-status stop),
  `AuthImage` bearer-leak origin guard + abort + 5 MB cap, BotLink allowlists.
- No hardcoded secrets/tokens in `src`; `__BACKEND_URL__` placeholder handling intact.
- Backend (read-only, not modified) confirms: library `stream_url` is relative
  (`/api/stream/{id}`), `public_stream_url` is relative (`/api/stream/s/{hash}`),
  grab `stream_url` is absolute with a file-bound `?token=`.

## Findings fixed by this run (all on branch `opencode/fullscan-frontend-22`)

1. `frontend/src/components/MediaPlayer.tsx:402,416,424,841,849` — error panel
   handed the account-wide JWT to external surfaces: "Copy URL" copied the
   `?token=<JWT>` URL to the clipboard, "Open in VLC" launched
   `vlc://…?token=<JWT>`, and the download fallback (`:371`) navigated to the
   JWT URL (JWT lands in clipboard history, chat logs, external apps, browser
   history). Fixed: VLC / copy / download-fallback now prefer the token-free
   public link and otherwise mint a short-lived file-bound download token (same
   pattern as GlobalContextMenu); download fallback with no public link closes
   the blank tab and toasts instead of navigating to the JWT URL; removed the
   now-unused `vlcUrl`/`externalUrl` consts.
2. `frontend/src/lib/api.ts:140` — added `backendUrl()` helper: resolves
   relative backend paths against `API_BASE` (split deploys), passes absolute
   URLs through untouched.
3. `frontend/src/components/GlobalContextMenu.tsx:146,154,244,265` —
   public-link / VLC / copy builders concatenated the frontend origin
   (`window.location.host`) with backend paths, producing same-origin-only URLs
   (404 on split deploys) and corrupting absolute stream URLs (`https://fe` +
   `https://be/…`). Fixed to use `backendUrl()`.
4. `frontend/src/components/FileBrowser.tsx:262` — paste with clipboard mode
   `copy` used a blocking `alert()`; replaced with a toast (+ `addToast` dep).
5. `frontend/src/components/AuthImage.tsx:103` — `parseInt(contentLength)`
   without radix; now `parseInt(…, 10)`.
6. `frontend/src/components/MediaPlayer.tsx:177,187` — subtitle upload rejected
   `.sub` files silently and had no `FileReader.onerror` handler (a failed read
   left the picker open with zero feedback). Both now toast.
7. `frontend/src/components/Sidebar.tsx:24` — logout / logout-all confirm
   modals had no Escape-to-close (every other modal in the app has one); added
   a document-level Escape handler, guarded while logout-all is in flight.

## Verification (2026-10-11, on the fix branch)

- `npx tsc --noEmit` — exit 0
- `npx eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0` — exit 0
- `npm test` (vitest) — 8/8 passed (`modalsEscape.test.tsx`)
- `npx vite build --outDir /tmp/… --emptyOutDir` — success (1540 modules;
  outDir overridden to /tmp so the backend `app/static` tree is untouched)

## Delivery

- Fix PR: https://github.com/tirforge/Aruvi/pull/72 (existing open frontend-fix
  PR for this area — new commits added to its branch
  `opencode/fullscan-frontend-22` instead of opening a duplicate)
