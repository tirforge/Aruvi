"""
Folder management API endpoints.
"""
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import defer

from ..database import get_db
from ..models import Folder, File, User
from ..schemas import FolderResponse, FolderCreate, FolderUpdate, FolderWithChildren, BatchMoveRequest
from ..auth import get_current_user
from ..telegram import delete_from_storage_channel, invalidate_message_cache_batch


router = APIRouter(prefix="/folders", tags=["Folders"])


async def get_folder_file_count(db: AsyncSession, folder_id: int) -> int:
    """Get the total number of files in a folder and all its subfolders."""
    # This is a recursive CTE approach for efficiency
    from sqlalchemy import text
    query = text("""
        WITH RECURSIVE subfolders AS (
            SELECT id FROM folders WHERE id = :root_id
            UNION ALL
            SELECT f.id FROM folders f
            INNER JOIN subfolders sf ON f.parent_id = sf.id
        )
        SELECT COUNT(*) FROM files
        WHERE folder_id IN (SELECT id FROM subfolders)
    """)
    result = await db.execute(query, {"root_id": folder_id})
    return result.scalar() or 0


@router.get("", response_model=List[FolderResponse])
async def list_folders(
    parent_id: Optional[int] = Query(None, description="Filter by parent folder ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List user's folders optimally."""
    # Select folder and count of files in one query
    stmt = (
        select(Folder, func.count(File.id).label("file_count"))
        .outerjoin(File, File.folder_id == Folder.id)
        .where(Folder.user_id == current_user.id)
        .group_by(Folder.id)
        .order_by(Folder.name)
    )
    
    if parent_id is not None:
        stmt = stmt.where(Folder.parent_id == parent_id)
    else:
        stmt = stmt.where(Folder.parent_id.is_(None))
    
    result = await db.execute(stmt)
    rows = result.all()
    
    return [
        FolderResponse(
            id=folder.id,
            name=folder.name,
            parent_id=folder.parent_id,
            user_id=folder.user_id,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
            file_count=file_count
        )
        for folder, file_count in rows
    ]


@router.get("/tree", response_model=List[FolderWithChildren])
async def get_folder_tree(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the complete folder tree for the user optimally."""
    # Get all folders with counts in one query
    stmt = (
        select(Folder, func.count(File.id).label("file_count"))
        .outerjoin(File, File.folder_id == Folder.id)
        .where(Folder.user_id == current_user.id)
        .group_by(Folder.id)
        .order_by(Folder.name)
    )
    
    result = await db.execute(stmt)
    rows = result.all()
    
    # Build tree
    folder_map = {}
    for folder, file_count in rows:
        folder_map[folder.id] = {
            "id": folder.id,
            "name": folder.name,
            "parent_id": folder.parent_id,
            "user_id": folder.user_id,
            "created_at": folder.created_at,
            "updated_at": folder.updated_at,
            "file_count": file_count,
            "children": [],
        }
    
    # Link parents and children
    roots = []
    for folder_data in folder_map.values():
        parent_id = folder_data["parent_id"]
        if parent_id and parent_id in folder_map:
            folder_map[parent_id]["children"].append(folder_data)
        else:
            roots.append(folder_data)
    
    return roots


@router.get("/{folder_id}", response_model=FolderResponse)
async def get_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific folder by ID with file count."""
    stmt = (
        select(Folder, func.count(File.id).label("file_count"))
        .outerjoin(File, File.folder_id == Folder.id)
        .where(Folder.id == folder_id, Folder.user_id == current_user.id)
        .group_by(Folder.id)
    )
    
    result = await db.execute(stmt)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    folder, file_count = row
    
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        user_id=folder.user_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        file_count=file_count,
    )


@router.post("", response_model=FolderResponse, status_code=201)
async def create_folder(
    folder_data: FolderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new folder."""
    # Validate parent exists if specified
    if folder_data.parent_id:
        parent_result = await db.execute(
            select(Folder).where(
                Folder.id == folder_data.parent_id,
                Folder.user_id == current_user.id
            )
        )
        if not parent_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Parent folder not found")
    
    # Check for duplicate name in same parent
    existing = await db.execute(
        select(Folder).where(
            Folder.user_id == current_user.id,
            Folder.parent_id == folder_data.parent_id,
            Folder.name == folder_data.name
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Folder with this name already exists")
    
    folder = Folder(
        user_id=current_user.id,
        name=folder_data.name,
        parent_id=folder_data.parent_id,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        user_id=folder.user_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        file_count=0,
    )


@router.patch("/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: int,
    update_data: FolderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a folder (rename, move)."""
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()
    
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    # Update fields
    if update_data.name is not None:
        folder.name = update_data.name
    if update_data.parent_id is not None:
        # Prevent moving folder into itself
        if update_data.parent_id == folder_id:
            raise HTTPException(status_code=400, detail="Cannot move folder into itself")

        target_id = update_data.parent_id if update_data.parent_id != 0 else None

        # Prevent circular hierarchy: check target isn't a descendant of this folder
        if target_id is not None:
            from sqlalchemy.orm import aliased
            descendants_cte = (
                select(Folder.id)
                .where(Folder.id == folder_id)
                .cte(name="descendants", recursive=True)
            )
            d_alias = aliased(Folder)
            descendants_cte = descendants_cte.union_all(
                select(d_alias.id).where(d_alias.parent_id == descendants_cte.c.id)
            )
            desc_result = await db.execute(select(descendants_cte.c.id))
            descendant_ids = set(desc_result.scalars().all())
            if target_id in descendant_ids:
                raise HTTPException(status_code=400, detail="Cannot move a folder into its own subfolder")

        # Verify target parent folder belongs to current user (security check)
        if target_id is not None:
            parent_check = await db.execute(
                select(Folder).where(
                    Folder.id == target_id,
                    Folder.user_id == current_user.id
                )
            )
            if not parent_check.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Parent folder not found")

        folder.parent_id = target_id
    
    await db.commit()
    await db.refresh(folder)
    
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        user_id=folder.user_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        file_count=0,
    )


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: int,
    move_files_to: Optional[int] = Query(None, description="Move files to this folder ID (null = root)"),
    delete_files: bool = Query(False, description="Delete files inside the folder instead of moving them"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a folder. By default the folder's files are moved to root
    (or to move_files_to). Pass delete_files=true to also delete the files
    and their Telegram channel copies."""
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()
    
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    # Get all descendant folder IDs (including this folder)
    from sqlalchemy.orm import aliased
    subfolders_cte = (
        select(Folder.id)
        .where(Folder.id == folder_id)
        .cte(name="subfolders", recursive=True)
    )
    f_alias = aliased(Folder)
    subfolders_cte = subfolders_cte.union_all(
        select(f_alias.id).where(f_alias.parent_id == subfolders_cte.c.id)
    )
    all_ids_result = await db.execute(select(subfolders_cte.c.id))
    all_folder_ids = list(all_ids_result.scalars().all())

    storage_message_ids: list[int] = []
    if not delete_files:
        # Move files out of the deleted subtree (default: root)
        target_folder_id = None
        if move_files_to is not None and move_files_to != 0:
            target = await db.execute(
                select(Folder).where(Folder.id == move_files_to, Folder.user_id == current_user.id)
            )
            if not target.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Target folder not found")
            if move_files_to in all_folder_ids:
                raise HTTPException(status_code=400, detail="Cannot move files into a folder being deleted")
            target_folder_id = move_files_to

        if all_folder_ids:
            from sqlalchemy import update
            await db.execute(
                update(File)
                .where(File.folder_id.in_(all_folder_ids))
                .values(folder_id=target_folder_id)
            )
    else:
        if all_folder_ids:
            file_query = (
                select(File)
                .where(File.folder_id.in_(all_folder_ids))
                .options(defer(File.thumbnail_data))
            )
            file_result = await db.execute(file_query)
            files_to_delete = file_result.scalars().all()

            storage_message_ids = [f.channel_message_id for f in files_to_delete if f.channel_message_id]
            if storage_message_ids:
                invalidate_message_cache_batch(storage_message_ids)

            await db.execute(delete(File).where(File.folder_id.in_(all_folder_ids)))
    
    # Delete all descendant folder rows explicitly — ORM cascade only fires
    # for loaded children, and SQLite FK cascade needs PRAGMA foreign_keys=ON
    if all_folder_ids:
        await db.execute(delete(Folder).where(Folder.id.in_(all_folder_ids)))
    await db.commit()

    # Best-effort cleanup from the Telegram storage channel — run AFTER the
    # commit so a slow batch of network deletes never holds the DB transaction
    # (and a checked-out pool connection) open.
    if storage_message_ids:
        chunk_size = 100
        for i in range(0, len(storage_message_ids), chunk_size):
            batch = storage_message_ids[i:i + chunk_size]
            try:
                await delete_from_storage_channel(batch)
            except Exception:
                pass
    
    return {"message": "Folder deleted successfully"}


@router.post("/batch-delete")
async def batch_delete_folders(
    folder_ids: List[int],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete multiple folders."""
    # Fetch all folders
    result = await db.execute(
        select(Folder).where(Folder.id.in_(folder_ids), Folder.user_id == current_user.id)
    )
    folders = result.scalars().all()
    
    if not folders:
        return {"message": "No folders found to delete"}
    
    # Recursive delete of files in all these folders — single CTE
    from sqlalchemy import delete as sqlalchemy_delete
    from sqlalchemy.orm import aliased

    folder_id_list = [f.id for f in folders]
    message_ids: list[int] = []
    subfolders_cte = (
        select(Folder.id)
        .where(Folder.id.in_(folder_id_list))
        .cte(name="subfolders", recursive=True)
    )
    f_alias = aliased(Folder)
    subfolders_cte = subfolders_cte.union_all(
        select(f_alias.id).where(f_alias.parent_id == subfolders_cte.c.id)
    )
    folder_result = await db.execute(select(subfolders_cte.c.id))
    all_affected_folder_ids = folder_result.scalars().all()
    
    if all_affected_folder_ids:
        # Get files to delete from Telegram
        file_query = (
            select(File)
            .where(File.folder_id.in_(all_affected_folder_ids))
            .options(defer(File.thumbnail_data))
        )
        file_result = await db.execute(file_query)
        files_to_delete = file_result.scalars().all()

        # Collect message IDs and drop cached references now (deleted columns)
        message_ids = [f.channel_message_id for f in files_to_delete if f.channel_message_id]
        if message_ids:
            invalidate_message_cache_batch(message_ids)

        # Delete files from DB
        await db.execute(sqlalchemy_delete(File).where(File.folder_id.in_(all_affected_folder_ids)))
    
    # Delete all affected folder rows explicitly (ORM cascade only fires for loaded children)
    if all_affected_folder_ids:
        await db.execute(sqlalchemy_delete(Folder).where(Folder.id.in_(all_affected_folder_ids)))
        
    await db.commit()

    # Best-effort cleanup from Telegram storage channel — AFTER the commit so
    # the DB transaction is never held across slow network deletes.
    if message_ids:
        chunk_size = 100
        for i in range(0, len(message_ids), chunk_size):
            batch = message_ids[i:i + chunk_size]
            try:
                await delete_from_storage_channel(batch)
            except Exception:
                pass
    
    return {"message": f"Deleted {len(folders)} folders and their content"}


@router.post("/batch-move")
async def batch_move_folders(
    move_data: BatchMoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move multiple folders to another folder."""
    folder_ids = move_data.ids
    target_id = move_data.folder_id
    
    if target_id == 0:
        target_id = None
        
    # Prevent moving folder into itself
    if target_id in folder_ids:
        raise HTTPException(status_code=400, detail="Cannot move a folder into itself")
    
    # Prevent circular hierarchy: check if target is a descendant of any moved folder
    if target_id is not None:
        from sqlalchemy.orm import aliased
        descendants_cte = (
            select(Folder.id)
            .where(Folder.id.in_(folder_ids))
            .cte(name="descendants", recursive=True)
        )
        d_alias = aliased(Folder)
        descendants_cte = descendants_cte.union_all(
            select(d_alias.id).where(d_alias.parent_id == descendants_cte.c.id)
        )
        desc_result = await db.execute(select(descendants_cte.c.id))
        descendant_ids = set(desc_result.scalars().all())
        if target_id in descendant_ids:
            raise HTTPException(status_code=400, detail="Cannot move a folder into its own subfolder")
        
    # Verify target parent folder belongs to user
    if target_id is not None:
        parent_check = await db.execute(
            select(Folder).where(Folder.id == target_id, Folder.user_id == current_user.id)
        )
        if not parent_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Target parent folder not found")
            
    # Update folders
    from sqlalchemy import update
    result = await db.execute(
        update(Folder)
        .where(Folder.id.in_(folder_ids), Folder.user_id == current_user.id)
        .values(parent_id=target_id, updated_at=datetime.now(timezone.utc).replace(tzinfo=None))
    )

    await db.commit()
    return {"message": f"Moved {result.rowcount} folders"}
