"""One-shot Telegram login helper for self-hosters.

Generates a Pyrogram session string server-side so users never have to run
MTProto in a browser. Every endpoint is gated by SETUP_PASSWORD; with it unset
the whole router disables itself.

Flow:
    POST /api/setup/send-code  {setup_key, api_id, api_hash, phone}
        -> {token, phone_code_hash}
    POST /api/setup/sign-in    {setup_key, token, code, password?}
        -> {session_string}   (or 401 need_password when 2FA is on)
"""

import os
import secrets
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..rate_limit import limiter
from ..utils import spawn_background

router = APIRouter()

# token -> {"client": Client, "phone": str, "hash": str, "ts": float}
_pending: dict = {}
_TTL_SECONDS = 600
# Rate limits cap new attempts at ~3/min, so 32 live logins is generous; the
# cap only exists so a leaked/abandoned token can never grow this forever.
_MAX_PENDING = 32


def _disconnect_later(client) -> None:
    """Disconnect off the request path, via the app's tracked-task helper."""
    coro = client.disconnect()
    try:
        spawn_background(coro)
    except Exception:
        # No running loop (e.g. a sync caller): close the coroutine so it is
        # not reported as "never awaited".
        coro.close()


def _cleanup_expired() -> None:
    now = time.monotonic()
    stale = [k for k, v in _pending.items() if now - v["ts"] > _TTL_SECONDS]
    for k in stale:
        entry = _pending.pop(k, None)
        if entry:
            _disconnect_later(entry["client"])


def _evict_oldest() -> None:
    """Drop the oldest pending login (and its client) once the cap is hit."""
    if not _pending:
        return
    key = next(iter(_pending))
    entry = _pending.pop(key, None)
    if entry:
        _disconnect_later(entry["client"])


def _check_key(provided: str | None) -> None:
    # PUBLIC RELEASE: this router is OFF until the operator deliberately opts in
    # by setting SETUP_PASSWORD. We deliberately do NOT fall back to
    # DEBUG_PASSWORD — debug mode must never silently expose a Telegram-login
    # relay through the server's IP.
    expected = os.environ.get("SETUP_PASSWORD")
    if not expected:
        raise HTTPException(503, "Setup helper disabled: set SETUP_PASSWORD to enable")
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(403, "Invalid setup key")


def _get_client(token: str):
    entry = _pending.get(token)
    if not entry:
        raise HTTPException(404, "Login attempt expired or unknown token — start again")
    return entry


class SendCodeIn(BaseModel):
    setup_key: str
    api_id: int
    api_hash: str
    phone: str


class SignInIn(BaseModel):
    setup_key: str
    token: str
    code: str
    password: str | None = None


@router.post("/setup/send-code")
@limiter.limit("3/minute")
async def setup_send_code(request: Request, body: SendCodeIn):
    _check_key(body.setup_key)
    _cleanup_expired()
    while len(_pending) >= _MAX_PENDING:
        _evict_oldest()
    from pyrogram import Client  # deferred: heavy import only when actually used

    token = uuid.uuid4().hex[:16]
    client = Client(
        f"setup_{token}",
        api_id=body.api_id,
        api_hash=body.api_hash,
        in_memory=True,
    )
    try:
        await client.connect()
        phone_code_hash = await client.send_code(body.phone.strip())
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        raise HTTPException(400, f"Telegram rejected the request: {e}")

    _pending[token] = {
        "client": client,
        "phone": body.phone.strip(),
        "hash": phone_code_hash,
        "ts": time.monotonic(),
    }
    return {"token": token}


@router.post("/setup/sign-in")
@limiter.limit("6/minute")
async def setup_sign_in(request: Request, body: SignInIn):
    _check_key(body.setup_key)
    _cleanup_expired()
    entry = _get_client(body.token)
    client = entry["client"]

    # Typed exceptions from Pyrogram/Kurigram. The old code imported an
    # all-caps "SESSION_PASSWORD" constant that does not exist in
    # pyrogram.errors, so the ImportError fired before the try block and
    # /setup/sign-in always 500'd — the 2FA branch never ran at all.
    from pyrogram.errors import (
        PasswordHashInvalid,
        PhoneCodeExpired,
        PhoneCodeInvalid,
        SessionPasswordNeeded,
    )

    try:
        await client.sign_in(entry["phone"], entry["hash"], body.code.strip())
    except SessionPasswordNeeded:
        if not body.password:
            raise HTTPException(401, "need_password")
        try:
            await client.check_password(body.password)
        except PasswordHashInvalid as e:
            raise HTTPException(403, f"Wrong 2FA password: {e}")
    except PhoneCodeInvalid as e:
        raise HTTPException(400, f"Invalid login code: {e}")
    except PhoneCodeExpired as e:
        raise HTTPException(400, f"Login code expired: {e}")
    except Exception as e:
        raise HTTPException(400, f"Sign-in failed: {e}")

    session_string = await client.export_session_string()
    _disconnect_later(client)
    _pending.pop(body.token, None)

    return {"session_string": session_string}
