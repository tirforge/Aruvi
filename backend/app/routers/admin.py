from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..database import get_db
from ..models import User, File, Folder
from ..schemas import AdminUserResponse, AdminStats
from ..auth import get_current_user

router = APIRouter(prefix="/admin", tags=["Admin"])


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@router.get("/stats", response_model=AdminStats)
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    users_c = await db.execute(select(func.count()).select_from(User))
    files_c = await db.execute(select(func.count()).select_from(File))
    folders_c = await db.execute(select(func.count()).select_from(Folder))
    storage_c = await db.execute(select(func.coalesce(func.sum(File.file_size), 0)))
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    active_c = await db.execute(
        select(func.count()).where(User.last_active >= cutoff)
    )
    return AdminStats(
        total_users=users_c.scalar() or 0,
        total_files=files_c.scalar() or 0,
        total_folders=folders_c.scalar() or 0,
        total_storage_bytes=int(storage_c.scalar() or 0),
        active_today=active_c.scalar() or 0,
    )


@router.get("/users", response_model=list[AdminUserResponse])
async def admin_list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    storage_subq = (
        select(func.coalesce(func.sum(File.file_size), 0))
        .where(File.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    file_count_subq = (
        select(func.count(File.id))
        .where(File.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    folder_count_subq = (
        select(func.count(Folder.id))
        .where(Folder.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    result = await db.execute(
        select(
            User.id,
            User.telegram_id,
            User.username,
            User.first_name,
            User.last_name,
            User.is_admin,
            User.created_at,
            User.last_active,
            file_count_subq.label("file_count"),
            folder_count_subq.label("folder_count"),
            storage_subq.label("storage_bytes"),
        )
        # No outerjoins: joining files×folders materializes |files|×|folders|
        # intermediate rows per user before the aggregation; correlated scalar
        # subqueries use the existing indexes instead.
        .order_by(User.last_active.desc())
    )
    rows = result.all()
    return [
        AdminUserResponse(
            id=row.id,
            telegram_id=row.telegram_id,
            username=row.username,
            first_name=row.first_name,
            last_name=row.last_name,
            is_admin=row.is_admin,
            created_at=row.created_at,
            last_active=row.last_active,
            file_count=row.file_count,
            folder_count=row.folder_count,
            storage_bytes=row.storage_bytes,
        )
        for row in rows
    ]


@router.post("/users/{user_id}/toggle-admin")
async def admin_toggle_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own admin status")
    user.is_admin = not user.is_admin
    await db.commit()
    return {"is_admin": user.is_admin}


@router.delete("/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    # Collect storage-channel message ids BEFORE the cascade delete removes
    # the file rows, so the Telegram copies can be cleaned up after commit.
    from ..telegram import delete_from_storage_channel, invalidate_message_cache_batch
    msg_result = await db.execute(
        select(File.channel_message_id).where(File.user_id == user.id)
    )
    msg_ids = [mid for (mid,) in msg_result.all() if mid]
    if msg_ids:
        invalidate_message_cache_batch(msg_ids)

    await db.delete(user)
    await db.commit()

    # Best-effort cleanup from Telegram AFTER commit so slow network deletes
    # never hold the DB transaction open. DB rows are already gone either way.
    if msg_ids:
        for i in range(0, len(msg_ids), 100):
            batch = msg_ids[i:i + 100]
            try:
                await delete_from_storage_channel(batch)
            except Exception:
                pass

    return {"deleted": True}
