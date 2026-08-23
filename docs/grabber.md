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

### 2.1 Generate Ivy session strings (Telegram mobile account)

Each Ivy session is a Telethon **StringSession** tied to one phone number.

1. **Get API credentials**: go to https://my.telegram.org → `API development tools` → create an app → note `API_ID` and `API_HASH`. One app can be reused for all sessions.
2. **Generate the string** (run locally once per phone number):

   ```bash
   pip install telethon
   python3 -c "
   from telethon.sync import TelegramClient
   from telethon.sessions import StringSession
   client = TelegramClient(StringSession(), API_ID, API_HASH)
   client.start(phone='+91XXXXXXXXXX')  # enter code from Telegram
   print(client.session.save())
   "
   ```

   It prints a long string starting with `1...` or `BQIk...` — that is your `GRAB_SESSION_STRINGS` entry. Keep it secret — it is a full login.

   Alternative: use the helper script if present: `python backend/scripts/gen_session.py --phone +91...`

3. **Join the groups** with that phone account: open Telegram (mobile/desktop) logged in as that number → search `group_username` → `Join`. Confirm you can see files there.
4. **Paste into `.env`**: `GRAB_SESSION_STRINGS=<string1>,<string2>` — one string per group is ideal; strings are comma-separated with no spaces. They are read in `backend/app/config.py:173` and pooled in `backend/app/grabber.py:96` (`_IvyPool`).

Never commit session strings — `.env` is gitignored (`**/.env`). If a string leaks, revoke it via Telegram `Settings → Devices → Terminate` and regenerate.

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
