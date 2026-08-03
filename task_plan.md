# Plan: Pool-Based Client Assignment (Aruvi-backend)

## Goal
Replace the current round-robin client assignment in `streaming.py` with a pool-based system that is connection-aware, load-balanced, and flood-aware — preventing overloading slow/dead clients while maximizing throughput from healthy ones.

## Current Design (streaming.py:589-591)
```python
client = clients[worker_id % pool_size]
```
- Simple modulo — no awareness of connection state, load, or flood status
- `concurrency = max(1, sum(1 for c in clients if c.is_connected))` — counts connected but doesn't balance
- Per-client semaphore at `telegram_client_concurrency=5` is the only safeguard

## Proposed Design: ClientPool

### Core Idea
A `ClientPool` class wrapping `clients[]` with a **weighted-least-loaded** scheduler:

```
Worker → pool.acquire() → best available client
         ↓
   - connected? (filter dead)
   - active_workers / capacity
   - cooldown? (recent flood wait)
   - success_rate (exponential moving average)
```

### Components

1. **ClientPool class** — per-client state: `active_workers`, `cooldown_until`, `success_rate`
   - `acquire()` → scores & returns best client
   - `release(idx)` → decrements active count
   - `report_failure(idx, flood_wait=0)` → adjusts score, optionally sets cooldown
   - `report_success(idx)` → adjusts score up

2. **Scoring** (higher = better):
   ```
   score = 100 if connected else 0
     - active_workers × 10          (load penalty)
     - cooldown_remaining × 100     (cooldown penalty)
     - (1 - success_rate) × 50      (failure penalty)
   ```

3. **Cooldown** — after flood wait: `flood_wait × 2` (min 30s, max 300s)

## Phases

### Phase 1: ClientPool class
- [ ] Define `ClientPool` with per-client state
- [ ] Implement `acquire()` scoring
- [ ] Implement `release()`, `report_failure()`, `report_success()`
- [ ] Wire into `parallel_stream_generator()` replacing modulo

### Phase 2: Integration & edge cases
- [ ] All-disconnected fallback
- [ ] Cooldown expiry + retry
- [ ] asyncio lock for state mutations

### Phase 3: Diagnostics
- [ ] Expose pool health via status endpoint
- [ ] Log pool distribution periodically

## Decisions
| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Weighted scoring over queue | Simpler, avoids starvation, natural balance |
| 2 | Cooldown on flood only | Auth errors already handled by reconnect |
| 3 | Per-worker acquire/release | More granular than per-batch |
