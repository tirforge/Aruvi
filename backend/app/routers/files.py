"""
File management API endpoints.
"""
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
import secrets
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, update
from sqlalchemy.orm import selectinload, defer

from ..database import get_db
from ..models import File, Folder, User, WatchProgress
from ..schemas import FileResponse, FileListResponse, FileUpdate, WatchProgressUpdate, WatchProgressResponse, BatchMoveRequest
from ..auth import get_current_user, create_file_download_token
from ..telegram import delete_from_storage_channel, invalidate_message_cache, invalidate_message_cache_batch
from ..config import get_settings
from ..services import (
    escape_like, 
    add_urls_to_file, 
    fetch_recent_files, 
    fetch_continue_watching_files
)
from ..utils import sanitize_filename

router = APIRouter(prefix="/files", tags=["Files"])
settings = get_settings()


@router.get("", response_model=FileListResponse)
async def list_files(
    folder_id: Optional[int] = Query(None, description="Filter by folder ID (null for root)"),
    file_type: Optional[str] = Query(None, description="Filter by file type"),
    search: Optional[str] = Query(None, description="Search by filename"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List user's files with optional filtering."""
    query = select(File).where(File.user_id == current_user.id).options(
        selectinload(File.watch_progress),
        defer(File.thumbnail_data),  # never serialized in lists — don't send blobs from DB
    )
    
    
    # Apply filters
    if folder_id is not None:
        query = query.where(File.folder_id == folder_id)
    elif not search and not file_type:
        # If simply browsing (no search/filter), only show files in root (folder_id is NULL)
        query = query.where(File.folder_id.is_(None))
        
    if file_type:
        query = query.where(File.file_type == file_type)
    if search:
        query = query.where(File.file_name.ilike(f"%{escape_like(search)}%", escape="\\"))
    
    # Direct count with same filters (avoid subquery materialization)
    count_query = select(func.count(File.id)).where(File.user_id == current_user.id)
    if folder_id is not None:
        count_query = count_query.where(File.folder_id == folder_id)
    elif not search and not file_type:
        count_query = count_query.where(File.folder_id.is_(None))
    if file_type:
        count_query = count_query.where(File.file_type == file_type)
    if search:
        count_query = count_query.where(File.file_name.ilike(f"%{escape_like(search)}%", escape="\\"))
    total = (await db.execute(count_query)).scalar()
    
    # Apply pagination
    query = query.order_by(File.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    
    result = await db.execute(query)
    files = result.scalars().all()
    
    return FileListResponse(
        files=[FileResponse(**add_urls_to_file(f)) for f in files],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/recent", response_model=FileListResponse)
async def get_recent_files(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get recently added files across all folders."""
    files = await fetch_recent_files(db, current_user.id, limit)
    
    return FileListResponse(
        files=[FileResponse(**add_urls_to_file(f)) for f in files],
        total=len(files),
        page=1,
        per_page=limit,
    )


@router.get("/continue-watching", response_model=FileListResponse)
async def get_continue_watching(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get files with watch progress."""
    files = await fetch_continue_watching_files(db, current_user.id, limit)
    
    return FileListResponse(
        files=[FileResponse(**add_urls_to_file(f)) for f in files],
        total=len(files),
        page=1,
        per_page=limit,
    )


@router.get("/storage", response_model=dict)
async def get_storage_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get total storage usage."""
    query = select(func.sum(File.file_size)).where(File.user_id == current_user.id)
    result = await db.execute(query)
    total_size = int(result.scalar() or 0)
    
    return {
        "total_size": total_size,
        "limit": -1  # Unlimited
    }


@router.get("/{file_id}", response_model=FileResponse)
async def get_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific file by ID."""
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id).options(selectinload(File.watch_progress))
    )
    file = result.scalar_one_or_none()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(**add_urls_to_file(file))


@router.patch("/{file_id}", response_model=FileResponse)
async def update_file(
    file_id: int,
    update_data: FileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update file metadata (rename, move to folder)."""
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Update fields
    if update_data.file_name is not None:
        file.file_name = sanitize_filename(update_data.file_name)
    if update_data.folder_id is not None:
        target_folder_id = update_data.folder_id if update_data.folder_id != 0 else None
        # Verify target folder belongs to the current user (mirrors batch_move_files)
        if target_folder_id is not None:
            folder_check = await db.execute(
                select(Folder).where(Folder.id == target_folder_id, Folder.user_id == current_user.id)
            )
            if not folder_check.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Target folder not found")
        file.folder_id = target_folder_id
    
    await db.commit()
    
    # Re-fetch with relationships
    result = await db.execute(
        select(File).where(File.id == file_id).options(selectinload(File.watch_progress))
    )
    file = result.scalar_one()
    
    return FileResponse(**add_urls_to_file(file))

@router.post("/{file_id}/download-token")
async def get_file_download_token(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Issue a short-lived, file-bound download token for the current user's file."""
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()

    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    token = create_file_download_token(
        current_user.telegram_id, file_id, version=current_user.auth_version
    )
    return {"token": token}


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a file from database and Telegram channel."""
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Delete from database first — if this fails, Telegram file is untouched
    channel_message_id = file.channel_message_id
    invalidate_message_cache(channel_message_id)
    await db.delete(file)
    await db.commit()
    
    # Best-effort cleanup from Telegram storage channel
    try:
        await delete_from_storage_channel(channel_message_id)
    except Exception:
        pass
    
    return {"message": "File deleted successfully"}


@router.post("/batch-delete")
async def batch_delete_files(
    file_ids: list[int],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete multiple files."""
    # Fetch all files
    result = await db.execute(
        select(File)
        .where(File.id.in_(file_ids), File.user_id == current_user.id)
        .options(defer(File.thumbnail_data))
    )
    files = result.scalars().all()
    
    if not files:
        return {"message": "No files found to delete"}
    
    # Collect message IDs and delete from DB first
    msg_ids = [f.channel_message_id for f in files if f.channel_message_id]
    invalidate_message_cache_batch(msg_ids)
    for file in files:
        await db.delete(file)
    await db.commit()
    
    # Best-effort cleanup from Telegram
    if msg_ids:
        chunk_size = 100
        for i in range(0, len(msg_ids), chunk_size):
            batch = msg_ids[i:i + chunk_size]
            try:
                await delete_from_storage_channel(batch)
            except Exception:
                pass
    
    return {"message": f"Deleted {len(files)} files"}


@router.post("/{file_id}/progress")
@router.put("/{file_id}/progress")
async def update_progress(
    file_id: int,
    progress: WatchProgressUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update watch progress. Supports both POST and PUT."""
    # Check file exists
    result = await db.execute(select(File).where(File.id == file_id, File.user_id == current_user.id))
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
        
    # ponytail: upsert -- SELECT first, INSERT on miss, catch race-condition IntegrityError on commit
    duration_val = int(progress.duration) if progress.duration else None
    is_completed = progress.completed if progress.completed is not None else (
        progress.position >= duration_val if duration_val else False
    )
    result = await db.execute(
        select(WatchProgress).where(WatchProgress.file_id == file_id, WatchProgress.user_id == current_user.id)
    )
    watch_progress = result.scalar_one_or_none()
    if watch_progress:
        watch_progress.position = progress.position
        if progress.duration:
            watch_progress.duration = int(progress.duration)
        if progress.completed is not None:
            watch_progress.completed = progress.completed
        elif ((progress.duration and progress.position >= int(progress.duration))
              or (watch_progress.duration and progress.position >= watch_progress.duration)):
            watch_progress.completed = True
        else:
            watch_progress.completed = False
        await db.commit()
    else:
        watch_progress = WatchProgress(
            user_id=current_user.id,
            file_id=file_id,
            position=progress.position,
            duration=duration_val,
            completed=is_completed,
        )
        db.add(watch_progress)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            result = await db.execute(
                select(WatchProgress).where(WatchProgress.file_id == file_id, WatchProgress.user_id == current_user.id)
            )
            watch_progress = result.scalar_one_or_none()
            if watch_progress:
                watch_progress.position = progress.position
                if progress.duration:
                    watch_progress.duration = int(progress.duration)
                if progress.completed is not None:
                    watch_progress.completed = progress.completed
                elif ((progress.duration and progress.position >= int(progress.duration))
                      or (watch_progress.duration and progress.position >= watch_progress.duration)):
                    watch_progress.completed = True
                else:
                    watch_progress.completed = False
                await db.commit()
            else:
                # The IntegrityError was NOT the (user, file) unique race —
                # e.g. the file row was deleted between the ownership check
                # and this commit (FK violation). refresh(None) would 500.
                raise HTTPException(status_code=404, detail="File not found")
    await db.refresh(watch_progress)
    return watch_progress


@router.get("/{file_id}/progress", response_model=WatchProgressResponse | None)
async def get_progress(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get watch progress for a file."""
    result = await db.execute(
        select(WatchProgress).where(
            WatchProgress.file_id == file_id,
            WatchProgress.user_id == current_user.id
        )
    )
    progress = result.scalar_one_or_none()
    return progress


@router.post("/{file_id}/share", response_model=FileResponse)
async def share_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a permanent public link for the file."""
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id).options(selectinload(File.watch_progress))
    )
    file = result.scalar_one_or_none()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Generate hash only if one doesn't already exist
    if not file.public_hash:
        file.public_hash = secrets.token_hex(16)
    
    await db.commit()
    
    # Re-fetch with relationships
    result = await db.execute(
        select(File).where(File.id == file_id).options(selectinload(File.watch_progress))
    )
    file = result.scalar_one()
    
    return FileResponse(**add_urls_to_file(file))


@router.delete("/{file_id}/share", response_model=FileResponse)
async def revoke_share(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke the public link for the file."""
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id).options(selectinload(File.watch_progress))
    )
    file = result.scalar_one_or_none()
    
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    file.public_hash = None
    
    await db.commit()
    
    # Re-fetch with relationships
    result = await db.execute(
        select(File).where(File.id == file_id).options(selectinload(File.watch_progress))
    )
    file = result.scalar_one()
    
    return FileResponse(**add_urls_to_file(file))


@router.post("/batch-move")
async def batch_move_files(
    move_data: BatchMoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move multiple files to a folder."""
    file_ids = move_data.ids
    folder_id = move_data.folder_id
    
    if folder_id == 0:
        folder_id = None
        
    # Verify target folder belongs to user
    if folder_id is not None:
        folder_check = await db.execute(
            select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
        )
        if not folder_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Target folder not found")
            
    # Update files
    result = await db.execute(
        update(File)
        .where(File.id.in_(file_ids), File.user_id == current_user.id)
        .values(folder_id=folder_id, updated_at=datetime.now(timezone.utc).replace(tzinfo=None))
    )
    
    await db.commit()
    return {"message": f"Moved {result.rowcount} files"}
