"""
Shared business logic and database queries.
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from .models import File, WatchProgress, Folder
from sqlalchemy.orm import selectinload, defer
from .media_types import classify_file_type

def escape_like(value: str) -> str:
    """Escape special LIKE/ILIKE characters to prevent SQL injection."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def add_urls_to_file(file: File) -> dict:
    """Add stream and thumbnail URLs to file response."""
    # Recompute the effective type from mime/extension so pre-migration rows
    # (e.g. .mkv stored as "document") render correctly even before the
    # startup DB reclassification catches up.
    effective_type = classify_file_type(file.file_name, file.mime_type)
    data = {
        "id": file.id,
        "user_id": file.user_id,
        "folder_id": file.folder_id,
        "file_id": file.file_id,
        "file_unique_id": file.file_unique_id,
        "file_name": file.file_name,
        "file_size": file.file_size,
        "mime_type": file.mime_type,
        "file_type": effective_type,
        "duration": file.duration,
        "width": file.width,
        "height": file.height,
        "created_at": file.created_at,
        "updated_at": file.updated_at,
        "stream_url": f"/api/stream/{file.id}",
        "thumbnail_url": f"/api/stream/{file.id}/thumbnail" if file.thumbnail_file_id else None,
        "last_pos": file.watch_progress[0].position if file.watch_progress else 0,
    }
    
    if file.public_hash:
        data["public_hash"] = file.public_hash
        data["public_stream_url"] = f"/api/stream/s/{file.public_hash}"
        
    return data

async def fetch_recent_files(db: AsyncSession, user_id: int, limit: int) -> List[File]:
    """Get recently added files across all folders."""
    query = (
        select(File)
        .where(File.user_id == user_id)
        .options(selectinload(File.watch_progress), defer(File.thumbnail_data))
        .order_by(desc(File.created_at))
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()

async def fetch_continue_watching_files(db: AsyncSession, user_id: int, limit: int) -> List[File]:
    """Get files with watch progress (not completed)."""
    query = (
        select(File)
        .join(WatchProgress, File.id == WatchProgress.file_id)
        .where(
            File.user_id == user_id,
            WatchProgress.user_id == user_id,
            WatchProgress.position > 0,
            WatchProgress.completed == False
        )
        .options(selectinload(File.watch_progress), defer(File.thumbnail_data))
        .order_by(desc(WatchProgress.updated_at))
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().unique().all()
