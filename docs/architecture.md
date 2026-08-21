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
| **RAM (Hot)** | 200 MB per video | ~Memory speed | ❌ Lost on restart |
| **Disk (Cold)** | 8 GB total / 2 GB per video | ~SSD speed | ✅ 30 min after last use |

**Prefetcher:** While you watch, we silently download the next 128 MB ahead of you — so seeking is instant.

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