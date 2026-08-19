"""
Authentication API endpoints.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import User, LoginCode
from ..rate_limit import limiter
from ..schemas import (
    Token,
    UserResponse,
    LoginCodeRequest,
    LoginCodeResponse,
    VerifyCodeRequest,
    AuthResponse,
    RefreshTokenRequest,
    BotInfoResponse,
)
from ..auth import (
    create_access_token,
    create_refresh_token,
    verify_token_payload,
    get_current_user,
)
from ..telegram import tg_client


_bot_info_cache = {"data": None, "ts": 0}
_BOT_INFO_TTL_SECONDS = 3600

router = APIRouter(prefix="/auth", tags=["Authentication"])



@router.get("/bot/info", response_model=BotInfoResponse)
async def get_bot_info_endpoint():
    """Get bot username and name for the login screen (cached to avoid Telegram flood waits)."""
    cached = _bot_info_cache["data"]
    if cached and time.time() - _bot_info_cache["ts"] < _BOT_INFO_TTL_SECONDS:
        return cached
    try:
        me = await tg_client.get_me()
        data = BotInfoResponse(
            username=me.username,
            name=f"{me.first_name} {me.last_name or ''}".strip(),
            server_version="1.0.0"
        )
        _bot_info_cache["data"] = data
        _bot_info_cache["ts"] = time.time()
        return data
    except Exception as e:
        logging.getLogger("auth").error("Failed to get bot info: %s", e)
        if cached:
            return cached
        raise HTTPException(status_code=500, detail="Unable to fetch bot info")


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token."""
    payload = verify_token_payload(request.refresh_token, token_type="refresh")
    telegram_id = int(payload.get("sub")) if payload and payload.get("sub") else None
    token_version = payload.get("ver") if payload else None
    
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    
    # Verify user exists
    result = await db.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    if token_version is not None and token_version < user.auth_version:
        raise HTTPException(status_code=401, detail="Refresh token has been invalidated")
    
    # Generate new tokens
    new_access_token = create_access_token(telegram_id, version=user.auth_version)
    new_refresh_token = create_refresh_token(telegram_id, version=user.auth_version)
    
    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )


@router.post("/logout-all")
async def logout_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate all active sessions for the current user."""
    current_user.auth_version += 1
    db.add(current_user)
    await db.commit()
    return {"message": "All sessions have been invalidated"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """Get current authenticated user information."""
    return UserResponse(
        id=current_user.id,
        telegram_id=current_user.telegram_id,
        username=current_user.username,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        created_at=current_user.created_at,
        last_active=current_user.last_active,
    )


@router.post("/generate-code", response_model=LoginCodeResponse)
@limiter.limit("10/minute")
async def generate_login_code(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a new login code for TV/Device authentication.
    The code is displayed to the user and entered in the Telegram bot.
    """
    # Generate unique 6-character alphanumeric code.
    # LoginCode.code is UNIQUE and shared with codes minted by the bot's
    # /login, so a rare collision must be retried instead of 500-ing.
    import secrets
    import string
    from sqlalchemy.exc import IntegrityError

    alphabet = string.ascii_uppercase + string.digits
    code = None
    login_code = None
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)
    for _ in range(5):
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        login_code = LoginCode(
            code=code,
            telegram_id=None,  # Initially null, set by bot
            expires_at=expires_at
        )
        db.add(login_code)
        try:
            await db.commit()
            break
        except IntegrityError:
            await db.rollback()
            login_code = None

    if login_code is None:
        raise HTTPException(status_code=500, detail="Failed to generate a login code")

    await db.refresh(login_code)
    
    return LoginCodeResponse(
        code=code,
        expires_at=expires_at
    )


@router.post("/verify-code", response_model=AuthResponse)
@limiter.limit("40/minute")  # Allow TV polling while limiting brute force attempts
async def verify_login_code(
    request: Request,  # Required for rate limiter
    code_request: VerifyCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Check if the login code has been claimed by a user via Telegram bot.
    If claimed, returns access tokens and user info.
    """
    # Find code (case-insensitive)
    result = await db.execute(
        select(LoginCode).where(LoginCode.code == code_request.code.upper())
    )
    login_code = result.scalar_one_or_none()
    
    if not login_code:
        # Don't distinguish between invalid and unclaimed — always return 202
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"detail": "Code not yet verified", "status": "pending"},
            headers={"Retry-After": "3"},
        )
        
    if login_code.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        await db.delete(login_code)
        await db.commit()
        # Same response as unclaimed — don't reveal code existed
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"detail": "Code not yet verified", "status": "pending"},
            headers={"Retry-After": "3"},
        )
    
    # Check if user has claimed it (telegram_id is set)
    if not login_code.telegram_id:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"detail": "Code not yet verified", "status": "pending"},
            headers={"Retry-After": "3"},
        )
        
    # Get user
    result = await db.execute(
        select(User).where(User.telegram_id == login_code.telegram_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        # Should not happen if bot flow is correct
        raise HTTPException(status_code=404, detail="User not found")
        
    # Generate tokens
    access_token = create_access_token(user.telegram_id, version=user.auth_version)
    refresh_token = create_refresh_token(user.telegram_id, version=user.auth_version)
    
    # Delete code after successful login
    await db.delete(login_code)
    await db.commit()
    
    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user, from_attributes=True)
    )


# Keep this for backward compatibility or direct code login if needed, 
# but verify-code is the main one for TV flow now.
@router.post("/code", response_model=AuthResponse)
async def login_with_code(
    request: Request,
    code_request: LoginCodeRequest,
    db: AsyncSession = Depends(get_db),
):
   """Legacy endpoint - use verify-code instead."""
   # Same logic as verify-code but returns only Token
   # ... (reusing logic or redirecting)
   return await verify_login_code(
       request,
       VerifyCodeRequest(code=code_request.code),
       db
   )
