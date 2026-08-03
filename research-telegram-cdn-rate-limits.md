# Telegram CDN & Rate Limit Research

## What Is the CDN Layer?

Telegram uses CDN (Content Delivery Network) DCs to offload file downloads for **public channels with >100,000 subscribers**. When a file from such a channel becomes popular in a region, the main DC redirects clients to a nearby CDN DC via `upload.fileCdnRedirect`.

CDN DCs are fundamentally different from main DCs:

| Property | Main DC | CDN DC |
|----------|---------|--------|
| Methods supported | All RPC methods | Only 3: `upload.getCdnFile`, `initConnection`, `invokeWithLayer` |
| Flood limits | Yes (`FLOOD_WAIT`, `FLOOD_PREMIUM_WAIT`) | **None** |
| File storage | Permanent | In-memory only (LRU eviction) |
| Trust | Trusted | "Enemy territory" - no decryption keys |
| Auth key | Stable | "May be deleted at any moment" (-404) |
| Error types | FILE_REFERENCE_EXPIRED, FLOOD_WAIT, etc. | Only: FILE_TOKEN_INVALID, cdnFileReuploadNeeded, -404 |

---

## Key Finding: CDN Has NO Flood Limits

The official `upload.getCdnFile` documentation lists only 3 possible errors:

- **FILE_TOKEN_INVALID** → "The CDN DC did not accept the file_token (e.g., the token has expired). Continue downloading the file from the master DC using upload.getFile."
- **cdnFileReuploadNeeded** → reupload via `upload.reuploadCdnFile` on master DC
- **-404** → auth_key deleted, generate new key

**No `FLOOD_WAIT`. No `FLOOD_PREMIUM_WAIT`. No rate limits.**

On the **master DC** path (`upload.getFile`), these ARE present:

- `FLOOD_WAIT_X` — standard rate limit
- `FLOOD_PREMIUM_WAIT_X` — "download speed is limited because the current account does not have a Premium subscription... This error can only be received when the user has uploaded tens of gigabytes or more."

---

## Parallel Download Limits (Official Config)

From `help.getAppConfig` default values:

| Config Key | Value | Meaning |
|-----------|-------|---------|
| `small_queue_max_active_operations_count` | **5** | Max parallel downloads <20MB from same DC |
| `large_queue_max_active_operations_count` | **2** | Max parallel downloads >20MB from same DC |
| `upload_premium_speedup_download` | **10** | Premium download is 10x faster (on master DC only) |

These are described as **"soft limits"** — recommendations, not hard caps.

---

## Telegram's Own Recommendation

From the official files docs:

> *"It is recommended that large queries (upload.getFile, upload.saveFilePart, upload.getWebFile) be handled through **one or more separate sessions** and separate connections, in which no methods other than these should be executed. This way, data transfer will cause less interference with getting updates and other method calls."*

And for CDN specifically:

> *"When downloading multiple files in parallel from the same DC, clients should limit the parallelism to download at most `small_queue_max_active_operations_count` / `large_queue_max_active_operations_count` files in parallel when downloading files smaller/bigger than 20MB."*

Our shared CDN session approach aligns with this — one session, one connection, no interference.

---

## So What Actually Caused Our "Death Spiral"?

**It was NOT a Telegram API rate limit.** It was **transport-level congestion:**

1. 14 workers each opened a separate TCP connection to the same CDN node
2. Each connection competed for the same source IP's bandwidth bucket
3. When one chunk was late, watchdog spawned 13 more connections → 27 connections fighting
4. More connections → more TCP head-of-line blocking → more timeouts → more watchdog spawns

CDN nodes have per-IP rate limits at the **transport layer** (packet shaping, TCP connection limits), not at the **API layer** (FLOOD_WAIT). These are enforced by the CDN infrastructure, not by Telegram's MTProto.

---

## Self-Hosted Bot API — Why It Doesn't Help

| Aspect | Self-Hosted Bot API | Our MTProto CDN Path |
|--------|--------------------|---------------------|
| File access | Full file only (no offset/limit) | Random access via offset/limit |
| 1GB file stream | Must download entire 1GB to disk first | Stream 1MB chunks on-demand |
| Rate limits | Per-bot-token (same as cloud) **not bypassed** | CDN has no rate limits |
| Bandwidth cap | Same per-bot-token cap | CDN bandwidth is separate |
| Confirmed by Telegram | Issue #755: "No" to rate limit bypass | N/A |

The self-hosted Bot API helps only for:
- 50MB → 2GB file uploads (not relevant for streaming)
- Higher message throughput (not relevant for streaming)

It does **nothing** for our streaming contention.

---

## CDN vs Non-CDN: Which Is Better?

| Scenario | CDN | Non-CDN (master DC) |
|----------|-----|--------------------|
| Flood limits | **None** | FLOOD_PREMIUM_WAIT after tens of GB |
| Parallel file limit | Unlimited | 2 files >20MB / 5 files <20MB |
| Bandwidth | Edge node (close to user) | Central DC |
| Connection stability | Auth key may drop (-404) | Stable |
| File availability | In-memory LRU (may need reupload) | Always available |
| Fallback | FILE_TOKEN_INVALID → master DC | No fallback needed |

**CDN is strictly better** for streaming — no flood limits, higher parallelism, lower latency. The only downsides are auth key instability and FILE_TOKEN_INVALID (both handled by falling back to master DC).

---

## What Can Actually Fix It Further?

Based on official docs, here's the complete toolbox:

### What We Already Did ✅
1. **Shared CDN session** — 1 TCP connection instead of 14 (eliminates transport congestion)
2. **Killed death spiral** — no watchdog spawning extra connections
3. **CDN fallback preserved** — FILE_TOKEN_INVALID → `stream_media`

### What Telegram Recommends
4. **Dedicated media session** — "separate sessions and connections" for `upload.getFile` only (we already do this - CDN path uses raw session, not main client)
5. **Respect `small_queue_max_active_operations_count`** — max 5 parallel for <20MB, max 2 for >20MB

### Premium Subscription
6. **Premium removes FLOOD_PREMIUM_WAIT** — `upload_premium_speedup_download: 10` means 10x faster downloads on master DC. This ONLY matters for the non-CDN fallback path, since CDN has no flood limits.

### Architecture Changes (If Transport Congestion Persists)
7. **Per-bot CDN sessions** — if one CDN connection hits IP-level throttling, use different bot's session (different IP for SOCKS5). We already have 14 bots.
8. **Per-stream sessions** — one CDN session per unique stream, not one global CDN session. Avoids head-of-line blocking where a stuck chunk on one stream blocks all others.
9. **CDN node rotation** — if FILE_TOKEN_INVALID or -404, reconnect to a different CDN node (same DC, different IP from `help.getConfig`)

---

## Summary

**No, removing CDN would NOT solve the issue — it would make it worse.**

- CDN has **zero** flood limits
- Master DC has FLOOD_PREMIUM_WAIT after tens of GB
- Our "death spiral" was transport congestion (14 TCP connections), not API rate limits
- Our shared CDN session fix addresses the root cause correctly
- Self-hosted Bot API does nothing for streaming (no offset/limit support)

**Sources:**
1. https://core.telegram.org/api/files — Uploading/downloading files, parallelism limits
2. https://core.telegram.org/method/upload.getFile — Possible errors (FLOOD_PREMIUM_WAIT)
3. https://core.telegram.org/method/upload.getCdnFile — CDN-only errors (no flood limits)
4. https://blogfork.telegram.org/cdn — CDN architecture, limitations, error handling
5. https://core.telegram.org/api/config — Client config: small_queue_max_active_operations_count (5), large_queue_max_active_operations_count (2), upload_premium_speedup_download (10)
6. https://github.com/tdlib/telegram-bot-api/issues/755 — Telegram dev confirms getFile rate limits are per-bot-token, self-hosting doesn't change them
7. https://github.com/tdlib/telegram-bot-api/issues/141 — offset/limit for getFile rejected (not implementable)
