# Grabber — Add Source Groups

The grabber indexes movies from **Telegram groups you follow** so users can search and request them in Aruvi. It is optional — Aruvi works fine with only `TELEGRAM_STORAGE_CHANNEL_ID`.

---

## 1. What it does

- You configure 1+ source group usernames (e.g. movie request groups).
- Aruvi joins them with dedicated Ivy sessions and listens for new files.
- Users search via the app (`Movies → Search`) — results come from those groups.

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
