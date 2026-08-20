"""
Database models for TelePlay streaming app.
"""
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import BigInteger, String, Integer, Boolean, ForeignKey, DateTime, Text, Index, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Telegram user who uses the bot."""
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(255))
    last_name: Mapped[Optional[str]] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gdrive_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_sessions: Mapped[List["RefreshSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_active: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    
    # Relationships
    folders: Mapped[List["Folder"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    files: Mapped[List["File"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    watch_progress: Mapped[List["WatchProgress"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Folder(Base):
    """User-created folder for organizing files."""
    __tablename__ = "folders"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="folders")
    parent: Mapped[Optional["Folder"]] = relationship(back_populates="children", remote_side=[id])
    children: Mapped[List["Folder"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    files: Mapped[List["File"]] = relationship(back_populates="folder")
    
    # Indexes
    __table_args__ = (
        Index("idx_folder_user_parent", user_id, parent_id),
    )


class File(Base):
    """File stored in Telegram, metadata in database."""
    __tablename__ = "files"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[Optional[int]] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    
    # Telegram-specific identifiers
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_unique_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    channel_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    
    # File metadata
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)  # video, audio, document, image
    
    # Media-specific metadata
    duration: Mapped[Optional[int]] = mapped_column(Integer)  # seconds
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    thumbnail_file_id: Mapped[Optional[str]] = mapped_column(String(255))
    thumbnail_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    
    # Sharing
    public_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="files")
    folder: Mapped[Optional["Folder"]] = relationship(back_populates="files")
    watch_progress: Mapped[List["WatchProgress"]] = relationship(back_populates="file", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index("idx_file_user_folder", user_id, folder_id),
        Index("idx_file_type", file_type),
        Index("idx_file_user_created_at", user_id, created_at),
        Index("idx_file_user_updated_at", user_id, updated_at),
    )


class WatchProgress(Base):
    """Track video watch progress for continue watching feature."""
    __tablename__ = "watch_progress"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)  # seconds
    duration: Mapped[Optional[int]] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="watch_progress")
    file: Mapped["File"] = relationship(back_populates="watch_progress")
    
    # Constraints and indexes
    __table_args__ = (
        Index("idx_watch_user_file", user_id, file_id, unique=True),
        Index("idx_watch_updated", updated_at),
    )


class LoginCode(Base):
    """Temporary login code for TV/Web auth."""
    __tablename__ = "login_codes"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(6), unique=True, index=True, nullable=False)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RefreshSession(Base):
    """A single issued refresh token (device session). Rotation deletes the old
    row and inserts the new one, so a rotated/replayed token stops working."""
    __tablename__ = "refresh_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="refresh_sessions")
