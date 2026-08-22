"""
Streaming API endpoints for media playback.
"""
import re
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from fastapi.responses import StreamingResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import File, User
from ..auth import get_current_user, get_current_user_opt, verify_token, verify_token_payload

from ..telegram import get_message_from_channel, tg_client, clients
from ..streaming import stream_file as stream_file_chunks, prefetch_first_batch_safe, prefetch_by_ids, _cache_manager, _forward_streams, _dc_disk_size
from ..config import get_settings
from ..rate_limit import limiter
from ..utils import bearer_token_matches, spawn_background

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/stream", tags=["Streaming"])


async def _user_from_download_token(request: Request, file_id: int, db: AsyncSession):
    """Resolve a user from a ``?token=`` download JWT, enforcing the token's
    file_id binding. Every token must carry a ``file_id`` claim; tokens bound
    to a different file are rejected with 403 (this includes the grab/bot
    flow links, which mint file-bound tokens via create_download_token)."""
    token = request.query_params.get("token")
    if not token:
        return None
    payload = verify_token_payload(token, token_type="download")
    if not payload:
        return None
    claimed = payload.get("file_id")
    if claimed is None:
        raise HTTPException(status_code=403, detail="Token not valid for this file")
    try:
        if int(claimed) != file_id:
            raise HTTPException(status_code=403, detail="Token not valid for this file")
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="Token not valid for this file")
    sub = payload.get("sub")
    if sub is None:
        return None
    try:
        tid = int(sub)
    except (TypeError, ValueError):
        return None
    token_version = payload.get("ver")
    result = await db.execute(select(User).where(User.telegram_id == tid))
    user = result.scalar_one_or_none()
    if user and (token_version is None or token_version >= user.auth_version):
        return user
    return None


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse HTTP Range header for video seeking support.

    For a zero-byte file there is no body to satisfy, so the caller answers
    ``0, -1`` + a 200 against a 0 length instead of a bogus 416. Multipart
    ranges (``bytes=a-b,c-d``) are rejected with ``None`` — the caller turns
    that into a 416 rather than silently serving only the first range.
    """
    if range_header:
        if "," in range_header:
            return None
        # Suffix range: bytes=-500 (last N bytes)
        suffix_match = re.match(r'bytes=-(\d+)', range_header)
        if suffix_match:
            suffix_len = int(suffix_match.group(1))
            if file_size == 0:
                return 0, -1
            start = max(0, file_size - suffix_len)
            return start, file_size - 1

        match = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if not match:
            return 0, file_size - 1

        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else file_size - 1
        if file_size == 0:
            return 0, -1
        return start, min(end, file_size - 1)

    if file_size == 0:
        return 0, -1
    return 0, file_size - 1


@router.get("/debug")
async def streaming_debug(request: Request):
    # Allow Bearer aarsha or valid admin JWT
    auth = request.headers.get("Authorization", "")
    if not bearer_token_matches(auth, settings.debug_password):
        try:
            token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
            tid = verify_token(token) if token else None
            if not tid:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            from ..database import async_session
            from ..models import User
            from sqlalchemy import select
            async with async_session() as db:
                r = await db.execute(select(User).where(User.telegram_id == tid))
                user = r.scalar_one_or_none()
            if not user or not user.is_admin:
                raise HTTPException(status_code=403, detail="Admin access required")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    try:
        cache_info = _cache_manager.info
        per_video = _cache_manager.per_video

        disk_bytes = await asyncio.to_thread(_dc_disk_size)
        disk_mb = round(disk_bytes / 1024 / 1024, 1)

        bots = []
        for i, c in enumerate(clients):
            bots.append({
                "index": i,
                "label": "Main" if i == 0 else f"Helper {i}",
                "connected": c.is_connected,
            })

        forward_info = []
        for mid in list(_forward_streams.keys()):
            info = _forward_streams.get(mid)
            if not info:
                continue
            futures = info.get("results", {})
            done = sum(1 for f in list(futures.values()) if f.done())
            total = info.get("total_chunks", 0)
            forward_info.append({
                "message_id": mid,
                "done_futures": done,
                "total_futures": len(futures),
                "total_chunks": total,
            })

        return {
            "cache": {
                "ram_chunks": cache_info["chunks"],
                "ram_mb": cache_info["size_mb"],
                "hits": cache_info["hits"],
                "misses": cache_info["misses"],
                "evictions": cache_info["evictions"],
                "hit_rate_pct": round(
                    cache_info["hits"] / (cache_info["hits"] + cache_info["misses"]) * 100, 1
                ) if (cache_info["hits"] + cache_info["misses"]) > 0 else 0,
                "per_video": per_video,
            },
            "disk_cache_mb": disk_mb,
            "bots": bots,
            "active_streams": forward_info,
            "active_stream_count": len(forward_info),
        }
    except Exception as e:
        logger.exception("Failed to build debug response")
        raise HTTPException(status_code=500, detail=str(e))


PARALLEL_DOWNLOAD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Download</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0a;color:#e0e0e0;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}
.card{background:#141414;border:1px solid #222;border-radius:16px;padding:32px;max-width:480px;width:100%}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:20px}
.logo span{font-size:1.2rem;font-weight:600;background:linear-gradient(135deg,#6366f1,#a855f7,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.file-info{color:#888;font-size:.85rem;margin-bottom:24px;word-break:break-all}
.btn{width:100%;padding:12px;border:none;border-radius:12px;font-size:1rem;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;transition:opacity .2s;margin-bottom:10px;background:linear-gradient(135deg,#6366f1,#a855f7,#ec4899);color:#fff}
.btn:disabled{opacity:.5;cursor:default}
.btn-outline{width:100%;padding:10px;border:1px solid #333;border-radius:12px;font-size:.9rem;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;background:transparent;color:#888;transition:all .2s}
.btn-outline:hover{background:#1a1a1a;color:#ccc}
.spinner{width:20px;height:20px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.bar-wrap{background:#222;border-radius:8px;height:8px;margin:16px 0 8px;overflow:hidden}
.bar-fill{height:100%;border-radius:8px;background:linear-gradient(90deg,#6366f1,#a855f7,#ec4899);transition:width .3s ease}
.stats{display:flex;justify-content:space-between;font-size:.85rem;color:#888}
.chunk-grid{display:grid;grid-template-columns:repeat(8,1fr);gap:4px;margin-top:12px}
.chunk{aspect-ratio:1;background:#1a1a1a;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:.6rem;color:#555;transition:all .3s}
.chunk.done{background:#1a3a1a;color:#4caf50}
#error{color:#f55;font-size:.85rem;margin-top:12px;display:none}
</style></head><body>
<div class="card">
<div class="logo"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="url(#g)" stroke-width="2"><defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#6366f1"/><stop offset="100%" stop-color="#ec4899"/></linearGradient></defs><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg><span>Download</span></div>
<p class="file-info" id="fileInfo">Loading...</p>
<button class="btn" id="dlBtn"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Start Download</button>
<button class="btn-outline" id="directDlBtn">Download directly</button>
<div id="progress" style="display:none"><div class="bar-wrap"><div class="bar-fill" id="bar"></div></div><div class="stats"><span id="speed">0 MB/s</span><span id="pct">0%</span></div><div class="chunk-grid" id="chunkGrid"></div></div>
<div id="error"></div>
</div>
<script>
const C=4,S=5*1024*1024,R=3,L=200*1024*1024;
const $=id=>document.getElementById(id);
const nm=(cd,fb)=>{const m=/filename\*=utf-8''([^;]+)/.exec(cd||'');return m?decodeURIComponent(m[1]):fb};
function init(){const q=new URLSearchParams(location.search),id=q.get('id'),token=q.get('token'),hash=q.get('hash');if(!id&&!hash){$('fileInfo').textContent='Missing id or hash';return}
const base=hash?'/api/stream/s/'+encodeURIComponent(hash):'/api/stream/'+id+(token?'?token='+encodeURIComponent(token):'');$('fileInfo').textContent=hash?'Hash: '+hash:'ID: '+id;const direct=base+(base.indexOf('?')>=0?'&':'?')+'download=1';$('dlBtn').onclick=()=>start(base,hash||id);$('directDlBtn').onclick=()=>{location.href=direct}}
async function start(url,fb){const prog=$('progress'),btn=$('dlBtn'),grid=$('chunkGrid');prog.style.display='block';btn.disabled=true;btn.innerHTML='<div class="spinner"></div>';$('error').style.display='none';let chunks=[];const bufs=[]
try{const head=await fetch(url,{method:'HEAD'});if(!head.ok)throw new Error('HTTP '+head.status);const size=parseInt(head.headers.get('content-length')||'0');if(!size)throw new Error('No content-length');
if(size>L){location.href=url+(url.indexOf('?')>=0?'&':'?')+'download=1';return}
const count=Math.ceil(size/S);grid.innerHTML='';for(let c=0;c<count;c++){const d=document.createElement('div');d.className='chunk';d.textContent=c+1;grid.appendChild(d);chunks.push(d)}
const t0=Date.now();let got=0;setInterval(()=>{const s=Date.now()-t0;if(s>0){const k=got*1e3/s;$('speed').textContent=(k>=1e6?(k/1e6).toFixed(1)+' MB/s':(k/1e3).toFixed(1)+' KB/s')}},200)
const fetchChunk=async chunk=>{for(let n=0;n<R&&!chunk.done;n++)try{const r=await fetch(url,{headers:{Range:'bytes='+chunk.start+'-'+chunk.end}});if(r.status!==206){if(r.status===416)break;continue}const m=/^bytes (\d+)-(\d+)\/\d+/.exec(r.headers.get('content-range')||'');if(!m||+m[1]!==chunk.start)continue;const buf=await r.arrayBuffer();got+=buf.byteLength;bufs[chunk.start/S|0]=buf;chunks[chunk.start/S|0].classList.add('done');$('pct').textContent=Math.round(got/size*100)+'%';chunk.done=true;return}catch{}}
const ranges=[];for(let t=0;t<count;t++)ranges.push({start:t*S,end:Math.min(t*S+S-1,size-1)});for(let i=0;i<ranges.length;i+=C)await Promise.all(ranges.slice(i,i+C).map(fetchChunk))
if(got>=size){$('bar').style.width='100%';$('pct').textContent='100%';const u=URL.createObjectURL(new Blob(bufs,{type:head.headers.get('content-type')||'application/octet-stream'}));const a=document.createElement('a');a.href=u;a.download=nm(head.headers.get('content-disposition'),'download_'+(fb||'file'));document.body.appendChild(a);a.click();a.remove();btn.innerHTML='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M22 12A10 10 0 1 1 12 2a10 10 0 0 1 10 10z"/><polyline points="16 12 12 8 8 12"/><line x1="12" y1="16" x2="12" y2="8"/></svg> Download Complete'}
else{btn.disabled=false;btn.innerHTML='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Retry';$('error').textContent='Incomplete: '+Math.round(got/size*100)+'% downloaded. Click retry.';$('error').style.display='block'}
}catch(e){btn.disabled=false;btn.innerHTML='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Retry';$('error').textContent='Error: '+e.message;$('error').style.display='block'}}
document.addEventListener('DOMContentLoaded',init);
</script></body></html>"""


@router.get("/dl", include_in_schema=False)
async def parallel_download_page(
    id: int = Query(None),
    hash: str = Query(None),
    token: str = Query(None),
):
    """Serve parallel chunk-download HTML page.
    Use ?id=FILE_ID&token=TOKEN for auth, or ?hash=PUBLIC_HASH for public files.
    """
    return HTMLResponse(PARALLEL_DOWNLOAD_HTML)


@router.head("/{file_id}")
async def stream_file_head(
    file_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_opt),
):
    """HEAD variant of stream_file.

    Required by movi-player (and browser <video> probing): the player resolves
    the total file size with a HEAD request before issuing ranged GETs. Without
    this the route only answers GET and HEAD returns 405, which makes the player
    give up with a blank screen.
    """
    if not current_user:
        current_user = await _user_from_download_token(request, file_id, db)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Player resolves size via HEAD right before it starts playback — use this
    # moment to warm the chunk cache so the first GET serves from cache.
    try:
        spawn_background(prefetch_by_ids(get_settings().telegram_storage_channel_id, file.channel_message_id))
    except Exception:
        pass  # best-effort

    from urllib.parse import quote
    mime_type = file.mime_type or "application/octet-stream"
    disposition = "inline" if ("video/" in mime_type or "audio/" in mime_type or "image/" in mime_type) else "attachment"
    encoded_filename = quote(file.file_name)
    headers = {
        "Content-Type": mime_type,
        "Content-Disposition": f"{disposition}; filename*=utf-8''{encoded_filename}",
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=300",
        "Content-Length": str(file.file_size),
    }
    return Response(status_code=200, content=b"", headers=headers)


@router.get("/{file_id}")
async def stream_file(
    file_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_opt),
    download: int = Query(0, description="Set to 1 to force download"),
):
    """Stream file from Telegram with range request support for seeking."""
    # Fall back to download token if not authenticated normally
    if not current_user:
        current_user = await _user_from_download_token(request, file_id, db)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Get file from database
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    file_size = file.file_size

    # Parse range header
    range_header = request.headers.get("range")
    parsed = parse_range_header(range_header, file_size)

    # Validate range
    if parsed is None:
        # Multipart ranges (bytes=a-b,c-d) aren't supported; tell the client
        # plainly instead of silently serving only the first range as a 206.
        return Response(
            status_code=416,
            content="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    from_bytes, until_bytes = parsed

    if until_bytes == -1:
        # Zero-byte file: satisfy a plain GET with an empty 200 body; a Range
        # on a zero-byte file can't be satisfied per RFC 7233 → 416.
        if range_header:
            # Prefer staying consistent — send the 206 empty body variant when
            # range is satisfiable, otherwise 416. Empty body → 206/200 equally
            # fine; use 416 to match the RFC.
            return Response(
                status_code=416,
                content="416: Range not satisfiable",
                headers={"Content-Range": "bytes */0"},
            )
        headers = {
            "Content-Type": file.mime_type or "application/octet-stream",
            "Content-Disposition": "attachment" if download else "inline",
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store" if download else "private, max-age=300",
            "Content-Length": "0",
        }
        return Response(status_code=200, content=b"", headers=headers)

    # Validate range
    if (until_bytes > file_size) or (from_bytes < 0) or (from_bytes > until_bytes):
        return Response(
            status_code=416,
            content="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    # Get message from channel
    message = await get_message_from_channel(file.channel_message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found in channel")

    # Pre-fetch first batch to reduce load time
    spawn_background(prefetch_first_batch_safe(tg_client, message, from_bytes))

    async def file_streamer():
        """Generator that streams file chunks from Telegram MTProto."""
        try:
            async for chunk in stream_file_chunks(
                tg_client,
                message,
                from_bytes,
                until_bytes,
                request=request,
            ):
                yield chunk
        except asyncio.TimeoutError:
            logger.warning("Stream aborted (chunk unrecoverable) for file %d", file_id)
            raise
        except Exception as e:
            logger.error("Stream failed for file %d: %s", file_id, e)
            raise

    # Determine content disposition
    mime_type = file.mime_type or "application/octet-stream"
    # SVG is excluded from inline serving: it can carry scripts, so a shared
    # link would execute in our origin (stored XSS). Force download instead.
    disposition = "attachment" if download else ("inline" if ("video/" in mime_type or "audio/" in mime_type or ("image/" in mime_type and "svg" not in mime_type)) else "attachment")

    from urllib.parse import quote
    encoded_filename = quote(file.file_name)

    content_length = until_bytes - from_bytes + 1
    headers = {
        "Content-Type": mime_type,
        "Content-Disposition": f"{disposition}; filename*=utf-8''{encoded_filename}",
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store" if download else "private, max-age=300",
        "Content-Length": str(content_length),
        "X-Accel-Buffering": "no",
    }
    if range_header:
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"

    return StreamingResponse(
        file_streamer(),
        status_code=206 if range_header else 200,
        media_type=mime_type,
        headers=headers
    )


async def _download_thumb(msg, thumb_obj):
    """Download thumbnail; on AUTH_BYTES_INVALID retry with fresh message."""
    try:
        return await tg_client.download_media(thumb_obj.file_id, in_memory=True)
    except Exception as e:
        if "AUTH_BYTES_INVALID" not in str(e):
            raise
        # stale file reference — re-fetch bypassing cache
        refreshed = await tg_client.get_messages(msg.chat.id, msg.id)
        if not refreshed:
            raise
        rt = None
        if refreshed.video and refreshed.video.thumbs:
            rt = refreshed.video.thumbs[0]
        elif refreshed.document and refreshed.document.thumbs:
            rt = refreshed.document.thumbs[0]
        elif refreshed.audio and refreshed.audio.thumbs:
            rt = refreshed.audio.thumbs[0]
        elif refreshed.photo:
            rt = refreshed.photo
        if not rt:
            raise
        return await tg_client.download_media(rt.file_id, in_memory=True)


@router.get("/{file_id}/thumbnail")
async def get_thumbnail(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get file thumbnail with caching."""
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Serve from cache if available
    if file.thumbnail_data:
        mime = _detect_image_mime(file.thumbnail_data)
        return Response(content=file.thumbnail_data, media_type=mime)
    
    if not file.thumbnail_file_id:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    
    try:
        # Get the message and download thumbnail
        message = await get_message_from_channel(file.channel_message_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

        # Extract thumbnail object
        thumbnail = None
        if message.video and message.video.thumbs:
            thumbnail = message.video.thumbs[0]
        elif message.document and message.document.thumbs:
            thumbnail = message.document.thumbs[0]
        elif message.audio and message.audio.thumbs:
            thumbnail = message.audio.thumbs[0]
        elif message.photo:
            thumbnail = message.photo
            
        if not thumbnail:
            if file.thumbnail_file_id:
                try:
                    thumb_bytes = await tg_client.download_media(
                        file.thumbnail_file_id,
                        in_memory=True
                    )
                    data = bytes(thumb_bytes.getbuffer()) if hasattr(thumb_bytes, 'getbuffer') else thumb_bytes
                except Exception:
                    raise HTTPException(status_code=404, detail="Thumbnail not found in message")
            else:
                raise HTTPException(status_code=404, detail="Thumbnail not found in message")
        else: #YH
            thumb_bytes = await _download_thumb(message, thumbnail) #KJ
            data = thumb_bytes.getvalue() if hasattr(thumb_bytes, 'getvalue') else bytes(thumb_bytes) #SY
        
        # Cache for future requests
        file.thumbnail_data = data
        await db.commit()

        mime = _detect_image_mime(data)
        return Response(content=data, media_type=mime)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Thumbnail error for file {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get thumbnail")


def _detect_image_mime(data: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:2] == b"BM":
        return "image/bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


@router.get("/s/{public_hash}")
@limiter.limit("60/minute")  # Rate limit public streaming to prevent abuse
async def stream_public_file(
    public_hash: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    download: int = Query(0, description="Set to 1 to force download"),
):
    """Stream file via public link (no auth required)."""
    # Get file by hash
    result = await db.execute(select(File).where(File.public_hash == public_hash))
    file = result.scalar_one_or_none()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found or link revoked")
        
    file_size = file.file_size
    
    # Parse range header
    range_header = request.headers.get("range")
    parsed = parse_range_header(range_header, file_size)

    # Validate range
    if parsed is None:
        # Multipart ranges (bytes=a-b,c-d) aren't supported; tell the client
        # plainly instead of crashing with a TypeError on tuple unpacking.
        return Response(
            status_code=416,
            content="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    from_bytes, until_bytes = parsed

    if until_bytes == -1:
        # Zero-byte file: satisfy a plain GET with an empty 200 body; a Range
        # on a zero-byte file can't be satisfied per RFC 7233 → 416.
        if range_header:
            return Response(
                status_code=416,
                content="416: Range not satisfiable",
                headers={"Content-Range": "bytes */0"},
            )
        headers = {
            "Content-Type": file.mime_type or "application/octet-stream",
            "Content-Disposition": "attachment" if download else "inline",
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=86400",
            "Content-Length": "0",
        }
        return Response(status_code=200, content=b"", headers=headers)

    if (until_bytes > file_size) or (from_bytes < 0) or (from_bytes > until_bytes):
        return Response(
            status_code=416,
            content="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    # Get message from channel
    message = await get_message_from_channel(file.channel_message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found in channel")

    # Pre-fetch first batch to reduce load time
    spawn_background(prefetch_first_batch_safe(tg_client, message, from_bytes))

    async def file_streamer():
        """Generator that streams file chunks from Telegram MTProto."""
        try:
            async for chunk in stream_file_chunks(
                tg_client,
                message,
                from_bytes,
                until_bytes,
                request=request,
            ):
                yield chunk
        except asyncio.TimeoutError:
            logger.warning("Public stream timed out after 300s for hash %s", public_hash)
            raise
        except Exception as e:
            logger.error("Public stream failed for hash %s: %s", public_hash, e)
            raise

    # Determine content disposition
    mime_type = file.mime_type or "application/octet-stream"
    # SVG is excluded from inline serving: it can carry scripts, so a shared
    # link would execute in our origin (stored XSS). Force download instead.
    disposition = "attachment" if download else ("inline" if ("video/" in mime_type or "audio/" in mime_type or ("image/" in mime_type and "svg" not in mime_type)) else "attachment")

    from urllib.parse import quote
    encoded_filename = quote(file.file_name)

    content_length = until_bytes - from_bytes + 1
    headers = {
        "Content-Type": mime_type,
        "Content-Disposition": f"{disposition}; filename*=utf-8''{encoded_filename}",
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
        "Content-Length": str(content_length),
        "X-Accel-Buffering": "no",
    }
    if range_header:
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"

    return StreamingResponse(
        file_streamer(),
        status_code=206 if range_header else 200,
        media_type=mime_type,
        headers=headers
    )



