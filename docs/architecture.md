# Aruvi Architecture — Simple Explanation

## What is Aruvi?

Aruvi is a **media streaming platform** that stores files in Telegram and streams them to web/TV apps.

**Think of it like:** Netflix, but your "video library" lives in a private Telegram channel instead of S3.

---

## The Big Picture (3 Parts)

```
┌──────────────┐     ┌──────────────┐     ┌────────────────────┐
│   Your TV    │────▶│  Aruvi API   │────▶│  Telegram Channel  │
│  / Browser   │◀───│  (Port 7680) │◀───│  (Your Storage)    │
└──────────────┘     └──────────────┘     └────────────────────┘
                            │
                     ┌──────┴──────┐
                     │  Disk Cache │
                     │  /vcache/   │  ← persists across restarts
                     └─────────────┘
```

1. **Client** — Web browser, Android TV app, or mobile web
2. **Aruvi API** — FastAPI server that handles auth, streaming, search
3. **Telegram Channel** — Where files actually live (each file = 1 message)
4. **Disk Cache** — Local SSD cache so we don't re-download from Telegram every time

---

## How a Video Plays

```
User clicks "Play" on movie.mp4
         │
         ▼
┌─────────────────────────────────────┐
│ 1. API checks: "Do I have this in   │
│    RAM cache?" → Yes → Stream fast  │
└─────────────────────────────────────┘
         │ No
         ▼
┌─────────────────────────────────────┐
│ 2. Check disk cache (/vcache/)      │
│    → Yes → Stream from SSD          │
└─────────────────────────────────────┘
         │ No
         ▼
┌─────────────────────────────────────┐
│ 3. Fetch from Telegram (slow)       │
│    → Save to RAM + Disk             │
│    → Stream to user                 │
└─────────────────────────────────────┘
```

**Key insight:** First play is slow (Telegram download). Second play is instant (local cache).

---

## The 11 Bots (Why So Many?)

Telegram limits how fast one bot can download. Solution: **11 bot accounts** working in parallel.

- **Bot 0 (Main)** — Handles user commands, uploads, login
- **Bots 1-10 (Helpers)** — Only download chunks for streaming

They all connect to the same storage channel. Round-robin load balancing.

---

## Two-Tier Cache (The Secret Sauce)

| Layer | Size | Speed | Persists? |
|-------|------|-------|-----------|
| **RAM (Hot)** | 300 MB per video (`STREAM_RAM_PER_VIDEO_MB`) | ~Memory speed | ❌ Lost on restart |
| **Disk (Cold)** | 8 GB total / 2 GB per video | ~SSD speed | ✅ 30 min after last use |

**Prefetcher:** While you watch, we silently download the next ~192 MB ahead of you — so seeking is instant.

---

## Request Lifecycle (What Happens on One API Call)

```
GET /api/files/42
     │
     ▼
main.py (FastAPI app)
     │  CORS → exception handlers
     ▼
routers/files.py @router.get("/{file_id}")
     │  Depends(get_current_user)      ← JWT check (15-min token)
     │  Depends(get_db)                ← AsyncSession
     ▼
models.py (SQLAlchemy async)
     │  SELECT * FROM files WHERE id=42 AND user_id=<you>
     ▼
schemas.py (Pydantic)
     │  FileResponse model validates output
     ▼
JSON back to client
```

Streaming requests skip JWT entirely — they use the 30-day download token in the query string (see [auth.md](auth.md)).

---

## Component Inventory

| Module | Role | Key Exports |
|--------|------|-------------|
| `main.py` | App assembly, CORS, startup/shutdown | `app` |
| `config.py` | Pydantic Settings, all env vars | `get_settings()` |
| `database.py` | Async engine + session factory | `get_db`, `engine` |
| `models.py` | 5 SQLAlchemy tables | `User`, `File`, `Folder`, ... |
| `auth.py` | JWT mint/verify, token factories | `create_access_token`, `create_download_token` |
| `streaming.py` | Cache tiers, workers, prefetcher, range logic | `_cache_manager`, `_backpressure` |
| `telegram.py` | 11-bot pool, chunk fetch, message cache | `get_client`, `stream_media` |
| `disk_cache.py` | LRU disk tier, atomic writes | `put`, `get`, `touch` |
| `patch.py` | Telethon client wrapper + listener registry | `resolve_listener`, `cancel_listener` |
| `bot.py` | Command handlers (/start codes, admin) | router registration |
| `grabber.py` | Movie search across source channels | `search_movie` |
| `subtitles.py` (provider logic) | Multi-provider subtitle search | provider functions |
| `gdrive.py` | Google Drive OAuth + import | auth URL builders |
| `routers/*` | 11 HTTP routers (see [api.md](api.md)) | `router` |

---

## Configuration Reference (defaults from code)

### Streaming & Cache
| Env Var | Default | Meaning |
|---------|---------|---------|
| `CHUNK_SIZE` | 1 MB (fixed) | Telegram fetch granularity |
| `STREAM_RAM_PER_VIDEO_MB` | 300 | RAM hot-cache cap per video |
| `STREAM_INFLIGHT_MB` | 200 | Un-backlogged in-flight data per stream |
| `STREAM_MAX_CONCURRENT` | 4 | Worker semaphore per stream |
| `STREAM_PREFETCH_AHEAD_MB` | 192 | How far ahead to prefetch |
| `STREAM_BATCH_SIZE` | 10 | Chunks per `stream_media` batch |
| `DISK_CACHE_DIR` | `./data/vcache` | Disk tier location |
| `DISK_CACHE_TTL` | 1800 s | Dir expires 30 min after last activity |
| `DISK_CACHE_MAX_BYTES` | 8 GB | Total disk tier cap |
| `DISK_CACHE_PER_VIDEO_BYTES` | 2 GB | Per-video disk cap |
| `DISK_CACHE_ENABLED` | 1 | Set 0 to disable disk tier |

### Telegram Pool
| Env Var | Default | Meaning |
|---------|---------|---------|
| `TELEGRAM_CLIENT_CONCURRENCY` | 5 | Per-bot download semaphore |
| `TELEGRAM_HELPER_BOT_TOKENS` | — | Comma-separated; 10 helpers expected |

### Auth
| Env Var | Default | Meaning |
|---------|---------|---------|
| `JWT_SECRET` | required | Signing key (32+ chars) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 15 | Access JWT TTL |
| `REFRESH_TOKEN_DURATION` | 60 min | Refresh TTL (rotates each use) |
| `DOWNLOAD_TOKEN_DURATION` | 30 days | Streaming URL token TTL |

---

## Upload Flow (How Files Get In)

```
User sends file to bot OR grabber imports from source channel
        │
        ▼
Bot uploads to STORAGE CHANNEL (private, -100...)
        │  message_id returned
        ▼
INSERT INTO files (channel_message_id, user_id, ...)
        │
        ▼
File appears in library — nothing is copied.
Streaming always reads straight from the channel via message_id.
```

**Key insight:** Aruvi never stores video bytes itself. The DB row is just a pointer into the Telegram channel.

---

## Auth in 30 Seconds

| Token | Lifetime | Purpose |
|-------|----------|---------|
| **Access Token (JWT)** | 15 min | API calls (`Authorization: Bearer ...`) |
| **Refresh Token** | 60 min | Get new access tokens (rotates each use!) |
| **Download Token** | 30 days | Streaming URLs (`?token=...` bound to one file) |

**Rotation:** Every refresh = old token dies. Replay attack = impossible.

---

## Key Files (Where to Look)

| Feature | File |
|---------|------|
| Streaming engine | `backend/app/streaming.py` |
| Telegram bots | `backend/app/telegram.py` |
| Disk cache | `backend/app/disk_cache.py` |
| API routes | `backend/app/routers/streaming.py` |
| Auth logic | `backend/app/auth.py` + `routers/auth.py` |
| Movie search | `backend/app/grabber.py` |
| Bot commands | `backend/app/bot.py` |

---

## Design Principles (TL;DR)

1. **Disk is truth** — RAM caches are disposable
2. **Backpressure everywhere** — Never unbounded queues
3. **One media session at a time** — Serializes Telegram auth
4. **Fail fast, retry bounded** — Timeouts + cooldowns, not infinite retries
5. **Stateless workers** — Bots share nothing; safe to restart any time