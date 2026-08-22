"""Behavioral tests for the verify-code long-poll (login speed-up).

Mirrors test_fixes' temp_db pattern: a fresh sqlite DB per test with the
config/database/models modules reloaded, so the suite is order-independent.
"""
import asyncio
import importlib
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import conftest  # noqa: F401  (env vars must be set before app import)


@pytest_asyncio.fixture
async def temp_db():
    """Fresh database + reloaded modules (see test_fixes.temp_db)."""
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


async def _session():
    from app.database import async_session
    return async_session()


async def _seed_user(telegram_id: int) -> None:
    from app.models import User
    async with await _session() as db:
        db.add(User(telegram_id=telegram_id))
        await db.commit()


async def _seed_code(code: str, telegram_id: int | None = None, minutes: float = 10) -> None:
    from app.models import LoginCode
    async with await _session() as db:
        db.add(LoginCode(
            code=code,
            telegram_id=telegram_id,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=minutes),
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_wait_zero_returns_pending_immediately(temp_db):
    from app.main import app
    await _seed_code("LPZ000")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        t0 = time.monotonic()
        r = await c.post("/api/auth/verify-code", json={"code": "LPZ000"})
        elapsed = time.monotonic() - t0
    assert r.status_code == 202
    assert elapsed < 1.0, f"wait=0 must not hold the request (took {elapsed:.2f}s)"


@pytest.mark.asyncio
async def test_longpoll_returns_pending_after_wait(temp_db):
    from app.main import app
    await _seed_code("LPW000")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        t0 = time.monotonic()
        r = await c.post("/api/auth/verify-code", json={"code": "LPW000", "wait": 1})
        elapsed = time.monotonic() - t0
    assert r.status_code == 202
    assert 0.8 <= elapsed < 3.0, f"expected ~1s hold, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_longpoll_completes_when_claimed_mid_wait(temp_db):
    """The whole point: the response returns within one poll tick (~300ms)
    of the code being claimed, not after the full wait window."""
    from app.main import app
    await _seed_user(424242)
    await _seed_code("LPC000")

    async def claim_soon():
        from app.models import LoginCode
        from sqlalchemy import select
        await asyncio.sleep(1.0)
        async with await _session() as db:
            row = (await db.execute(select(LoginCode).where(LoginCode.code == "LPC000"))).scalar_one()
            row.telegram_id = 424242
            await db.commit()

    claimer = asyncio.create_task(claim_soon())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        t0 = time.monotonic()
        r = await c.post("/api/auth/verify-code", json={"code": "LPC000", "wait": 8})
        elapsed = time.monotonic() - t0
    await claimer

    assert r.status_code == 200, r.text
    assert "access_token" in r.json()
    # claimed at t=1.0s; response must arrive well before the 8s deadline
    assert elapsed < 3.5, f"long-poll should return ~300ms after claim, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_longpoll_expired_code_is_terminal(temp_db):
    from app.main import app
    await _seed_code("LPE000", minutes=-1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        t0 = time.monotonic()
        r = await c.post("/api/auth/verify-code", json={"code": "LPE000", "wait": 5})
        elapsed = time.monotonic() - t0
    assert r.status_code == 202
    assert elapsed < 1.5, f"expired code must not hold the request (took {elapsed:.2f}s)"
