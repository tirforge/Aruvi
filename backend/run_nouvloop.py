"""Bootstrap for uvicorn with capture_signals disabled (Python 3.13 workaround)."""
import asyncio
import contextlib
import gc
import logging
import os
import time
import ctypes
import uvicorn
import uvicorn.server as uvs

_libc = ctypes.CDLL("libc.so.6")
_log = logging.getLogger("run")

uvs.Server.capture_signals = lambda self: contextlib.nullcontext()

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app.main import app
from app.streaming import _cache_manager, _forward_streams, _cache_finished_at, CACHE_TTL
from app.telegram import _prune_msg_cache

async def _periodic_housekeeping():
    """Every 60s: release free memory, evict stale stream caches, prune msg cache."""
    while True:
        await asyncio.sleep(60)
        gc.collect()
        _libc.malloc_trim(0)
        try:
            now = time.monotonic()
            # Active streams — never evict
            active = {(info["chat_id"], mid) for mid, info in list(_forward_streams.items())}
            # Recently finished streams — keep for CACHE_TTL (10min) for resume after network drop
            for key, finished_at in list(_cache_finished_at.items()):
                if now - finished_at < CACHE_TTL:
                    active.add(key)
                else:
                    _cache_finished_at.pop(key, None)
            freed = _cache_manager.clear_all(exclude_keys=active)
            if freed:
                _log.info("Housekeeping: freed %.1f MB from stale caches", freed / 1024 / 1024)
        except Exception as e:
            _log.warning("Housekeeping cache eviction error: %s", e)
        try:
            _prune_msg_cache()
        except Exception as e:
            _log.warning("Housekeeping msg cache prune error: %s", e)

config = uvicorn.Config(app, host="0.0.0.0", port=7680, log_level="info", access_log=False)
server = uvs.Server(config)

async def run():
    asyncio.create_task(_periodic_housekeeping())
    await server.serve()

try:
    import uvloop  # disabled
    # asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass
asyncio.run(run())
