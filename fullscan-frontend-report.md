# Fullscan Frontend Report — 2026-10-01

Scope: `frontend/` only. No other top-level dirs, `.github/`, or vendored/build
output touched (`frontend/public/vendor/`, backend `app/static/*` left alone).

## Dirs scanned

- `frontend/` (root configs: `index.html`, `package.json`, `vite.config.ts`,
  `vitest.config.ts`, `tailwind.config.js`, `postcss.config.js`,
  `.eslintrc.cjs`, `tsconfig.json`, `tsconfig.node.json`)
- `frontend/src/` (`App.tsx`, `main.tsx`, `index.css`, `vite-env.d.ts`,
  `plyr.d.ts`)
- `frontend/src/lib/` (`api.ts`, `store.ts`, `loginCode.ts`, `useFocusReturn.ts`)
- `frontend/src/components/` (`AdminPanel`, `AuthImage`, `DeleteConfirmModal`,
  `FileBrowser`, `FileCard`, `FolderCard`, `GlobalContextMenu`, `GrabSearch`,
  `MediaPlayer`, `MoveFileModal`, `NewFolderModal`, `RenameModal`, `Sidebar`,
  `Toasts`, `modalsEscape.test.tsx`)
- `frontend/scripts/` (`gzip-assets.mjs`), `frontend/public/` (listing only;
  `public/vendor/` not modified)

**File count:** 46 files under `frontend/` (excluding `node_modules`);
all 46 read in full (the ~11k-line vendored `public/vendor/movi-player-*
file was listed/grepped, not hand-reviewed line by line, and not modified).

## What was checked

Auth/token handling (refresh interceptor, multi-tab rotation, JWT in URLs,
clipboard/VLC/download flows), injection/XSS sinks (`dangerouslySetInnerHTML`,
`innerHTML`, `eval`, `javascript:` URLs — none found; all server/user strings
rendered via React text nodes), secrets in source (none — only registry URLs
in lockfile and i18n blobs in the vendored player matched keyword greps),
race conditions (refresh queue, drag selection, polling loops, copy timers),
error handling (interceptor fallthroughs, mutation rejections, image/token
fallbacks), dead code, invalid HTML nesting, timer/observer/abort cleanup,
`useSyncExternalStore` usage, and toolchain verification (`tsc --noEmit`,
`eslint --max-warnings 0`, `vitest run`, `vite build`).

## Verdict: NOT CLEAN — 8 findings, all fixed (see Fix PR below)

1. **Lint broken — unused eslint-disable directives** (`frontend/src/components/RenameModal.tsx:44`, `:80`).
   `react-hooks/exhaustive-deps` is `off` in `.eslintrc.cjs`, so both
   `// eslint-disable-next-line react-hooks/exhaustive-deps` comments were
   unused and `npm run lint` (`--report-unused-disable-directives
   --max-warnings 0`) failed. Fix: removed the two directives. Verified:
   lint now exits 0.
2. **Copy-feedback timer race** (`frontend/src/components/GlobalContextMenu.tsx:104`).
   `handleCopy` fired a bare `setTimeout(() => setCopiedId(null), 2000)` per
   copy with no tracking: copying link B 1.5s after link A let A's stale timer
   clear B's "✓ Copied!" after 0.5s. Fix: `copyTimerRef` (cleared before each
   new timer + on unmount), mirroring the existing `GrabSearch` pattern.
3. **VLC `window.open` missing `noopener,noreferrer`** (`frontend/src/components/GlobalContextMenu.tsx:226`).
   The download handler on line 157 already passed `'noopener,noreferrer'`;
   the "Play in VLC" handler did not, leaving `window.opener` set. Fix: added
   the third argument (return value unused there, so no behavior change).
4. **Invalid HTML: `<div>` inside `<button>`** (`frontend/src/components/MoveFileModal.tsx:183-186`).
   The folder-tree expand chevron was a `<div onClick>` nested in the select
   `<button>`. Fix: changed to `<span>` (valid phrasing content; flex-item
   layout unchanged).
5. **`formatDuration` swallowed NaN into `''`** (`frontend/src/lib/api.ts:795-796`).
   `if (!seconds) return ''` caught NaN (falsy), making the
   `!Number.isFinite` → `'—'` branch unreachable for NaN (only `Infinity`
   reached it). Fix: `if (seconds == null || !(seconds > 0)) return '';`
   (null/undefined/0/negative/NaN → `''`, `±Infinity` → `'—'`).
6. **`selectAll` O(visible × selected) scan on drag frames** (`frontend/src/lib/store.ts:153-157`).
   `state.visibleFiles.filter((f) => fileIds.includes(f.id))` ran an
   `Array.includes` scan per visible file on every rubber-band frame that
   changed the selection. Fix: single `new Set(fileIds)` + `Set.has` lookup.
7. **Account JWT appended to any `http(s)` stream URL + fragile URL join** (`frontend/src/components/MediaPlayer.tsx:269-273,280-295,318-320`).
   (a) `getAbsoluteUrl` returned any `http`-prefixed `stream_url` untouched
   and the token was then appended unconditionally — a foreign-origin URL
   would exfiltrate the account JWT (AuthImage already guards against exactly
   this; MediaPlayer did not). (b) Naive `origin + path` concatenation
   mangled slash-less relative paths into `https://hostapi/...`. Fix:
   `new URL()`-based resolution (as in AuthImage) plus `isOwnBackendUrl` /
   `withToken` helpers that only attach `?token=` for same-origin or
   `__BACKEND_URL__`-origin URLs (token-rotation re-source skips foreign
   origins entirely).
8. **Dead code** — `getFileIcon` (`frontend/src/lib/api.ts:807-815`, zero
   imports), `setMoveFiles` (`frontend/src/lib/store.ts:46,175`, zero uses),
   `frontend/src/plyr.d.ts:1-40` (types for `plyr`, which is not a dependency —
   player is movi-player), stale dev-note comment (`frontend/src/App.tsx:76-80`,
   referenced an old import set). Fix: removed all four.

Checked and intentionally left unchanged: `MediaPlayer` error-panel "Copy URL"
(JWT stream URL by design — external players need it; context menu already
mints short-lived download tokens where async is viable), `window.open('',
'_blank')` download pattern (same-origin target; `win === null` fallback
already handles blockers), `console.*` in catch paths (diagnostic logging),
`Math.random` toast ids (78B collision space), `plyr`-free build output.

## Verification (after fixes)

- `npx tsc --noEmit` → clean (exit 0)
- `npx eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0` → clean (exit 0; was failing before fix 1)
- `npx vitest run` → 1 file, 8/8 tests pass
- `npx vite build --outDir /tmp/opencode/frontend-dist` → success (1540 modules; redirected outDir so `backend/app/static` untouched — `git status` shows frontend-only changes)

## Fix PR

Fix PR: TBD (filled in immediately after opening)
