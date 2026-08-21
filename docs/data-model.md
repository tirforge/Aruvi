# Data Model (SQLAlchemy 2.0)

## Core Tables

### `users`
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| telegram_id | BigInteger | UNIQUE, indexed |
| username | String(64) | nullable |
| first_name | String(64) | |
| last_name | String(64) | nullable |
| is_admin | Boolean | default False |
| auth_version | Integer | default 0, bumped on logout-all |
| gdrive_token | Text | nullable (encrypted Google OAuth) |
| created_at | DateTime | |
| last_active | DateTime | |

Relationships: `files`, `folders`, `login_codes`, `refresh_sessions`

### `files`
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| user_id | Integer | FK → users.id (CASCADE) |
| folder_id | Integer | FK → folders.id (SET NULL) |
| file_name | String(512) | |
| mime_type | String(128) | |
| file_size | BigInteger | bytes |
| channel_message_id | Integer | Telegram message ID in storage channel |
| file_unique_id | String(128) | Telegram file_unique_id |
| created_at | DateTime | |

Indexes: `(user_id, folder_id)`, `(user_id, created_at)`

### `folders`
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| user_id | Integer | FK → users.id (CASCADE) |
| parent_id | Integer | FK → folders.id (CASCADE, self-ref) |
| name | String(256) | |
| created_at | DateTime | |

Self-referential adjacency list. Root folders have `parent_id = NULL`.

### `login_codes`
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| code | String(16) | UNIQUE, uppercase alphanumeric |
| telegram_id | BigInteger | nullable until claimed |
| expires_at | DateTime | TTL ~10 min |
| created_at | DateTime | |

Used for TV app pairing via `/start <code>`.

### `refresh_sessions`
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| user_id | Integer | FK → users.id (CASCADE) |
| token_hash | String(64) | UNIQUE, SHA256(refresh_token) |
| expires_at | DateTime | |
| last_used_at | DateTime | updated on each refresh |
| created_at | DateTime | |

One row per active refresh token. Rotation overwrites `token_hash`.

## Relationships Summary

```
User
├── files (one-to-many)
├── folders (one-to-many, roots only)
├── login_codes (one-to-many)
└── refresh_sessions (one-to-many)

Folder
├── parent (many-to-one, self)
├── children (one-to-many, self)
└── files (one-to-many)
```

## Migration Notes

- `refresh_sessions` added in `fix: harden auth...` commit
- `User.refresh_token_hash` column was **reverted** (transient approach) — only the session table persists
- `LoginCode.expires_at` TTL enforced in bot handler claim query