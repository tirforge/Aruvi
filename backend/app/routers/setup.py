"""One-shot Telegram login helper for self-hosters.

Generates a Pyrogram session string server-side so users never have to run
MTProto in a browser. Every endpoint is gated by SETUP_PASSWORD (falling back
to DEBUG_PASSWORD); with neither set the whole router disables itself.

Flow:
    POST /api/setup/send-code  {setup_key, api_id, api_hash, phone}
        -> {token, phone_code_hash}
    POST /api/setup/sign-in    {setup_key, token, code, password?}
        -> {session_string}   (or 401 need_password when 2FA is on)
"""

import asyncio
import os
import secrets
import time
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..rate_limit import limiter

_log = logging.getLogger(__name__)

router = APIRouter()

# token -> {"client": Client, "phone": str, "hash": str, "ts": float}
_pending: dict = {}
_TTL_SECONDS = 600
_PENDING_MAX = 100


def _cleanup_expired() -> None:
    now = time.time()
    stale = [k for k, v in _pending.items() if now - v["ts"] > _TTL_SECONDS]
    for k in stale:
        entry = _pending.pop(k, None)
        if entry:
            try:
                asyncio.get_running_loop().create_task(
                    entry["client"].disconnect()
                )
            except RuntimeError:
                pass
            except Exception:
                pass
    # Bound memory: evict oldest when over cap (request-driven cleanup only).
    if len(_pending) > _PENDING_MAX:
        oldest = sorted(_pending.items(), key=lambda kv: kv[1]["ts"])
        for k, _ in oldest[: len(_pending) - _PENDING_MAX]:
            _pending.pop(k, None)


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
    setup_key: str = Field(max_length=256)
    api_id: int = Field(ge=1, le=2**31 - 1)
    api_hash: str = Field(min_length=1, max_length=256)
    phone: str = Field(min_length=1, max_length=32)


class SignInIn(BaseModel):
    setup_key: str = Field(max_length=256)
    token: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=32)
    password: str | None = Field(default=None, max_length=256)


@router.post("/setup/send-code")
@limiter.limit("3/minute")
async def setup_send_code(request: Request, body: SendCodeIn):
    _check_key(body.setup_key)
    _cleanup_expired()
    from pyrogram import Client  # deferred: heavy import only when actually used

    token = secrets.token_hex(16)
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
        _log.warning("setup send-code rejected: %s", e)
        raise HTTPException(400, "Telegram rejected the request")

    _pending[token] = {
        "client": client,
        "phone": body.phone.strip(),
        "hash": phone_code_hash,
        "ts": time.time(),
    }
    return {"token": token}


@router.post("/setup/sign-in")
@limiter.limit("6/minute")
async def setup_sign_in(request: Request, body: SignInIn):
    _check_key(body.setup_key)
    _cleanup_expired()
    entry = _get_client(body.token)
    client = entry["client"]

    from pyrogram.errors import SESSION_PASSWORD_NEEDED

    try:
        await client.sign_in(entry["phone"], entry["hash"], body.code.strip())
    except SESSION_PASSWORD_NEEDED:
        if not body.password:
            raise HTTPException(401, "need_password")
        try:
            await client.check_password(body.password)
        except Exception as e:
            _log.warning("setup 2FA failed: %s", e)
            raise HTTPException(403, "Wrong 2FA password")
    except Exception as e:
        _log.warning("setup sign-in failed: %s", e)
        raise HTTPException(400, "Sign-in failed")

    session_string = await client.export_session_string()
    try:
        await client.disconnect()
    except Exception:
        pass
    _pending.pop(body.token, None)

    return {"session_string": session_string}
