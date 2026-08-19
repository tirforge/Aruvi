"""
Pydantic schemas for API request/response validation.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator #WP


# ============== User Schemas ==============

class UserBase(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserResponse(UserBase):
    id: int
    created_at: datetime
    last_active: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AdminUserResponse(UserResponse):
    file_count: int = 0
    folder_count: int = 0
    storage_bytes: int = 0


class AdminStats(BaseModel):
    total_users: int
    total_files: int
    total_folders: int
    total_storage_bytes: int
    active_today: int


# ============== Folder Schemas ==============

class FolderBase(BaseModel):
    name: str
    parent_id: Optional[int] = None


class FolderCreate(FolderBase):
    pass


class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None


class FolderResponse(FolderBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    file_count: int = 0
    
    model_config = ConfigDict(from_attributes=True)


class FolderWithChildren(FolderResponse):
    children: List["FolderWithChildren"] = []
    

# ============== File Schemas ==============

class FileBase(BaseModel):
    file_name: str
    file_size: int
    mime_type: Optional[str] = None
    file_type: str  # video, audio, document, image
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


class FileCreate(FileBase):
    file_id: str
    file_unique_id: str
    channel_message_id: int
    thumbnail_file_id: Optional[str] = None
    folder_id: Optional[int] = None


class FileUpdate(BaseModel):
    file_name: Optional[str] = None
    folder_id: Optional[int] = None


class FileResponse(FileBase):
    id: int
    user_id: int
    folder_id: Optional[int] = None
    file_id: str
    file_unique_id: str
    created_at: datetime
    updated_at: datetime
    thumbnail_url: Optional[str] = None
    stream_url: Optional[str] = None
    download_url: Optional[str] = None
    public_hash: Optional[str] = None
    public_stream_url: Optional[str] = None
    last_pos: int = 0
    
    model_config = ConfigDict(from_attributes=True)


class FileListResponse(BaseModel):
    files: List[FileResponse]
    total: int
    page: int
    per_page: int


# ============== Watch Progress Schemas ==============

class WatchProgressBase(BaseModel):
    position: int
    duration: Optional[int] = None
    completed: bool = False


class WatchProgressUpdate(BaseModel): #QB
    position: int #PT
    duration: Optional[int] = None #XB
    completed: Optional[bool] = None #QZ

    model_config = ConfigDict(extra="ignore")  # Android client sends extra fields

    @field_validator('position', 'duration', mode='before')
    @classmethod
    def _int_from_float(cls, v):
        return int(v) if isinstance(v, float) else v


class WatchProgressResponse(WatchProgressBase):
    id: int
    user_id: int
    file_id: int
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============== Auth Schemas ==============

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """Request body for token refresh."""
    refresh_token: str = Field(..., alias="refreshToken")
    
    model_config = ConfigDict(populate_by_name=True)


class TokenPayload(BaseModel):
    sub: int  # user telegram_id
    exp: datetime


class LoginCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$")


class LoginCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class VerifyCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$")


class AuthResponse(Token):
    user: UserResponse


class BotInfoResponse(BaseModel):
    username: str
    name: Optional[str] = None
    server_version: str = "1.0.0"


class BatchMoveRequest(BaseModel):
    ids: list[int]
    folder_id: Optional[int] = None


# Resolve forward references
FolderWithChildren.model_rebuild()
