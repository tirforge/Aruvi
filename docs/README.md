# Aruvi Documentation

## Quick Links

| Topic | File |
|-------|------|
| **How it works (5 min read)** | [architecture.md](architecture.md) |
| **Streaming engine** | [streaming.md](streaming.md) |
| **Auth & tokens** | [auth.md](auth.md) |
| **Database schema** | [data-model.md](data-model.md) |
| **Deploy & runbook** | [deployment.md](deployment.md) |
| **Agent instructions** | [../AGENTS.md](../AGENTS.md) |

---

## TL;DR

**Aruvi** = Your media library stored in a Telegram channel, streamed via FastAPI with a two-tier cache (RAM + disk).

- **11 bots** download chunks in parallel
- **RAM cache** (200 MB/video) = instant replay
- **Disk cache** (8 GB) = survives restarts
- **Refresh tokens rotate** = replay attacks impossible
- **Daily re-clone at 3:30 AM** = push before then or lose changes

---

## Start Here

1. **New to the project?** → [architecture.md](architecture.md)
2. **Fixing a streaming bug?** → [streaming.md](streaming.md)
3. **Auth issue?** → [auth.md](auth.md)
4. **Deploying to live?** → [deployment.md](deployment.md#start--restart---critical)
5. **Coding agent?** → [AGENTS.md](../AGENTS.md)