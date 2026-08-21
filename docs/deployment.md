# Deployment & Runbook

## Environment

- **Container**: Ubuntu-based, 3 GiB memory limit, 4 vCPU
- **Python**: 3.11.15 at `/home/container/python3.11/python/bin/python3.11`
- **uvloop**: 0.21.0 (pinned — 0.22.x segfaults on ARM64)
- **Database**: PostgreSQL via Supabase (asyncpg)
- **Ports**: 7680 (FastAPI), 24696 (opencode UI)

## Directory Layout

```
/home/container/grabber-deploy/
├── backend/
│   ├── app/                 # FastAPI application (synced from release repo)
│   ├── run.py               # Uvicorn bootstrap
│   ├── .env                 # Secrets (see below)
│   ├── grabber.log          # Stdout/stderr log
│   ├── session/             # Kurigram SQLite sessions (gitignored)
│   └── venv/                # Python virtualenv
├── frontend/                # React source (not used at runtime)
└── AGENTS.md                # This project's agent instructions
```

## Required `.env` Variables

```bash
# Telegram (required)
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_STORAGE_CHANNEL_ID=-100xxxxxxxxxx
TELEGRAM_HELPER_BOT_TOKENS=token1,token2,...  # 10 helpers

# Auth
JWT_SECRET=...                      # 32+ chars
DEBUG_PASSWORD=...                  # for /diag/* endpoints

# Database
DATABASE_URL=postgresql+asyncpg://...

# Google Drive (optional)
GDRIVE_CLIENT_ID=...
GDRIVE_CLIENT_SECRET=...

# Streaming tuning (see AGENTS.md for defaults)
STREAM_RAM_PER_VIDEO_MB=200
STREAM_INFLIGHT_MB=200
STREAM_PREFETCH_AHEAD_MB=128
STREAM_PREFETCH_CONCURRENCY=1
STREAM_MAX_CONCURRENT=3

# Grabber
GRAB_GROUP_USERNAME=...
GRAB_BOT_USERNAME=...
GRAB_BOT_USERNAMES=...

# Subtitles
OPENSUBTITLES_API_KEY=...
```

## Start / Restart (CRITICAL)

**Two separate commands** — never combine kill + start in one line or the shell hangs on `setsid` pipe.

```bash
# 1. Kill (separate command)
P=$(ps aux | grep "[r]un\.py" | grep -v grep | awk '{print $2}' | tail -1); kill $P

# 2. Start (separate command)
cd /home/container/grabber-deploy/backend
setsid -f /home/container/python3.11/python/bin/python3.11 -u run.py \
  >> /home/container/grabber.log 2>&1 < /dev/null
```

Wait 13–15 s, then verify:
```bash
tail -20 /home/container/grabber.log
# Should show: "Application startup complete" + all 11 bots connected
```

## Daily Auto-Restart

- Cron at 3:30 AM IST: fresh `git clone --depth=1 origin/main`
- **Uncommitted/unpushed changes are LOST** on restart
- Always `git push` after manual fixes before 3:30 AM

## Health Checks

```bash
# Basic liveness
curl -sf http://localhost:7680/ | grep -q "Aruvi" && echo OK

# Diagnostic (requires DEBUG_PASSWORD)
curl -sf -H "Authorization: Bearer $DEBUG_PASSWORD" \
  "http://localhost:7680/diag/stream?msg=197&chat=-1003950847652" \
  -H "Range: bytes=0-1023" -w "\n%{http_code}\n"
# Expect HTTP 206 + 1024 bytes
```

## Log Analysis

```bash
# Stream health
grep -E "Batch.*timed out|Batch.*OK|Worker.*failed" /home/container/grabber.log

# Auth issues
grep -E "Refresh token|Invalid.*token|auth_version" /home/container/grabber.log

# Cache stats
grep "Housekeeping" /home/container/grabber.log

# Telegram client issues
grep -E "Client.*start|FLOOD_WAIT|AuthKey|FILE_REFERENCE" /home/container/grabber.log
```

## Common Ops

### Clear disk cache (disk tier only, RAM auto-clears on restart)
```bash
rm -rf /home/container/vcache/*
```

### Reset Telegram sessions (forces re-auth)
```bash
rm -rf /home/container/grabber-deploy/backend/session/*.session
# Then restart service
```

### View active streams
```bash
curl -sf -H "Authorization: Bearer $DEBUG_PASSWORD" http://localhost:7680/diag/active
```

### Rotate DEBUG_PASSWORD
Edit `.env`, restart service.

## Scaling Knobs

| Env | Default | Effect |
|-----|---------|--------|
| `TELEGRAM_CLIENT_CONCURRENCY` | 5 | Per-bot get/save file semaphore |
| `STREAM_MAX_CONCURRENT` | 3 | Workers per stream (2 users + 1 prefetch) |
| `STREAM_PREFETCH_CONCURRENCY` | 1 | Bots used for prefetch |
| `STREAM_INFLIGHT_MB` | 200 | Unbacklogged data cap per stream |
| `STREAM_RAM_PER_VIDEO_MB` | 200 | L1 hot cache per video |

Raise `TELEGRAM_CLIENT_CONCURRENCY` for more pipelined chunk fetches; watch RAM and `Batch ... timed out`.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Endless `upload.GetFile` retry | Stuck CDN/media session | Check `_dc_auth_failure_until`, restart |
| `Batch ... timed out` repeatedly | Slow disk / memory pressure | Increase `STREAM_INFLIGHT_MB`, check `OOM_THRESHOLD_PCT` |
| 401 on `/auth/refresh` | Refresh token replayed | Client must use latest token (rotation) |
| No bots connect | Invalid `TELEGRAM_BOT_TOKEN` / network | Verify tokens, check container egress |
| `sqlite3.OperationalError: locked` | Concurrent session access | Ensure single process; kill zombies |