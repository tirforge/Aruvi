# Mirror Bot Merge Plan

## Per-User Google Drive OAuth + Full Mirror Engine

---

## 1. Strategy Overview

Combine **two** open-source Telegram bots into one:

| Source | What we take | Purpose |
|---|---|---|
| **[telegram-drive-bot](https://github.com/nithilamandiw/telegram-drive-bot)** (nithilamandiw) | OAuth flow, per-user credential storage, GDrive API helpers | Each user connects their own Google Drive |
| **[mirrorbot137](https://github.com/Bots137/mirrorbot137)** (Bots137 fork) | aria2 engine, yt-dlp, mirror/leech/watch commands, queue, extract, zip, clone, search | Full download engine |

**Architecture:** Take mirrorbot137 as the base. Replace its single global `token.pickle` GDrive auth with telegram-drive-bot's per-user OAuth system. Each user runs `/connect` once -> browser OAuth -> their files go to **their own** Google Drive.

---

## 2. What Each Repo Provides

### 2.1 telegram-drive-bot - OAuth System

Single file: `bot.py` (~1200 lines, python-telegram-bot + aiohttp)

Key components to extract:

| Function/Component | Purpose |
|---|---|
| `get_user_creds_path(user_id)` | returns `user_creds/{uid}.json` path |
| `user_has_credentials(user_id)` | checks if creds file exists |
| `get_user_service(user_id)` | loads creds -> refreshes if expired -> builds Drive service |
| `_build_oauth_client_config()` | builds OAuth config dict from env vars |
| `handle_connect()` | `/connect` command - generates auth URL |
| `handle_oauth_callback()` | aiohttp web handler - fetches token - saves to `user_creds/{uid}.json` |
| `disconnect_handler()` | `/disconnect` - deletes creds file |
| `require_connection()` | guard function |

Storage format: `user_creds/{user_id}.json` - standard Google OAuth token JSON with refresh token.

Web server: aiohttp on port 8080, single route `GET /oauth/callback?code=...&state={user_id}`

### 2.2 mirrorbot137 - Download Engine

Multi-file project in `bot/` directory (Pyrogram-based):

```
bot/
├── __init__.py              # main entry, bot startup
├── modules/
│   ├── gdrive.py            # GDrive upload/download (uses global token.pickle)
│   ├── mirror.py            # /mirror command -> aria2 -> upload
│   ├── leech.py             # /leech -> download -> Telegram
│   ├── clone.py             # /clone -> copy between Drives
│   ├── watch.py             # /watch -> yt-dlp -> upload
│   ├── extract.py           # archive extraction
│   ├── zip.py               # zip/unzip
│   ├── search.py            # Drive search
│   ├── status.py            # download status
│   ├── speedtest.py         # speed test
│   └── helpers/
│       ├── aria2.py         # aria2 RPC client
│       ├── yt_dlp.py        # yt-dlp wrapper
│       └── telegram.py      # Telegram upload helpers
```

---

## 3. Files to Patch

### 3.1 NEW FILE: `oauth_server.py` (project root)

Copy from telegram-drive-bot `bot.py`:
- `get_user_creds_path(user_id)`
- `user_has_credentials(user_id)`
- `get_user_service(user_id)`
- `_build_oauth_client_config()`
- `handle_connect()` - adapt to Pyrogram handler
- `handle_oauth_callback()` - aiohttp web handler
- `disconnect_handler()` - adapt to Pyrogram
- `require_connection()` - guard function
- aiohttp web app setup on `OAUTH_SERVER_PORT` (default 8080)

### 3.2 PATCH: `bot/__init__.py`

```python
from oauth_server import start_oauth_server
start_oauth_server()  # launches aiohttp on OAUTH_SERVER_PORT
```

Register `/connect` and `/disconnect` command handlers.

### 3.3 PATCH: `bot/modules/gdrive.py` (CORE PATCH)

Every function that loads `token.pickle` -> accept `user_id` and call `get_user_service(user_id)`.

| Current (global token) | Patched (per-user) |
|---|---|
| `gdrive_upload(path, dest_id)` | `gdrive_upload(path, dest_id, user_id)` |
| `gdrive_download(file_id, dest)` | `gdrive_download(file_id, dest, user_id)` |
| `gdrive_clone(src, dest)` | `gdrive_clone(src, dest, user_id)` |
| `gdrive_list(folder_id)` | `gdrive_list(folder_id, user_id)` |
| `gdrive_delete(file_id)` | `gdrive_delete(file_id, user_id)` |
| `gdrive_search(query)` | `gdrive_search(query, user_id)` |

Patch pattern:
```python
# BEFORE:
def gdrive_upload(file_path, dest_id):
    creds = Credentials.from_authorized_user_file("token.pickle")
    service = build("drive", "v3", credentials=creds)

# AFTER:
def gdrive_upload(file_path, dest_id, user_id):
    service = get_user_service(user_id)  # from oauth_server.py
```

### 3.4 PATCH: `bot/modules/mirror.py`

Thread `user_id` through download chain: `/mirror` captures `update.from_user.id` -> passes to `aria2_download()` -> after complete, passes to `gdrive_upload()`.

### 3.5 PATCH: `bot/modules/watch.py`

Same: `/watch` captures `user_id` -> passes through yt-dlp -> gdrive upload.

### 3.6 PATCH: `bot/modules/clone.py`

`/clone` captures `user_id` -> passes to `gdrive_clone()`.

### 3.7 PATCH: `bot/modules/search.py`

Search the calling user's Drive instead of a fixed folder.

### 3.8 PATCH: `bot/modules/leech.py`

If it has GDrive save options, thread user_id through.

---

## 4. File Map

```
NEW:    oauth_server.py          (from telegram-drive-bot bot.py)
NEW:    user_creds/              (created at runtime)

PATCH:  bot/__init__.py          (start OAuth server, register commands)
PATCH:  bot/modules/gdrive.py   (all functions take user_id)
PATCH:  bot/modules/mirror.py   (thread user_id)
PATCH:  bot/modules/watch.py    (thread user_id)
PATCH:  bot/modules/clone.py    (thread user_id)
PATCH:  bot/modules/search.py   (use user's Drive)
PATCH:  bot/modules/leech.py    (if GDrive options)

EDIT:   requirements.txt         (add google-auth-oauthlib, aiohttp, google-api-python-client)
EDIT:   Dockerfile               (add deps if needed)
EDIT:   .env / config.env        (add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, OAUTH_REDIRECT_URI, OAUTH_SERVER_PORT)
```

---

## 5. Environment Variables

### New:

| Variable | Example |
|---|---|
| `GOOGLE_CLIENT_ID` | `123456789-xxxxx.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | `GOCSPX-xxxxxxxxxxxx` |
| `OAUTH_REDIRECT_URI` | `http://YOUR_IP:8080/oauth/callback` |
| `OAUTH_SERVER_PORT` | `8080` |

### Existing (keep from mirrorbot137):

`BOT_TOKEN`, `TELEGRAM_API`, `TELEGRAM_HASH`, `OWNER_ID`, `DATABASE_URL`, `GDRIVE_ID`...

---

## 6. Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/) -> create project
2. Enable **Google Drive API**
3. Credentials -> Create OAuth client ID -> **Web application**
4. Add redirect URI: `http://YOUR_IP:8080/oauth/callback`
5. Copy Client ID + Client Secret
6. OAuth consent screen: add `.../auth/drive` scope, add test users

---

## 7. HidenCloud Free Tier

### PYTHON: BUDGET FREE

| Resource | Value |
|---|---|
| CPU | 0.5 vCore (AMD EPYC, x86_64) |
| RAM | 0.5 GB DDR4 |
| Storage | 2 GB SSD |
| Ports | 1 |
| Renewal | Weekly |

### Free Server (3GB RAM, ARM64) - alternative

If you need more RAM, use this plan (also €0/week):
- 2 vCPU (Cobalt 100 ARM64), 3GB RAM, 15GB SSD, 2 ports
- Use static binaries for aria2/ffmpeg (ARM64 builds available from GitHub releases)

### Deployment Steps

1. Sign up at https://hidencloud.com
2. Order PYTHON: BUDGET FREE from Dashboard -> Store -> Free
3. Upload code via File Manager
4. Run `pip install -r requirements.txt` in console
5. Set env vars in Settings -> Environment
6. Set startup command: `python bot/__init__.py`
7. Start server

### Weekly Renewal

Every 7 days: Dashboard -> suspended services -> Renew -> Create Invoice -> Pay (€0). You have a 5-day grace period after suspension.

### ToS Note

HidenCloud **prohibits BitTorrent**. Bot uses: aria2 (HTTP/FTP links only), yt-dlp (streaming sites), Telegram file download. Torrent must be disabled in config.

---

## 8. Build Order (New Session)

Session checklist:
1. Clone mirrorbot137
2. Read `bot/modules/gdrive.py` - identify all token.pickle usages
3. Create `oauth_server.py` by extracting from telegram-drive-bot's `bot.py`
4. Patch `gdrive.py` - replace global token with `get_user_service(user_id)`
5. Patch `mirror.py` - thread user_id
6. Patch `watch.py` - thread user_id
7. Patch `clone.py` - thread user_id
8. Patch `search.py` - thread user_id
9. Patch `bot/__init__.py` - start OAuth server on boot
10. Update `requirements.txt`
11. Update `.env` / `config.env`
12. Disable torrent in aria2 config
13. Set up Google Cloud project + OAuth
14. Deploy to HidenCloud
15. Test: /connect -> browser auth -> /mirror -> verify upload to user's Drive

---

## 9. Sources

- telegram-drive-bot: https://github.com/nithilamandiw/telegram-drive-bot
- mirrorbot137: https://github.com/Bots137/mirrorbot137
- HidenCloud free tier docs: https://docs.hidencloud.com/free/free-tier
- HidenCloud ToS: https://docs.hidencloud.com/legal/terms
- Google Drive API: https://developers.google.com/drive/api
