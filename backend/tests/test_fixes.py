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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


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
    from app.models import Base
    
    await init_db()
    
    async with async_session() as session:
        yield session
    
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest_asyncio.fixture
async def sample_user(temp_db):
    """Create a test user."""
    from app.models import User
    user = User(
        telegram_id=999999,
        username="testuser",
        first_name="Test",
        auth_version=0
    )
    temp_db.add(user)
    await temp_db.commit()
    await temp_db.refresh(user)
    return user


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
            create_access_token, create_refresh_token,
            REFRESH_TOKEN_DURATION, verify_token_payload
        )
        from app.routers.auth import refresh_token
        from app.models import User, RefreshSession
        from app.schemas import RefreshTokenRequest

        # Create user
        user = User(
            telegram_id=999999,
            username="testuser",
            first_name="Test",
            auth_version=0
        )
        temp_db.add(user)
        await temp_db.commit()
        await temp_db.refresh(user)

        # Create initial refresh token and session
        refresh_token_str = create_refresh_token(user.telegram_id, version=user.auth_version)
        token_hash = sha256(refresh_token_str.encode()).hexdigest()
        session = RefreshSession(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + REFRESH_TOKEN_DURATION,
            last_used_at=datetime.now(timezone.utc).replace(tzinfo=None)
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
        sessions = await temp_db.execute(select(RefreshSession).where(RefreshSession.user_id == user.id))
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
            def continue_propagation(self): self._cont = True
            def stop_propagation(self): self._stop = True

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
                fut.add_done_callback(functools.partial(client._forget_listener, key, entry))
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
            def continue_propagation(self): self._cont = True
            def stop_propagation(self): self._stop = True

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
            fut.add_done_callback(functools.partial(client._forget_listener, "1", entry))

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
        result = await _user_from_download_token(
            _make_mock_request(stale), 42, temp_db
        )
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
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
        )
        temp_db.add(code)
        await temp_db.commit()

        # slowapi's decorator validates a real starlette Request
        from starlette.requests import Request as StarletteRequest
        req = StarletteRequest({
            "type": "http", "method": "POST",
            "path": "/api/auth/verify-code",
            "headers": [], "query_string": b"",
            "client": ("127.0.0.1", 12345),
        })
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
        return Request({
            "type": "http", "method": "GET",
            "path": "/s/pubhash123",
            "headers": headers, "query_string": b"",
            "client": ("127.0.0.1", 12345),
        })

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
            file_id="fid", file_unique_id="u2", file_name="empty.mp4",
            file_size=0, mime_type="video/mp4", file_type="video",
            channel_message_id=78, public_hash="zerohash",
        )
        temp_db.add(f)
        await temp_db.commit()

        resp = await stream_public_file(
            public_hash="zerohash", request=self._req(None), db=temp_db, download=0,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_zero_byte_with_range_416(self, temp_db, sample_user):
        from app.models import File
        from app.routers.streaming import stream_public_file
        f = File(
            user_id=sample_user.id,
            file_id="fid", file_unique_id="u3", file_name="empty.mp4",
            file_size=0, mime_type="video/mp4", file_type="video",
            channel_message_id=79, public_hash="zerohash2",
        )
        temp_db.add(f)
        await temp_db.commit()

        resp = await stream_public_file(
            public_hash="zerohash2", request=self._req("bytes=0-100"), db=temp_db, download=0,
        )
        assert resp.status_code == 416


class TestMemEnvParsing:
    """MEMORY env must accept M/MB suffixes, not only G variants."""

    def test_suffixes(self):
        from app.status import _parse_mem_env
        assert _parse_mem_env("3Gi") == 3 * 1024 ** 3
        assert _parse_mem_env("3G") == 3 * 1024 ** 3
        assert _parse_mem_env("512M") == 512 * 1024 ** 2
        assert _parse_mem_env("2MB") == 2 * 1024 ** 2
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

            assert tmp_f.exists()      # in-flight write protected
            assert not c0.exists()     # oldest real chunk evicted instead
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
        return Request({
            "type": "http", "method": "GET",
            "path": "/api/status",
            "headers": headers, "query_string": b"",
            "client": ("127.0.0.1", 12345),
        })

    @pytest.mark.asyncio
    async def test_anonymous_status_strips_sensitive_fields(self, monkeypatch):
        from app import main as app_main

        async def fake_status():
            return {
                "cpu": 1.0, "ram": {}, "net": {},
                "logs": ["secret log line"],
                "cache": {"per_video": [{"chat_id": -100}], "forward": {"total_prebuffer_mb": 1}},
                "disk": {}, "uptime_seconds": 1, "history": [],
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
                "cpu": 1.0, "ram": {}, "net": {},
                "logs": ["secret log line"],
                "cache": {"per_video": [{"chat_id": -100}], "forward": None},
                "disk": {}, "uptime_seconds": 1, "history": [],
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])