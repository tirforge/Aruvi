"""
FastAPI main application with Telegram MTProto client lifecycle.
"""
import asyncio
import ctypes
import gc
import logging
import os
from contextlib import asynccontextmanager

_libc = ctypes.CDLL("libc.so.6")
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db
from .disk_cache import _disk_cache
from .rate_limit import limiter
from .telegram import start_telegram_client, stop_telegram_client
from .status import get_status, attach_ring_handler, clear_logs, maybe_oom_clear
from .streaming import _evict_idle_ram_caches
from .utils import bearer_token_matches
from .gzip_middleware import CompressibleGZipMiddleware

from .routers import files_router, folders_router, streaming_router, auth_router, tv_router, admin_router, gdrive_router, legal_router, diagnostic_router, grab_router, subtitles_router, setup_router #JT

# Import bot to register handlers
from . import bot  # noqa

logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pyrogram.dispatcher").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - start/stop Telegram client and init DB."""
    logger.info("Starting TelePlay Backend...")
    gc.collect(2)
    gc.freeze()
    gc.set_threshold(50000, gc.get_threshold()[1], gc.get_threshold()[2])
    await init_db()
    logger.info("Database initialized")
    attach_ring_handler()
    startup_task = await start_telegram_client()
    logger.info("Telegram client started")

    # Start background tasks
    cleanup_task = asyncio.create_task(_cleanup_expired_codes())
    oom_task = asyncio.create_task(_oom_guard_loop())
    disk_sweep_task = asyncio.create_task(_disk_cache_sweep_loop())
    
    yield
    
    oom_task.cancel()
    cleanup_task.cancel()
    startup_task.cancel()
    disk_sweep_task.cancel()
    try:
        await oom_task
        await cleanup_task
        await startup_task
        await disk_sweep_task
    except asyncio.CancelledError:
        pass
    
    logger.info("Shutting down...")
    await stop_telegram_client()
    logger.info("Telegram client stopped")


async def _cleanup_expired_codes():
    """Periodically delete expired login codes."""
    from .database import async_session
    from .models import LoginCode
    from sqlalchemy import delete
    while True:
        try:
            await asyncio.sleep(300)  # every 5 minutes
            # Naive-UTC cutoff matching the app's timestamp convention
            # (models._utcnow) — func.now() on PostgreSQL returns a
            # timestamptz that skews the comparison unless the session
            # timezone is UTC.
            from datetime import datetime, timezone
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
            async with async_session() as db:
                await db.execute(
                    delete(LoginCode).where(LoginCode.expires_at < cutoff)
                )
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


async def _oom_guard_loop():
    """Check memory every 15s and clear caches if above 65%."""
    def _gc_and_trim():
        gc.collect()
        _libc.malloc_trim(0)

    while True:
        try:
            await asyncio.sleep(15)
            maybe_oom_clear()
            # Full collection on a large heap stalls the loop for tens of ms —
            # run it (and the trim) off the event loop.
            await asyncio.to_thread(_gc_and_trim)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


async def _disk_cache_sweep_loop():
    """Periodically enforce disk cache TTL/size cap and RAM cache TTL retention."""
    while True:
        try:
            await asyncio.sleep(300)
            freed = await asyncio.to_thread(_disk_cache.sweep)
            if freed:
                logger.info("Disk cache sweep freed %.1f MB", freed / 1024 / 1024)
            _evict_idle_ram_caches()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


app = FastAPI(
    title="TelePlay API",
    description="Stream files from Telegram to Android TV and Web",
    version="1.0.0",
    lifespan=lifespan,
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware - Properly configured for production
# List allowed origins explicitly instead of using "*"
allowed_origins = [
    settings.web_base_url,
    "https://REDACTED_DOMAIN",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=".*",  # Cast devices (Default/Styled) fetch media/tracks from varied origins (https://www.gstatic.com, chrome-extension://) – must be CORS-allowed for TextTrack MediaTracks (see /cast/docs/android_sender/media_tracks CORS note). Regex allows any origin while keeping allow_credentials for web dashboard.
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Range", "Accept-Encoding"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Type"],
)


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware that injects security headers.

    Deliberately NOT a BaseHTTPMiddleware: on an upstream exception after the
    response body has started (e.g. a stream aborting mid-transfer),
    BaseHTTPMiddleware re-sends a final empty body, which makes uvicorn raise
    "Response content shorter than Content-Length". A plain ASGI middleware
    lets the exception propagate straight to uvicorn, which just closes the
    connection cleanly.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"SAMEORIGIN"),
                    (b"x-xss-protection", b"1; mode=block"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                ]
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(CompressibleGZipMiddleware, minimum_size=1024)
app.add_middleware(SecurityHeadersMiddleware)



# Include routers
app.include_router(auth_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(folders_router, prefix="/api")
app.include_router(streaming_router, prefix="/api")
app.include_router(tv_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(gdrive_router, prefix="/api")
app.include_router(legal_router)
app.include_router(diagnostic_router, prefix="/api") #WH
app.include_router(grab_router, prefix="/api") #YQ
app.include_router(subtitles_router, prefix="/api")
app.include_router(setup_router, prefix="/api")  # one-shot session generator




@app.head("/health", include_in_schema=False)
async def health_head():
    """HEAD handler for load balancer probes."""
    return ""


@app.get("/health")
async def health():
    """Health check with client connection status."""
    from .telegram import tg_client
    return {
        "status": "healthy",
        "client_connected": tg_client.is_connected if tg_client else False,
    }



@app.get("/diag")
async def diagnostic(request: Request):
    """Diagnostic endpoint (logs, client status, env info)."""
    auth = request.headers.get("Authorization", "")
    if not bearer_token_matches(auth, settings.debug_password):
        raise HTTPException(status_code=401, detail="Invalid debug token")
    from .telegram import tg_client, clients, get_diag_logs
    return {
        "client_connected": tg_client.is_connected if tg_client else False,
        "num_clients": len(clients),
        "logs": get_diag_logs(),
    }


@app.get("/api/diag/bot-test")
async def diag_bot_test(request: Request):
    auth = request.headers.get("Authorization", "")
    if not bearer_token_matches(auth, settings.debug_password):
        raise HTTPException(status_code=401, detail="Invalid debug token")
    from .telegram import tg_client, clients
    from pyrogram import handlers
    import inspect
    result = {
        "client_connected": tg_client.is_connected if tg_client else False,
        "client_initialized": tg_client.is_initialized if tg_client else False,
        "dispatcher_workers": len(tg_client.dispatcher.handler_worker_tasks) if tg_client else 0,
    }
    handler_counts = {}
    for group, hs in tg_client.dispatcher.groups.items():
        handler_counts[str(group)] = [
            {"type": type(h).__name__, "callback": h.callback.__name__ if inspect.isfunction(h.callback) else str(h.callback)[:50]}
            for h in hs
        ]
    result["handler_groups"] = handler_counts
    try:
        me = await tg_client.get_me()
        result["bot_username"] = me.username
        result["bot_id"] = me.id
    except Exception as e:
        result["get_me_error"] = str(e)
    try:
        dc_id = await tg_client.storage.dc_id()
        result["dc_id"] = dc_id
        is_bot = await tg_client.storage.is_bot()
        result["is_bot"] = is_bot
        user_id = await tg_client.storage.user_id()
        result["user_id"] = user_id
    except Exception as e:
        result["storage_error"] = str(e)
    return result


@app.get("/api/diag/bot-send")
async def diag_bot_send(request: Request, chat_id: int = 0):
    auth = request.headers.get("Authorization", "")
    if not bearer_token_matches(auth, settings.debug_password):
        raise HTTPException(status_code=401, detail="Invalid debug token")
    if not chat_id:
        return {"error": "pass ?chat_id=YOUR_TELEGRAM_ID"}
    from .telegram import tg_client
    try:
        msg = await tg_client.send_message(chat_id, "🧪 Bot test message — if you see this, sending works!")
        return {"sent": True, "message_id": msg.id}
    except Exception as e:
        return {"sent": False, "error": str(e)}


@app.get("/api/v")
async def api_v():
    return {"v": 2, "commit": "33c4c1a57a7a"}

def _has_debug_auth(request: Request) -> bool:
    auth = request.headers.get("Authorization", "")
    return bearer_token_matches(auth, settings.debug_password)


@app.get("/api/status")
async def api_status(request: Request):
    status = await get_status()
    if not _has_debug_auth(request):
        # Public dashboard mode: metrics stay visible, but logs and per-video
        # entries leak chat/message IDs, so strip them for unauthenticated viewers.
        status["logs"] = []
        cache = status.get("cache")
        if isinstance(cache, dict):
            cache["per_video"] = []
            cache["forward"] = None
    return status


@app.post("/api/status/clear-logs")
async def api_clear_logs(request: Request):
    if not _has_debug_auth(request):
        raise HTTPException(status_code=401, detail="Invalid debug token")
    clear_logs()
    return {"status": "ok"}


@app.get("/status", include_in_schema=False)
async def status_page():
    return FileResponse("app/static/status.html")


if os.path.exists("app/static/assets"):
    app.mount("/assets", StaticFiles(directory="app/static/assets"), name="assets")

NO_CACHE_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@app.get("/", include_in_schema=False)
async def index():
    if os.path.exists("app/static/index.html"):
        return FileResponse("app/static/index.html", headers=NO_CACHE_HEADERS)
    return JSONResponse(status_code=404, content={"detail": "Not found"})

@app.get("/download", include_in_schema=False)
async def download_page():
    return FileResponse("app/static/download.html", headers=NO_CACHE_HEADERS)

@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    """Serve the React SPA for any non-API routes."""
    if full_path == "api" or full_path.startswith("api/") or ".." in full_path:
        raise HTTPException(status_code=404, detail="Not found")

    # Stats + precompressed lookups off the event loop (slow disks under
    # load would stall active streams).
    static_file_path = f"app/static/{full_path}"
    import mimetypes

    def _resolve():
        if os.path.isfile(static_file_path):
            gz = static_file_path + ".gz"
            if os.path.isfile(gz):
                return static_file_path, gz
            return static_file_path, None
        return None, None

    accepts_gzip = "gzip" in request.headers.get("accept-encoding", "")
    static_file, gz_file = await asyncio.to_thread(_resolve)
    if static_file:
        if gz_file and accepts_gzip:
            # Precompressed sibling from the build — ~70% smaller on the wire
            # (385KB JS -> 116KB, 11MB player -> ~3MB).
            media_type = mimetypes.guess_type(static_file)[0] or "application/octet-stream"
            return FileResponse(
                gz_file,
                media_type=media_type,
                headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
            )
        return FileResponse(static_file_path)

    index_exists = await asyncio.to_thread(
        lambda: os.path.exists("app/static/index.html")
    )
    if index_exists:
        return FileResponse("app/static/index.html", headers=NO_CACHE_HEADERS)

    return JSONResponse(status_code=404, content={"detail": "Not found"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=True
    )
