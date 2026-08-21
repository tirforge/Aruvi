# Aruvi Architecture Overview

## System Context

Aruvi is a Telegram-backed media streaming platform:
- **Storage**: Files stored as messages in a private Telegram channel
- **Delivery**: FastAPI + Kurigram (Telegram MTProto) streaming to clients
- **Frontend**: React 18 SPA served from `backend/app/static/`
- **Auth**: JWT access + rotating refresh tokens (per-user session table)
- **Database**: PostgreSQL (Supabase) via SQLAlchemy 2.0 async

## High-Level Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Client    │────▶│  FastAPI     │────▶│  Telegram Channel│
│  (Web/TV)   │◀───│  (Port 7680) │◀───│  (Storage)       │
└─────────────┘     └──────────────┘     └─────────────────┘
                           │
                    ┌──────┴──────┐
                    │  Disk Cache │
                    │ /vcache/    │
                    └─────────────┘
```

## Component Diagram

```
backend/
├── app/
│   ├── main.py              # FastAPI app, lifespan, SPA catch-all
│   ├── config.py            # Pydantic Settings (.env driven)
│   ├── database.py          # Async SQLAlchemy engine/session
│   ├── models.py            # ORM models (User, File, Folder, LoginCode, RefreshSession)
│   ├── auth.py              # JWT creation/verification, token minting
│   ├── routers/
│   │   ├── auth.py          # /auth/* — login, refresh, logout, verify-code
│   │   ├── streaming.py     # /stream/* — file streaming with Range support
│   │   ├── files.py         # /files/* — CRUD, upload, search
│   │   ├── folders.py       # /folders/* — folder tree ops
│   │   ├── grab.py          # /grab/* — movie search via Telegram bots
│   │   ├── tv.py            # /tv/* — TV app pairing
│   │   ├── subtitles.py     # /subtitles/* — OpenSubtitles search/download
│   │   └── diagnostic.py    # /diag/* — health, range test, cache mgmt
│   ├── streaming.py         # Core: ChunkCache, prefetcher, worker pool, disk tier bridge
│   ├── telegram.py          # Client pool lifecycle, message cache, warmup
│   ├── disk_cache.py        # Lazy disk tier (TTL on inactivity)
│   ├── grabber.py           # Movie search via helper bots
│   ├── patch.py             # Pyrogram listener queue (multi-listener FIFO + cmd routing)
│   ├── bot.py               # Telegram bot handlers (user-facing commands)
│   └── gdrive.py            # Google Drive upload (async I/O, sibling abort)
├── frontend/                # React source (built to backend/app/static/)
└── run.py                   # Uvicorn bootstrap (uvloop, housekeeping)
```

## Key Design Principles

1. **Disk-first streaming** — RAM is a hot layer; disk is authoritative
2. **Backpressure everywhere** — bounded RAM, bounded in-flight, memory-pressure gate
3. **Serialization of Telegram media sessions** — one ImportAuthorization at a time
4. **Fail-fast with bounded retries** — wall-clock timeouts, per-DC cooldowns
5. **Stateless horizontal scaling** — multiple bot clients share nothing; pool round-robin