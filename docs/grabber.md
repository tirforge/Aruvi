# Grabber — Add Source Groups

The grabber indexes movies from **Telegram groups you follow** so users can search and request them in Aruvi. It is optional — Aruvi works fine with only `TELEGRAM_STORAGE_CHANNEL_ID`.

---

## 1. What it does

- You configure 1+ source group usernames (e.g. movie request groups).
- Aruvi joins them with dedicated Ivy sessions and listens for new files.
- Users search via the app (`Movies → Search`) — results come from those groups.

## 1.1 Requirements — Telegram mobile account (mandatory)

The grabber **cannot work with bot tokens alone**. It needs a **real Telegram mobile account** (phone number + API ID/HASH) because:

- Bots can only see messages that mention them; they miss most group files.
- User accounts (Ivy sessions via Telethon MTProto) see the full group history like a normal Telegram app.
- Each `GRAB_GROUP_*` you configure is joined **as that user account**, not as the bot.

What you need:
- **One phone number per concurrent group** is recommended (you can reuse one number for 2–3 groups, but separate numbers avoid rate limits).
- The phone number must be able to **join the source groups** (open Telegram with that number → `Join` the group). If the group is private/invite-only, you must join manually first — the grabber will then see `channel access OK`, otherwise it logs `not a member`.
- Keep the account active — if you log out or change the password, the session string expires and grabs stop.

---

## 2. Add groups (`.env`)

In `.env` (see `.env.example:78`):

```bash
# Single group (legacy)
GRAB_GROUP_USERNAME=my_movie_group

# Multiple groups (preferred) — comma-separated, no @, no t.me/
GRAB_GROUP_USERNAMES=movie_group1,movie_group2,CinemaGalaxy_Group

# Bots that post in those groups (positional — one per group, empty = auto-detect)
GRAB_BOT_USERNAMES=FileBot,Toby2Robot,

# Ivy sessions for parallel fetching (one per group recommended)
GRAB_SESSION_STRINGS=1_sender_session_string,2_sender_session_string
```

**Rules:**
- Usernames only — e.g. `Film_Factorys_Group` not `https://t.me/Film_Factorys_Group` and not `@Film_Factorys_Group`.
- Groups must be **public** or your Ivy sessions must already be **members** (join manually with those accounts first).
- Order matters: `GRAB_BOT_USERNAMES` maps positionally to `GRAB_GROUP_USERNAMES`. Leave blank entry with comma to auto-detect: `bot1,,bot3`.

Get the username: open the group in Telegram → `Group Info` → the `@username` or `t.me/<username>` link → use `<username>`.

### 2.1 Generate Ivy session strings — step-by-step for beginners

Think of a session string as a **password that lets the server log in as your phone** without asking for OTP every time. You create it once, paste it in `.env`, and never share it.

> **You need:** a phone number with Telegram installed, a computer with Python 3.11+, 10 minutes.

**Step 1 — Get Telegram API credentials (one-time, free)**

1. Open https://my.telegram.org and log in with your phone number (you will get a code in Telegram).
2. Click **API development tools**.
3. Fill the form: `App title` = `Aruvi`, `Short name` = `aruvi`, `Platform` = `Other` → click **Create application**.
4. You will see `App api_id` (e.g. `1234567`) and `App api_hash` (e.g. `abc123...`). Copy both — one app can be reused for all your session strings.

**Step 2 — Install Telethon**

On your computer (not on the server):

```bash
pip install telethon
```

**Step 3 — Generate the session string**

Create a file `gen_session.py` anywhere (e.g. on your Desktop) and paste this:

```python
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = 1234567              # ← put your api_id here (numbers only, no quotes)
API_HASH = "abc123..."        # ← put your api_hash here (keep the quotes)

client = TelegramClient(StringSession(), API_ID, API_HASH)
client.start()                # it will ask for phone, then code, then 2FA password if you have one
print("\nYOUR SESSION STRING (copy the whole line):")
print(client.session.save())
```

Run it:

```bash
python3 gen_session.py
```

What happens:
- It asks `Please enter your phone:` → type `+919876543210` (with country code).
- Telegram sends a **login code** to your Telegram app → type it in the terminal.
- If you have 2FA password, it asks for it → type it.
- It prints a **very long string** starting with `1...` or `BQIk...` — that is your session string. It is a full login — **never share it or push it to GitHub**.

Do this **once per phone number**. One number can handle 2–3 groups; for many groups use multiple numbers (one string per group is ideal).

If you see an error, check that `API_ID` is numbers without quotes and `API_HASH` has quotes.

**Step 4 — Join the source groups with that phone account**

Open Telegram **logged in as the same phone number** → search the group username (e.g. `CinemaGalaxy_Group`) → tap **Join**. Open the group and confirm you can see files. If the group is private/invite-only, you must join via invite link first — the grabber cannot join it for you.

**Step 5 — Paste into `.env`**

On your server, open `.env`:

```bash
GRAB_GROUP_USERNAMES=Film_Factorys_Group,CinemaGalaxy_Group
GRAB_BOT_USERNAMES=Toby2Robot,          # leave blank with comma to auto-detect
GRAB_SESSION_STRINGS=PASTE_FIRST_STRING_HERE,PASTE_SECOND_STRING_HERE
```

Rules:
- `GRAB_SESSION_STRINGS` entries are **comma-separated, no spaces**.
- Order: first string corresponds to first group, etc. They are pooled in `backend/app/grabber.py:96` (`_IvyPool`) and read via `backend/app/config.py:173`.

**Security:** `.env` is gitignored (`**/.env` in `.gitignore:3`) — it will never be pushed. If a string leaks, go to Telegram `Settings → Devices → Terminate` that session and regenerate.

### 2.2 Easiest way via GitHub (no local Python needed)

If you don't want to install Python locally, use **GitHub Codespaces** (free):

1. On GitHub, click `Code → Create codespace on main` (browser, no install).
2. In the terminal that opens, run:

   ```bash
   pip install telethon
   python scripts/setup_helper.py
   ```

   Choose `3) Both` — it will ask for `API_ID`/`API_HASH` → phone → code → 2FA, then **prints your session string and lists all your channels/groups with their `-100...` IDs and usernames**.

3. Copy the IDs into `.env` locally (`TELEGRAM_STORAGE_CHANNEL_ID` and `GRAB_GROUP_USERNAMES`), and close the codespace.

The script is `scripts/setup_helper.py:1` — it runs entirely in your codespace, nothing is stored.

---

## 3. Restart & verify

```bash
python run.py   # or docker compose restart
```

Watch logs:
```bash
grep -E "grab_groups|Grab.*start|Client.*start" grabber.log
# expect: grab_groups=['movie_group1', 'movie_group2'] and each group shows channel access OK
```

In the app: `Movies → Search "test"` — results should appear within seconds. If not, check logs for `FLOOD_WAIT` or `not a member`.

---

## 4. Common issues

| Symptom | Fix |
|---------|-----|
| `not a member` / `CHANNEL_PRIVATE` | Ivy session account must join the group first (open Telegram with that account → Join). |
| No results | Verify group username spelling (case-sensitive), restart, check `grab_groups` in logs. |
| `FLOOD_WAIT` | Too many concurrent grabs — reduce groups or wait; sessions are rate-limited per DC. |
| Bot mismatch | Ensure `GRAB_BOT_USERNAMES` count matches `GRAB_GROUP_USERNAMES` (use `,,` for auto). |

---

## 5. Where else it is documented

- `.env.example:78` — inline comments
- `backend/app/config.py:164-192` — field definitions (`grab_group_usernames_str`, `grab_group_bots`)
- `docs/deployment.md:46` — env block summary (links here)

To add a new group later: append its username to `GRAB_GROUP_USERNAMES` (and matching bot entry), restart.
