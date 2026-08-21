# Authentication & Token Flow

## Token Types

### Access Token (JWT)
- Short-lived: `JWT_EXPIRY_MINUTES` (default 15 min)
- Payload: `sub` (telegram_id), `ver` (auth_version), `iat`, `exp`
- Used in `Authorization: Bearer <access>` for API calls
- Verified by `get_current_user` / `get_current_user_opt` dependencies

### Refresh Token (JWT + server-side session)
- Long-lived: `REFRESH_TOKEN_DURATION = jwt_expiry_minutes * 4` (default 60 min)
- Payload: `sub`, `jti` (unique ID), `ver`, `iat`, `exp`
- **Server-side session table**: `refresh_sessions`
  - `token_hash` = SHA256(refresh_token)
  - `expires_at`, `last_used_at`
  - FK to `users.id` with CASCADE delete

## Rotation Flow

```
POST /auth/refresh  (Bearer refresh_token)
       │
       ▼
1. sha256(refresh_token) → lookup RefreshSession
       │
       ├─ Not found → 401 "Refresh token has been invalidated"
       ├─ Expired (now > expires_at) → delete row, 401
       └─ Valid →
            │
            ▼
2. ROTATE in place:
   - new_access = create_access_token(user)
   - new_refresh = create_refresh_token(user)  (new jti)
   - UPDATE refresh_sessions SET token_hash=sha256(new_refresh),
                                  expires_at=now+duration,
                                  last_used_at=now
   - return {access_token, refresh_token, token_type, expires_in}
```

## Replay Protection

- Old refresh token's `token_hash` is **overwritten** on rotation
- Replaying the old token → lookup fails → 401
- Only the **latest** refresh token works

## Login Code Flow (TV Pairing)

```
1. TV app calls POST /auth/login-code  → returns {code, bot_username, expires_in}
2. User opens Telegram, sends /start <CODE>
3. Bot handler:
   - Atomic claim: UPDATE login_codes SET telegram_id=? WHERE code=? AND expires>now AND telegram_id IS NULL
   - On success: create RefreshSession, return access+refresh to TV via polling
   - On failure: distinct errors (already used / expired / invalid)
```

## Logout All

```
POST /auth/logout-all
   │
   ▼
1. Bump user.auth_version += 1  (invalidates all existing access tokens)
2. DELETE FROM refresh_sessions WHERE user_id=?
3. Return 204
```

## Download Tokens (Streaming Auth)

- Separate mint: `create_download_token(telegram_id, file_id, version)`
- 30-day TTL, bound to **specific file_id** (fixes IDOR)
- Used by bot/grabber to generate streaming URLs: `?token=<download_token>`
- Verified in `_user_from_download_token(request, file_id)` — matches file_id claim

## Token Versioning

- `User.auth_version` increments on logout-all / password change
- Access/refresh tokens embed `ver = auth_version` at mint
- Verification rejects tokens with `ver < current_auth_version`

## Security Notes

- `JWT_SECRET` from env (32+ chars recommended)
- Refresh tokens hashed at rest (SHA256) — DB leak ≠ token leak
- `httponly` cookies not used; SPA stores in memory/localStorage
- Android app compatible: `AuthRepository.saveTokens(access, refresh)` persists rotation