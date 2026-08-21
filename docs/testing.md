# Testing

## Run the Suite

```bash
cd backend
PYTHONPATH=. /home/container/python3.11/python/bin/python3.11 -m pytest tests/ -v
```

Expected output:

```
tests/test_fixes.py  18 passed in ~2s
```

Config lives in `backend/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto   # async fixtures/tests need no decorators
testpaths = tests
```

---

## What's Covered (18 tests)

### `TestAuthRotation` — refresh token rotation
| Test | Proves |
|------|--------|
| `test_refresh_token_rotation_rejects_replay` | First refresh rotates; replaying the OLD token → 401 "invalidated"; new token works; exactly **1** session row remains |

### `TestAuthRotation` — download tokens
| Test | Proves |
|------|--------|
| `test_download_token_binds_file_id` | Token minted for file 42 authorizes file 42 |
| `test_wrong_file_id_rejected` | Same token on file 43 → **403** (IDOR blocked) |
| `test_malformed_sub_returns_none` | JWT with `sub="notanint"` → `None`, no crash |

### `TestParseRangeHeader` — HTTP Range parsing (8 cases)
| Test | Input → Result |
|------|----------------|
| no header | `None` → full content (200) |
| normal | `bytes=0-99` → (0, 99) |
| open-ended | `bytes=100-` → (100, EOF) |
| suffix | `bytes=-500` → last 500 bytes |
| clamped end | end > size → clamped to size-1 |
| multipart rejected | `bytes=0-1,5-6` → single coalesced range, not multi-part |
| zero-byte + GET | size=0, no header → full 200 |
| zero-byte + Range | size=0 with header → handled without 416 crash |

### `TestPatchListenerQueue` — bot listener handling
| Test | Proves |
|------|--------|
| `test_fifo_delivery` | Two replies arrive out of order → listener gets them in arrival order, both delivered |
| `test_command_not_swallowed` | `/start` from a user with a pending listener is routed as a command, not eaten by the listener |

### `TestDiskCacheUniqueTemp`
| Test | Proves |
|------|--------|
| `test_concurrent_put_no_tear` | 8 concurrent `put()` calls → all 8 files intact, no temp-file clobbering |

### `TestGDriveRawWrite`
| Test | Proves |
|------|--------|
| `test_raw_write_creates_file` | `_raw_write` creates the file at the right path |

### `TestGrabberCollectReplies`
| Test | Proves |
|------|--------|
| `test_direct_reply_preferred` | Direct reply to request beats other candidates |

---

## How Isolation Works

Each test gets a **fresh SQLite DB** in its own tmpdir:

```
temp_db fixture:
  1. tempfile.mkdtemp()                    ← unique per test
  2. Set DATABASE_URL to sqlite+aiosqlite:///<tmpdir>/t.db
  3. importlib.reload(app.config / database / models)
  4. create_all()                          ← fresh schema
  5. yield AsyncSession
  6. dispose engine + shutil.rmtree(tmpdir)
```

This is why tests can run in any order and never see each other's rows (the old shared-DB approach hit `UNIQUE constraint failed: users.telegram_id`).

Env vars needed by app imports are set in `tests/conftest.py` **before** any `app.*` import — dummy Telegram tokens etc. No real credentials are ever touched.

---

## Adding a Test

```python
@pytest.mark.asyncio
async def test_my_feature(self, temp_db):
    from app.models import User
    user = User(telegram_id=111, username="u", auth_version=0)
    temp_db.add(user)
    await temp_db.commit()

    # call the function under test...
```

Rules of thumb:

1. **Need a DB?** Take the `temp_db` fixture (it *is* the session).
2. **Need a user?** Take `sample_user` instead.
3. **Pure function?** No fixture needed (`parse_range_header` tests).
4. **Telegram-dependent code?** Monkeypatch the client object — never hit the network.
5. Keep one behavior assertion-cluster per test; name it after the behavior.

---

## What's NOT Covered (gaps)

- Live streaming pipeline (needs real Telegram) — covered by manual diag checks instead:
  ```bash
  curl -H "Authorization: Bearer $DEBUG_PASSWORD" \
    "http://localhost:7680/api/diag/stream?msg=197&chat=-1003950847652" \
    -H "Range: bytes=0-1023" -o /dev/null -w "%{http_code} %{size_download}\n"
  # expect: 206 1024
  ```
- Frontend (no JS test runner configured yet)
- Subtitle providers (external network)

---

## CI Notes

No CI configured yet. Minimum gate before pushing:

```bash
cd backend && PYTHONPATH=. python3.11 -m pytest tests/ -q \
  && python3.11 -m compileall -q app
cd frontend && npx tsc --noEmit && npx eslint . --ext ts,tsx --max-warnings 0
```
