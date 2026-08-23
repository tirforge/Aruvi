# Deployment & Runbook — Simple Explanation

## The Server

- **Container**: 3 GB RAM, 4 vCPU, Ubuntu
- **Python**: 3.11.15 at `/home/container/python3.11/python/bin/python3.11`
- **Database**: PostgreSQL (Supabase)
- **Ports**: 7680 (API), 24696 (opencode UI)

---

## Directory Layout

```
/home/container/grabber-deploy/
├── backend/
│   ├── app/              # FastAPI code (synced from GitHub)
│   ├── run.py            # Starts the server
│   ├── .env              # ALL SECRETS HERE
│   ├── grabber.log       # stdout/stderr
│   ├── session/          # Telegram session files (gitignored)
│   └── venv/             # Python packages
├── frontend/             # React source (build ignored at runtime)
└── AGENTS.md             # This file
```

---

## Required `.env` Variables

```bash
# Telegram (REQUIRED - get from @BotFather)
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_STORAGE_CHANNEL_ID=-100xxxxxxxxxx  # see "Add your storage channel" below
TELEGRAM_HELPER_BOT_TOKENS=token1,token2,...  # 10 helpers

# Auth
JWT_SECRET=...                      # 32+ random chars
DEBUG_PASSWORD=...                  # for /diag/* endpoints

# Database (Supabase)
DATABASE_URL=postgresql+asyncpg://...

# Optional: Google Drive, Subtitles, Grabber
GDRIVE_CLIENT_ID=...
GDRIVE_CLIENT_SECRET=...
OPENSUBTITLES_API_KEY=...
GRAB_GROUP_USERNAME=...             # single source group for grabber (legacy)
GRAB_GROUP_USERNAMES=group1,group2  # comma-separated source groups (preferred)
GRAB_BOT_USERNAME=...
GRAB_BOT_USERNAMES=bot1,bot2
```

### Add your storage channel (local self-host)

This channel is **your library** — Aruvi only streams files you put there.

1. Telegram → **New Channel** (private, e.g. `My Aruvi Storage`).
2. **Add bot as admin**: open channel → `Manage channel → Administrators → Add admin` → select `@YourBot` → enable `Post messages`.
3. **Get the channel ID**: send any message to the channel, forward it to [`@userinfobot`](https://t.me/userinfobot) — it replies `ID: -100...`. Copy the full `-100...` number.
   - Alt: `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates` → find `chat.id`.
4. **Set in `.env`**: `TELEGRAM_STORAGE_CHANNEL_ID=-100...` (keep the `-100` prefix).
5. **Restart**: `python run.py` or `docker compose restart`; watch logs for `Client 0 (@YourBot): channel access OK`.
6. **Verify**: upload a test file to the channel → appears in `Home → Your Files` in seconds. If not, check `grabber.log` for `FLOOD_WAIT` or `channel access` errors.

---

## Start / Restart — TWO COMMANDS (CRITICAL)

**NEVER combine kill + start in one line.** The `setsid` pipe will hang your shell.

```bash
# 1. KILL (separate command, wait for it to finish)
P=$(ps aux | grep "[r]un\.py" | grep -v grep | awk '{print $2}' | tail -1); kill $P

# 2. START (separate command)
cd /home/container/grabber-deploy/backend
setsid -f /home/container/python3.11/python/bin/python3.11 -u run.py \
  >> /home/container/grabber.log 2>&1 < /dev/null
```

Wait 15 seconds, then verify:
```bash
tail -20 /home/container/grabber.log
# Look for: "Application startup complete" + all 11 bots connected
```

---

## Daily Auto-Restart (3:30 AM IST)

- Cron does: `git clone --depth=1 origin/main` → fresh deploy
- **Uncommitted/unpushed changes are LOST**
- **Always `git push` before 3:30 AM** if you fixed something manually

---

## Health Checks

```bash
# Basic: is the API up?
curl -sf http://localhost:7680/ | grep -q "Aruvi" && echo OK

# Streaming: does range request work? (needs DEBUG_PASSWORD)
curl -sf -H "Authorization: Bearer $DEBUG_PASSWORD" \
  "http://localhost:7680/diag/stream?msg=197&chat=-1003950847652" \
  -H "Range: bytes=0-1023" -w "\n%{http_code}\n"
# Expect: HTTP 206 + 1024 bytes
```

---

## Log Analysis (Common Queries)

```bash
# Stream health
grep -E "Batch.*timed out|Batch.*OK|Worker.*failed" /home/container/grabber.log

# Auth issues
grep -E "Refresh token|Invalid.*token|auth_version" /home/container/grabber.log

# Cache stats
grep "Housekeeping" /home/container/grabber.log

# Telegram issues
grep -E "Client.*start|FLOOD_WAIT|AuthKey|FILE_REFERENCE" /home/container/grabber.log
```

---

## Common Operations

| Task | Command |
|------|---------|
| Clear disk cache | `rm -rf /home/container/vcache/*` |
| Reset Telegram sessions | `rm -rf /home/container/grabber-deploy/backend/session/*.session` then restart |
| View active streams | `curl -H "Authorization: Bearer $DEBUG_PASSWORD" http://localhost:7680/diag/active` |
| Rotate DEBUG_PASSWORD | Edit `.env`, restart service |

---

## Scaling Knobs (Environment Variables)

| Variable | Default | What It Does |
|----------|---------|--------------|
| `TELEGRAM_CLIENT_CONCURRENCY` | 5 | Per-bot download semaphore |
| `STREAM_MAX_CONCURRENT` | 4 | Worker semaphore per stream |
| `STREAM_BATCH_SIZE` | 10 | Chunks per Telegram batch fetch |
| `STREAM_PREFETCH_AHEAD_MB` | 192 | How far ahead to prefetch |
| `STREAM_PREFETCH_CONCURRENCY` | 1 | Bots used for prefetch |
| `STREAM_INFLIGHT_MB` | 200 | Unbacklogged data cap per stream |
| `STREAM_RAM_PER_VIDEO_MB` | 300 | RAM hot cache per video |
| `DISK_CACHE_TTL` | 1800 | Seconds a cache dir lives after last use |
| `DISK_CACHE_MAX_BYTES` | 8 GB | Total disk tier cap |
| `DISK_CACHE_PER_VIDEO_BYTES` | 2 GB | Per-video disk cap |

Raise `TELEGRAM_CLIENT_CONCURRENCY` for more parallel chunk fetches; watch for `Batch ... timed out` and RAM.

---

## Troubleshooting Cheat Sheet

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Endless `upload.GetFile` retry | Stuck CDN/media session | Check `_dc_auth_failure_until`, restart |
| `Batch ... timed out` repeatedly | Slow disk / memory pressure | Increase `STREAM_INFLIGHT_MB`, check `OOM_THRESHOLD_PCT` |
| 401 on `/auth/refresh` | Refresh token replayed | Client must use latest token (rotation) |
| No bots connect | Invalid token / network | Verify tokens, check container egress |
| `sqlite3.OperationalError: locked` | Two processes using sessions | Kill zombies, ensure single process |