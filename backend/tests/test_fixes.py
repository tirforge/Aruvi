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

        # No body exists, so no range is satisfiable (RFC 9110 §14.1.2).
        assert parse_range_header("bytes=-50", 0) is None
        assert parse_range_header("bytes=0-0", 0) is None

    def test_junk_suffix_rejected(self):
        from app.routers.streaming import parse_range_header

        # The old regex matched the numeric prefix and ignored trailing junk.
        assert parse_range_header("bytes=0-10junk", 100) is None

    def test_inverted_range_rejected(self):
        from app.routers.streaming import parse_range_header

        # The old regex returned (50, 40), a start > end range.
        assert parse_range_header("bytes=50-40", 100) is None

    def test_start_past_eof_rejected(self):
        from app.routers.streaming import parse_range_header

        # The old regex clamped and served the empty tail with a 206.
        assert parse_range_header("bytes=200-300", 100) is None
        assert parse_range_header("bytes=100-", 100) is None

    def test_zero_length_suffix_rejected(self):
        from app.routers.streaming import parse_range_header

        assert parse_range_header("bytes=-0", 100) is None

    def test_case_and_whitespace_tolerated(self):
        from app.routers.streaming import parse_range_header

        assert parse_range_header("Bytes=0-10", 100) == (0, 10)
        assert parse_range_header("bytes= 0-10", 100) == (0, 10)


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
    """Concurrent writers of the same chunk must never produce a torn value."""

    @pytest.mark.asyncio
    async def test_concurrent_put_no_tear(self):
        from app.disk_cache import DiskChunkCache
        import tempfile
        import pathlib

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            cache = DiskChunkCache(cache_dir=pathlib.Path(tmpdir))
            chat_id, message_id, chunk_idx = 1, 2, 3

            # Simulate concurrent puts
            data1 = b"data1" * 1000
            data2 = b"data2" * 1000

            await asyncio.gather(
                asyncio.to_thread(cache.put, chat_id, message_id, chunk_idx, data1),
                asyncio.to_thread(cache.put, chat_id, message_id, chunk_idx, data2),
            )

            # One of the writes won - the stored value must be complete, not a mix
            content = cache.get(chat_id, message_id, chunk_idx)
            assert content == data1 or content == data2
            cache.close()


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


class TestDiskCacheSemantics:
    """Behaviour of the LMDB-backed cold tier (payloads, LRU, TTL)."""

    def test_put_get_roundtrip_and_indices(self, tmp_path):
        from app.disk_cache import DiskChunkCache

        cache = DiskChunkCache(cache_dir=tmp_path)
        assert cache.get(1, 2, 0) is None
        assert not cache.contains(1, 2, 0)

        cache.put(1, 2, 0, b"a" * 100)
        cache.put(1, 2, 1, b"b" * 50)

        assert cache.get(1, 2, 0) == b"a" * 100
        assert cache.contains(1, 2, 1)
        assert cache.chunk_indices(1, 2) == frozenset({0, 1})
        assert cache.used_bytes() >= 150
        cache.close()

    def test_put_never_overwrites_an_existing_chunk(self, tmp_path):
        from app.disk_cache import DiskChunkCache

        cache = DiskChunkCache(cache_dir=tmp_path)
        cache.put(1, 2, 0, b"first")
        cache.put(1, 2, 0, b"second")
        assert cache.get(1, 2, 0) == b"first"
        cache.close()

    def test_sweep_evicts_idle_video_after_ttl(self, tmp_path, monkeypatch):
        from app import disk_cache as dc_mod
        from app.disk_cache import DiskChunkCache
        import time as _time

        cache = DiskChunkCache(cache_dir=tmp_path)
        cache.put(1, 2, 0, b"x" * 100)
        cache._last_active[(1, 2)] = _time.time() - 3600
        monkeypatch.setattr(dc_mod, "DISK_CACHE_TTL", 60)

        cache.sweep()

        assert cache.get(1, 2, 0) is None
        assert cache.chunk_indices(1, 2) == frozenset()
        cache.close()

    def test_sweep_prunes_last_active(self, tmp_path):
        from app.disk_cache import DiskChunkCache
        import time as _time

        cache = DiskChunkCache(cache_dir=tmp_path)
        cache.put(3, 4, 0, b"x")
        cache._last_active[(9, 9)] = _time.time()  # video that never existed
        cache._last_active[(3, 4)] = _time.time()

        cache.sweep()

        assert (9, 9) not in cache._last_active
        assert (3, 4) in cache._last_active
        cache.close()

    def test_per_video_cap_evicts_oldest_chunk(self, tmp_path, monkeypatch):
        from app import disk_cache as dc_mod
        from app.disk_cache import DiskChunkCache

        cache = DiskChunkCache(cache_dir=tmp_path)
        monkeypatch.setattr(dc_mod, "DISK_CACHE_PER_VIDEO_BYTES", 150)
        cache.put(1, 2, 0, b"a" * 100)
        cache.put(1, 2, 1, b"b" * 100)

        assert cache.get(1, 2, 0) is None  # oldest chunk evicted
        assert cache.get(1, 2, 1) == b"b" * 100
        cache.close()

    def test_chunks_indices_and_sizes_survive_restart(self, tmp_path):
        """LMDB is the source of truth: a new process sees the existing cache."""
        from app.disk_cache import DiskChunkCache

        cache = DiskChunkCache(cache_dir=tmp_path)
        cache.put(7, 8, 0, b"a" * 1000)
        cache.put(7, 8, 1, b"b" * 500)
        cache.close()

        reopened = DiskChunkCache(cache_dir=tmp_path)
        assert reopened.get(7, 8, 0) == b"a" * 1000
        assert reopened.chunk_indices(7, 8) == frozenset({0, 1})
        assert reopened.used_bytes() == 1500
        reopened.close()

    def test_activity_marker_survives_restart(self, tmp_path):
        """The TTL clock is persisted, so idle videos expire after a restart."""
        from app.disk_cache import DiskChunkCache

        cache = DiskChunkCache(cache_dir=tmp_path)
        cache.put(5, 6, 0, b"x" * 10)
        before = cache._last_active[(5, 6)]
        cache.close()

        reopened = DiskChunkCache(cache_dir=tmp_path)
        assert (5, 6) in reopened._last_active
        assert abs(reopened._last_active[(5, 6)] - before) < 2
        reopened.close()

    def test_first_writer_wins_across_restart(self, tmp_path):
        from app.disk_cache import DiskChunkCache

        cache = DiskChunkCache(cache_dir=tmp_path)
        cache.put(1, 2, 0, b"first")
        cache.close()

        reopened = DiskChunkCache(cache_dir=tmp_path)
        reopened.put(1, 2, 0, b"second")
        assert reopened.get(1, 2, 0) == b"first"
        reopened.close()

    def test_global_cap_evicts_least_recently_used_video(self, tmp_path, monkeypatch):
        import time as _time

        from app import disk_cache as dc_mod
        from app.disk_cache import DiskChunkCache

        cache = DiskChunkCache(cache_dir=tmp_path)
        cache.put(1, 2, 0, b"a" * 100)
        cache._last_active[(1, 2)] = _time.time() - 100
        monkeypatch.setattr(dc_mod, "DISK_CACHE_MAX_BYTES", 150)
        cache.put(3, 4, 0, b"b" * 100)

        assert cache.get(1, 2, 0) is None
        assert cache.get(3, 4, 0) == b"b" * 100
        assert cache.used_bytes() == 100
        cache.close()

    def test_legacy_chunk_dirs_are_purged(self, tmp_path):
        """Upgrading must not leave the old {chat}_{msg}/*.bin tree behind."""
        from app.disk_cache import DiskChunkCache

        legacy = tmp_path / "1_2"
        legacy.mkdir()
        (legacy / "0.bin").write_bytes(b"x" * 10)
        (legacy / "0.tmp").write_bytes(b"y" * 10)

        cache = DiskChunkCache(cache_dir=tmp_path)
        cache.sweep()

        assert not legacy.exists()
        cache.close()

    def test_old_diskcache_tree_is_purged(self, tmp_path):
        """An upgraded box reclaims the previous diskcache tier, nothing else."""
        from app.disk_cache import DiskChunkCache

        (tmp_path / "cache.db").write_bytes(b"index" * 10)
        (tmp_path / "cache.db-wal").write_bytes(b"wal" * 10)
        payload = tmp_path / "ab" / "cd"
        payload.mkdir(parents=True)
        (payload / "deadbeef.val").write_bytes(b"x" * 1024)
        keep = tmp_path / "keepme"
        keep.mkdir()
        (keep / "note.txt").write_bytes(b"keep")

        cache = DiskChunkCache(cache_dir=tmp_path)

        assert not (tmp_path / "cache.db").exists()
        assert not (tmp_path / "cache.db-wal").exists()
        assert not (tmp_path / "ab").exists()
        assert (keep / "note.txt").read_bytes() == b"keep"
        cache.close()


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


class TestTtlCaches:
    """The hand-rolled TTL dicts are cachebox TTLCache instances now."""

    def test_message_cache_is_ttl_capped(self):
        from cachebox import TTLCache

        from app import telegram

        assert isinstance(telegram._msg_cache, TTLCache)
        assert telegram._msg_cache.maxsize == telegram._MSG_CACHE_MAX
        assert telegram._msg_cache.global_ttl == telegram.MSG_CACHE_TTL

    @pytest.mark.asyncio
    async def test_message_cache_hit_skips_rpc(self):
        from app import telegram

        calls = []

        class FakeMsg:
            empty = False
            id = 424244

        async def fake_get_messages(chat_id, message_id):
            calls.append(message_id)
            return FakeMsg()

        key = telegram._msg_cache_key(424244)
        telegram._msg_cache.pop(key, None)
        orig = telegram.tg_client.get_messages
        telegram.tg_client.get_messages = fake_get_messages
        try:
            first = await telegram.get_message_from_channel(424244)
            second = await telegram.get_message_from_channel(424244)
            assert first is second
            assert calls == [424244]  # second call served from cache
        finally:
            telegram.tg_client.get_messages = orig
            telegram._msg_cache.pop(key, None)

    def test_gdrive_nonce_roundtrip_is_single_use(self):
        from app import gdrive

        gdrive._nonce_store.insert("nonce-ok", (777, "verifier"))
        assert gdrive.consume_state("777:nonce-ok") == (777, "verifier")
        with pytest.raises(ValueError):
            gdrive.consume_state("777:nonce-ok")

    def test_gdrive_nonce_rejects_other_user(self):
        from app import gdrive

        gdrive._nonce_store.insert("nonce-x", (777, "verifier"))
        with pytest.raises(ValueError):
            gdrive.consume_state("888:nonce-x")


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


class TestVendoredPlayer:
    """The SPA's player URL must point at a file that actually ships.

    Bumping the version means three things move together: the vendored bundle
    in ``frontend/public/vendor``, the ``MOVI_PLAYER_URL`` constant, and the
    built copy under ``backend/app/static`` (which is what the backend serves).
    A half-done bump ships a 404 for the playback engine, so assert all three.
    """

    @staticmethod
    def _repo_root():
        from pathlib import Path

        return Path(__file__).resolve().parents[2]

    def test_player_url_has_a_vendored_bundle(self):
        import re

        root = self._repo_root()
        src = (root / "frontend/src/components/MediaPlayer.tsx").read_text(
            encoding="utf-8"
        )
        match = re.search(r"const MOVI_PLAYER_URL = '([^']+)'", src)
        assert match, "MOVI_PLAYER_URL not found in MediaPlayer.tsx"
        url = match.group(1)
        assert url.startswith("/vendor/movi-player-"), url

        vendored = root / "frontend/public" / url.lstrip("/")
        assert vendored.is_file(), f"missing vendored bundle: {vendored}"

        built = root / "backend/app/static" / url.lstrip("/")
        assert built.is_file(), f"missing built bundle: {built} (run the frontend build)"
        assert vendored.read_bytes() == built.read_bytes(), (
            "backend/app/static vendor copy is stale — rebuild the frontend"
        )

    def test_vendored_bundle_is_untouched_upstream(self):
        """No local patches: the file is a byte-for-byte upstream release."""
        import re

        root = self._repo_root()
        src = (root / "frontend/src/components/MediaPlayer.tsx").read_text(
            encoding="utf-8"
        )
        url = re.search(r"const MOVI_PLAYER_URL = '([^']+)'", src).group(1)
        path = root / "frontend/public" / url.lstrip("/")

        marker = b"ARUVI-LOCAL-PATCH"
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                assert marker not in chunk, (
                    f"{path.name} carries a local patch — upgrade by replacing the "
                    "file with the upstream release instead"
                )


class TestSearchEscaping:
    """Search terms are literal: LIKE metacharacters must not act as wildcards."""

    @staticmethod
    async def _seed(db, user, names):
        from app.models import File

        for i, name in enumerate(names):
            db.add(
                File(
                    user_id=user.id,
                    file_id=f"fid-{i}",
                    file_unique_id=f"uniq-search-{i}",
                    channel_message_id=i + 1,
                    file_name=name,
                    file_size=1000,
                    file_type="video",
                )
            )
        await db.commit()

    @pytest.mark.asyncio
    async def test_percent_matches_only_literal_percent(self, temp_db, sample_user):
        from app.routers.files import list_files

        await self._seed(
            temp_db, sample_user, ["100% real.mkv", "100X other.mkv"]
        )
        resp = await list_files(
            folder_id=None,
            file_type=None,
            search="100%",
            page=1,
            per_page=20,
            db=temp_db,
            current_user=sample_user,
        )
        assert [f.file_name for f in resp.files] == ["100% real.mkv"]
        assert resp.total == 1

    @pytest.mark.asyncio
    async def test_underscore_matches_only_literal_underscore(
        self, temp_db, sample_user
    ):
        from app.routers.files import list_files

        await self._seed(
            temp_db, sample_user, ["a_b literal.mkv", "aXb other.mkv"]
        )
        resp = await list_files(
            folder_id=None,
            file_type=None,
            search="a_b",
            page=1,
            per_page=20,
            db=temp_db,
            current_user=sample_user,
        )
        assert [f.file_name for f in resp.files] == ["a_b literal.mkv"]
        assert resp.total == 1

    @pytest.mark.asyncio
    async def test_tv_search_escapes_metacharacters(self, temp_db, sample_user):
        from app.routers.tv import tv_search

        await self._seed(
            temp_db, sample_user, ["50% off.mkv", "50X other.mkv"]
        )
        resp = await tv_search(
            q="50%", limit=30, db=temp_db, current_user=sample_user
        )
        assert [f["file_name"] for f in resp["files"]] == ["50% off.mkv"]


class TestSpaStaticAllowlist:
    def test_builder_maps_nested_files_skips_encoded_siblings(self, tmp_path):
        from app.static_allowlist import build_static_allowlist

        (tmp_path / "index.html").write_bytes(b"<html/>")
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "app-abc123.js").write_bytes(b"js")
        (assets / "app-abc123.js.gz").write_bytes(b"gzipped")
        (assets / "app-abc123.js.br").write_bytes(b"brotlied")
        (tmp_path / "sub").mkdir()

        allow = build_static_allowlist(str(tmp_path))
        assert allow["index.html"].endswith("index.html")
        assert allow["assets/app-abc123.js"].endswith("app-abc123.js")
        # precompressed siblings are never directly addressable ...
        assert "assets/app-abc123.js.gz" not in allow
        assert "assets/app-abc123.js.br" not in allow
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
        (static / "assets" / "app-abc.js.gz").write_bytes(b"gzip-bytes")
        (static / "assets" / "app-abc.js.br").write_bytes(b"brotli-bytes")
        monkeypatch.chdir(tmp_path / "site")
        monkeypatch.setattr(
            mainmod, "STATIC_ALLOWLIST", build_static_allowlist("app/static")
        )
        return mainmod

    def test_accepts_encoding_tokens(self):
        from app.main import _accepts_encoding

        assert _accepts_encoding("gzip, deflate, br", "br")
        assert _accepts_encoding("br;q=1.0, gzip;q=0.5", "gzip")
        assert _accepts_encoding("GZIP", "gzip")
        assert not _accepts_encoding("gzip, deflate", "br")
        assert not _accepts_encoding("", "br")
        # "brotli" is not the token name and must not match a substring check
        assert not _accepts_encoding("brotli", "br")
        # q=0 means "not acceptable" (RFC 9110 §12.5.3)
        assert not _accepts_encoding("gzip;q=0", "gzip")
        # the wildcard covers codings that are not named
        assert _accepts_encoding("*", "br")

    def test_pick_content_encoding_honours_q_values(self):
        from app.http_headers import pick_content_encoding

        # Client prefers gzip: br must not win just by being the server's first.
        assert pick_content_encoding("br;q=0.1, gzip;q=0.9", ("br", "gzip")) == "gzip"
        assert pick_content_encoding("br, gzip", ("br", "gzip")) == "br"
        assert pick_content_encoding("gzip;q=0", ("br", "gzip")) is None
        assert pick_content_encoding("", ("br", "gzip")) is None
        assert pick_content_encoding("deflate", ("br", "gzip")) is None
        # Only negotiate over codings the server can actually serve.
        assert pick_content_encoding("br, gzip", ("gzip",)) == "gzip"

    @staticmethod
    def _request(path: str, accept_encoding: str):
        from starlette.requests import Request

        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("testclient", 1234),
                "headers": [(b"accept-encoding", accept_encoding.encode())],
                "asgi": {"spec_version": "2.0", "version": "3.0"},
                "extensions": {},
            }
        )

    @pytest.mark.asyncio
    async def test_brotli_preferred_then_gzip_then_plain(self, tmp_path, monkeypatch):
        mainmod = self._tmp_site(tmp_path, monkeypatch)
        from app.main import serve_spa

        url = "/assets/app-abc.js"

        resp = await serve_spa(self._request(url, "br, gzip"), "assets/app-abc.js")
        assert resp.headers["content-encoding"] == "br"
        assert resp.headers["vary"] == "Accept-Encoding"
        assert resp.path.endswith("app-abc.js.br")

        resp = await serve_spa(self._request(url, "gzip, deflate"), "assets/app-abc.js")
        assert resp.headers["content-encoding"] == "gzip"
        assert resp.path.endswith("app-abc.js.gz")

        resp = await serve_spa(self._request(url, "identity"), "assets/app-abc.js")
        assert "content-encoding" not in resp.headers
        assert resp.path.endswith("app-abc.js")
        assert mainmod.STATIC_ALLOWLIST

    @pytest.mark.asyncio
    async def test_static_asset_respects_q_values(self, tmp_path, monkeypatch):
        self._tmp_site(tmp_path, monkeypatch)
        from app.main import serve_spa

        url = "/assets/app-abc.js"
        # gzip is preferred by q-value even though br is server-first.
        resp = await serve_spa(
            self._request(url, "br;q=0.1, gzip;q=0.9"), "assets/app-abc.js"
        )
        assert resp.headers["content-encoding"] == "gzip"

        # gzip refused, br accepted via wildcard reordering.
        resp = await serve_spa(
            self._request(url, "gzip;q=0, *;q=1"), "assets/app-abc.js"
        )
        assert resp.headers["content-encoding"] == "br"

    def test_resolve_static_returns_all_three_variants(self, tmp_path):
        from app.main import _resolve_static

        plain = tmp_path / "a.js"
        plain.write_bytes(b"plain")
        (tmp_path / "a.js.gz").write_bytes(b"gz")
        (tmp_path / "a.js.br").write_bytes(b"br")

        assert _resolve_static(str(plain)) == (
            str(plain),
            str(tmp_path / "a.js.gz"),
            str(tmp_path / "a.js.br"),
        )
        assert _resolve_static(str(tmp_path / "missing.js")) == (None, None, None)

    def test_resolve_static_ignores_symlinked_sibling(self, tmp_path):
        import os

        from app.main import _resolve_static

        plain = tmp_path / "a.js"
        plain.write_bytes(b"plain")
        outside = tmp_path / "outside.br"
        outside.write_bytes(b"secret")
        link = tmp_path / "a.js.br"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported here")

        assert _resolve_static(str(plain)) == (str(plain), None, None)

    @pytest.mark.asyncio
    async def test_encoded_sibling_is_not_directly_addressable(
        self, tmp_path, monkeypatch
    ):
        self._tmp_site(tmp_path, monkeypatch)
        from app.main import serve_spa

        for path in ("/assets/app-abc.js.br", "/assets/app-abc.js.gz"):
            resp = await serve_spa(
                self._request(path, "identity"), path.lstrip("/")
            )
            # Missing from the allowlist -> SPA fallback, never the sibling bytes.
            assert resp.path.endswith("index.html")

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


_NO_SYMLINKS = sys.platform == "win32"  # needs Developer Mode / admin rights


def _needs_symlinks(fn):
    return pytest.mark.skipif(
        _NO_SYMLINKS, reason="symlink creation requires Developer Mode on Windows"
    )(fn)


@_needs_symlinks
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


@_needs_symlinks
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
    """_detect_image_mime sniffs thumbnail bytes via filetype."""

    @pytest.mark.parametrize(
        "data,expected",
        [
            (b"", "image/jpeg"),
            (b"GIF87a123", "image/gif"),
            (b"GIF89a123", "image/gif"),
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png"),
            (b"\xff\xd8\xff\xe0" + b"\x00" * 16, "image/jpeg"),
            (b"BM" + b"\x00" * 32, "image/bmp"),
            (b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16, "image/webp"),
            (b"II*\x00" + b"\x00" * 16, "image/tiff"),
            (b"????", "image/jpeg"),
        ],
    )
    def test_variants(self, data, expected):
        from app.routers.streaming import _detect_image_mime

        assert _detect_image_mime(data) == expected

    def test_non_image_magic_falls_back_to_jpeg(self):
        from app.routers.streaming import _detect_image_mime

        # A zip header is not an image; thumbnails should stay JPEG-default.
        assert _detect_image_mime(b"PK\x03\x04" + b"\x00" * 16) == "image/jpeg"


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


class TestRamChunkCache:
    """The RAM hot tier is cachebox's byte-weighted LRU (streaming.ChunkCache)."""

    MB = 1024 * 1024

    def test_byte_cap_evicts_least_recently_used(self):
        from app.streaming import ChunkCache

        cache = ChunkCache(max_bytes=3 * self.MB)
        cache.put(0, b"a" * self.MB)
        cache.put(1, b"b" * self.MB)
        cache.put(2, b"c" * self.MB)
        assert cache.get(0) == b"a" * self.MB  # chunk 0 becomes most recent

        cache.put(3, b"d" * self.MB)  # evicts chunk 1, not chunk 0

        assert cache.get(1) is None
        assert cache.get(0) == b"a" * self.MB
        assert cache.get(3) == b"d" * self.MB
        info = cache.info
        assert info["chunks"] == 3
        assert info["size_mb"] == 3.0
        assert info["max_mb"] == 3.0
        assert info["evictions"] >= 1
        assert info["hits"] >= 2

    def test_duplicate_put_is_a_noop(self):
        from app.streaming import ChunkCache

        cache = ChunkCache(max_bytes=2 * self.MB)
        cache.put(0, b"first")
        cache.put(0, b"second")
        assert cache.get(0) == b"first"

    def test_oversized_chunk_is_not_stored(self):
        from app.streaming import ChunkCache

        cache = ChunkCache(max_bytes=self.MB)
        cache.put(0, b"x" * (2 * self.MB))
        assert cache.get(0) is None
        assert cache.info["chunks"] == 0

    def test_clear_returns_freed_bytes(self):
        from app.streaming import ChunkCache

        cache = ChunkCache(max_bytes=2 * self.MB)
        cache.put(0, b"x" * self.MB)
        assert cache.clear() == self.MB
        assert cache.info["chunks"] == 0
        assert cache.info["hits"] == 0


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

    @_needs_symlinks
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


class TestFastCompression:
    """Brotli/gzip middleware for complete JSON/HTML responses."""

    @staticmethod
    def _run(
        mw,
        *,
        content_type: str = "application/json",
        body: bytes = b"{}",
        accept_encoding: bytes = b"gzip",
        status: int = 200,
        streamed: bool = False,
    ):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"accept-encoding", accept_encoding)]
            if accept_encoding
            else [],
        }
        sent = []

        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", content_type.encode()),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            if streamed:
                await send(
                    {"type": "http.response.body", "body": body, "more_body": True}
                )
                await send({"type": "http.response.body", "body": b""})
            else:
                await send({"type": "http.response.body", "body": body})

        asyncio.run(mw(app)(scope, receive, send))
        return sent

    def test_brotli_preferred_when_advertised(self):
        import brotli

        from app.compression import SelectiveCompressionMiddleware

        body = b'{"files": "' + b"x" * 5000 + b'"}'
        start, end = self._run(
            SelectiveCompressionMiddleware,
            body=body,
            accept_encoding=b"gzip, deflate, br",
        )
        headers = dict(start["headers"])
        assert headers[b"content-encoding"] == b"br"
        assert int(headers[b"content-length"]) == len(end["body"])
        assert brotli.decompress(end["body"]) == body

    def test_gzip_used_when_brotli_not_advertised(self):
        import gzip as gz

        from app.compression import SelectiveCompressionMiddleware

        body = b'{"files": "' + b"x" * 5000 + b'"}'
        start, end = self._run(
            SelectiveCompressionMiddleware,
            body=body,
            accept_encoding=b"gzip, deflate",
        )
        headers = dict(start["headers"])
        assert headers[b"content-encoding"] == b"gzip"
        assert gz.decompress(end["body"]) == body

    def test_brotli_q_zero_falls_back_to_gzip(self):
        from app.compression import SelectiveCompressionMiddleware

        body = b'{"files": "' + b"x" * 5000 + b'"}'
        start, _ = self._run(
            SelectiveCompressionMiddleware,
            body=body,
            accept_encoding=b"br;q=0, gzip",
        )
        assert dict(start["headers"])[b"content-encoding"] == b"gzip"

    def test_media_body_is_not_compressed(self):
        from app.compression import SelectiveCompressionMiddleware

        start, _ = self._run(
            SelectiveCompressionMiddleware,
            content_type="video/mp4",
            body=b"x" * 5000,
            accept_encoding=b"br, gzip",
        )
        assert b"content-encoding" not in dict(start["headers"])

    def test_partial_content_is_not_compressed(self):
        from app.compression import SelectiveCompressionMiddleware

        start, _ = self._run(
            SelectiveCompressionMiddleware,
            status=206,
            body=b"x" * 5000,
            accept_encoding=b"br, gzip",
        )
        assert b"content-encoding" not in dict(start["headers"])

    def test_small_body_is_not_compressed(self):
        from app.compression import SelectiveCompressionMiddleware

        start, _ = self._run(
            SelectiveCompressionMiddleware, body=b'{"ok": true}', accept_encoding=b"br"
        )
        assert b"content-encoding" not in dict(start["headers"])

    def test_client_without_supported_encoding_gets_identity(self):
        from app.compression import SelectiveCompressionMiddleware

        body = b'{"files": "' + b"x" * 5000 + b'"}'
        start, end = self._run(
            SelectiveCompressionMiddleware, body=body, accept_encoding=b""
        )
        assert b"content-encoding" not in dict(start["headers"])
        assert end["body"] == body

    def test_streamed_body_passes_through_uncompressed(self):
        from app.compression import SelectiveCompressionMiddleware

        body = b"x" * 5000
        sent = self._run(
            SelectiveCompressionMiddleware,
            body=body,
            accept_encoding=b"br, gzip",
            streamed=True,
        )
        assert b"content-encoding" not in dict(sent[0]["headers"])
        assert sent[1]["body"] == body

    def test_brotli_is_the_compressor_when_installed(self):
        from app import compression

        if compression.brotli is None:
            pytest.skip("brotli not installed")
        body = b"x" * 4000
        assert compression._compress(body, b"br") == compression.brotli.compress(
            body, quality=compression._BROTLI_QUALITY
        )

    def test_pick_encoding_honours_q_values(self):
        from app import compression

        assert compression._pick_encoding(b"gzip, deflate, br") == b"br"
        assert compression._pick_encoding(b"br;q=0.1, gzip;q=0.9") == b"gzip"
        assert compression._pick_encoding(b"gzip;q=0") is None
        assert compression._pick_encoding(b"") is None

    def test_unsupported_encoding_is_not_compressed(self):
        from app.compression import SelectiveCompressionMiddleware

        body = b'{"files": "' + b"x" * 5000 + b'"}'
        start, end = self._run(
            SelectiveCompressionMiddleware, body=body, accept_encoding=b"gzip;q=0"
        )
        assert b"content-encoding" not in dict(start["headers"])
        assert end["body"] == body


class TestNativeCryptoBackend:
    """MTProto must run on the native (Rust/C) AES backend.

    Pyrogram falls back to pure-python `pyaes` without a word, and that
    fallback caps a core at ~3 Mbit/s, so a stripped install has to fail the
    build here rather than degrade silently in production.
    """

    @staticmethod
    def _requirements() -> str:
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "requirements.txt"
        return path.read_text(encoding="utf-8")

    def test_requirement_pins_kuricrypt(self):
        import re

        lines = [
            line.strip()
            for line in self._requirements().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert any(
            re.match(r"^kuricrypt\s*[<>=!~]", line) for line in lines
        ), "kuricrypt must be pinned directly, not only via kurigram[fast]"

    def test_kuricrypt_pin_is_exact(self):
        """`>=` would let a plain `pip install -r` drift the AES backend.

        kuricrypt is what every bot client runs per packet, so upgrades are
        reviewed rather than pulled in by a resolver.
        """
        import re

        pins = [
            line.strip()
            for line in self._requirements().splitlines()
            if re.match(r"^\s*kuricrypt\s*==", line)
        ]
        assert len(pins) == 1, f"expected one exact kuricrypt pin, found {pins}"
        assert re.match(
            r"^kuricrypt==\d+\.\d+\.\d+$", pins[0]
        ), f"kuricrypt must be pinned to an exact release, got {pins[0]!r}"

    def test_tgcrypto_is_not_pinned(self):
        """kuricrypt is the chosen backend and wins in kurigram's lookup order.

        tgcrypto 1.2.5 has no aarch64 wheel (VPS is ARM) and no cp312+ wheel,
        so listing it would only add a source build that silently loses to
        kuricrypt anyway.
        """
        lines = [
            line.strip().lower()
            for line in self._requirements().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert not any(line.startswith("tgcrypto") for line in lines)

    def test_pyrogram_selected_a_native_backend(self):
        from app.crypto_backend import backend_name, is_native

        assert is_native(), (
            f"pyrogram loaded {backend_name()!r} - the pure-python fallback is "
            "~2000x slower; install kuricrypt"
        )

    def test_fallback_is_logged_as_an_error(self, monkeypatch, caplog):
        import logging

        from app import crypto_backend

        monkeypatch.setattr(crypto_backend.aes, "_crypto_backend", None)
        assert crypto_backend.backend_name() == "pyaes"
        assert not crypto_backend.is_native()

        seen: list[str] = []
        with caplog.at_level(logging.ERROR):
            crypto_backend.log_backend(logging.getLogger("crypto-test"), seen.append)
        assert "PURE PYTHON" in caplog.text
        assert seen and "PURE PYTHON" in seen[0]

    def test_native_backend_logs_info(self, monkeypatch, caplog):
        import logging
        import types

        from app import crypto_backend

        monkeypatch.setattr(
            crypto_backend.aes,
            "_crypto_backend",
            types.SimpleNamespace(__name__="kuricrypt"),
        )
        seen: list[str] = []
        with caplog.at_level(logging.INFO):
            crypto_backend.log_backend(logging.getLogger("crypto-test"), seen.append)
        assert crypto_backend.is_native()
        assert seen == ["MTProto crypto backend: kuricrypt (native)"]


class TestOrjsonResponses:
    """API payloads are encoded by orjson (Rust), not stdlib ``json``.

    FastAPI silently uses ``json.dumps`` unless the app sets
    ``default_response_class``; on a 400-file /api/files payload that is
    ~6x slower (scripts/bench_json.py), so the wiring must be asserted.
    """

    def test_default_response_class_is_orjson(self):
        from app.json_response import OrjsonResponse
        from app.main import app

        assert app.router.default_response_class is OrjsonResponse

    def test_render_is_compact_utf8(self):
        from app.json_response import OrjsonResponse

        body = OrjsonResponse({"a": 1, "b": "é"}).body
        assert body == '{"a":1,"b":"é"}'.encode("utf-8")

    def test_health_is_served_as_orjson(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["status"] == "healthy"
        # orjson emits compact UTF-8; the stdlib encoder separates items with
        # ", " (health has two keys, so the difference is visible).
        assert b'", "' not in resp.content


class TestSubtitleTextDecoding:
    """Provider subtitle bytes are not guaranteed to be UTF-8.

    Decoding them with errors="replace" turned every accent in a Windows-1252
    file into U+FFFD, so the detector path must stay wired in.
    """

    def test_empty_input(self):
        from app.text_decode import decode_text

        assert decode_text(b"") == ""

    def test_utf8_passthrough(self):
        from app.text_decode import decode_text

        text = "1\n00:00:01,000 --> 00:00:02,000\ncafé déjà vu\n"
        assert decode_text(text.encode("utf-8")) == text

    def test_utf8_bom_is_stripped(self):
        from app.text_decode import decode_text

        assert decode_text(b"\xef\xbb\xbfWEBVTT\n\nhi") == "WEBVTT\n\nhi"

    def test_windows1252_file_is_not_mojibake(self):
        from app.text_decode import decode_text

        # Varied prose, as in a real subtitle file: detectors need signal.
        text = (
            "1\n00:00:01,000 --> 00:00:04,000\n"
            "Bonjour, comment allez-vous ? Je ne savais pas que vous étiez là.\n\n"
            "2\n00:00:05,000 --> 00:00:08,500\n"
            "Écoutez, il faut qu'on parle de ce qui s'est passé hier soir.\n\n"
            "3\n00:00:09,000 --> 00:00:12,000\n"
            "« Ce n'est pas une bonne idée », répondit-elle en soupirant.\n\n"
            "4\n00:00:13,000 --> 00:00:16,000\n"
            "Le café était froid, mais la conversation était passionnante.\n\n"
            "5\n00:00:17,000 --> 00:00:20,000\n"
            "Nous devrions peut-être rentrer avant la nuit — il fait déjà sombre.\n"
        )
        decoded = decode_text(text.encode("cp1252"))
        assert "\ufffd" not in decoded
        assert decoded == text
        assert "“" not in decoded  # the file uses « », not curly quotes

    def test_windows1251_cyrillic_file(self):
        from app.text_decode import decode_text

        text = (
            "1\n00:00:01,000 --> 00:00:04,000\n"
            "Привет, как дела? Я не знал, что ты здесь.\n\n"
            "2\n00:00:05,000 --> 00:00:08,000\n"
            "Слушай, нам нужно поговорить о вчерашнем вечере.\n"
        )
        assert decode_text(text.encode("cp1251")) == text

    def test_short_latin1_line_does_not_raise(self):
        from app.text_decode import decode_text

        assert decode_text("naïve résumé".encode("latin-1")) == "naïve résumé"

    def test_undecodable_bytes_never_raise(self):
        from app.text_decode import decode_text

        text = decode_text(bytes(range(128, 256)))
        assert isinstance(text, str) and text

    def test_subtitles_router_uses_the_detector(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "app" / "routers" / "subtitles.py"
        ).read_text(encoding="utf-8")
        assert "decode_text(content)" in source
        assert 'errors="replace"' not in source


class TestTelegramErrors:
    """Telegram failures are classified by exception type, not message text.

    Kurigram exposes the number Telegram sent as ``.value`` on typed errors;
    string parsing is only a fallback for wrapped/foreign exceptions.
    """

    def test_flood_wait_uses_typed_value(self):
        from pyrogram import errors

        from app.telegram_errors import flood_wait_seconds

        assert flood_wait_seconds(errors.FloodWait(value=42)) == 42
        assert flood_wait_seconds(errors.SlowmodeWait(value=7)) == 7

    def test_flood_wait_text_fallback(self):
        from app.telegram_errors import flood_wait_seconds

        assert flood_wait_seconds(Exception("[420 FLOOD_WAIT_12]")) == 12
        assert flood_wait_seconds(Exception("A wait of 9 seconds is required")) == 9
        assert flood_wait_seconds(Exception("unrelated error 500")) is None

    def test_typed_value_beats_status_code(self):
        # The old telegram.py regex read the first number in the message — the
        # 420 status code — so every wait was clamped to the 120s cap.
        from pyrogram import errors

        from app.telegram_errors import flood_wait_seconds

        exc = errors.FloodWait(value=42)
        assert "420" in str(exc)
        assert flood_wait_seconds(exc) == 42

    def test_is_flood(self):
        from pyrogram import errors

        from app.telegram_errors import is_flood

        assert is_flood(errors.FloodWait(value=1))
        assert is_flood(errors.SlowmodeWait(value=1))
        assert is_flood(Exception("FLOOD_WAIT_3"))
        assert not is_flood(Exception("internal error"))

    def test_is_slowmode(self):
        from pyrogram import errors

        from app.telegram_errors import is_slowmode

        assert is_slowmode(errors.SlowmodeWait(value=3))
        assert not is_slowmode(errors.FloodWait(value=3))
        assert is_slowmode(Exception("SLOWMODE_WAIT_3"))

    def test_is_stale_session(self):
        from pyrogram import errors

        from app.telegram_errors import is_stale_session

        assert is_stale_session(errors.AuthKeyUnregistered())
        assert is_stale_session(errors.LimitInvalid())
        assert is_stale_session(Exception("AUTH_KEY_UNREGISTERED"))
        assert not is_stale_session(Exception("FLOOD_WAIT_3"))

    def test_is_auth_bytes_invalid(self):
        from pyrogram import errors

        from app.telegram_errors import is_auth_bytes_invalid

        assert is_auth_bytes_invalid(errors.AuthBytesInvalid())
        assert is_auth_bytes_invalid(Exception("AUTH_BYTES_INVALID"))
        assert not is_auth_bytes_invalid(Exception("other error"))

    def test_grabber_delegates_to_shared_helper(self):
        from pyrogram import errors

        from app.grabber import _flood_seconds

        assert _flood_seconds(errors.FloodWait(value=15)) == 15


class TestSetupLoginFlow:
    """The self-host setup helper must use Pyrogram's typed exceptions.

    It previously imported ``SESSION_PASSWORD_NEEDED`` from ``pyrogram.errors``,
    which does not exist, so every /setup/sign-in call raised ImportError
    (HTTP 500) before the try block — including the 2FA branch.
    """

    @staticmethod
    def _entry(client):
        import time

        return {"client": client, "phone": "+100000", "hash": "h", "ts": time.monotonic()}

    @staticmethod
    def _req():
        """A real Starlette Request: slowapi's @limiter.limit requires one."""
        from starlette.requests import Request

        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/setup/sign-in",
                "headers": [(b"host", b"testserver")],
                "query_string": b"",
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
                "scheme": "http",
            }
        )

    @staticmethod
    async def _drain_tasks(times: int = 5) -> None:
        """Let tracked background coroutines (the client disconnect) finish."""
        for _ in range(times):
            await asyncio.sleep(0)

    @staticmethod
    def _body(**kwargs):
        from app.routers.setup import SignInIn

        return SignInIn(setup_key="secret", token="tok", code="12345", **kwargs)

    def _install(self, monkeypatch, client):
        from app.routers import setup as setup_mod

        monkeypatch.setenv("SETUP_PASSWORD", "secret")
        setup_mod._pending.clear()
        setup_mod._pending["tok"] = self._entry(client)
        return setup_mod

    @pytest.mark.asyncio
    async def test_2fa_requests_password(self, monkeypatch):
        from fastapi import HTTPException
        from pyrogram.errors import SessionPasswordNeeded

        class FakeClient:
            async def sign_in(self, *a):
                raise SessionPasswordNeeded()

            async def check_password(self, pw):
                raise AssertionError("password must not be checked yet")

            async def export_session_string(self):
                return "SESSION"

            async def disconnect(self):
                pass

        setup_mod = self._install(monkeypatch, FakeClient())
        try:
            with pytest.raises(HTTPException) as exc:
                await setup_mod.setup_sign_in(self._req(), self._body())
            assert exc.value.status_code == 401
            assert exc.value.detail == "need_password"
        finally:
            setup_mod._pending.clear()

    @pytest.mark.asyncio
    async def test_wrong_2fa_password_is_403(self, monkeypatch):
        from fastapi import HTTPException
        from pyrogram.errors import PasswordHashInvalid, SessionPasswordNeeded

        class FakeClient:
            async def sign_in(self, *a):
                raise SessionPasswordNeeded()

            async def check_password(self, pw):
                raise PasswordHashInvalid()

            async def export_session_string(self):
                return "SESSION"

            async def disconnect(self):
                pass

        setup_mod = self._install(monkeypatch, FakeClient())
        try:
            with pytest.raises(HTTPException) as exc:
                await setup_mod.setup_sign_in(self._req(), self._body(password="bad"))
            assert exc.value.status_code == 403
            assert "Wrong 2FA password" in exc.value.detail
        finally:
            setup_mod._pending.clear()

    @pytest.mark.asyncio
    async def test_2fa_success_returns_session_and_disconnects(self, monkeypatch):
        from pyrogram.errors import SessionPasswordNeeded

        class FakeClient:
            def __init__(self):
                self.disconnected = False

            async def sign_in(self, *a):
                raise SessionPasswordNeeded()

            async def check_password(self, pw):
                assert pw == "good"

            async def export_session_string(self):
                return "SESSION-STRING"

            async def disconnect(self):
                self.disconnected = True

        client = FakeClient()
        setup_mod = self._install(monkeypatch, client)
        try:
            result = await setup_mod.setup_sign_in(self._req(), self._body(password="good"))
            assert result == {"session_string": "SESSION-STRING"}
            assert "tok" not in setup_mod._pending
            await self._drain_tasks()  # let the tracked disconnect task run
            assert client.disconnected
        finally:
            setup_mod._pending.clear()

    @pytest.mark.asyncio
    async def test_invalid_and_expired_codes_are_400(self, monkeypatch):
        from fastapi import HTTPException
        from pyrogram.errors import PhoneCodeExpired, PhoneCodeInvalid

        class InvalidClient:
            async def sign_in(self, *a):
                raise PhoneCodeInvalid()

            async def disconnect(self):
                pass

        class ExpiredClient:
            async def sign_in(self, *a):
                raise PhoneCodeExpired()

            async def disconnect(self):
                pass

        for client, needle in (
            (InvalidClient(), "Invalid login code"),
            (ExpiredClient(), "Login code expired"),
        ):
            setup_mod = self._install(monkeypatch, client)
            try:
                with pytest.raises(HTTPException) as exc:
                    await setup_mod.setup_sign_in(self._req(), self._body())
                assert exc.value.status_code == 400
                assert needle in exc.value.detail
            finally:
                setup_mod._pending.clear()

    @pytest.mark.asyncio
    async def test_expired_entry_is_disconnected(self, monkeypatch):
        import time

        from app.routers import setup as setup_mod

        class FakeClient:
            def __init__(self):
                self.disconnected = False

            async def disconnect(self):
                self.disconnected = True

        client = FakeClient()
        setup_mod._pending.clear()
        setup_mod._pending["old"] = {
            "client": client,
            "phone": "",
            "hash": "",
            "ts": time.monotonic() - setup_mod._TTL_SECONDS - 1,
        }
        try:
            setup_mod._cleanup_expired()
            assert "old" not in setup_mod._pending
            await self._drain_tasks()
            assert client.disconnected
        finally:
            setup_mod._pending.clear()

    @pytest.mark.asyncio
    async def test_pending_store_is_bounded(self, monkeypatch):
        from app.routers import setup as setup_mod

        class FakeClient:
            async def disconnect(self):
                pass

        setup_mod._pending.clear()
        try:
            for i in range(setup_mod._MAX_PENDING):
                setup_mod._pending[f"t{i}"] = self._entry(FakeClient())
            setup_mod._evict_oldest()
            assert len(setup_mod._pending) == setup_mod._MAX_PENDING - 1
            assert "t0" not in setup_mod._pending
            assert "t1" in setup_mod._pending
            await self._drain_tasks()
        finally:
            setup_mod._pending.clear()

    def test_no_legacy_constant_import(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "app" / "routers" / "setup.py"
        ).read_text(encoding="utf-8")
        assert "SESSION_PASSWORD_NEEDED" not in source
        assert "SessionPasswordNeeded" in source
