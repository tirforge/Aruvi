# Aruvi Documentation Index

## Architecture
- [architecture.md](architecture.md) — System context, component diagram, data flow
- [streaming.md](streaming.md) — Two-tier cache, prefetcher, worker pool, circuit breakers
- [auth.md](auth.md) — JWT access/refresh rotation, login codes, download tokens, logout-all
- [data-model.md](data-model.md) — SQLAlchemy tables, relationships, migrations
- [deployment.md](deployment.md) — Runbook, restart procedure, health checks, scaling knobs

## Quick Links

| Topic | File |
|-------|------|
| How streaming works | [streaming.md](streaming.md#two-tier-cache) |
| Token rotation & replay protection | [auth.md](auth.md#rotation-flow) |
| Database schema | [data-model.md](data-model.md#core-tables) |
| Restarting the live service | [deployment.md](deployment.md#start--restart-critical) |
| Environment variables | [deployment.md](deployment.md#required-env-variables) |
| Log analysis | [deployment.md](deployment.md#log-analysis) |

## Key Invariants

1. **Disk is authoritative** — RAM hot layer evicts freely; disk persists 30 min after last activity
2. **Refresh tokens rotate** — replaying old token = 401; server stores only SHA256 hash
3. **Download tokens bind to file_id** — prevents cross-user access (IDOR fix)
4. **Media sessions serialize** — single `ImportBotAuthorization` at a time via global lock
5. **Daily re-clone wipes state** — push fixes before 3:30 AM IST or they're lost