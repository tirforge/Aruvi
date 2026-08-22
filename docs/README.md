# Aruvi Documentation

## Quick Links

| Topic | File |
|-------|------|
| **How it works (5 min read)** | [architecture.md](architecture.md) |
| **API endpoint reference** | [api.md](api.md) |
| **Streaming engine** | [streaming.md](streaming.md) |
| **Auth & tokens** | [auth.md](auth.md) |
| **Database schema** | [data-model.md](data-model.md) |
| **Testing** | [testing.md](testing.md) |
| **Deploy & runbook** | [deployment.md](deployment.md) |
| **Agent instructions** | [../AGENTS.md](../AGENTS.md) |

---

## TL;DR

**Aruvi** = Your media library stored in a Telegram channel, streamed via FastAPI with a two-tier cache (RAM + disk).

- **11 bots** download chunks in parallel
- **RAM cache** (300 MB/video) = instant replay
- **Disk cache** (8 GB) = survives restarts
- **Prefetcher** keeps ~192 MB ahead of the playhead
- **Refresh tokens rotate** = replay attacks impossible
- **Daily re-clone at 3:30 AM** = push before then or lose changes

---

## Start Here

1. **New to the project?** → [architecture.md](architecture.md)
2. **Building a client / calling the API?** → [api.md](api.md)
3. **Fixing a streaming bug?** → [streaming.md](streaming.md)
4. **Auth issue?** → [auth.md](auth.md)
5. **Writing tests?** → [testing.md](testing.md)
6. **Deploying to live?** → [deployment.md](deployment.md#start--restart---two-commands-critical)
7. **Coding agent?** → [AGENTS.md](../AGENTS.md)

---

## Live Preview

Web app: **http://localhost:7680** (your own deployment)

---

## Doc Conventions

- Every doc leads with a plain-English explanation, then details.
- Config tables list **code defaults**, not just what's in `.env`.
- Diagrams are ASCII so they render anywhere (terminal, GitHub, editors).