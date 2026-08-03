# Backend Code Review Report — Aruvi / MirrorBot

**Review Date:** 2026-07-24  
**Scope:** `mirrorbot-clean/` (primary review), `app/src/main/java/com/aruvi/tir/data/` (secondary review)  
**Reviewer:** Code Review Agent  
**Overall Assessment:** REQUEST CHANGES

---

## Summary

The mirrorbot-clean backend is a Telegram bot for mirroring files to Google Drive. It has **critical security vulnerabilities** (SQL injection, lack of input validation), **race conditions** from shared global state, **unbounded memory usage**, and **poor error handling** with bare `except:` blocks throughout. The Android networking layer has `runBlocking` on the OkHttp dispatcher thread and potential memory leaks. Both codebases need major fixes before production use.

---

## Key Findings

- **1 CRITICAL** — SQL injection in `db_handler.py`
- **2 CRITICAL** — Race conditions on global mutable state
- **3 HIGH** — Unbounded `except:` / bare except blocks masking errors
- **4 HIGH** — `runBlocking` on OkHttp dispatcher thread (Android)
- **5 HIGH** — No HTTP timeouts on outgoing requests
- **6 MEDIUM** — Resource leaks (unclosed files, threads)
- **7 MEDIUM** — Wasted 130MB download in `aria2c_init` on every startup
- **8 MEDIUM** — Duplicate code blocks across message utils
- **9 LOW** — Parsing `speed()` strings with fragile string splitting

---

## Detailed Analysis

### CRITICAL: SQL Injection in Database Handler

**File:** `mirrorbot-clean/bot/helper/ext_utils/db_handler.py` lines 25, 36, 48, 55, 66

**Issue:** All SQL queries use Python f-string formatting with unsanitized `chat_id` parameters. An attacker who can control the `chat_id` value (it comes from Telegram user IDs, which are technically controlled by Telegram, but if the DB_URI environment variable leaks or if there's a path to inject via other means, this is game over).

```python
# db_handler.py line 25
sql = 'INSERT INTO users VALUES ({});'.format(chat_id)  # SQLi!
self.cur.execute(sql)

# line 36  
sql = 'DELETE from users where uid = {};'.format(chat_id)  # SQLi!
```

**Fix:** Use parameterized queries everywhere:

```python
sql = 'INSERT INTO users VALUES (%s);'
self.cur.execute(sql, (chat_id,))
```

---

### CRITICAL: Race Conditions on Global Mutable State

**Files:**
- `mirrorbot-clean/bot/__init__.py` — `download_dict`, `status_reply_dict`, `Interval`, `AUTHORIZED_CHATS`, `SUDO_USERS`
- `mirrorbot-clean/bot/helper/ext_utils/bot_utils.py` — `setInterval` class

**Issue:** The bot uses thread-level locks (`download_dict_lock`, `status_reply_dict_lock`, etc.) but the `setInterval` class runs on a separate thread without coordinating with the main handler threads. The `Interval[0]` singleton pattern is fragile — cancel/del calls in `mirror.py:clean()` can hit `IndexError` if the interval was already cleaned up.

**Evidence:** `mirror.py` lines 87-93:
```python
def clean(self):
    try:
        Interval[0].cancel()
        del Interval[0]
        delete_all_messages()
    except IndexError:
        pass
```

The bare `except IndexError` means if any other exception occurs during cleanup, it's silently swallowed.

Additionally, `AUTHORIZED_CHATS` is a `set()` modified from multiple threads without any lock in `authorize.py`:

```python
# authorize.py line 48 (no lock)
AUTHORIZED_CHATS.add(user_id)
```

**Fix:** 
1. Replace `setInterval` with a proper scheduler (or `threading.Timer` with rescheduling)
2. Use `threading.Lock` for all writes to `AUTHORIZED_CHATS` and `SUDO_USERS`
3. Use proper exception handling — don't catch `IndexError` to mask all errors

---

### CRITICAL: Broad Bare `except:` Blocks

**Files:** Throughout the entire codebase — `mirror.py`, `gdriveTools.py`, `bot_utils.py`, `__init__.py`, `authorize.py`

**Issue:** Widespread use of bare `except:` clauses that catch **everything** including `SystemExit`, `KeyboardInterrupt`, and `GeneratorExit`. This masks real bugs and makes debugging nearly impossible.

**Examples:**

`mirrorbot-clean/bot/__init__.py` lines 171-172:
```python
except:
    pass
```

`mirrorbot-clean/bot/modules/mirror.py` line 125:
```python
try:
    shutil.rmtree(m_path)
except:
    os.remove(m_path)
```

`mirrorbot-clean/bot/helper/mirror_utils/upload_utils/gdriveTools.py` line 225:
```python
try:
    self.typee = file_metadata['mimeType']
except:
    self.typee = 'File'
```

**Fix:** Always specify the exception type. Never use bare `except:`.

---

### HIGH: `runBlocking` on OkHttp Dispatcher Thread

**File:** `app/src/main/java/com/aruvi/tir/data/api/AuthInterceptor.kt` line 30

**Issue:** `runBlocking` is called on the OkHttp dispatcher thread. OkHttp has a limited dispatcher thread pool. If the auth repository makes a network call to refresh the token, this blocks the entire OkHttp dispatcher, causing all concurrent requests to queue up. This can cause **deadlock** if the token refresh itself needs OkHttp to make a request.

```kotlin
// line 30 — blocks OkHttp's dispatcher thread!
val accessToken = runBlocking { authRepository.get().getAccessToken() }
```

**Fix:** Use OkHttp's `addInterceptor` with `async` variants, or better, make the interceptor use `callback`-based patterns. At minimum, offload to a background dispatcher:

```kotlin
val accessToken = runBlocking(Dispatchers.IO) { 
    authRepository.get().getAccessToken() 
}
```

But even that is not ideal. The proper fix is to use an `Authenticator` instead of an interceptor for token refresh:

```kotlin
class AuthAuthenticator @Inject constructor(
    private val authRepository: dagger.Lazy<AuthRepository>
) : Authenticator {
    override fun authenticate(route: Route?, response: Response): Request? {
        val newToken = runBlocking(Dispatchers.IO) {
            authRepository.get().refreshAccessToken()
        } ?: return null
        return response.request.newBuilder()
            .header("Authorization", "Bearer $newToken")
            .build()
    }
}
```

---

### HIGH: No HTTP Timeouts on Outgoing Requests

**Files:** 
- `mirrorbot-clean/bot/helper/mirror_utils/download_utils/direct_link_generator.py` — all `requests.get/post` calls
- `mirrorbot-clean/bot/helper/mirror_utils/upload_utils/gdriveTools.py` — Google API calls
- `mirrorbot-clean/bot/__init__.py` — `requests.get(CONFIG_FILE_URL)`
- `mirrorbot-clean/bot/modules/mirror.py` — shortener API calls

**Issue:** Outgoing HTTP requests have no timeout set. If a remote server hangs, the bot thread blocks indefinitely. This includes the shortener API calls made during upload completion.

**Example** (`mirror.py` lines 281-283):
```python
surl = requests.get(
    f"https://{SHORTENER}/api?api={SHORTENER_API}&url={link}&format=text"
).text  # No timeout — could hang forever
```

**Fix:** Add timeouts to all `requests` calls:
```python
surl = requests.get(..., timeout=30).text
```

---

### HIGH: Unhandled Exception in Link Parsing

**File:** `mirrorbot-clean/bot/modules/mirror.py` lines 401-408

**Issue:** The `_mirror` function parses `message_args[1]` and if `link.startswith("|")` sets it to empty, but the structure is fragile. If `message_args[1]` is None or an unexpected type, the `.startswith()` call crashes.

```python
try:
    link = message_args[1]
    print(link)  # Debug print leaks to stdout in production
    if link.startswith("|") or link.startswith("pswd: "):
```

Also line 403 — `print(link)` is a debug statement that should be `LOGGER.debug()`.

---

### HIGH: Memory Leak — Thread References in Global Dicts

**Files:** `mirrorbot-clean/bot/__init__.py`, `mirrorbot-clean/bot/helper/telegram_helper/message_utils.py`

**Issue:** `download_dict` and `status_reply_dict` are global dictionaries that accumulate entries over the bot's lifetime. While entries are removed on completion, if a task crashes without calling cleanup, the dict entry leaks.

`mirror.py` `onUploadError` line 360:
```python
del download_dict[self.message.message_id]  
# Uses wrong key! Should be self.uid, not self.message.message_id
```

This is a **bug** — `download_dict` is keyed by `listener.uid` (= `message.message_id`), but this line uses `self.message.message_id` which might differ in some flows.

---

### HIGH: Wasted 130MB Download on Every Startup

**File:** `mirrorbot-clean/bot/__init__.py` lines 125-141

**Issue:** `aria2c_init` downloads a **130MB Ubuntu ISO torrent file** on every startup as a "health check" for aria2c, then removes it after 30 seconds. This wastes bandwidth, disk I/O, and delays startup by 30+ seconds.

```python
link = "https://releases.ubuntu.com/21.10/ubuntu-21.10-desktop-amd64.iso.torrent"
aria2.add_uris([link], {'dir': path})
time.sleep(3)
downloads = aria2.get_downloads()
time.sleep(30)  # 30 second delay!
for download in downloads:
    aria2.remove([download], force=True, files=True)
```

**Fix:** Use a simple aria2c `getVersion()` API call instead:
```python
aria2.client.get_version()  # This confirms aria2c is running
```

---

### HIGH: Duplicate Code — Speed Computation in Three Places

**Files:**
- `mirrorbot-clean/bot/helper/telegram_helper/message_utils.py` — `update_all_messages()` lines 108-125
- `mirrorbot-clean/bot/helper/telegram_helper/message_utils.py` — `sendStatusMessage()` lines 145-162
- `mirrorbot-clean/bot/helper/ext_utils/bot_utils.py` — `get_readable_message()` lines 124-154

**Issue:** The download speed computation (parsing `speedy` strings like "1.2M" to bytes) is duplicated identically in three places. If the format string ever changes, all three must be updated in sync.

**Fix:** Extract to a shared helper function:
```python
def compute_speed_stats():
    dlspeed_bytes = 0
    uldl_bytes = 0
    for download in list(download_dict.values()):
        speedy = download.speed()
        if download.status() == MirrorStatus.STATUS_DOWNLOADING:
            if 'K' in speedy:
                dlspeed_bytes += float(speedy.split('K')[0]) * 1024
            elif 'M' in speedy:
                dlspeed_bytes += float(speedy.split('M')[0]) * 1048576
        ...
    return dlspeed_bytes, uldl_bytes
```

---

### MEDIUM: Fragile String Parsing for Transfer Speeds

**Files:** `message_utils.py` lines 114-122 and 151-159

**Issue:** Speed strings are parsed by checking if `'K'` or `'M'` is in the string, then splitting on that character. This breaks if:
- The speed is in GB/s (unlikely but possible)
- The string contains the letter 'K' or 'M' in the unit suffix naturally
- The format changes upstream

```python
if 'K' in speedy:
    dlspeed_bytes += float(speedy.split('K')[0]) * 1024
elif 'M' in speedy:
    dlspeed_bytes += float(speedy.split('M')[0]) * 1048576
```

**Fix:** Use a regex or a proper unit parser:
```python
import re
match = re.match(r'([\d.]+)\s*([KMGT]?)(?:B)?/s', speedy)
if match:
    value = float(match.group(1))
    unit = match.group(2)
    multipliers = {'': 1, 'K': 1024, 'M': 1048576, 'G': 1073741824}
    dlspeed_bytes += value * multipliers.get(unit, 1)
```

---

### MEDIUM: Thread Explosion — Every Command Spawns Threads

**File:** `mirrorbot-clean/bot/__main__.py` — all handlers use `run_async=True`

**Issue:** Every command handler runs in a new thread via `run_async=True`. There is no thread pool or rate limiting. If a user spams 100 commands, 100 threads are created. Python's GIL means these don't run in true parallel for CPU work, but the thread overhead is significant and can exhaust system resources.

Additionally, `mirror.py` `_mirror` function spawns even more threads:
```python
threading.Thread(target=_mirror, args=(...)).start()  # line 466
threading.Thread(target=auto_delete_message, args=(...)).start()  # line 396
```

**Fix:** Use a `ThreadPoolExecutor` with a bounded max size (e.g., 10-20 workers) instead of unbounded `threading.Thread.start()`.

---

### MEDIUM: No Retry Logic for Transient Failures

**Files:** `mirrorbot-clean/bot/helper/mirror_utils/download_utils/telegram_downloader.py` lines 76-88

**Issue:** The Telegram download has no retry logic. If the download fails mid-way due to a transient network issue, the entire download is lost and the user gets an error. Google Drive operations in `gdriveTools.py` use `tenacity.retry`, but Telegram downloads don't.

---

### MEDIUM: Unclosed File Handles in Several Places

**Files:**
- `mirrorbot-clean/bot/helper/mirror_utils/download_utils/direct_link_generator.py` line 484 — `open(file_name, "wb").write(resp.content)` — file opened but never properly closed
- `mirrorbot-clean/bot/__init__.py` line 48-50 — `f.close()` is redundant after `with` block
- `mirrorbot-clean/bot/__main__.py` line 84-86 — file handle saved via `with` but used after `with` block ends

---

### MEDIUM: `gdtot_link` Variable Reference Error

**File:** `mirrorbot-clean/bot/modules/mirror.py` lines 493, 533

**Issue:** `gdtot_link` is assigned in a `try` block at line 493 but used later at line 533. If the `try` block raises a `DirectDownloadLinkException` that is not "ERROR:" or "Youtube", the function returns. But if the function **doesn't** return (e.g., link is not a GDTOT link), `gdtot_link` may be `True` from a previous line or undefined.

This is actually correct in flow but fragile — `gdtot_link` is computed at line 493 but could be stale.

---

### MEDIUM: Logging of Sensitive Data

**File:** `mirrorbot-clean/bot/modules/mirror.py` line 431

```python
LOGGER.info(link)  # Logs the full download link including any embedded credentials
```

If links contain credentials (e.g., `http://user:pass@example.com/file`), these get logged in plain text. For the file transfer scenario this is low risk, but it's a bad practice.

---

### MEDIUM: Resource Leak in `pyrogramEngine.py`

**File:** `mirrorbot-clean/bot/helper/mirror_utils/upload_utils/pyrogramEngine.py` lines 112-113

```python
if self.thumb is None and thumb is not None and os.path.lexists(thumb):
    os.remove(thumb)
```

The thumbnail is only cleaned up in one branch but not in others. The `Thumbnails/` directory can accumulate stale files.

---

### LOW: Debug Print Leak

**File:** `mirrorbot-clean/bot/modules/mirror.py` line 403

```python
print(link)
```

This should be `LOGGER.debug(link)` or removed.

---

### LOW: Insecure Temporary File

**File:** `mirrorbot-clean/bot/modules/mirror.py` line 484

```python
open(file_name, "wb").write(resp.content)  # In current directory, no prefix, predictable name
```

The torrent file is saved with a predictable name (timestamp-based) in the current working directory. A race condition could allow a local attacker to write a different file.

---

### LOW: Hardcoded Button Limits

**File:** `mirrorbot-clean/bot/modules/mirror.py` `onUploadComplete`

**Issue:** Three configurable buttons (`BUTTON_THREE`, `BUTTON_FOUR`, `BUTTON_FIVE`) but buttons ONE and TWO are hardcoded as Drive Link and Index Link. There's no way to reorder or disable the hardcoded buttons.

---

## Android App-Specific Issues

### MEDIUM: `serviceScope` Memory Leak

**File:** `app/src/main/java/com/aruvi/tir/service/DownloadService.kt` line 33

```kotlin
private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
```

If the service is destroyed and recreated (e.g., due to memory pressure), a new scope is created but the old one's cancellation is only on `onDestroy`. If `onCreate` is called twice without `onDestroy` in between, the old scope leaks.

**Fix:** Make it a lazy property or ensure cancellation in `onCreate`:
```kotlin
private var serviceScope: CoroutineScope? = null

override fun onCreate() {
    super.onCreate()
    serviceScope?.cancel()
    serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
}
```

### MEDIUM: No Response Body Null Checks

**File:** `app/src/main/java/com/aruvi/tir/data/api/TelePlayApi.kt`

**Issue:** All API calls return `Response<T>` but none of the callers in the repository layer check `response.body()` for null before accessing it. Retrofit returns `null` for body on error responses or if the response can't be deserialized.

### LOW: Missing Network Error Handling

**File:** `app/src/main/java/com/aruvi/tir/data/api/TelePlayApi.kt`

**Issue:** No `@Headers("Connection: close")` or connection pooling configuration visible. Failed requests could leak connections.

---

## Performance Issues Summary

| Issue | Severity | Impact |
|-------|----------|--------|
| No connection pooling for API calls | HIGH | Increased latency |
| Wasted 130MB download on startup | HIGH | Startup delayed by 30s |
| Thread explosion with 10+ handler threads | MEDIUM | Resource exhaustion |
| Duplicate speed computation 3x | MEDIUM | Unnecessary CPU cycles |
| Global lock contention on download_dict | MEDIUM | Slowed concurrent operations |
| No timeout on external HTTP calls | HIGH | Bot hangs if remote server is slow |
| Parsing speed strings with fragile splitting | LOW | Wrong values on unexpected format |

---

## Top 5 Things to Fix Before Deployment

1. **SQL Injection** in `db_handler.py` — use parameterized queries immediately
2. **`runBlocking` on OkHttp dispatcher** in `AuthInterceptor.kt` — use `Authenticator` pattern
3. **Add HTTP timeouts** to all `requests.get/post` calls across the entire codebase
4. **Replace bare `except:` blocks** with specific exception types
5. **Fix aria2c_init** — remove the 130MB Ubuntu ISO download, use a lightweight version check instead

---

## Files Reviewed

### mirrorbot-clean (Python Backend — 27 files)
- `bot/__init__.py` — Global config, startup, state
- `bot/__main__.py` — Entry point, handlers
- `bot/modules/mirror.py` — Mirror command (627 lines)
- `bot/modules/clone.py` — Google Drive clone
- `bot/modules/list.py` — Search Drive
- `bot/modules/cancel_mirror.py` — Cancel downloads
- `bot/modules/delete.py` — Delete from Drive
- `bot/modules/authorize.py` — User auth management
- `bot/modules/watch.py` — YouTube-dl watch
- `bot/modules/speedtest.py` — Speed test
- `bot/modules/leech_settings.py` — Leech settings
- `bot/helper/ext_utils/bot_utils.py` — Utilities
- `bot/helper/ext_utils/fs_utils.py` — Filesystem operations
- `bot/helper/ext_utils/db_handler.py` — Database handler (SQLi!)
- `bot/helper/ext_utils/exceptions.py` — Exception classes
- `bot/helper/telegram_helper/message_utils.py` — Message helpers
- `bot/helper/telegram_helper/filters.py` — Auth filters
- `bot/helper/mirror_utils/upload_utils/gdriveTools.py` — GDrive upload
- `bot/helper/mirror_utils/upload_utils/pyrogramEngine.py` — Telegram upload
- `bot/helper/mirror_utils/download_utils/telegram_downloader.py` — TG download
- `bot/helper/mirror_utils/download_utils/direct_link_generator.py` — Link gen
- `bot/helper/mirror_utils/status_utils/listeners.py` — Listeners
- `requirements.txt`, `Dockerfile`

### app/src (Android/Kotlin — 3 files)
- `data/api/TelePlayApi.kt` — Retrofit API interface
- `data/api/AuthInterceptor.kt` — JWT interceptor
- `service/DownloadService.kt` — Download foreground service
