"""
JWT authentication utilities.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets

from cachebox import TTLCache
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from .config import get_settings
from .database import get_db
from .models import User


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# telegram_id → "last_active was written recently" marker (throttle).
#
# A plain dict here leaked: every telegram_id that ever authenticated stayed in
# it forever, so memory grew with the user table and never shrank. cachebox
# expires each entry after the throttle window and caps the map, so the entry
# exists exactly while it is still suppressing writes. Evicting an entry only
# costs one extra UPDATE on the next request.
_LAST_ACTIVE_TOUCH_TTL = 300  # 5 minutes
_last_active_touch: TTLCache = TTLCache(
    maxsize=10_000, global_ttl=_LAST_ACTIVE_TOUCH_TTL
)

settings = get_settings()
security = HTTPBearer(auto_error=False)

REFRESH_TOKEN_DURATION = timedelta(minutes=settings.jwt_expiry_minutes * 4)


def create_download_token(telegram_id: int, file_id: int, version: int = 0) -> str:
    """Create a JWT download token bound to a specific file (valid 30 days)."""
    expire = datetime.now(timezone.utc) + timedelta(days=30)
    payload = {
        "sub": str(telegram_id),
        "exp": expire,
        "type": "download",
        "file_id": file_id,
        "ver": version,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_file_download_token(telegram_id: int, file_id: int, version: int = 0) -> str:
    """Create a short-lived JWT download token bound to a specific file (10 min)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=10)
    payload = {
        "sub": str(telegram_id),
        "exp": expire,
        "type": "download",
        "file_id": file_id,
        "ver": version,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_access_token(telegram_id: int, version: int = 0) -> str:
    """Create a JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiry_minutes)
    payload = {
        "sub": str(telegram_id),  # Subject must be string
        "exp": expire,
        "type": "access",
        "ver": version,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(telegram_id: int, version: int = 0) -> str:
    """Create a JWT refresh token (4x longer than access token)."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expiry_minutes * 4
    )
    payload = {
        "sub": str(telegram_id),  # Subject must be string
        "exp": expire,
        "type": "refresh",
        "ver": version,
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_token_payload(token: str, token_type: str = "access") -> Optional[dict]:
    """Verify JWT token and return full payload if valid."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != token_type:
            return None
        return payload
    except (JWTError, ValueError):
        return None


def verify_token(token: str, token_type: str = "access") -> Optional[int]:
    """Verify JWT token and return telegram_id if valid."""
    payload = verify_token_payload(token, token_type)
    if not payload:
        return None

    sub = payload.get("sub")
    if sub is None:
        return None
    try:
        return int(sub)
    except (TypeError, ValueError):
        return None


async def get_current_user_opt(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Optional auth — returns None instead of raising on missing/invalid token."""
    token = None
    if credentials:
        token = credentials.credentials
    if not token and request and "token" in request.query_params:
        token = request.query_params["token"]
    if not token:
        return None
    try:
        payload = verify_token_payload(token)
        telegram_id = (
            int(payload.get("sub")) if payload and payload.get("sub") else None
        )
        token_version = payload.get("ver") if payload else None
    except Exception:
        return None
    if not telegram_id:
        return None
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return None
    if token_version is not None and token_version < user.auth_version:
        return None
    return user


async def get_current_user(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency to get current authenticated user. Supports Bearer token or query param."""
    token = None

    # Try getting token from Authorization header
    if credentials:
        token = credentials.credentials

    # If not in header, try query parameter (for streaming/images)
    if not token and request and "token" in request.query_params:
        token = request.query_params["token"]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify token
    try:
        payload = verify_token_payload(token)
        telegram_id = (
            int(payload.get("sub")) if payload and payload.get("sub") else None
        )
        token_version = payload.get("ver") if payload else None
    except Exception:
        telegram_id = None
        token_version = None

    if not telegram_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Check token version for global logout
    if token_version is not None and token_version < user.auth_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Track activity for the admin "active today" stat. Throttled to one
    # write per user per 5 minutes — a per-request write would hammer the
    # users table on every stream chunk/authenticated call. The marker is
    # inserted *before* the write, so a failing DB write still throttles.
    if _last_active_touch.get(user.id) is None:
        _last_active_touch.insert(user.id, True)
        try:
            await db.execute(
                update(User).where(User.id == user.id).values(last_active=_utcnow())
            )
            await db.commit()
        except Exception:
            await db.rollback()

    return user
