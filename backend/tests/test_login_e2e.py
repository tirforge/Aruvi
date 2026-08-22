"""End-to-end login flow tests: exact sequences the web/TV/Android clients run.

generate-code -> long-poll verify (pending 202) -> bot-style atomic claim ->
long-poll verify completes with tokens -> token works on /auth/me.
"""
import importlib
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import conftest  # noqa: F401


@pytest_asyncio.fixture
async def temp_db():
    tmpdir = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{os.path.join(tmpdir, 'test.db')}"
    import app.config
    importlib.reload(app.config)
    import app.database
    importlib.reload(app.database)
    import app.models
    importlib.reload(app.models)
    from app.database import init_db
    await init_db()
    yield
    shutil.rmtree(tmpdir, ignore_errors=True)


async def _bot_style_claim(code: str, telegram_id: int) -> int:
    """Exactly what bot.py /start <code> does: atomic UPDATE."""
    from sqlalchemy import update
    from app.database import async_session
    from app.models import LoginCode
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with async_session() as db:
        result = await db.execute(
            update(LoginCode)
            .where(LoginCode.code == code)
            .where(LoginCode.expires_at > now)
            .where(LoginCode.telegram_id.is_(None))
            .values(telegram_id=telegram_id)
        )
        await db.commit()
        return result.rowcount


@pytest.mark.asyncio
async def test_full_login_flow_web_sequence(temp_db):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # 1. Client generates a code (unauthenticated)
        r = await c.post("/api/auth/generate-code")
        assert r.status_code == 200, r.text
        code = r.json()["code"]
        assert len(code) == 6

        # 2. Long-poll while pending — comes back 202 after the wait window
        t0 = time.monotonic()
        r = await c.post("/api/auth/verify-code", json={"code": code, "wait": 1})
        assert r.status_code == 202
        assert time.monotonic() - t0 >= 0.8

        # 3. User taps Start in Telegram -> bot's get_or_create_user runs,
        #    then the code is claimed for that telegram_id
        from app.database import async_session
        from app.models import User
        async with async_session() as db:
            db.add(User(telegram_id=777001))
            await db.commit()
        claimed = await _bot_style_claim(code, telegram_id=777001)
        assert claimed == 1

        # 4. Client's next poll returns tokens immediately
        r = await c.post("/api/auth/verify-code", json={"code": code, "wait": 8})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["access_token"] and body["refresh_token"]
        assert body["user"]["telegram_id"] == 777001

        # 5. The minted access token authenticates /auth/me
        me = await c.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200, me.text
        assert me.json()["telegram_id"] == 777001

        # 6. Code is single-use: a second verify (another device) gets 202
        r2 = await c.post("/api/auth/verify-code", json={"code": code, "wait": 0})
        assert r2.status_code == 202


@pytest.mark.asyncio
async def test_bot_minted_preclaimed_code_logs_in_immediately(temp_db):
    """/login on the phone mints a code ALREADY bound to the user; typing it
    on the TV must log in on the first verify."""
    from app.database import async_session
    from app.models import LoginCode, User
    from app.main import app

    async with async_session() as db:
        db.add(User(telegram_id=888001))
        db.add(LoginCode(
            code="PRECL1",
            telegram_id=888001,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10),
        ))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/auth/verify-code", json={"code": "PRECL1", "wait": 0})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["telegram_id"] == 888001


@pytest.mark.asyncio
async def test_legacy_code_endpoint_still_works(temp_db):
    """The manual-login path (web 'Submit code' button) posts /auth/code."""
    from app.main import app
    from app.database import async_session
    from app.models import LoginCode, User

    async with async_session() as db:
        db.add(User(telegram_id=999001))
        db.add(LoginCode(
            code="LEGAC1",
            telegram_id=999001,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10),
        ))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        pending = await c.post("/api/auth/code", json={"code": "ZZZZZZ"})
        assert pending.status_code == 202  # unknown code, wait=0 -> immediate

        ok = await c.post("/api/auth/code", json={"code": "LEGAC1"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["access_token"]


@pytest.mark.asyncio
async def test_claimed_code_with_missing_user_is_terminal_410(temp_db):
    """Regression: an account row deleted after claiming used to 404 forever
    (web polled silently, Android said 'invalid code'). Must be a terminal
    410 with an actionable message."""
    from app.main import app
    from app.database import async_session
    from app.models import LoginCode

    async with async_session() as db:
        db.add(LoginCode(
            code="ORPHN1",
            telegram_id=123123,  # claimed, but no User row exists
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10),
        ))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/auth/verify-code", json={"code": "ORPHN1", "wait": 0})
        assert r.status_code == 410
        assert "generate a new code" in r.json()["detail"].lower()
