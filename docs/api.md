# API Reference

All routes live under `/api` except `/privacy` and `/terms`. Auth-protected routes expect `Authorization: Bearer <access_token>` (15-min JWT).

**Base URL:** `https://movie.aaruvi.space/api` (live) or `http://localhost:7680/api` (dev)

---

## Route Map (11 routers)

| Router | Prefix | Auth | Purpose |
|--------|--------|------|---------|
| auth | `/api/auth` | Mixed | Login, tokens, sessions |
| files | `/api/files` | JWT | File CRUD, progress, sharing |
| folders | `/api/folders` | JWT | Folder tree CRUD |
| streaming | `/api/stream` | Download token / public | Video streaming |
| tv | `/api/tv` | JWT | TV-optimized browsing |
| grab | `/api/grab` | JWT | Movie search & import |
| gdrive | `/api/gdrive` | JWT | Google Drive import |
| subtitles | `/api/subtitles` | JWT | Subtitle search & fetch |
| admin | `/api/admin` | Admin | User management, stats |
| diag | `/api/diag` | DEBUG_PASSWORD | Health & diagnostics |
| legal | `/privacy`, `/terms` | None | Static HTML pages |

---

## Authentication (`/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/auth/bot/info` | None | Bot username for login deep-links |
| POST | `/auth/generate-code` | None | Create TV pairing code (10 min TTL) |
| POST | `/auth/verify-code` | None | Poll: code claimed? → returns token pair |
| POST | `/auth/code` | None | Legacy alias for verify-code |
| POST | `/auth/refresh` | Refresh token | **Rotates** refresh token; replay = 401 |
| GET | `/auth/me` | JWT | Current user profile |
| POST | `/auth/logout-all` | JWT | Bump `auth_version`, kill all sessions |

### Login flow (TV)
```
1. POST /auth/generate-code        → {code, bot_username, expires_in}
2. User sends /start <CODE> to bot in Telegram
3. TV polls POST /auth/verify-code → {access_token, refresh_token}
4. On 401 later: POST /auth/refresh with refresh_token
```

---

## Files (`/files`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/files` | List files (paginated, filter by folder) |
| GET | `/files/recent` | Recently added |
| GET | `/files/continue-watching` | In-progress items |
| GET | `/files/storage` | Quota usage summary |
| GET | `/files/{file_id}` | File metadata |
| PATCH | `/files/{file_id}` | Rename / move file |
| DELETE | `/files/{file_id}` | Delete file (+ Telegram message) |
| POST | `/files/batch-delete` | Delete many at once |
| POST | `/files/batch-move` | Move many to folder |
| PUT/POST | `/files/{file_id}/progress` | Save watch position |
| GET | `/files/{file_id}/progress` | Get watch position |
| POST | `/files/{file_id}/share` | Enable public share (returns hash) |
| DELETE | `/files/{file_id}/share` | Disable public share |
| POST | `/files/{file_id}/download-token` | Mint 30-day streaming token |

---

## Folders (`/folders`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/folders` | List root-level folders |
| GET | `/folders/tree` | Full nested tree |
| GET | `/folders/{folder_id}` | One folder |
| POST | `/folders` | Create folder |
| PATCH | `/folders/{folder_id}` | Rename / move |
| DELETE | `/folders/{folder_id}` | Delete subtree |
| POST | `/folders/batch-delete` | Delete many |
| POST | `/folders/batch-move` | Move many |

---

## Streaming (`/stream`) — no JWT, uses download tokens

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/stream/{file_id}?token=...` | Download token | Video stream w/ Range support (206) |
| GET | `/stream/dl?...` | Download token | Direct download (Content-Disposition) |
| GET | `/stream/{file_id}/thumbnail?token=...` | Download token | JPEG thumbnail |
| GET | `/stream/s/{public_hash}` | None | Public shared stream |
| GET | `/stream/debug` | DEBUG_PASSWORD | Cache/session internals |

**Range behavior:** single range → `206 Partial Content`; multi-range → coalesced into one; open-ended (`bytes=100-`) and suffix (`bytes=-500`) supported; zero-byte files → plain `200`.

---

## TV (`/tv`) — big-screen UI helpers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/tv/browse` | Grid data for browse screen |
| GET | `/tv/revision` | Cheap change-detection counter |
| GET | `/tv/continue` | Continue-watching row |
| GET | `/tv/recent` | Recently added row |
| GET | `/tv/search?q=` | Search |
| GET | `/tv/folder/{folder_id}` | Folder contents |

---

## Grab (`/grab`) — movie search & import

| Method | Path | Description |
|--------|------|-------------|
| POST | `/grab/search` | Search source channels for a title |
| POST | `/grab/select` | Import selected result into your library |

---

## GDrive (`/gdrive`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/gdrive/auth` | Start OAuth flow |
| GET | `/gdrive/auth/callback` | OAuth redirect target |

---

## Subtitles (`/subtitles`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/subtitles/search?file_id=` | Find subtitles for a file |
| GET | `/subtitles/content?id=` | Fetch VTT/SRT content |

---

## Admin (`/admin`) — requires `is_admin`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/stats` | Platform-wide stats |
| GET | `/admin/users` | All users |
| POST | `/admin/users/{id}/toggle-admin` | Grant/revoke admin |
| DELETE | `/admin/users/{id}` | Delete user + their data |

---

## Diagnostics (`/diag`) — requires `Authorization: Bearer $DEBUG_PASSWORD`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/diag/ping` | Liveness |
| GET | `/diag/bandwidth` | Throughput measurements |
| GET | `/diag/active` | Currently active streams |
| GET | `/diag/stream?msg=&chat=` | Raw Telegram range test (206 expected) |
| GET | `/diag/clear-cache` | Drop RAM cache |

```bash
curl -H "Authorization: Bearer $DEBUG_PASSWORD" http://localhost:7680/api/diag/ping
```

---

## Error Shapes

All errors return FastAPI defaults:

```json
{"detail": "human-readable message"}
```

| Status | Meaning |
|--------|---------|
| 401 | Missing/expired access token, or replayed refresh token |
| 403 | Download token bound to different file, or stale `ver` claim |
| 404 | Resource not found (or not yours) |
| 429 | Upstream Telegram flood (rare — absorbed by sleep_threshold) |

Interactive docs: `http://localhost:7680/docs` (Swagger UI).
