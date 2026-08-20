"""
JWT authentication utilities.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets

from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .config import get_settings
from .database import get_db
from .models import User
from .schemas import TokenPayload

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
        "ver": version
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
        "ver": version
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(telegram_id: int, version: int = 0) -> str:
    """Create a JWT refresh token (4x longer than access token)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiry_minutes * 4)
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
    return int(sub) if sub is not None else None



async def get_current_user_opt(
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
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
        telegram_id = int(payload.get("sub")) if payload and payload.get("sub") else None
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
    db: AsyncSession = Depends(get_db)
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
        telegram_id = int(payload.get("sub")) if payload and payload.get("sub") else None
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
    
    return user
