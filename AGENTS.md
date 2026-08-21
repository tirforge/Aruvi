# Agent Instructions for Aruvi

## Quick Context

Aruvi = Telegram-backed media streaming platform. Files live in a Telegram channel. FastAPI streams them to web/TV clients with a two-tier cache (RAM + disk).

**Repo:** https://github.com/tirforge/Aruvi (public release)
**Live deploy:** `/home/container/grabber-deploy` (clones fresh daily at 3:30 AM IST)

---

## Critical Rules

1. **Never combine kill + start in one command** — `setsid` holds the shell pipe
2. **Push before 3:30 AM IST** — daily re-clone wipes uncommitted changes
3. **Test locally first** — `compileall -q app`, `tsc --noEmit`, `vite build`
4. **Don't commit secrets** — `.env` has PAT in git remote URL already

---

## Common Tasks

### Fix a Bug
```bash
# 1. Work in the release copy
cd /tmp/opencode/aruvi-release

# 2. Edit files, test
/home/container/python3.11/python/bin/python3.11 -m compileall -q app
cd frontend && npx tsc --noEmit && npx vite build

# 3. Commit + push
git add -A && git commit -m "fix: ..." && git push origin main

# 4. Deploy to live (if needed)
# See "Deploy to Live" below
```

### Deploy to Live
```bash
# 1. Sync code (separate commands!)
P=$(ps aux | grep "[r]un\.py" | grep -v grep | awk '{print $2}' | tail -1); kill $P

# 2. Copy fixed code
cp -r /tmp/opencode/aruvi-release/backend/app/* /home/container/grabber-deploy/backend/app/

# 3. Start (separate command!)
cd /home/container/grabber-deploy/backend
setsid -f /home/container/python3.11/python/bin/python3.11 -u run.py >> /home/container/grabber.log 2>&1 < /dev/null

# 4. Verify (wait 15s)
tail -20 /home/container/grabber.log
# Should show: "Application startup complete" + 11 bots connected
```

### Run Tests
```bash
# Backend
cd /tmp/opencode/aruvi-release/backend
/home/container/python3.11/python/bin/python3.11 -m compileall -q app

# Frontend
cd /tmp/opencode/aruvi-release/frontend
npx tsc --noEmit && npx eslint . --ext ts,tsx --max-warnings 0 && npx vite build
```

---

## Key Files to Know

| Area | File |
|------|------|
| Streaming core | `backend/app/streaming.py` |
| Telegram bots | `backend/app/telegram.py` |
| Disk cache | `backend/app/disk_cache.py` |
| Auth (JWT + rotation) | `backend/app/auth.py`, `routers/auth.py` |
| Movie search | `backend/app/grabber.py` |
| Bot commands | `backend/app/bot.py` |
| Streaming routes | `backend/app/routers/streaming.py` |

---

## Architecture Cheat Sheet

- **RAM cache** = 300 MB/video (hot, lost on restart)
- **Disk cache** = 8 GB total / 2 GB/video (persists 30 min after last use)
- **11 bots** = 1 main + 10 helpers (round-robin chunk downloads)
- **Prefetcher** = silently downloads ~192 MB ahead while you watch
- **Backpressure** = permits acquired ONLY on successful chunk delivery
- **Refresh tokens rotate** = replay = 401; server stores SHA256 hash only
- **Download tokens bind to file_id** = prevents cross-user access

---

## Environment Variables (Live)

All in `/home/container/grabber-deploy/backend/.env`:

```bash
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_STORAGE_CHANNEL_ID=-100...
TELEGRAM_HELPER_BOT_TOKENS=token1,token2,...
JWT_SECRET=...
DEBUG_PASSWORD=...
DATABASE_URL=postgresql+asyncpg://...
# Optional: GDRIVE_*, OPENSUBTITLES_API_KEY, GRAB_*
```

---

## Debug Endpoints (need DEBUG_PASSWORD)

```bash
# Stream range test
curl -H "Authorization: Bearer $DEBUG_PASSWORD" \
  "http://localhost:7680/diag/stream?msg=197&chat=-1003950847652" \
  -H "Range: bytes=0-1023"

# Active streams
curl -H "Authorization: Bearer $DEBUG_PASSWORD" \
  http://localhost:7680/diag/active

# Cache info
curl -H "Authorization: Bearer $DEBUG_PASSWORD" \
  http://localhost:7680/api/debug
```

---

## Log File

`/home/container/grabber.log` — stdout/stderr from `run.py`

Useful greps:
```bash
grep "Application startup complete" grabber.log
grep "Batch.*timed out" grabber.log
grep "Refresh token" grabber.log
grep "Housekeeping" grabber.log
```

---

## When Things Break

| Symptom | Check |
|---------|-------|
| 401 on refresh | Client using stale token (rotation) |
| Slow first play | Cold cache — normal |
| Endless `upload.GetFile` | Stuck media session → restart |
| `Batch timed out` | Disk slow / memory pressure |
| Bots won't connect | Bad token in `.env` |
| `sqlite3 locked` | Two processes → kill zombies |