# Aruvi

Self-hosted media platform that streams your Telegram files (movies, series, audio) to the
browser, Android phone, and Android TV — powered by multi-bot parallel streaming with a
two-tier (RAM + disk) cache.

```
aruvi/
├── backend/      # FastAPI backend (streaming engine, Telegram bot, API, subtitles)
├── frontend/     # React SPA (web player + file manager + grabs)
└── android/      # Native Android / Android-TV app (Kotlin + Jetpack Compose)
```

## Features

- Stream large media directly from your private Telegram channel to any device
- Multi-bot parallel chunk fetching with a **RAM hot cache + disk cache** (survives restarts)
- Internet subtitle search + download (OpenSubtitles.com + keyless providers)
- Telegram-bot driven grab/movie search
- Web player (movi-player) and a native Android app (phone + TV flavors)
- Google Drive integration, thumbnails, continue-watching, folder management

## Quick Start

### 0. Docker (all-in-one, recommended)

Builds the React SPA and serves it from the backend in a single image:

```bash
cp .env.example .env          # fill in your Telegram credentials first
docker compose up -d --build
```

- Backend listens on `:7680` (override with `SERVER_PORT`).
- `./data` and `./session` are bind-mounted for persistence.
- The `.dockerignore` keeps `.env`, sessions, data and build junk out of the image.

### 1. Backend (required)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env    # fill in your Telegram credentials
python run.py
```

The web UI is served automatically from `backend/app/static` — the prebuilt SPA bundle
ships with the backend. To rebuild it from source, see [frontend](#3-frontend-optional).

> Windows / platforms without `uvloop`: use `python run_nouvloop.py` instead. Requires
> Python **3.11+**. `libjpeg`/`libcrypto` needed for Telegram media decryption on some
> platforms.

### 2. Environment configuration

Configuration is 100% env-driven. Copy [.env.example](.env.example) to `.env` and fill in
your values. Every cache, prefetch, concurrency and subtitle knob is tunable there — the
defaults match the values the project runs well on.

### 3. Frontend (optional, rebuild the bundled SPA)

```bash
cd frontend
npm install
npm run build      # outputs into ../backend/app/static
```

### 4. Android app (optional)

```bash
cd android
cp local.properties.example local.properties   # set sdk.dir + server URL
./gradlew assembleMobileDebug                   # phone/tablet flavor
./gradlew assembleTvDebug                       # Android TV flavor
```

The app logs in via a code from your Telegram bot (`/login <code>`). The default server
URL is `http://localhost:7680`. To point the app at a different backend, either set
`TELEGRAM_TV_SERVER_URL` in `local.properties` at build time, or enter the URL in the
app's Server Settings screen on the login page (mobile flavor).

## Architecture

- **Streaming engine** — batches of 1 MiB chunks fetched in parallel across a pool of
  Telegram bots; a per-video RAM hot cache sits in front of a disk cache, with an
  ahead-prefetcher that fills video ahead of the playhead. See `backend/app/streaming.py`.
- **Bot gateway** — the Telegram bot owns user/session auth and file delivery to your
  private storage channel.
- **Grabber (Ivy)** — a Pyrogram client pool that searches configured Telegram groups and
  forwards matched files to storage (see `backend/app/grabber.py`, `GRAB_*` env vars).
- **Subtitles** — title guessing via `guessit`, then OpenSubtitles.com (API key) plus
  subliminal keyless providers (`SUBTITLE_*` env vars).

## Configuration reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `TELEGRAM_API_ID` | — | Telegram app API ID (`my.telegram.org/apps`) |
| `TELEGRAM_API_HASH` | — | Telegram app API hash |
| `TELEGRAM_BOT_TOKEN` | — | Main bot token from BotFather |
| `TELEGRAM_HELPER_BOT_TOKENS` | *empty* | Comma-separated helper bots for parallel fetching |
| `TELEGRAM_STORAGE_CHANNEL_ID` | — | Channel id where media is stored/streamed from |
| `TELEGRAM_BOT_SESSION_STRINGS` | *empty* | Comma-separated session strings (optional) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/teleplay.db` | DB URL (PostgreSQL supported) |
| `JWT_SECRET` | auto-generated | Set it for sessions to survive restarts |
| `SERVER_PORT` | `7680` | HTTP port for the backend |
| `AUTH_USERS` / `ADMIN_IDS` | *empty* | Telegram user ids granted admin/access |
| `WEB_BASE_URL` | `http://localhost:7680` | Public base URL of the web app (tunnel/domain) |
| `MT_PROXY_URL` | *empty* | Optional SOCKS5 proxy |
| `TELEGRAM_CLIENT_CONCURRENCY` | `8` | Per-bot pipelined fetch concurrency |
| `GRAB_GROUP_USERNAMES` | *empty* | Telegram groups to search for movies |
| `GRAB_SESSION_STRINGS` | *empty* | Session pool for the grab client(s) |
| `STREAM_BATCH_SIZE` | `10` | Chunks per read batch |
| `STREAM_MAX_CONCURRENT` | `4` | Max concurrent stream workers |
| `STREAM_RAM_PER_VIDEO_MB` | `300` | RAM hot cache per video (MB) |
| `STREAM_INFLIGHT_MB` | `200` | In-flight/backpressure cap per stream (MB) |
| `STREAM_PREFETCH_AHEAD_MB` | `192` | How far ahead to prefetch (MB) |
| `STREAM_PREFETCH_CONCURRENCY` | `3` | Bots used for ahead-prefetching |
| `STREAM_PREFETCH_MAX_STREAMS` | `6` | Stop prefetch past this many active streams |
| `STREAM_BATCH_TIMEOUT_S` | `30` | Wall-clock budget per batch |
| `STREAM_BATCH_STALL_S` | `15` | Abort a batch if no progress this long |
| `STREAM_CHUNK_TIMEOUT_S` | `15` | Single-chunk fetch budget |
| `STREAM_SEM_WAIT_TIMEOUT_S` | `10` | Queue-wait budget behind a busy bot |
| `DISK_CACHE_DIR` | `./data/vcache` | Disk cache location (survives restarts) |
| `DISK_CACHE_ENABLED` | `1` | `0` disables the disk tier |
| `DISK_CACHE_TTL` | `1800` | Disk cache expiry (s) after last activity |
| `DISK_CACHE_MAX_BYTES` | `8 GB` | Global disk cache cap |
| `DISK_CACHE_PER_VIDEO_BYTES` | `2 GB` | Per-video disk cache cap |
| `SUBTITLE_LANGUAGES` | `en` | Subtitle language tags |
| `SUBTITLE_PROVIDERS` | `podnapisi,tvsubtitles,addic7ed` | Keyless providers |
| `OPENSUBTITLES_API_KEY` | *empty* | Enables OpenSubtitles.com search/download |
| `CLOUDFLARE_API_TOKEN` | *empty* | For tunnel/DNS via cloudflared |
| `GDRIVE_CLIENT_ID/SECRET` | *empty* | Google Drive integration |
| `DEBUG_PASSWORD` | *empty* | Password for diagnostic endpoints |

## License

MIT