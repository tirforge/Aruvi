"""
Google Drive OAuth callback endpoint.
User's browser hits this after approving Google consent.
We exchange the code for tokens, store on the User record, notify via bot.
"""

import json
import logging
from html import escape as html_escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..database import async_session
from ..models import User
from ..gdrive import exchange_code, consume_state, generate_auth_url
from ..config import get_settings
from ..auth import verify_token_payload
from sqlalchemy import select

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/gdrive", tags=["GDrive"])
settings = get_settings()


PAGE_CSS = """\
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#e8eaed;display:flex;align-items:center;justify-content:center;
min-height:100vh;margin:0;padding:20px;
}
.card{
background:#fff;border-radius:24px;padding:48px 40px 40px;
max-width:400px;width:100%;text-align:center;
box-shadow:0 1px 3px rgba(0,0,0,.08),0 4px 24px rgba(0,0,0,.06);
}
.icon-wrap{width:72px;height:72px;border-radius:50%;display:flex;
align-items:center;justify-content:center;margin:0 auto 24px;
background:#e8f5e9;
}
.icon-wrap svg{width:40px;height:40px}
h1{font-size:22px;font-weight:600;color:#202124;margin-bottom:8px}
p{font-size:14px;color:#5f6368;line-height:1.5;margin-bottom:4px}
.sub{font-size:13px;color:#9aa0a6;margin-top:16px;padding:0 8px}
.badge{display:inline-block;background:#f1f3f4;border-radius:16px;
padding:6px 16px;font-size:13px;color:#5f6368;margin-top:20px}
.badge svg{vertical-align:middle;margin-right:4px}
.btn{display:block;background:#1a73e8;color:#fff;text-decoration:none;
padding:12px;border-radius:20px;font-size:14px;font-weight:500;
margin-top:28px;transition:background .2s}
.btn:hover{background:#1557b0}
.error .icon-wrap{background:#fce8e6}
.error .icon-wrap svg .check{stroke:#d93025}
</style>"""

CHECK_SVG = """\
<svg viewBox="0 0 24 24" fill="none" stroke="#1e8e3e" stroke-width="2.5"
stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="10" stroke="#1e8e3e" fill="none" opacity="0.2"/>
<path class="check" d="M7 13l3 3 7-7"/>
</svg>"""

CROSS_SVG = """\
<svg viewBox="0 0 24 24" fill="none" stroke="#d93025" stroke-width="2.5"
stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="10" stroke="#d93025" fill="none" opacity="0.2"/>
<path class="check" d="M8 8l8 8M16 8l-8 8"/>
</svg>"""

DRIVE_SVG = """\
<svg viewBox="0 0 24 24" fill="#5f6368" width="14" height="14">
<path d="M12 2L2 18h8l2-4 2 4h8L12 2zM2 20v2h20v-2H2z"/>
</svg>"""


def _page(icon_svg: str, title: str, body: str, extra: str = "", is_error: bool = False) -> str:
    cls = " error" if is_error else ""
    home = settings.web_base_url
    title = html_escape(title)
    body = html_escape(body)
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} — Aruvi</title>{PAGE_CSS}</head>
<body>
<div class="card{cls}">
<img src="/aruvi-brand.png" alt="Aruvi" style="width:48px;height:48px;border-radius:12px;margin-bottom:16px">
<div class="icon-wrap">{icon_svg}</div>
<h1>{title}</h1>
<p>{body}</p>
{extra}
<a class="btn" href="{home}">Go to Aruvi</a>
</div>
</body>
</html>"""


async def _resolve_user(request: Request):
    """Extract token from query, verify it, return User or None."""
    token = request.query_params.get("token")
    if not token:
        return None
    payload = verify_token_payload(token)
    if not payload:
        return None
    try:
        telegram_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return None
        token_version = payload.get("ver")
        if token_version is not None and token_version < user.auth_version:
            return None
        return user


@router.get("/auth")
async def gdrive_auth(request: Request):
    """Redirect user to Google OAuth consent screen.

    Requires ?token= query param. If already connected, returns status.
    """
    user = await _resolve_user(request)
    if not user:
        return HTMLResponse(
            _page(CROSS_SVG, "Authentication required",
                  "Please login via Telegram first.",
                  '<p class="sub">Use /web in the bot to get a login link.</p>',
                  is_error=True),
            status_code=401,
        )

    if user.gdrive_token:
        return HTMLResponse(
            _page(CHECK_SVG, "Already connected",
                  "Your Google Drive is already linked to Aruvi.",
                  '<div class="badge">' + DRIVE_SVG + ' Google Drive · Connected</div>')
        )

    auth_url = generate_auth_url(user.telegram_id)
    return RedirectResponse(auth_url)


@router.get("/auth/callback")
async def gdrive_auth_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return HTMLResponse(
            _page(CROSS_SVG, "Authorization denied",
                  "You denied the Google Drive connection request.",
                  f"<p class=\"sub\">{html_escape(error)}</p>",
                  is_error=True),
            status_code=400,
        )

    if not code or not state:
        return HTMLResponse(
            _page(CROSS_SVG, "Missing parameters",
                  "The callback URL is missing required parameters.",
                  is_error=True),
            status_code=400,
        )

    try:
        telegram_id, code_verifier = consume_state(state)
    except ValueError as e:
        return HTMLResponse(
            _page(CROSS_SVG, "Session expired",
                  str(e),
                  '<p class="sub">Please tap "Save to Drive" again in Telegram.</p>',
                  is_error=True),
            status_code=400,
        )

    try:
        token_dict = await exchange_code(code, code_verifier)
    except Exception as e:
        _log.exception("GDrive token exchange failed for user %s", telegram_id)
        return HTMLResponse(
            _page(CROSS_SVG, "Token exchange failed",
                  str(e),
                  '<p class="sub">Please try again.</p>',
                  is_error=True),
            status_code=500,
        )

    # Store token on user record
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.gdrive_token = json.dumps(token_dict)
            await db.commit()

    # Notify user via Telegram bot
    try:
        from ..telegram import tg_client
        await tg_client.send_message(
            telegram_id,
            "✅ **Google Drive connected!**\n\n"
            "Your Drive account is now linked. "
            "Use the button on any file to upload it to your "
            "**Aruvi** folder in Google Drive.",
        )
    except Exception as e:
        _log.warning("Could not notify user %s: %s", telegram_id, e)

    return HTMLResponse(
        _page(CHECK_SVG, "Connected",
              "Your Google Drive is now linked to Aruvi.",
              '<div class="badge">' + DRIVE_SVG + ' Google Drive · Connected</div>'
              '<p class="sub">You can close this tab.</p>')
    )
