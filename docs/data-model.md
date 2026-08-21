# Data Model — Simple Explanation

## Core Tables (5 tables, that's it)

```
┌─────────────┐       ┌─────────────┐       ┌──────────────────┐
│   users     │──────▶│   files     │◀──────│    folders       │
│             │       │             │       │                  │
│ • id (PK)   │       │ • id (PK)   │       │ • id (PK)        │
│ • telegram_id│      │ • user_id   │       │ • user_id        │
│ • username  │       │ • folder_id │       │ • parent_id (FK) │
│ • auth_ver  │       │ • file_name │       │ • name           │
│ • gdrive_tok│       │ • ch_msg_id │       └──────────────────┘
└─────────────┘       └─────────────┘
        │                     │
        ▼                     ▼
┌──────────────────┐  ┌──────────────────┐
│  login_codes     │  │ refresh_sessions │
│                  │  │                  │
│ • code (PK)      │  │ • id (PK)        │
│ • telegram_id    │  │ • user_id (FK)   │
│ • expires_at     │  │ • token_hash     │
└──────────────────┘  │ • expires_at     │
                      └──────────────────┘
```

---

## Table Details

### `users` — One row per person
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | Primary key |
| `telegram_id` | BigInteger | **Unique**, from Telegram |
| `username` | String(64) | Nullable |
| `first_name` / `last_name` | String(64) | |
| `is_admin` | Boolean | Default false |
| `auth_version` | Integer | **Increments on logout-all** |
| `gdrive_token` | Text | Encrypted Google OAuth (nullable) |
| `created_at` / `last_active` | DateTime | |

### `files` — One row per uploaded file
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `user_id` | Integer | FK → users (CASCADE delete) |
| `folder_id` | Integer | FK → folders (SET NULL) |
| `file_name` | String(512) | Original filename |
| `mime_type` | String(128) | e.g. `video/mp4` |
| `file_size` | BigInteger | Bytes |
| `channel_message_id` | Integer | **Telegram message ID in storage channel** |
| `file_unique_id` | String(128) | Telegram's file_unique_id |
| `created_at` | DateTime | |

### `folders` — Tree structure (adjacency list)
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `user_id` | Integer | FK → users (CASCADE) |
| `parent_id` | Integer | FK → folders.id (self-ref, CASCADE) |
| `name` | String(256) | |
| `created_at` | DateTime | |

- Root folder = `parent_id IS NULL`
- Unlimited nesting

### `login_codes` — TV pairing codes
| Column | Type | Notes |
|--------|------|-------|
| `code` | String(16) | **PK**, uppercase alphanumeric |
| `telegram_id` | BigInteger | Null until claimed |
| `expires_at` | DateTime | ~10 min TTL |
| `created_at` | DateTime | |

### `refresh_sessions` — Rotation tracking
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `user_id` | Integer | FK → users (CASCADE) |
| `token_hash` | Char(64) | **Unique**, SHA256(refresh_token) |
| `expires_at` | DateTime | |
| `last_used_at` | DateTime | Updated each refresh |
| `created_at` | DateTime | |

---

## Relationships in Plain English

- **User** → has many **Files** (delete user = delete their files)
- **User** → has many **Folders** (roots only; children via `parent_id`)
- **Folder** → has many **Files** (move file = change `folder_id`)
- **User** → has many **LoginCodes** (one per TV pairing attempt)
- **User** → has many **RefreshSessions** (one per active device)

---

## Key Indexes (for fast queries)

```sql
-- Files by user + folder (browse)
CREATE INDEX ON files (user_id, folder_id);

-- Files by user + time (recent)
CREATE INDEX ON files (user_id, created_at DESC);

-- Folders by user + parent (tree)
CREATE INDEX ON folders (user_id, parent_id);
```

---

## Migration Note

`refresh_sessions` added in commit `2b9dc80`. Earlier approach used a `refresh_token_hash` column on `users` — **reverted** because:
- Single column = only one device at a time
- Session table = multiple devices, proper rotation, audit trail