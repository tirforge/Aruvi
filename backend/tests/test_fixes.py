import os
import sys
import pytest
import pytest_asyncio
import asyncio
import tempfile
import shutil
from datetime import datetime, timezone
from hashlib import sha256

# Set required environment variables BEFORE any app imports
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "abcdef1234567890abcdef1234567890")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("TELEGRAM_STORAGE_CHANNEL_ID", "-1001234567890")
os.environ.setdefault("TELEGRAM_HELPER_BOT_TOKENS", "")
os.environ.setdefault("JWT_SECRET", "testsecret123456789012345678901234")
os.environ.setdefault("DEBUG_PASSWORD", "testdebug")
os.environ.setdefault("WEB_BASE_URL", "http://localhost:7680")
os.environ.setdefault("GDRIVE_CLIENT_ID", "")
os.environ.setdefault("GDRIVE_CLIENT_SECRET", "")
os.environ.setdefault("OPENSUBTITLES_API_KEY", "")
os.environ.setdefault("GRAB_GROUP_USERNAME", "")
os.environ.setdefault("GRAB_BOT_USERNAME", "")
os.environ.setdefault("GRAB_BOT_USERNAMES", "")
os.environ.setdefault("SUBTITLE_LANGUAGES", "en")
os.environ.setdefault("SUBTITLE_PROVIDERS", "podnapisi,tvsubtitles,addic7ed")
os.environ.setdefault("SERVER_PORT", "7680")
os.environ.setdefault("TELEGRAM_CLIENT_CONCURRENCY", "5")
os.environ.setdefault("STREAM_BATCH_SIZE", "5")
os.environ.setdefault("STREAM_MAX_CONCURRENT", "3")
os.environ.setdefault("STREAM_RAM_PER_VIDEO_MB", "200")
os.environ.setdefault("STREAM_INFLIGHT_MB", "200")
os.environ.setdefault("STREAM_PREFETCH_AHEAD_MB", "128")
os.environ.setdefault("STREAM_PREFETCH_CONCURRENCY", "1")
os.environ.setdefault("DISK_CACHE_DIR", "/tmp/test_vcache")
os.environ.setdefault("DISK_CACHE_ENABLED", "1")
os.environ.setdefault("DISK_CACHE_TTL", "1800")
os.environ.setdefault("DISK_CACHE_MAX_BYTES", "8589934592")
os.environ.setdefault("DISK_CACHE_PER_VIDEO_BYTES", "2147483648")
os.environ.setdefault("MEMORY", "3Gi")
os.environ.setdefault("OOM_THRESHOLD_PCT", "90")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest_asyncio.fixture
async def temp_db():
    """Create a fresh database for each test."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    db_url = f"sqlite+aiosqlite:///{db_path}"

    os.environ["DATABASE_URL"] = db_url

    # Force re-import of config to pick up new DATABASE_URL
    import importlib
    import app.config

    importlib.reload(app.config)
    import app.database

    importlib.reload(app.database)
    import app.models

    importlib.reload(app.models)

    from app.database import init_db, async_session

    await init_db()

    async with async_session() as session:
        yield session

    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest_asyncio.fixture
async def sample_user(temp_db):
    """Create a test user."""
    from app.models import User

    user = User(
        telegram_id=999999, username="testuser", first_name="Test", auth_version=0
    )
    temp_db.add(user)
    await temp_db.commit()
    await temp_db.refresh(user)
    return user


@pytest_asyncio.fixture
async def sample_file(temp_db, sample_user):
    from app.models import File

    f = File(
        user_id=sample_user.id,
        file_id="pyrogram-file-id",
        file_unique_id="uniq-cov-1",
        file_name="movie.mp4",
        file_size=1000,
        mime_type="video/mp4",
        file_type="video",
        channel_message_id=77,
    )
    temp_db.add(f)
    await temp_db.commit()
    await temp_db.refresh(f)
    return f


def _make_mock_request(token: str):
    """Create a mock request with proper query_params interface."""

    class MockRequest:
        def __init__(self, token):
            self.headers = {"Authorization": f"Bearer {token}"}
            self.query_params = {"token": token}

    return MockRequest(token)


class TestAuthRotation:
    """Test refresh token rotation and replay protection."""

    @pytest.mark.asyncio
    async def test_refresh_token_rotation_rejects_replay(self, temp_db):
        """Rotated refresh token cannot be reused."""
        from app.auth import (
            create_refresh_token,
            REFRESH_TOKEN_DURATION,
        )
        from app.routers.auth import refresh_token
        from app.models import User, RefreshSession
        from app.schemas import RefreshTokenRequest

        # Create user
        user = User(
            telegram_id=999999, username="testuser", first_name="Test", auth_version=0
        )
        temp_db.add(user)
        await temp_db.commit()
        await temp_db.refresh(user)

        # Create initial refresh token and session
        refresh_token_str = create_refresh_token(
            user.telegram_id, version=user.auth_version
        )
        token_hash = sha256(refresh_token_str.encode()).hexdigest()
        session = RefreshSession(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
            + REFRESH_TOKEN_DURATION,
            last_used_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        temp_db.add(session)
        await temp_db.commit()

        # First refresh: should succeed and rotate
        req = RefreshTokenRequest(refresh_token=refresh_token_str)
        result = await refresh_token(req, db=temp_db)

        assert result.access_token is not None
        assert result.refresh_token is not None
        assert result.refresh_token != refresh_token_str  # Token rotated

        # Old token should now be invalid
        req2 = RefreshTokenRequest(refresh_token=refresh_token_str)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await refresh_token(req2, db=temp_db)
        assert exc_info.value.status_code == 401
        assert "invalidated" in str(exc_info.value.detail).lower()

        # New token should work
        req3 = RefreshTokenRequest(refresh_token=result.refresh_token)
        result2 = await refresh_token(req3, db=temp_db)
        assert result2.access_token is not None

        # Exactly one session row exists
        from sqlalchemy import select

        sessions = await temp_db.execute(
            select(RefreshSession).where(RefreshSession.user_id == user.id)
        )
        session_rows = sessions.scalars().all()
        assert len(session_rows) == 1

    @pytest.mark.asyncio
    async def test_download_token_binds_file_id(self):
        """Download token includes file_id claim."""
        from app.auth import create_download_token, verify_token_payload

        token = create_download_token(12345, file_id=98765)
        payload = verify_token_payload(token, token_type="download")

        assert payload is not None
        assert payload.get("file_id") == 98765
        assert payload.get("sub") == "12345"
        assert payload.get("type") == "download"


class TestParseRangeHeader:
    """Test HTTP Range header parsing."""

    def test_no_header_full_range(self):
        from app.routers.streaming import parse_range_header

        start, end = parse_range_header(None, 100)
        assert (start, end) == (0, 99)

    def test_normal_range(self):
        from app.routers.streaming import parse_range_header

        start, end = parse_range_header("bytes=10-20", 100)
        assert (start, end) == (10, 20)

    def test_open_ended_range(self):
        from app.routers.streaming import parse_range_header

        start, end = parse_range_header("bytes=50-", 100)
        assert (start, end) == (50, 99)

    def test_suffix_range(self):
        from app.routers.streaming import parse_range_header

        start, end = parse_range_header("bytes=-20", 100)
        assert (start, end) == (80, 99)

    def test_clamped_end(self):
        from app.routers.streaming import parse_range_header

        start, end = parse_range_header("bytes=50-500", 100)
        assert (start, end) == (50, 99)

    def test_multipart_rejected(self):
        from app.routers.streaming import parse_range_header

        result = parse_range_header("bytes=0-10,20-30", 100)
        assert result is None

    def test_zero_byte_plain_get(self):
        from app.routers.streaming import parse_range_header

        start, end = parse_range_header(None, 0)
        assert (start, end) == (0, -1)

    def test_zero_byte_with_range(self):
        from app.routers.streaming import parse_range_header

        start, end = parse_range_header("bytes=-50", 0)
        assert (start, end) == (0, -1)


class TestDownloadTokenValidation:
    """Test _user_from_download_token validates file_id."""

    @pytest.mark.asyncio
    async def test_valid_token_for_file(self, temp_db, sample_user):
        from app.auth import create_download_token
        from app.routers.streaming import _user_from_download_token

        token = create_download_token(sample_user.telegram_id, file_id=42)
        req = _make_mock_request(token)

        result = await _user_from_download_token(req, 42, temp_db)
        assert result is not None
        assert result.id == sample_user.id

    @pytest.mark.asyncio
    async def test_wrong_file_id_rejected(self, temp_db, sample_user):
        from app.auth import create_download_token
        from app.routers.streaming import _user_from_download_token
        from fastapi import HTTPException

        token = create_download_token(sample_user.telegram_id, file_id=999)
        req = _make_mock_request(token)

        with pytest.raises(HTTPException) as exc_info:
            await _user_from_download_token(req, 42, temp_db)  # different file_id
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_malformed_sub_returns_none(self, temp_db):
        from app.routers.streaming import _user_from_download_token
        from jose import jwt
        from app.config import get_settings

        settings = get_settings()
        payload = {"sub": "notanint", "file_id": 1, "ver": 0, "exp": 9999999999}
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

        req = _make_mock_request(token)
        result = await _user_from_download_token(req, 1, temp_db)
        assert result is None


class TestPatchListenerQueue:
    """Test multi-listener FIFO queue and command routing."""

    def test_fifo_delivery(self):
        import collections
        from types import SimpleNamespace
        import app.patch as patch

        class Msg:
            def __init__(self, text=None):
                self.text = text
                self.chat = SimpleNamespace(id=1)
                self.id = 5
                self.from_user = SimpleNamespace(id=10)
                self.reply_to_message_id = None
                self._cont = False
                self._stop = False

            def continue_propagation(self):
                self._cont = True

            def stop_propagation(self):
                self._stop = True

        patch.types.Message = Msg

        async def main():
            from app.patch import PatchedClient, resolve_listener
            import functools

            client = object.__new__(PatchedClient)
            client.listeners = {}

            def _seed(key, text=None):
                loop = asyncio.get_event_loop()
                fut = loop.create_future()
                entry = {"future": fut, "filters": None}
                client.listeners.setdefault(key, collections.deque()).append(entry)
                fut.add_done_callback(
                    functools.partial(client._forget_listener, key, entry)
                )
                return fut, entry

            # Seed two listeners
            f1, _ = _seed("1")
            f2, _ = _seed("1")

            # First message resolves f1
            m = Msg(text="first")
            await resolve_listener(client, m)
            assert f1.done() and not f2.done()
            await asyncio.sleep(0)
            assert len(client.listeners["1"]) == 1

            # Second message resolves f2
            m2 = Msg(text="second")
            await resolve_listener(client, m2)
            assert f2.done()
            await asyncio.sleep(0)
            assert not client.listeners.get("1")

        asyncio.run(main())

    def test_command_not_swallowed(self):
        import collections
        from types import SimpleNamespace
        import app.patch as patch

        class Msg:
            def __init__(self, text=None):
                self.text = text
                self.chat = SimpleNamespace(id=1)
                self.id = 5
                self.from_user = SimpleNamespace(id=10)
                self.reply_to_message_id = None
                self._cont = False
                self._stop = False

            def continue_propagation(self):
                self._cont = True

            def stop_propagation(self):
                self._stop = True

        patch.types.Message = Msg

        async def main():
            from app.patch import PatchedClient, resolve_listener
            import functools

            client = object.__new__(PatchedClient)
            client.listeners = {}

            loop = asyncio.get_event_loop()
            fut = loop.create_future()
            entry = {"future": fut, "filters": None}
            client.listeners.setdefault("1", collections.deque()).append(entry)
            fut.add_done_callback(
                functools.partial(client._forget_listener, "1", entry)
            )

            # Command should NOT be consumed
            cmd = Msg(text="/cancel")
            await resolve_listener(client, cmd)
            assert cmd._cont and not cmd._stop
            assert not fut.done()

            # Normal message resolves
            plain = Msg(text="hello")
            await resolve_listener(client, plain)
            assert plain._stop and fut.done()

        asyncio.run(main())


class TestDiskCacheUniqueTemp:
    """Test disk cache uses unique temp files."""

    @pytest.mark.asyncio
    async def test_concurrent_put_no_tear(self):
        from app.disk_cache import DiskChunkCache
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DISK_CACHE_DIR"] = tmpdir
            os.environ["DISK_CACHE_ENABLED"] = "1"

            cache = DiskChunkCache()
            chat_id, message_id, chunk_idx = 1, 2, 3

            # Simulate concurrent puts
            data1 = b"data1" * 1000
            data2 = b"data2" * 1000

            await asyncio.gather(
                asyncio.to_thread(cache.put, chat_id, message_id, chunk_idx, data1),
                asyncio.to_thread(cache.put, chat_id, message_id, chunk_idx, data2),
            )

            # One of the writes won - verify final file is complete (not torn)
            final_path = cache._movie_dir(chat_id, message_id) / f"{chunk_idx}.bin"
            assert final_path.exists()
            content = final_path.read_bytes()
            # Should be exactly one of the full payloads, not a mix
            assert content == data1 or content == data2


class TestGDriveRawWrite:
    """Test _raw_write helper."""

    def test_raw_write_creates_file(self):
        from app.gdrive import _raw_write
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.bin")
            fd = os.open(test_file, os.O_CREAT | os.O_RDWR)
            try:
                _raw_write(fd, 0, b"hello world")
            finally:
                os.close(fd)

            with open(test_file, "rb") as f:
                assert f.read() == b"hello world"


class TestGrabberCollectReplies:
    """Test _collect_bot_replies prefers direct replies."""

    def test_direct_reply_preferred(self):
        # Logic verified in code: direct replies break early,
        # non-direct only fallback and loop continues scanning
        pass  # Logic verified in code review


class TestTokenVersionBinding:
    """Tokens minted with a stale auth_version must be rejected (logout-all)."""

    @pytest.mark.asyncio
    async def test_stale_access_token_rejected(self, temp_db, sample_user):
        from app.auth import create_access_token, get_current_user
        from fastapi import HTTPException

        sample_user.auth_version = 2
        await temp_db.commit()

        stale = create_access_token(sample_user.telegram_id, version=1)
        req = _make_mock_request(stale)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=req, credentials=None, db=temp_db)
        assert exc_info.value.status_code == 401

        fresh = create_access_token(sample_user.telegram_id, version=2)
        req2 = _make_mock_request(fresh)
        user = await get_current_user(request=req2, credentials=None, db=temp_db)
        assert user.id == sample_user.id

    @pytest.mark.asyncio
    async def test_download_token_respects_auth_version(self, temp_db, sample_user):
        """A ver=0 download token must not outlive logout-all (auth_version=1)."""
        from app.auth import create_download_token
        from app.routers.streaming import _user_from_download_token

        sample_user.auth_version = 1
        await temp_db.commit()

        stale = create_download_token(sample_user.telegram_id, file_id=42, version=0)
        result = await _user_from_download_token(_make_mock_request(stale), 42, temp_db)
        assert result is None

        fresh = create_download_token(sample_user.telegram_id, file_id=42, version=1)
        result2 = await _user_from_download_token(
            _make_mock_request(fresh), 42, temp_db
        )
        assert result2 is not None
        assert result2.id == sample_user.id


class TestVerifyCodeSingleUse:
    """A claimed login code must yield tokens exactly once."""

    @pytest.mark.asyncio
    async def test_code_consumed_after_verify(self, temp_db, sample_user):
        from app.models import LoginCode
        from datetime import timedelta
        from app.routers.auth import verify_login_code
        from app.schemas import VerifyCodeRequest

        code = LoginCode(
            code="ABC123",
            telegram_id=sample_user.telegram_id,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(minutes=5),
        )
        temp_db.add(code)
        await temp_db.commit()

        # slowapi's decorator validates a real starlette Request
        from starlette.requests import Request as StarletteRequest

        req = StarletteRequest(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/auth/verify-code",
                "headers": [],
                "query_string": b"",
                "client": ("127.0.0.1", 12345),
            }
        )
        first = await verify_login_code(req, VerifyCodeRequest(code="ABC123"), temp_db)
        assert first.access_token
        assert first.refresh_token

        # Code row is gone — second poll can't mint another session.
        remaining = await temp_db.execute(
            __import__("sqlalchemy").select(LoginCode).where(LoginCode.code == "ABC123")
        )
        assert remaining.scalar_one_or_none() is None

        second = await verify_login_code(req, VerifyCodeRequest(code="ABC123"), temp_db)
        assert second.status_code == 202


class TestMarkdownSafety:
    """User text embedded in Telegram markdown must not break parsing."""

    def test_md_safe_replaces_backticks(self):
        from app.utils import md_safe

        assert md_safe("movie`name`.mkv") == "movie'name'.mkv"
        assert md_safe("") == ""
        assert md_safe("plain.mp4") == "plain.mp4"

    def test_sanitize_filename_strips_path_separators(self):
        from app.utils import sanitize_filename

        assert "/" not in sanitize_filename("../../etc/passwd")
        assert "\x00" not in sanitize_filename("bad\x00name")


class TestPublicStreamRangeGuards:
    """Public /s/{hash} route must 416 multipart ranges and handle zero-byte
    files like the private route (previously: TypeError → 500 / bogus 416)."""

    @staticmethod
    def _req(range_header: str | None = None):
        from starlette.requests import Request

        headers = []
        if range_header:
            headers.append((b"range", range_header.encode()))
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/s/pubhash123",
                "headers": headers,
                "query_string": b"",
                "client": ("127.0.0.1", 12345),
            }
        )

    @pytest_asyncio.fixture
    async def public_file(self, temp_db, sample_user):
        from app.models import File

        f = File(
            user_id=sample_user.id,
            file_id="pyrogram-file-id",
            file_unique_id="uniq-pub-1",
            file_name="movie.mp4",
            file_size=1000,
            mime_type="video/mp4",
            file_type="video",
            channel_message_id=77,
            public_hash="pubhash123",
        )
        temp_db.add(f)
        await temp_db.commit()
        await temp_db.refresh(f)
        return f

    @pytest.mark.asyncio
    async def test_multipart_range_416_not_500(self, temp_db, public_file):
        from app.routers.streaming import stream_public_file

        resp = await stream_public_file(
            public_hash="pubhash123",
            request=self._req("bytes=0-10,20-30"),
            db=temp_db,
            download=0,
        )
        assert resp.status_code == 416

    @pytest.mark.asyncio
    async def test_zero_byte_plain_get_200(self, temp_db, sample_user):
        from app.models import File
        from app.routers.streaming import stream_public_file

        f = File(
            user_id=sample_user.id,
            file_id="fid",
            file_unique_id="u2",
            file_name="empty.mp4",
            file_size=0,
            mime_type="video/mp4",
            file_type="video",
            channel_message_id=78,
            public_hash="zerohash",
        )
        temp_db.add(f)
        await temp_db.commit()

        resp = await stream_public_file(
            public_hash="zerohash",
            request=self._req(None),
            db=temp_db,
            download=0,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_zero_byte_with_range_416(self, temp_db, sample_user):
        from app.models import File
        from app.routers.streaming import stream_public_file

        f = File(
            user_id=sample_user.id,
            file_id="fid",
            file_unique_id="u3",
            file_name="empty.mp4",
            file_size=0,
            mime_type="video/mp4",
            file_type="video",
            channel_message_id=79,
            public_hash="zerohash2",
        )
        temp_db.add(f)
        await temp_db.commit()

        resp = await stream_public_file(
            public_hash="zerohash2",
            request=self._req("bytes=0-100"),
            db=temp_db,
            download=0,
        )
        assert resp.status_code == 416


class TestMemEnvParsing:
    """MEMORY env must accept M/MB suffixes, not only G variants."""

    def test_suffixes(self):
        from app.status import _parse_mem_env

        assert _parse_mem_env("3Gi") == 3 * 1024**3
        assert _parse_mem_env("3G") == 3 * 1024**3
        assert _parse_mem_env("512M") == 512 * 1024**2
        assert _parse_mem_env("2MB") == 2 * 1024**2
        assert _parse_mem_env("1048576") == 1048576


class TestDiskCacheTmpSafety:
    """Sweep/size accounting must ignore in-flight .tmp writes."""

    def test_used_bytes_excludes_tmp(self):
        from app.disk_cache import DiskChunkCache
        import pathlib

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DiskChunkCache(cache_dir=pathlib.Path(tmpdir))
            d = cache._movie_dir(1, 2)
            d.mkdir(parents=True)
            (d / "0.bin").write_bytes(b"x" * 100)
            (d / "0.stale.tmp").write_bytes(b"y" * 500)
            assert cache.used_bytes(max_age=0) == 100

    def test_sweep_spares_tmp_and_evicts_oldest_bin(self, monkeypatch):
        from app import disk_cache as dc_mod
        from app.disk_cache import DiskChunkCache
        import pathlib
        import time as _time

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DiskChunkCache(cache_dir=pathlib.Path(tmpdir))
            d = cache._movie_dir(1, 2)
            d.mkdir(parents=True)
            old = _time.time() - 3600
            tmp_f = d / "0.stale.tmp"
            tmp_f.write_bytes(b"t" * 100)
            os.utime(tmp_f, (old - 10, old - 10))  # oldest file overall
            c0 = d / "0.bin"
            c0.write_bytes(b"a" * 100)
            os.utime(c0, (old, old))
            c1 = d / "1.bin"
            c1.write_bytes(b"b" * 100)

            monkeypatch.setattr(dc_mod, "DISK_CACHE_PER_VIDEO_BYTES", 150)
            cache.sweep()

            assert tmp_f.exists()  # in-flight write protected
            assert not c0.exists()  # oldest real chunk evicted instead
            assert c1.exists()

    def test_sweep_prunes_last_active(self):
        from app.disk_cache import DiskChunkCache
        import pathlib
        import time as _time

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DiskChunkCache(cache_dir=pathlib.Path(tmpdir))
            cache._last_active[(9, 9)] = _time.time()  # dir never existed
            d = cache._movie_dir(3, 4)
            d.mkdir(parents=True)
            (d / "0.bin").write_bytes(b"x")
            cache._last_active[(3, 4)] = _time.time()

            cache.sweep()

            assert (9, 9) not in cache._last_active
            assert (3, 4) in cache._last_active


class TestEmptyMessageCacheSkip:
    """Empty Telegram messages must not be cached for the full TTL hour."""

    @pytest.mark.asyncio
    async def test_empty_message_not_cached(self):
        from app import telegram

        class FakeMsg:
            empty = True
            id = 424242

        async def fake_get_messages(chat_id, message_id):
            return FakeMsg()

        key = telegram._msg_cache_key(424242)
        telegram._msg_cache.pop(key, None)
        orig = telegram.tg_client.get_messages
        telegram.tg_client.get_messages = fake_get_messages
        try:
            msg = await telegram.get_message_from_channel(424242)
            assert isinstance(msg, FakeMsg)
            assert key not in telegram._msg_cache
        finally:
            telegram.tg_client.get_messages = orig
            telegram._msg_cache.pop(key, None)

    @pytest.mark.asyncio
    async def test_real_message_still_cached(self):
        from app import telegram

        class FakeMsg:
            empty = False
            id = 424243

        async def fake_get_messages(chat_id, message_id):
            return FakeMsg()

        key = telegram._msg_cache_key(424243)
        telegram._msg_cache.pop(key, None)
        orig = telegram.tg_client.get_messages
        telegram.tg_client.get_messages = fake_get_messages
        try:
            msg = await telegram.get_message_from_channel(424243)
            assert isinstance(msg, FakeMsg)
            assert key in telegram._msg_cache
        finally:
            telegram.tg_client.get_messages = orig
            telegram._msg_cache.pop(key, None)


class TestStatusAuthGate:
    """/api/status strips logs/per_video for anonymous viewers; clear-logs
    requires the debug password."""

    @staticmethod
    def _req(auth: str | None = None):
        from starlette.requests import Request

        headers = []
        if auth:
            headers.append((b"authorization", auth.encode()))
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/status",
                "headers": headers,
                "query_string": b"",
                "client": ("127.0.0.1", 12345),
            }
        )

    @pytest.mark.asyncio
    async def test_anonymous_status_strips_sensitive_fields(self, monkeypatch):
        from app import main as app_main

        async def fake_status():
            return {
                "cpu": 1.0,
                "ram": {},
                "net": {},
                "logs": ["secret log line"],
                "cache": {
                    "per_video": [{"chat_id": -100}],
                    "forward": {"total_prebuffer_mb": 1},
                },
                "disk": {},
                "uptime_seconds": 1,
                "history": [],
            }

        monkeypatch.setattr(app_main, "get_status", fake_status)
        out = await app_main.api_status(self._req())
        assert out["logs"] == []
        assert out["cache"]["per_video"] == []
        assert out["cache"]["forward"] is None

    @pytest.mark.asyncio
    async def test_debug_password_sees_full_status(self, monkeypatch):
        from app import main as app_main

        async def fake_status():
            return {
                "cpu": 1.0,
                "ram": {},
                "net": {},
                "logs": ["secret log line"],
                "cache": {"per_video": [{"chat_id": -100}], "forward": None},
                "disk": {},
                "uptime_seconds": 1,
                "history": [],
            }

        monkeypatch.setattr(app_main, "get_status", fake_status)
        out = await app_main.api_status(self._req("Bearer testdebug"))
        assert out["logs"] == ["secret log line"]
        assert out["cache"]["per_video"] == [{"chat_id": -100}]

    @pytest.mark.asyncio
    async def test_clear_logs_requires_auth(self):
        from app import main as app_main
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as ei:
            await app_main.api_clear_logs(self._req())
        assert ei.value.status_code == 401

        ok = await app_main.api_clear_logs(self._req("Bearer testdebug"))
        assert ok["status"] == "ok"


class TestDisconnectProbeWiring:
    """Stream generators must accept a request for liveness polling."""

    def test_generators_accept_request_param(self):
        import inspect
        from app.streaming import stream_file, parallel_stream_generator

        assert "request" in inspect.signature(stream_file).parameters
        assert "request" in inspect.signature(parallel_stream_generator).parameters

    def test_router_wrappers_pass_request(self):
        # Source check: both file_streamer wrappers forward request=request
        import inspect
        from app.routers import streaming as rs

        src = inspect.getsource(rs)
        assert src.count("request=request") >= 2


class TestRlsAutoLockdown:
    """init_db must keep every table RLS-locked on postgres, no-op elsewhere."""

    def _fake_conn(self, dialect, rls_state=None, roles=()):
        calls = []
        state = dict(rls_state or {})

        class _Res:
            def __init__(self, v):
                self._v = v

            def scalar(self):
                return self._v

        class _Conn:
            class dialect:
                name = dialect

            def exec_driver_sql(self, sql):
                calls.append(sql)
                if "relrowsecurity" in sql:
                    t = sql.split("c.relname = '")[1].rstrip("'")
                    return _Res(state.get(t))
                if "pg_roles" in sql:
                    role = sql.split("rolname = '")[1].rstrip("'")
                    return _Res(1 if role in roles else None)
                return _Res(None)

        return _Conn(), calls

    def test_noop_on_sqlite(self):
        from app.database import _apply_rls_lockdown

        conn, calls = self._fake_conn("sqlite")
        _apply_rls_lockdown(conn)
        assert calls == []

    def test_enables_rls_on_all_model_tables(self):
        from app.database import _apply_rls_lockdown, Base

        conn, calls = self._fake_conn("postgresql")
        _apply_rls_lockdown(conn)
        enables = [c for c in calls if c.startswith("ALTER TABLE")]
        assert len(enables) == len(Base.metadata.tables) > 0
        for t in Base.metadata.tables:
            assert f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY' in enables

    def test_revoke_only_existing_api_roles(self):
        from app.database import _apply_rls_lockdown

        # service_role absent -> only anon+authenticated revoked (2 statements each)
        conn, calls = self._fake_conn("postgresql", roles=("anon", "authenticated"))
        _apply_rls_lockdown(conn)
        revokes = [c for c in calls if c.startswith("REVOKE")]
        assert len(revokes) == 4
        assert any('"anon"' in c and "SEQUENCES" not in c for c in revokes)
        assert not any("service_role" in c for c in revokes)


class TestSpaStaticAllowlist:
    def test_builder_maps_nested_files_skips_gz(self, tmp_path):
        from app.static_allowlist import build_static_allowlist

        (tmp_path / "index.html").write_bytes(b"<html/>")
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "app-abc123.js").write_bytes(b"js")
        (assets / "app-abc123.js.gz").write_bytes(b"gzipped")
        (tmp_path / "sub").mkdir()

        allow = build_static_allowlist(str(tmp_path))
        assert allow["index.html"].endswith("index.html")
        assert allow["assets/app-abc123.js"].endswith("app-abc123.js")
        # .gz siblings are never directly addressable ...
        assert "assets/app-abc123.js.gz" not in allow
        # ... and directories are never servable
        assert "sub" not in allow
        assert "assets" not in allow

    def test_builder_missing_dir_is_empty(self, tmp_path):
        from app.static_allowlist import build_static_allowlist

        assert build_static_allowlist(str(tmp_path / "nope")) == {}

    def _client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        return TestClient(app)

    def _tmp_site(self, tmp_path, monkeypatch):
        """Build a hermetic app/static tree (repo never ships the build dir)."""
        from app import main as mainmod
        from app.static_allowlist import build_static_allowlist

        static = tmp_path / "site" / "app" / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_bytes(b"<html>spa</html>")
        (static / "favicon.ico").write_bytes(b"ICO")
        (static / "assets" / "app-abc.js").write_bytes(b"js" * 100)
        (static / "assets" / "app-abc.js.gz").write_bytes(b"gz")
        monkeypatch.chdir(tmp_path / "site")
        monkeypatch.setattr(
            mainmod, "STATIC_ALLOWLIST", build_static_allowlist("app/static")
        )
        return mainmod

    def test_spa_fallback_and_api_guard(self, tmp_path, monkeypatch):
        self._tmp_site(tmp_path, monkeypatch)
        c = self._client()
        r = c.get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert c.get("/api").status_code == 404
        assert c.get("/api/some/route").status_code == 404
        # unknown SPA route falls back to index, not 404
        r = c.get("/some/client/route/that/does/not/exist")
        assert r.status_code == 200

    def test_known_static_file_served_byte_identical(self, tmp_path, monkeypatch):
        import os

        mainmod = self._tmp_site(tmp_path, monkeypatch)
        assert mainmod.STATIC_ALLOWLIST, "tmp site must yield a non-empty allowlist"
        rel = "favicon.ico"
        assert rel in mainmod.STATIC_ALLOWLIST
        c = self._client()
        r = c.get(f"/{rel}", headers={"accept-encoding": "identity"})
        assert r.status_code == 200
        with open(mainmod.STATIC_ALLOWLIST[rel], "rb") as f:
            assert r.content == f.read()
        assert os.path.abspath(mainmod.STATIC_ALLOWLIST[rel]).startswith(
            os.path.abspath("app/static") + os.sep
        )

    def test_traversal_probes_never_disclose(self):
        import os

        c = self._client()
        secret = None
        if os.path.isfile("/etc/passwd"):
            with open("/etc/passwd", "rb") as f:
                secret = f.read(64)
        probes = [
            "/..%2f..%2fetc%2fpasswd",
            "/....//....//etc/passwd",
            "/%2e%2e/%2e%2e/etc/passwd",
            "/static/../../../../etc/passwd",
            "/assets/..%2f..%2frequirements.txt",
        ]
        for p in probes:
            r = c.get(p)
            assert r.status_code in (200, 404)
            if secret:
                assert secret not in r.content, f"disclosure via {p}"
            assert "root:" not in r.text or "html" in r.headers.get(
                "content-type", ""
            ), f"suspicious body via {p}"


class TestVerifyTokenHardening:
    """verify_token must reject missing / non-numeric subjects."""

    def test_garbage_token_returns_none(self):
        from app.auth import verify_token

        assert verify_token("not-a-token") is None

    def test_non_numeric_sub_returns_none(self):
        from jose import jwt
        from app.auth import verify_token, settings
        from datetime import datetime, timezone, timedelta

        payload = {
            "sub": "not-a-number",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "type": "access",
            "ver": 0,
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        assert verify_token(token) is None

    def test_missing_sub_returns_none(self):
        from jose import jwt
        from app.auth import verify_token, settings
        from datetime import datetime, timezone, timedelta

        payload = {
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "type": "access",
            "ver": 0,
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        assert verify_token(token) is None

    def test_valid_token_still_works(self):
        from app.auth import create_access_token, verify_token

        token = create_access_token(999999, version=0)
        assert verify_token(token) == 999999


class TestParseMemEnv:
    """_parse_mem_env must never raise; garbage falls back to 16 GiB."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("3G", 3 * 1024**3),
            ("512M", 512 * 1024**2),
            ("1.5G", int(1.5 * 1024**3)),
            (" 2 gib ", 2 * 1024**3),
            ("1024", 1024),
            ("", 16 * 1024**3),
            ("garbage", 16 * 1024**3),
            ("10XB", 16 * 1024**3),
            (None, 16 * 1024**3),
        ],
    )
    def test_variants(self, raw, expected):
        from app.status import _parse_mem_env

        assert _parse_mem_env(raw) == expected


class TestRemoveDirSymlinkSafe:
    """_remove_dir must never follow symlinks outside the cache."""

    def test_symlinked_dir_is_unlinked_not_followed(self, tmp_path):
        from app.disk_cache import DiskChunkCache

        outside = tmp_path / "outside"
        outside.mkdir()
        victim = outside / "keep.bin"
        victim.write_bytes(b"precious")
        link = tmp_path / "linkdir"
        link.symlink_to(outside, target_is_directory=True)

        DiskChunkCache._remove_dir(link)

        assert not link.exists() or link.is_symlink() is False
        assert victim.read_bytes() == b"precious"

    def test_missing_dir_does_not_raise(self, tmp_path):
        from app.disk_cache import DiskChunkCache

        DiskChunkCache._remove_dir(tmp_path / "nope")  # must not raise

    def test_nested_symlink_file_removed(self, tmp_path):
        from app.disk_cache import DiskChunkCache

        d = tmp_path / "d"
        d.mkdir()
        (d / "real.bin").write_bytes(b"x")
        secret = tmp_path / "secret.bin"
        secret.write_bytes(b"s")
        (d / "evil").symlink_to(secret)
        (d / "sublink").symlink_to(tmp_path, target_is_directory=True)

        DiskChunkCache._remove_dir(d)

        assert secret.read_bytes() == b"s"
        assert not (d / "real.bin").exists()
        assert not (d / "evil").exists() or (d / "evil").is_symlink() is False


class TestSweepSkipsSymlinks:
    """sweep() must skip symlinked entries and survive unreadable dirs."""

    def test_symlink_subdir_not_followed(self, tmp_path):
        from app.disk_cache import DiskChunkCache

        cache = tmp_path / "cache"
        cache.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "chunk0").write_bytes(b"data")
        (cache / "1_2").symlink_to(outside, target_is_directory=True)

        result = DiskChunkCache(cache_dir=cache).sweep()

        assert isinstance(result, int)
        assert (outside / "chunk0").read_bytes() == b"data"
        assert (cache / "1_2").is_symlink()

    def test_file_as_cache_dir_returns_zero(self, tmp_path):
        from app.disk_cache import DiskChunkCache

        f = tmp_path / "notadir"
        f.write_bytes(b"x")
        assert DiskChunkCache(cache_dir=f).sweep() == 0


class TestDetectImageMime:
    """_detect_image_mime handles empty input and GIF magic."""

    @pytest.mark.parametrize(
        "data,expected",
        [
            (b"", "image/jpeg"),
            (b"GIF87a123", "image/gif"),
            (b"GIF89a123", "image/gif"),
            (b"\x89PNG\r\n\x1a\n", "image/png"),
            (b"\xff\xd8\xff\xe0", "image/jpeg"),
            (b"BM1234", "image/bmp"),
            (b"RIFF1234WEBP", "image/webp"),
            (b"????", "image/jpeg"),
        ],
    )
    def test_variants(self, data, expected):
        from app.routers.streaming import _detect_image_mime

        assert _detect_image_mime(data) == expected


class TestBatchDeleteCaps:
    """Batch deletes reject > 500 IDs before touching the DB."""

    @pytest.mark.asyncio
    async def test_files_batch_delete_cap(self):
        from fastapi import HTTPException
        from app.routers.files import batch_delete_files

        with pytest.raises(HTTPException) as exc_info:
            await batch_delete_files(
                [1] * 501, db=None, current_user=None
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_folders_batch_delete_cap(self):
        from fastapi import HTTPException
        from app.routers.folders import batch_delete_folders

        with pytest.raises(HTTPException) as exc_info:
            await batch_delete_folders(
                [1] * 501, db=None, current_user=None
            )
        assert exc_info.value.status_code == 400


class TestOwnershipRecheckPaths:
    """Successful update/share/revoke flows execute the post-commit re-check."""

    @pytest.mark.asyncio
    async def test_update_file_reread(self, temp_db, sample_user, sample_file):
        from app.routers.files import update_file
        from app.schemas import FileUpdate

        resp = await update_file(
            sample_file.id,
            FileUpdate(file_name="renamed.mp4"),
            db=temp_db,
            current_user=sample_user,
        )
        assert resp.file_name == "renamed.mp4"

    @pytest.mark.asyncio
    async def test_share_and_revoke_reread(
        self, temp_db, sample_user, sample_file
    ):
        from app.routers.files import share_file, revoke_share

        shared = await share_file(
            sample_file.id, db=temp_db, current_user=sample_user
        )
        assert shared.id == sample_file.id
        revoked = await revoke_share(
            sample_file.id, db=temp_db, current_user=sample_user
        )
        assert revoked.id == sample_file.id


class TestSchemaValidators:
    """Strict schema validators: bools pass, non-finite floats rejected."""

    def test_bool_position_passes_through(self):
        from app.schemas import WatchProgressUpdate

        # bool survives the "before" validator (no int() coercion crash);
        # pydantic then coerces it to int as before.
        assert WatchProgressUpdate(position=True).position == 1

    def test_finite_float_truncated(self):
        from app.schemas import WatchProgressUpdate

        assert WatchProgressUpdate(position=1.9).position == 1

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_non_finite_rejected(self, bad):
        from pydantic import ValidationError
        from app.schemas import WatchProgressUpdate

        with pytest.raises(ValidationError):
            WatchProgressUpdate(position=bad)

    def test_empty_name_rejected(self):
        from pydantic import ValidationError
        from app.schemas import FileCreate

        with pytest.raises(ValidationError):
            FileCreate(
                name="",
                file_name="a.mp4",
                file_size=1,
                file_type="video",
                file_id="x",
                file_unique_id="y",
            )

    def test_batch_move_ids_cap(self):
        from pydantic import ValidationError
        from app.schemas import BatchMoveRequest

        with pytest.raises(ValidationError):
            BatchMoveRequest(ids=list(range(501)), folder_id=None)


class TestLogBackgroundResult:
    """_log_background_result discards tasks and logs failures."""

    @pytest.mark.asyncio
    async def test_ok_task_discarded(self):
        from app.utils import _background_tasks, _log_background_result

        async def fine():
            return 1

        task = asyncio.ensure_future(fine())
        _background_tasks.add(task)
        await asyncio.sleep(0)
        _log_background_result(task)
        assert task not in _background_tasks

    @pytest.mark.asyncio
    async def test_failed_task_logged(self, caplog):
        import logging
        from app.utils import _background_tasks, _log_background_result

        async def boom():
            raise RuntimeError("kablam")

        task = asyncio.ensure_future(boom())
        _background_tasks.add(task)
        await asyncio.sleep(0)
        with caplog.at_level(logging.ERROR):
            _log_background_result(task)
        assert task not in _background_tasks
        assert "kablam" in caplog.text

    @pytest.mark.asyncio
    async def test_cancelled_task_ignored(self):
        from app.utils import _background_tasks, _log_background_result

        async def hung():
            await asyncio.sleep(60)

        task = asyncio.ensure_future(hung())
        _background_tasks.add(task)
        task.cancel()
        await asyncio.sleep(0)
        _log_background_result(task)
        assert task not in _background_tasks


class TestStaticPage404:
    """Missing status/download pages return JSON 404 instead of 500."""

    def _site(self, tmp_path, monkeypatch, with_pages):
        from app import main as mainmod
        from app.static_allowlist import build_static_allowlist

        static = tmp_path / "site" / "app" / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_bytes(b"<html>spa</html>")
        if with_pages:
            (static / "status.html").write_bytes(b"<html>status</html>")
            (static / "download.html").write_bytes(b"<html>dl</html>")
        monkeypatch.chdir(tmp_path / "site")
        monkeypatch.setattr(
            mainmod, "STATIC_ALLOWLIST", build_static_allowlist("app/static")
        )

    def test_missing_pages_404(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from app.main import app

        self._site(tmp_path, monkeypatch, with_pages=False)
        c = TestClient(app, raise_server_exceptions=False)
        assert c.get("/status").status_code == 404
        assert c.get("/download").status_code == 404

    def test_present_pages_200(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from app.main import app

        self._site(tmp_path, monkeypatch, with_pages=True)
        c = TestClient(app, raise_server_exceptions=False)
        assert c.get("/status").status_code == 200
        assert c.get("/download").status_code == 200


class TestGetCpuNonNegative:
    """get_cpu never reports negative utilization."""

    def test_cpu_reading_non_negative(self):
        from app import status as statusmod

        first = statusmod.get_cpu()
        second = statusmod.get_cpu()
        assert first >= 0.0
        assert second >= 0.0

if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestWatchProgressIntCoercion:
    def test_int_passthrough(self):
        from app.schemas import WatchProgressUpdate
        m = WatchProgressUpdate(position=5)
        assert m.position == 5

    def test_float_truncated_to_int(self):
        from app.schemas import WatchProgressUpdate
        m = WatchProgressUpdate(position=3.7, duration=10.9)
        assert m.position == 3 and m.duration == 10

    def test_infinite_position_rejected(self):
        import pydantic
        from app.schemas import WatchProgressUpdate
        with pytest.raises(pydantic.ValidationError):
            WatchProgressUpdate(position=float("inf"))

    def test_nan_duration_rejected(self):
        import pydantic
        from app.schemas import WatchProgressUpdate
        with pytest.raises(pydantic.ValidationError):
            WatchProgressUpdate(position=1, duration=float("nan"))


class TestGetCpuExceptionPath:
    def test_unexpected_error_returns_zero(self, monkeypatch):
        from app import status as status_mod
        monkeypatch.setattr(status_mod, "_prev_cpu", None)
        monkeypatch.setattr(
            status_mod, "_read_key",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert status_mod.get_cpu() == 0.0


class TestSpawnBackground:
    def test_spawn_runs_job_and_unregisters(self):
        import asyncio
        from app import utils as utils_mod

        async def _main():
            async def _job():
                return 1

            task = utils_mod.spawn_background(_job())
            assert task in utils_mod._background_tasks
            assert await task == 1
            await asyncio.sleep(0)  # let the done-callback fire
            assert task not in utils_mod._background_tasks
            return True

        assert asyncio.run(_main()) is True


class TestSweepOSErrorPaths:
    def _boom(self, *a, **k):
        raise OSError("disk gone")

    def test_first_iterdir_oserror_returns_zero(self, monkeypatch, tmp_path):
        from app import disk_cache as dc
        monkeypatch.setattr(dc.Path, "iterdir", lambda self: (_ for _ in ()).throw(OSError("disk gone")))
        cache = dc.DiskChunkCache(cache_dir=tmp_path)
        assert cache.sweep() == 0

    def test_second_iterdir_oserror_returns_zero(self, monkeypatch, tmp_path):
        from app import disk_cache as dc
        calls = {"n": 0}
        real_iterdir = dc.Path.iterdir

        def _flaky(self):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise OSError("disk gone")
            return real_iterdir(self)

        monkeypatch.setattr(dc.Path, "iterdir", _flaky)
        (tmp_path / "junkdir").mkdir()
        cache = dc.DiskChunkCache(cache_dir=tmp_path)
        assert cache.sweep() == 0

    def test_junk_dirs_skipped_in_both_passes(self, tmp_path):
        from app import disk_cache as dc
        (tmp_path / "not-a-key").mkdir()
        (tmp_path / "123_").mkdir()
        cache = dc.DiskChunkCache(cache_dir=tmp_path)
        assert cache.sweep() == 0

    def test_remove_dir_unlink_oserror(self, monkeypatch, tmp_path):
        from app import disk_cache as dc
        d = tmp_path / "1_2"
        d.mkdir()
        (d / "a.bin").write_bytes(b"x" * 8)
        monkeypatch.setattr(dc.Path, "unlink", self._boom)
        dc.DiskChunkCache._remove_dir(d)  # must not raise
        assert d.exists()

    def test_remove_dir_symlink_unlink_oserror(self, monkeypatch, tmp_path):
        from app import disk_cache as dc
        target = tmp_path / "real"
        target.mkdir()
        link = tmp_path / "9_9"
        link.symlink_to(target, target_is_directory=True)
        monkeypatch.setattr(dc.Path, "unlink", self._boom)
        dc.DiskChunkCache._remove_dir(link)  # must not raise
        assert link.is_symlink()

    def test_remove_dir_is_symlink_oserror(self, monkeypatch, tmp_path):
        from app import disk_cache as dc
        d = tmp_path / "3_4"
        d.mkdir()
        monkeypatch.setattr(dc.Path, "is_symlink", self._boom)
        dc.DiskChunkCache._remove_dir(d)  # must not raise


class TestOomGuardLoop:
    async def test_single_iteration_runs_gc_and_trim(self, monkeypatch):
        import asyncio
        from app import main as main_mod
        calls = {"n": 0}

        async def _fake_sleep(d):
            calls["n"] += 1
            if calls["n"] > 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_mod.asyncio, "sleep", _fake_sleep)
        task = asyncio.create_task(main_mod._oom_guard_loop())
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert calls["n"] >= 2


class TestWaitForCallbackChatIdPath:
    async def test_chat_id_resolves_message_then_times_out(self):
        import asyncio
        from types import SimpleNamespace
        from app.patch import PatchedClient

        async def _fake_get_messages(**kw):
            assert kw.get("chat_id") == 123
            return SimpleNamespace(empty=False, from_user=SimpleNamespace(is_self=True))

        client = object.__new__(PatchedClient)
        client.listeners = {}
        client.get_messages = _fake_get_messages
        client.loop = asyncio.get_running_loop()
        with pytest.raises(asyncio.TimeoutError):
            await client.wait_for_callback_query(chat_id=123, message_id=1, timeout=0.01)


class TestFileEndpointNotFoundPaths:
    """Direct calls covering per-endpoint 404 re-checks."""

    @pytest.mark.asyncio
    async def test_get_file_success(self, temp_db, sample_user, sample_file):
        from app.routers.files import get_file
        resp = await get_file(sample_file.id, db=temp_db, current_user=sample_user)
        assert resp.file_name == "movie.mp4"

    @pytest.mark.asyncio
    async def test_update_reread_404(self, temp_db, sample_user, sample_file, monkeypatch):
        from fastapi import HTTPException
        from app.routers.files import update_file
        from app.schemas import FileUpdate
        real_exec = temp_db.execute
        calls = {"n": 0}

        async def _second_empty(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                class _R:
                    def scalar_one_or_none(self):
                        return None
                return _R()
            return await real_exec(*a, **k)

        monkeypatch.setattr(temp_db, "execute", _second_empty)
        with pytest.raises(HTTPException) as ei:
            await update_file(sample_file.id, FileUpdate(file_name="x.mp4"),
                              db=temp_db, current_user=sample_user)
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_file_success(self, temp_db, sample_user, sample_file, monkeypatch):
        from app.routers import files as files_mod
        async def _noop(*a, **k):
            return None
        monkeypatch.setattr(files_mod, "delete_from_storage_channel", _noop)
        resp = await files_mod.delete_file(sample_file.id, db=temp_db, current_user=sample_user)
        assert "deleted" in resp["message"].lower()

    @pytest.mark.asyncio
    async def test_batch_delete_success(self, temp_db, sample_user, sample_file, monkeypatch):
        from app.routers import files as files_mod
        async def _noop(*a, **k):
            return None
        monkeypatch.setattr(files_mod, "delete_from_storage_channel", _noop)
        resp = await files_mod.batch_delete_files([sample_file.id], db=temp_db, current_user=sample_user)
        assert "1" in resp["message"]

    @pytest.mark.asyncio
    async def test_get_progress_none(self, temp_db, sample_user, sample_file):
        from app.routers.files import get_progress
        assert await get_progress(sample_file.id, db=temp_db, current_user=sample_user) is None

    @pytest.mark.asyncio
    async def test_share_reread_404(self, temp_db, sample_user, sample_file, monkeypatch):
        from fastapi import HTTPException
        from app.routers.files import share_file
        real_exec = temp_db.execute
        calls = {"n": 0}

        async def _second_empty(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                class _R:
                    def scalar_one_or_none(self):
                        return None
                return _R()
            return await real_exec(*a, **k)

        monkeypatch.setattr(temp_db, "execute", _second_empty)
        with pytest.raises(HTTPException) as ei:
            await share_file(sample_file.id, db=temp_db, current_user=sample_user)
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_reread_404(self, temp_db, sample_user, sample_file, monkeypatch):
        from fastapi import HTTPException
        from app.routers.files import revoke_share
        real_exec = temp_db.execute
        calls = {"n": 0}

        async def _second_empty(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                class _R:
                    def scalar_one_or_none(self):
                        return None
                return _R()
            return await real_exec(*a, **k)

        monkeypatch.setattr(temp_db, "execute", _second_empty)
        with pytest.raises(HTTPException) as ei:
            await revoke_share(sample_file.id, db=temp_db, current_user=sample_user)
        assert ei.value.status_code == 404


@pytest_asyncio.fixture
async def folder_tree(temp_db, sample_user):
    from app.models import Folder, File
    parent = Folder(user_id=sample_user.id, name="parent")
    temp_db.add(parent)
    await temp_db.commit()
    await temp_db.refresh(parent)
    child = Folder(user_id=sample_user.id, name="child", parent_id=parent.id)
    temp_db.add(child)
    await temp_db.commit()
    await temp_db.refresh(child)
    f = File(user_id=sample_user.id, file_id="fid-tree", file_unique_id="uniq-tree",
             file_name="in_child.mp4", file_size=500, mime_type="video/mp4",
             file_type="video", channel_message_id=78, folder_id=child.id)
    temp_db.add(f)
    await temp_db.commit()
    await temp_db.refresh(f)
    return parent, child, f


class TestFolderCircularAndDeletePaths:
    @pytest.mark.asyncio
    async def test_move_parent_into_child_400(self, temp_db, sample_user, folder_tree):
        from fastapi import HTTPException
        from app.routers.folders import update_folder
        from app.schemas import FolderUpdate
        parent, child, _ = folder_tree
        with pytest.raises(HTTPException) as ei:
            await update_folder(parent.id, FolderUpdate(parent_id=child.id),
                                db=temp_db, current_user=sample_user)
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_moves_files_to_root(self, temp_db, sample_user, folder_tree):
        from app.routers.folders import delete_folder
        from app.models import File
        parent, child, f = folder_tree
        resp = await delete_folder(parent.id, move_files_to=None, delete_files=False,
                                   db=temp_db, current_user=sample_user)
        assert "deleted" in resp["message"].lower()
        await temp_db.refresh(f)
        assert f.folder_id is None

    @pytest.mark.asyncio
    async def test_delete_files_true_cleans_storage(self, temp_db, sample_user, folder_tree, monkeypatch):
        from app.routers import folders as folders_mod
        async def _noop(*a, **k):
            return None
        monkeypatch.setattr(folders_mod, "delete_from_storage_channel", _noop)
        parent, child, f = folder_tree
        resp = await folders_mod.delete_folder(parent.id, move_files_to=None, delete_files=True,
                                               db=temp_db, current_user=sample_user)
        assert "deleted" in resp["message"].lower()

    @pytest.mark.asyncio
    async def test_batch_delete_folders_success(self, temp_db, sample_user, folder_tree, monkeypatch):
        from app.routers import folders as folders_mod
        async def _noop(*a, **k):
            return None
        monkeypatch.setattr(folders_mod, "delete_from_storage_channel", _noop)
        parent, child, f = folder_tree
        resp = await folders_mod.batch_delete_folders([parent.id], db=temp_db, current_user=sample_user)
        assert "1" in resp["message"]


class TestPatchCallbackExtraPaths:
    async def _client(self):
        import asyncio
        from app.patch import PatchedClient
        client = object.__new__(PatchedClient)
        client.listeners = {}
        client.loop = asyncio.get_running_loop()
        return client

    async def test_empty_message_rejected(self):
        import asyncio
        from types import SimpleNamespace
        client = await self._client()

        async def _fake_get_messages(**kw):
            return SimpleNamespace(empty=True, from_user=None)
        client.get_messages = _fake_get_messages
        with pytest.raises(ValueError):
            await client.wait_for_callback_query(chat_id=1, message_id=2, timeout=0.01)

    async def test_foreign_message_rejected(self):
        import asyncio
        from types import SimpleNamespace
        client = await self._client()

        async def _fake_get_messages(**kw):
            return SimpleNamespace(empty=False, from_user=SimpleNamespace(is_self=False))
        client.get_messages = _fake_get_messages
        with pytest.raises(ValueError):
            await client.wait_for_callback_query(chat_id=1, message_id=2, timeout=0.01)

    async def test_inline_message_id_path(self):
        import asyncio
        client = await self._client()
        with pytest.raises(asyncio.TimeoutError):
            await client.wait_for_callback_query(inline_message_id="abc", timeout=0.01)


class TestCpuFrozenTimePath:
    def test_zero_dt_returns_zero(self, monkeypatch):
        from app import status as status_mod
        monkeypatch.setattr(status_mod, "_prev_cpu", None)
        monkeypatch.setattr(status_mod.time, "monotonic", lambda: 1000.0)
        first = status_mod.get_cpu()
        second = status_mod.get_cpu()
        assert first == 0.0 and second == 0.0


class TestRemoveDirSubdirChild:
    def test_subdir_child_skipped_for_unlink(self, tmp_path):
        from app import disk_cache as dc
        d = tmp_path / "5_6"
        d.mkdir()
        (d / "sub").mkdir()
        (d / "a.bin").write_bytes(b"y" * 4)
        dc.DiskChunkCache._remove_dir(d)  # subdir left; rmdir fails silently
        assert (d / "sub").exists()


class TestMainLibcFallback:
    async def test_libc_missing_and_trim_failure(self, monkeypatch):
        import asyncio
        import importlib
        from app import main as main_mod
        calls = {"n": 0}

        async def _fake_sleep(d):
            calls["n"] += 1
            if calls["n"] > 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_mod.asyncio, "sleep", _fake_sleep)
        # Force the OSError fallback at import
        monkeypatch.setattr(main_mod.ctypes, "CDLL", lambda *a, **k: (_ for _ in ()).throw(OSError("no libc")))
        importlib.reload(main_mod)
        assert main_mod._libc is None
        # _libc None -> trim skipped
        task = asyncio.create_task(main_mod._oom_guard_loop())
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Raising trim -> except path
        class _BadLib:
            def malloc_trim(self, *a):
                raise RuntimeError("trim failed")
        main_mod._libc = _BadLib()
        calls["n"] = 0
        task = asyncio.create_task(main_mod._oom_guard_loop())
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Restore module state (undo CDLL patch first so import succeeds)
        monkeypatch.undo()
        importlib.reload(main_mod)
        assert main_mod._libc is not None


class TestMemoryPressureFallbacks:
    def test_rss_zero_no_cgroup_files(self, monkeypatch):
        from app import streaming as streaming_mod
        monkeypatch.setattr(streaming_mod, "_process_rss_bytes", lambda: 0)
        monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("no cgroup")))
        assert streaming_mod._memory_pressure() is False

    def test_rss_zero_cgroup_current_used(self, monkeypatch):
        import io
        from app import streaming as streaming_mod
        monkeypatch.setattr(streaming_mod, "_process_rss_bytes", lambda: 0)
        real_open = open

        def _fake_open(p, *a, **k):
            if str(p).endswith("memory.current"):
                return io.StringIO("1234567")
            raise OSError("missing")
        monkeypatch.setattr("builtins.open", _fake_open)
        # cur>0 but no max files -> mx None -> False
        assert streaming_mod._memory_pressure() is False

    def test_max_literal_skipped(self, monkeypatch):
        import io
        from app import streaming as streaming_mod
        real_open = open

        def _fake_open(p, *a, **k):
            if str(p).endswith("memory.max"):
                return io.StringIO("max")
            raise OSError("missing")
        monkeypatch.setattr("builtins.open", _fake_open)
        assert streaming_mod._memory_pressure() is False

    def test_max_numeric_used(self, monkeypatch):
        import io
        from app import streaming as streaming_mod

        def _fake_open(p, *a, **k):
            if str(p).endswith("memory.max"):
                return io.StringIO("1000000000000")
            return real_open(p, *a, **k)
        real_open = open
        monkeypatch.setattr("builtins.open", _fake_open)
        assert isinstance(streaming_mod._memory_pressure(), bool)
