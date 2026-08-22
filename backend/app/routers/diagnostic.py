import time
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Request, Response, Query
from fastapi.responses import StreamingResponse
from ..config import get_settings
from ..utils import bearer_token_matches, spawn_background
from ..telegram import tg_client
from ..streaming import stream_file as stream_file_chunks, prefetch_first_batch_safe, _fetch_message, _cache_manager

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/diag", tags=["Diagnostic"])


def _check_auth(request: Request):
    auth = request.headers.get("Authorization", "")
    if not bearer_token_matches(auth, settings.debug_password):
        raise HTTPException(status_code=401, detail="Invalid debug token")


def _get_file_attrs(message) -> tuple[int, str, str] | None:
    media = message.video or message.document or message.audio or message.photo
    if not media:
        return None
    if message.video:
        return message.video.file_size, message.video.mime_type or "video/mp4", getattr(message.video, "file_name", "video.mp4")
    if message.document:
        return message.document.file_size, message.document.mime_type or "application/octet-stream", getattr(message.document, "file_name", "file.bin")
    if message.audio:
        return message.audio.file_size, message.audio.mime_type or "audio/mpeg", getattr(message.audio, "file_name", "audio.mp3")
    if message.photo:
        return message.photo.file_size, "image/jpeg", "photo.jpg"
    return None


@router.get("/bandwidth")
async def diag_bandwidth(
    request: Request,
    mb: int = Query(10, ge=1, le=2000, description="Data size in MB"),
    chunk: int = Query(65536, ge=4096, le=1048576, description="Chunk size in bytes"),
):
    _check_auth(request)
    t0 = time.perf_counter()
    total_bytes = mb * 1024 * 1024
    payload = b"\x00" * chunk

    async def _gen():
        remaining = total_bytes
        while remaining > 0:
            to_send = min(chunk, remaining)
            yield payload[:to_send]
            remaining -= to_send

    elapsed = time.perf_counter() - t0
    return StreamingResponse(
        _gen(),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(total_bytes),
            "X-Test-Size-Bytes": str(total_bytes),
            "X-Test-Chunk-Size": str(chunk),
            "Server-Timing": f"setup;dur={int(elapsed*1000)}",
            "Cache-Control": "no-store",
        },
    )


@router.get("/ping")
async def diag_ping(request: Request):
    _check_auth(request)
    return {
        "server_time": time.time(),
        "status": "ok",
    }


@router.get("/clear-cache")
async def diag_clear_cache(request: Request):
    """Free the in-app chunk cache (RAM heap) and force a GC pass.
    Note: this does not touch the kernel page cache, which is reclaimable
    and freed automatically by the OS under memory pressure."""
    _check_auth(request)
    from ..status import _forward_streams
    active = {(info["chat_id"], mid) for mid, info in list(_forward_streams.items())}
    freed = _cache_manager.clear_all(exclude_keys=active)
    import gc
    freed_gc = gc.collect(2)
    return {
        "status": "ok",
        "chunk_cache_freed_mb": round(freed / 1024 / 1024, 1),
        "gc_collected_objects": freed_gc,
        "streams_preserved": len(active),
    }


async def _diag_media_response(request: Request, msg: int, chat: int | None, head: bool = False) -> StreamingResponse:
    """Shared GET/HEAD handler. HEAD is required by Range-based clients
    (e.g. movi-player's HttpSource) that probe file size first."""
    _check_auth(request)

    chat_id = chat if chat is not None else settings.telegram_storage_channel_id

    t0 = time.perf_counter()
    message = await _fetch_message(tg_client, chat_id, msg)
    if not message:
        raise HTTPException(status_code=404, detail=f"Message {msg} not found in chat {chat_id}")

    attrs = _get_file_attrs(message)
    if not attrs:
        raise HTTPException(status_code=400, detail="Message has no streamable media (video/document/audio/photo)")

    file_size, mime_type, file_name = attrs
    ttfb_ms = round((time.perf_counter() - t0) * 1000, 1)

    range_header = request.headers.get("range")
    from_bytes = 0
    until_bytes = file_size - 1

    has_range = False
    if range_header:
        import re
        match = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if match:
            from_bytes = int(match.group(1))
            end_str = match.group(2)
            until_bytes = int(end_str) if end_str else file_size - 1
            if until_bytes >= file_size:
                until_bytes = file_size - 1
            # Zero-byte file or unsatisfiable start → 416 instead of a
            # negative/empty chunk window downstream.
            if file_size == 0 or from_bytes >= file_size or from_bytes > until_bytes:
                raise HTTPException(
                    status_code=416,
                    detail="Range not satisfiable",
                    headers={"Content-Range": f"bytes */{file_size}"},
                )
            has_range = True

    if not head:
        spawn_background(prefetch_first_batch_safe(tg_client, message, from_bytes))

    async def _stream():
        try:
            async for chunk in stream_file_chunks(tg_client, message, from_bytes, until_bytes, request=request):
                yield chunk
        except asyncio.TimeoutError:
            logger.warning("Diag stream timed out for chat=%s msg=%d", chat_id, msg)
            raise
        except Exception as e:
            logger.error("Diag stream failed for chat=%s msg=%d: %s", chat_id, msg, e)
            raise

    from urllib.parse import quote
    encoded_name = quote(file_name)

    headers = {
        "Content-Type": mime_type,
        "Content-Disposition": f'inline; filename*=utf-8\'\'{encoded_name}',
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
        "X-Diag-Ttfb-Ms": str(ttfb_ms),
        "X-Diag-File-Size": str(file_size),
        "X-Diag-Msg-Id": str(msg),
        "X-Diag-Chat-Id": str(chat_id),
    }
    if has_range:
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"

    return StreamingResponse(
        _stream(),
        status_code=206 if has_range else 200,
        media_type=mime_type,
        headers=headers,
    )


@router.get("/stream")
async def diag_stream(
    request: Request,
    msg: int = Query(..., description="Message ID in the chat"),
    chat: int = Query(None, description="Chat ID (defaults to storage channel)"),
):
    return await _diag_media_response(request, msg, chat)


@router.head("/stream")
async def diag_stream_head(
    request: Request,
    msg: int = Query(..., description="Message ID in the chat"),
    chat: int = Query(None, description="Chat ID (defaults to storage channel)"),
):
    return await _diag_media_response(request, msg, chat, head=True)
