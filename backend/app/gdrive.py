"""
Google Drive integration — OAuth + two-phase upload.
Downloads the full file to NVMe temp via 13-bot parallel streaming,
then uploads sequentially to Google Drive with 10MB chunks.
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from base64 import urlsafe_b64encode
from datetime import datetime
from pathlib import Path

import httpx
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from .config import get_settings
from .streaming import _byte_accurate_file_stream, get_client_semaphore
from .telegram import clients

_log = logging.getLogger(__name__)
settings = get_settings()

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class TokenExpiredError(Exception):
    """Google OAuth refresh token has been revoked or expired."""
    pass

# In-memory nonce store for OAuth CSRF protection
# {nonce: (telegram_id, timestamp, code_verifier)}
_nonce_store: dict[str, tuple[int, float, str]] = {}
_NONCE_TTL = 600  # 10 minutes


def _prune_nonces():
    now = time.monotonic()
    expired = [k for k, (_, ts, _) in _nonce_store.items() if now - ts > _NONCE_TTL]
    for k in expired:
        _nonce_store.pop(k, None)


def _pkce_challenge(verifier: str) -> str:
    """Compute S256 code_challenge from a code_verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _flow() -> Flow:
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.gdrive_client_id,
                "client_secret": settings.gdrive_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.gdrive_redirect_uri],
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = settings.gdrive_redirect_uri
    return flow


def generate_auth_url(telegram_id: int) -> str:
    """Generate Google OAuth URL for the given Telegram user.

    Uses PKCE (S256) and embeds a nonce in the state param to prevent CSRF.
    The code_verifier is stored in-memory alongside the nonce.
    """
    _prune_nonces()
    flow = _flow()
    nonce = secrets.token_hex(16)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _pkce_challenge(code_verifier)
    _nonce_store[nonce] = (telegram_id, time.monotonic(), code_verifier)
    state = f"{telegram_id}:{nonce}"
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
        include_granted_scopes="true",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    return auth_url


def consume_state(state: str) -> tuple[int, str]:
    """Verify and consume the OAuth state, returning (telegram_id, code_verifier).
    Raises ValueError if the nonce is invalid or expired.
    """
    _prune_nonces()
    try:
        telegram_id_str, nonce = state.split(":", 1)
        telegram_id = int(telegram_id_str)
    except (ValueError, IndexError):
        raise ValueError("Invalid state format")

    stored = _nonce_store.pop(nonce, None)
    if stored is None:
        raise ValueError("Invalid or expired nonce — please re-authorize")
    stored_id, _, code_verifier = stored
    if stored_id != telegram_id:
        raise ValueError("telegram_id mismatch in state")
    return telegram_id, code_verifier


async def exchange_code(code: str, code_verifier: str) -> dict:
    """Exchange an OAuth authorization code for a token dict.

    Requires the code_verifier used during the authorization request (PKCE).
    The dict is JSON-serialisable and suitable for storing in the DB.
    Runs the blocking Google token exchange off the event loop.
    """
    flow = _flow()
    await asyncio.to_thread(flow.fetch_token, code=code, code_verifier=code_verifier)
    creds = flow.credentials
    return _creds_to_dict(creds)


def _creds_to_dict(creds: UserCredentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "scopes": list(creds.scopes),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def _creds_from_dict(d: dict) -> UserCredentials:
    expiry = None
    if d.get("expiry"):
        try:
            expiry = datetime.fromisoformat(d["expiry"])
        except Exception:
            pass
    return UserCredentials(
        token=d.get("token"),
        refresh_token=d.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.gdrive_client_id,
        client_secret=settings.gdrive_client_secret,
        scopes=d.get("scopes") or SCOPES,
        expiry=expiry,
    )


def _refresh_creds(token_dict: dict) -> UserCredentials:
    """Refresh credentials if expired.  Raises TokenExpiredError on invalid_grant
    (revoked/expired refresh token) or missing refresh token, and clears the
    refresh_token in token_dict."""
    creds = _creds_from_dict(token_dict)
    if creds.expired:
        if not creds.refresh_token:
            raise TokenExpiredError(
                "Google Drive authorization expired. Send /drive to reconnect."
            )
        try:
            creds.refresh(GoogleAuthRequest())
        except RefreshError as e:
            if "invalid_grant" in str(e):
                token_dict["refresh_token"] = None
                token_dict.pop("expiry", None)
                raise TokenExpiredError(
                    "Google Drive authorization expired. Send /drive to reconnect."
                )
            raise
        token_dict["token"] = creds.token
        if creds.expiry:
            token_dict["expiry"] = creds.expiry.isoformat()
    return creds


def get_access_token(token_dict: dict) -> str:
    """Return a valid access token string, refreshing if needed."""
    return _refresh_creds(token_dict).token


def build_service(token_dict: dict):
    """Build an authenticated Google Drive API v3 service from a stored
    token dict.  Auto-refreshes the access token if expired.
    Raises TokenExpiredError if the refresh token has been revoked."""
    return build("drive", "v3", credentials=_refresh_creds(token_dict))


def ensure_aruvi_folder(service) -> str:
    """Return the ID of the 'Aruvi' folder in the user's Drive.
    Creates it if it doesn't exist.  Handles TOCTOU race on create.
    Fully synchronous (httplib2) — call via asyncio.to_thread from async code."""
    q = (
        "name='Aruvi'"
        " and mimeType='application/vnd.google-apps.folder'"
        " and trashed=false"
    )

    def _find() -> str | None:
        result = service.files().list(q=q, spaces="drive", fields="files(id)").execute()
        files = result.get("files", [])
        return files[0]["id"] if files else None

    folder_id = _find()
    if folder_id:
        return folder_id

    try:
        folder = (
            service.files()
            .create(
                body={"name": "Aruvi", "mimeType": "application/vnd.google-apps.folder"},
                fields="id",
            )
            .execute()
        )
        return folder["id"]
    except Exception:
        folder_id = _find()
        if folder_id:
            return folder_id
        raise


GDRIVE_UPLOAD_DIR = Path("data/gdrive_upload")
CHUNK_SIZE = 10 * 1024 * 1024
MAX_GDRIVE_FILE = 4 * 1024 * 1024 * 1024

# Limit concurrent 1MB slot downloads to prevent OOM (30 × 1MB = 30MB in-flight)
_GDRIVE_DOWNLOAD_SEM = asyncio.Semaphore(30)


def _raw_write(fd: int, offset: int, data: bytes) -> None:
    """pwrite + FADV_DONTNEED, run on a worker thread by callers."""
    os.pwrite(fd, data, offset)
    try:
        os.posix_fadvise(fd, offset, len(data), os.POSIX_FADV_DONTNEED)
    except OSError:
        pass


async def upload_streaming(
    token_dict: dict,
    msg: "Message",
    file_name: str,
    mime_type: str,
    file_size: int,
    folder_id: str,
    progress_callback=None,
) -> str:
    """Download the full file to NVMe temp (via 13-bot parallel streaming,
    then upload sequentially to Google Drive with 20MB chunks.
    Deletes the temp file after upload.
    """
    if file_size > MAX_GDRIVE_FILE:
        raise ValueError("File exceeds 4GB limit for GDrive upload")

    total = file_size
    metadata = json.dumps(
        {
            "name": file_name,
            "mimeType": mime_type,
            "parents": [folder_id],
        }
    )

    # ── Phase 1: Download full file to NVMe temp (pipelined byte-accurate) ──
    GDRIVE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = GDRIVE_UPLOAD_DIR / f"{msg.id}_{int(time.time())}.tmp"

    try:
        # Pre-allocate temp file
        with open(tmp, "wb") as f:
            f.truncate(total)

        downloaded = 0
        last_ts = 0
        dlerr = None
        lock = asyncio.Lock()
        # No O_DSYNC: syncing every 1MB pwrite to disk freezes the event loop
        # (and the whole service) for the duration of the task-gather. Page
        # cache + one final fsync below gives the same durability without the
        # per-chunk stall.
        fd = os.open(tmp, os.O_RDWR | os.O_CREAT, 0o644)

        # Split file into 1MB slots — each slot is one _byte_accurate_file_stream call
        SLOT_SIZE = 1024 * 1024
        slot_starts = list(range(0, total, SLOT_SIZE))

        # Use helper bots (skip bot 0)
        helper_clients = [c for c in clients if getattr(c, "pool_index", 0) != 0]
        if not helper_clients:
            raise RuntimeError("No helper bots available")

        async def _download_slot(slot_start: int, client_idx: int):
            nonlocal downloaded, last_ts, dlerr
            if dlerr:
                return
            async with _GDRIVE_DOWNLOAD_SEM:
                client = clients[client_idx]
                sem = get_client_semaphore(client_idx)
                slot_end = min(slot_start + SLOT_SIZE, total)
                for attempt in range(2):
                    try:
                        async with sem:
                            async for offset, chunk in _byte_accurate_file_stream(
                                client, msg, total, slot_start, slot_end
                            ):
                                # Offload blocking pwrite/fadvise to a thread —
                                # these syscalls must never run on the event loop.
                                await asyncio.to_thread(
                                    _raw_write, fd, offset, chunk
                                )
                                async with lock:
                                    downloaded += len(chunk)
                                    now = time.monotonic()
                                    if progress_callback and (now - last_ts >= 1 or downloaded >= total):
                                        await progress_callback(downloaded, total, "Downloading from Telegram")
                                        last_ts = now
                        break  # success
                    except Exception as e:
                        if attempt == 0 and ("AUTH_KEY_UNREGISTERED" in str(e) or "LIMIT_INVALID" in str(e)):
                            continue  # retry once with fresh session
                        async with lock:
                            if dlerr is None:
                                dlerr = e
                        break

        tasks = []
        for i, slot_start in enumerate(slot_starts):
            c_idx = helper_clients[i % len(helper_clients)].pool_index
            tasks.append(asyncio.create_task(_download_slot(slot_start, c_idx)))

        async def _abort_siblings(on_err: BaseException):
            # Stop remaining slots the moment one fails — otherwise the other
            # ~N slots keep downloading a multi-GB file that will be thrown away.
            nonlocal dlerr, tasks
            if dlerr is None:
                dlerr = on_err
            for t in tasks:
                if not t.done():
                    t.cancel()
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                tasks = []

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            # A caller cancelled the whole upload: stop slots cleanly, re-raise.
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        except Exception as e:
            await _abort_siblings(e)
            raise
        finally:
            if fd is not None:
                try:
                    os.fsync(fd)  # single durable flush after all slots
                except OSError:
                    pass
                os.close(fd)

        if dlerr:
            raise dlerr

        _log.info("Phase 1 done: downloaded %d/%d bytes", downloaded, total)

        # Validate download completed fully
        if downloaded < total:
            raise RuntimeError(
                f"Incomplete download: {downloaded}/{total} bytes "
                f"({downloaded * 100 // total}%). "
                f"Telegram likely dropped chunks. Try again."
            )

        # ── Phase 2: Upload sequentially to Drive ──
        # Token refresh does blocking network I/O — keep it off the event loop.
        access_token = await asyncio.to_thread(get_access_token, token_dict)
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            session_resp = await client.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": mime_type,
                    "X-Upload-Content-Length": str(downloaded),
                },
                content=metadata,
            )
            session_resp.raise_for_status()
            upload_url = session_resp.headers["Location"]

            uploaded = 0
            last_report = 0
            resp = None
            with open(tmp, "rb") as f:
                while True:
                    chunk = await asyncio.to_thread(f.read, CHUNK_SIZE)
                    if not chunk:
                        break
                    start = uploaded
                    end = uploaded + len(chunk) - 1
                    resp = await _upload_block(client, upload_url, chunk, start, end, downloaded)
                    uploaded += len(chunk)
                    now = time.monotonic()
                    if progress_callback and (now - last_report >= 1 or uploaded >= downloaded):
                        await progress_callback(uploaded, downloaded, "Uploading to Google Drive")
                        last_report = now

    finally:
        tmp.unlink(missing_ok=True)

    if resp is None:
        raise RuntimeError("No chunks were uploaded (empty file?)")

    file_resource = resp.json()
    file_id = file_resource.get("id")
    if not file_id:
        raise RuntimeError("Upload completed but no file ID returned")

    try:
        def _fetch_link() -> dict:
            # build_service may refresh the token and .execute() does blocking
            # HTTPS — run both on a worker thread.
            service = build_service(token_dict)
            return (
                service.files()
                .get(fileId=file_id, fields="webViewLink")
                .execute()
            )

        file_meta = await asyncio.to_thread(_fetch_link)
        return file_meta.get(
            "webViewLink",
            f"https://drive.google.com/file/d/{file_id}/view",
        )
    except TokenExpiredError:
        _log.warning("Token expired after upload completed — returning fallback link")
        return f"https://drive.google.com/file/d/{file_id}/view"
    except Exception:
        _log.exception("Failed to fetch webViewLink — returning fallback")
        return f"https://drive.google.com/file/d/{file_id}/view"


async def _upload_block(
    client: httpx.AsyncClient, upload_url: str, block: bytes,
    start: int, end: int, total: int,
) -> httpx.Response:
    """Upload a single block with retries.
    Raises TokenExpiredError on HTTP 401 (token revoked mid-upload)."""
    last_error = None
    for attempt in range(3):
        try:
            resp = await client.put(
                upload_url,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total}",
                    "Content-Length": str(len(block)),
                },
                content=block,
            )
            if resp.status_code in (200, 201, 308):
                return resp
            if resp.status_code == 401:
                raise TokenExpiredError(
                    "Google Drive authorization expired during upload. Send /drive to reconnect."
                )
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp.status_code < 500 and resp.status_code != 429:
                break
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_error = str(e)
        await asyncio.sleep(1 * (attempt + 1))
    raise RuntimeError(f"Upload block failed after 3 retries: {last_error}")
