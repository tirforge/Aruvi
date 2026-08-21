# Aruvi

Self-hosted media platform that streams your Telegram files (movies, series, audio) to the
browser, Android phone, and Android TV — powered by multi-bot parallel streaming with a
two-tier (RAM + disk) cache.

## Live Preview

**https://movie.aaruvi.space** — try the web player (demo instance).

```
aruvi/
├── backend/      # FastAPI backend (streaming engine, Telegram bot, API, subtitles)
├── frontend/     # React SPA (web player + file manager + grabs)
├── android/      # Native Android / Android-TV app (Kotlin + Jetpack Compose)
└── docs/         # Architecture, streaming, auth, data model, deployment guides
```

## Features

- Stream large media directly from your private Telegram channel to any device
- Multi-bot parallel chunk fetching with a **RAM hot cache + disk cache** (survives restarts)
- Internet subtitle search + download (OpenSubtitles.com + keyless providers)
- Telegram-bot driven grab/movie search
- Web player and native Android app (phone + TV flavors)
- Google Drive integration, thumbnails, continue-watching, folder management

## Quick Start

### 0. Docker (all-in-one, recommended)

```bash
cp .env.example .env          # fill in your Telegram credentials first
docker compose up -d --build
```
- Backend on `:7680` (override via `SERVER_PORT`)
- `./data` and `./session` bind-mounted for persistence

### 1. Backend (manual)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env    # fill in your Telegram credentials
python run.py
```
Web UI served from `backend/app/static` (prebuilt SPA bundle included).

> Windows / no `uvloop`: use `python run_nouvloop.py` instead. Requires Python **3.11+**.

### 2. Environment

Copy `.env.example` → `.env` and fill in. Every cache/prefetch/concurrency knob is tunable — defaults match the live instance.

### 3. Frontend (rebuild SPA)

```bash
cd frontend
npm install
npm run build      # outputs to ../backend/app/static
```

### 4. Android app

```bash
cd android
cp local.properties.example local.properties
./gradlew assembleMobileDebug   # phone/tablet
./gradlew assembleTvDebug       # Android TV
```

---

## Architecture in 30 Seconds

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

- **11 bots** (1 main + 10 helpers) download chunks in parallel
- **RAM cache**: 300 MB/video (instant replay)
- **Disk cache**: 8 GB total / 2 GB/video (survives restarts)
- **Refresh tokens rotate** — replay attacks impossible
- **Download tokens bind to file_id** — prevents cross-user access

See [docs/architecture.md](docs/architecture.md) for the full simple explanation.

---

## Documentation

| Topic | File |
|-------|------|
| Architecture (5 min) | [docs/architecture.md](docs/architecture.md) |
| API reference | [docs/api.md](docs/api.md) |
| Streaming engine | [docs/streaming.md](docs/streaming.md) |
| Auth & tokens | [docs/auth.md](docs/auth.md) |
| Database schema | [docs/data-model.md](docs/data-model.md) |
| Testing | [docs/testing.md](docs/testing.md) |
| Deploy & runbook | [docs/deployment.md](docs/deployment.md) |
| Agent cheat sheet | [AGENTS.md](AGENTS.md) |

---

## Key Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `TELEGRAM_API_ID` | — | Telegram app API ID |
| `TELEGRAM_API_HASH` | — | Telegram app API hash |
| `TELEGRAM_BOT_TOKEN` | — | Main bot token from BotFather |
| `TELEGRAM_HELPER_BOT_TOKENS` | *empty* | 10 helper bots for parallel fetching |
| `TELEGRAM_STORAGE_CHANNEL_ID` | — | Channel where media is stored |
| `DATABASE_URL` | SQLite | PostgreSQL supported |
| `JWT_SECRET` | auto-generated | Set for sessions to survive restarts |
| `SERVER_PORT` | `7680` | HTTP port |
| `WEB_BASE_URL` | `http://localhost:7680` | Public base URL |
| `STREAM_RAM_PER_VIDEO_MB` | `200` | RAM hot cache per video |
| `STREAM_INFLIGHT_MB` | `200` | Backpressure cap per stream |
| `STREAM_PREFETCH_AHEAD_MB` | `128` | Prefetch ahead of playhead |
| `DISK_CACHE_DIR` | `./data/vcache` | Disk cache location |
| `DISK_CACHE_TTL` | `1800` | Disk expiry (s) after last activity |
| `OPENSUBTITLES_API_KEY` | *empty* | Enables OpenSubtitles.com |
| `DEBUG_PASSWORD` | *empty* | For `/diag/*` endpoints |

Full list in `.env.example`.

---

## License

MIT