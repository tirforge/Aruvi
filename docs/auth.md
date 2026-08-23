# Auth System — Simple Explanation

## Three Token Types

```
┌─────────────────────┬────────────┬─────────────────────────────────┐
│ Token               │ Lifetime   │ Purpose                         │
├─────────────────────┼────────────┼─────────────────────────────────┤
│ Access Token (JWT)  │ 7 days     │ Every API call                  │
│ Refresh Token       │ 28 days    │ Get new access tokens           │
│ Download Token      │ 30 days    │ Streaming URLs (?token=...)     │
└─────────────────────┴────────────┴─────────────────────────────────┘
```

---

## How Refresh Rotation Works (Replay Protection)

```
User has: access_token (expired) + refresh_token (valid)
          │
          ▼
POST /auth/refresh  (Bearer refresh_token)
          │
          ▼
Server:
  1. SHA256(refresh_token) → look up in refresh_sessions table
  2. NOT FOUND? → 401 "Refresh token has been invalidated"
  3. EXPIRED?   → delete row, 401
  4. VALID?     → ROTATE IN PLACE:
       • new_access  = create_access_token(user)
       • new_refresh = create_refresh_token(user)  ← NEW jti (unique ID)
       • UPDATE refresh_sessions SET token_hash=SHA256(new_refresh),
                                     expires_at=now+60min,
                                     last_used_at=now
       • Return {access_token, refresh_token, ...}
```

**Key point:** Old refresh token's hash is **overwritten**. Replaying it → lookup fails → 401.

---

## Login Code Flow (TV App Pairing)

```
1. TV app: POST /auth/login-code
   → Returns: {code: "ABC123", bot_username: "@Aaruvi_movie_bot", expires_in: 600}

2. User opens Telegram, sends: /start ABC123

3. Bot handler (atomic):
   UPDATE login_codes
   SET telegram_id = <user_id>
   WHERE code = "ABC123"
     AND expires_at > now()
     AND telegram_id IS NULL
   
   • Row updated (rowcount=1) → SUCCESS
   • Row exists but telegram_id set → "Already used"
   • Row exists but expired → "Code expired"
   • No row → "Invalid code"

4. On success: create RefreshSession, TV polls for tokens
```

---

## Logout All (Nuclear Option)

```
POST /auth/logout-all
  │
  ▼
1. user.auth_version += 1          → All existing access tokens INSTANTLY invalid
2. DELETE FROM refresh_sessions    → All refresh tokens GONE
3. Return 204
```

---

## Download Tokens (For Streaming URLs)

```
create_download_token(telegram_id, file_id, version=0)
  → JWT with: sub=telegram_id, fid=file_id, ver=auth_version
  → 30-day TTL
```

**Used by:** Bot/grabber to give you `https://api/stream/123?token=xyz`

**Verified by:** `_user_from_download_token(request, file_id)`
- Checks `fid` claim matches requested `file_id` → **prevents IDOR**
- Checks `ver` >= user's current `auth_version` → respects logout-all

---

## Token Versioning (Single Source of Truth)

| Event | `user.auth_version` | Effect |
|-------|---------------------|--------|
| Login | 0 | Baseline |
| Password change | +1 | Old access tokens rejected |
| Logout all | +1 | All tokens + refresh sessions dead |

Access/refresh tokens embed `ver` at mint. Verification: `token.ver >= user.auth_version`.

---

## Database: `refresh_sessions` Table

```sql
CREATE TABLE refresh_sessions (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id) ON DELETE CASCADE,
    token_hash    CHAR(64) UNIQUE NOT NULL,   -- SHA256(refresh_token)
    expires_at    TIMESTAMP NOT NULL,
    last_used_at  TIMESTAMP NOT NULL,
    created_at    TIMESTAMP NOT NULL
);
```

- One row per **active** refresh token
- Rotation = `UPDATE token_hash` (not INSERT + DELETE)
- DB leak ≠ token leak (only hashes stored)

---

## Android App Compatibility

`AuthRepository.kt:116`:
```kotlin
saveTokens(body.accessToken, body.refreshToken)
```
Just persists the new pair — rotation works transparently.