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
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# token -> {"client": Client, "phone": str, "hash": str, "ts": float}
_pending: dict = {}
_TTL_SECONDS = 600


def _cleanup_expired() -> None:
    now = time.time()
    stale = [k for k, v in _pending.items() if now - v["ts"] > _TTL_SECONDS]
    for k in stale:
        entry = _pending.pop(k, None)
        if entry:
            try:
                asyncio.get_event_loop().create_task(entry["client"].disconnect())
            except Exception:
                pass


def _check_key(provided: str | None) -> None:
    expected = os.environ.get("SETUP_PASSWORD") or os.environ.get("DEBUG_PASSWORD")
    if not expected:
        raise HTTPException(503, "Setup helper disabled: no SETUP_PASSWORD configured")
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
async def setup_send_code(body: SendCodeIn):
    _check_key(body.setup_key)
    _cleanup_expired()
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
        "ts": time.time(),
    }
    return {"token": token}


@router.post("/setup/sign-in")
async def setup_sign_in(body: SignInIn):
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
            raise HTTPException(403, f"Wrong 2FA password: {e}")
    except Exception as e:
        raise HTTPException(400, f"Sign-in failed: {e}")

    session_string = await client.export_session_string()
    try:
        await client.disconnect()
    except Exception:
        pass
    _pending.pop(body.token, None)

    return {"session_string": session_string}
