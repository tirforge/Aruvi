"""
Telegram Bot handlers using PyroTGFork MTProto.
Handles commands, file uploads, and inline callbacks.
"""

import asyncio
import functools
import json
import secrets
import string
import traceback
from datetime import datetime, timedelta, timezone
from pyrogram import filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError

from .patch import ListenerCanceled
from .telegram import tg_client, forward_to_storage_channel, invalidate_message_cache, delete_from_storage_channel
from .database import async_session
from .models import User, File, Folder, LoginCode
from .config import get_settings
from .auth import create_access_token, create_download_token
from .media_types import classify_file_type
from . import gdrive as gdrive_mod

settings = get_settings()

_log = __import__('logging').getLogger(__name__)


def _log_exceptions(coro):
    """Wrap a coroutine handler with exception logging to stderr."""
    @functools.wraps(coro)
    async def wrapper(*args, **kwargs):
        try:
            return await coro(*args, **kwargs)
        except Exception:
            _log.exception("Unhandled exception in %s", coro.__name__)
            traceback.print_exc()
    return wrapper


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(seconds: int) -> str:
    """Format seconds to human readable duration."""
    if not seconds:
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {secs}s"


from .utils import sanitize_filename, md_safe  # noqa: re-export for backward compat



async def get_or_create_user(telegram_id: int, username: str = None, 
                             first_name: str = None, last_name: str = None) -> User:
    """Get or create a user in the database. Auto-admins: first user ever,
    users in ADMIN_IDS env var, and users in AUTH_USERS env var."""
    async with async_session() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

        is_admin = telegram_id in settings.admin_ids or telegram_id in settings.auth_users

        if not user:
            try:
                count = await db.execute(select(func.count()).select_from(User))
                if count.scalar() == 0:
                    is_admin = True
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_admin=is_admin,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
            except IntegrityError:
                # Concurrent first message — another request just created this
                # user (unique telegram_id). Roll back and re-select.
                await db.rollback()
                result = await db.execute(select(User).where(User.telegram_id == telegram_id))
                user = result.scalar_one_or_none()
                if user is not None and is_admin and not user.is_admin:
                    user.is_admin = True
                    await db.commit()
                    await db.refresh(user)
        elif is_admin and not user.is_admin:
            user.is_admin = True
            await db.commit()
            await db.refresh(user)

        return user


async def _resolve_user_id(db, telegram_id: int):
    """Resolve the internal DB user id for a Telegram id, or None."""
    result = await db.execute(select(User.id).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_web_app_button(telegram_id: int, text: str = "🌐 Open Web") -> InlineKeyboardButton:
    """Create a URL button with authenticated link. Uses a regular URL button
    instead of WebApp because the domain is not registered with BotFather.

    Embeds the user's current ``auth_version`` so links keep working after
    /logout_all bumps it (a stale ver=0 token would be rejected forever)."""
    from urllib.parse import quote
    async with async_session() as db:
        result = await db.execute(
            select(User.auth_version).where(User.telegram_id == telegram_id)
        )
        version = result.scalar_one_or_none() or 0
    token = create_access_token(telegram_id, version=version)
    encoded_token = quote(token, safe='')
    web_url = f"{settings.web_base_url}/auth?token={encoded_token}"
    return InlineKeyboardButton(text, url=web_url)

# ============== Authorization Middleware ==============

@tg_client.on_message(filters.private, group=-2)
@_log_exceptions
async def check_auth(client, message: Message):
    """All users can use the bot."""
    pass

# ============== Command Handlers ==============

@tg_client.on_message(filters.command("start") & filters.private)
@_log_exceptions
async def start_command(client, message: Message):
    _log.info("start_command called by user %s", message.from_user.id)
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
    )
    
    # Check for deep-linked login codes (e.g. /start ABCDEF)
    if len(message.command) > 1:
        code_input = message.command[1].strip().upper()
        async with async_session() as db:
            # Atomic claim: UPDATE WHERE telegram_id IS NULL prevents race condition
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            result = await db.execute(
                update(LoginCode)
                .where(LoginCode.code == code_input)
                .where(LoginCode.expires_at > now)
                .where(LoginCode.telegram_id.is_(None))
                .values(telegram_id=message.from_user.id)
            )
            if result.rowcount == 1:
                await db.commit()
                await message.reply(
                    "✅ **Success!**\n"
                    "You have successfully logged in on your device.\n"
                    "You can now enjoy watching! 🍿"
                )
                return
            # Claim failed — check why
            result2 = await db.execute(select(LoginCode).where(LoginCode.code == code_input))
            login_code = result2.scalar_one_or_none()
            if login_code and login_code.telegram_id:
                await message.reply("⚠️ This code has already been used.")
            elif login_code:
                await message.reply("❌ This code has expired.")
            else:
                await message.reply("❌ Invalid login code. Use /login on your TV app to generate a fresh one.")

    from pyrogram.errors import ButtonUrlInvalid, MessageNotModified
    try:
        await message.reply(
            "📺 **Welcome to Aruvi!**\n\n"
            "Your personal media streaming platform.\n"
            "Upload files here, stream anywhere!\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 **QUICK START**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣ Send any media file to upload\n"
            "2️⃣ Use /web to open web player\n"
            "3️⃣ Use /login on your TV app\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📝 **COMMANDS**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "/myfiles - Your files with IDs\n"
            "/file `<id>` - Manage a file\n"
            "/folders - Browse folders\n"
            "/newfolder `<name>` - New folder\n"
            "/help - Full help guide\n\n"
            
            "💡 After uploading, you'll get the **File ID**\n"
            "Use `/file <id>` to rename, move, or delete.",
            reply_markup=InlineKeyboardMarkup([
                [await get_web_app_button(message.from_user.id, "🌐 Open Web Interface")],
                [
                    InlineKeyboardButton("📁 My Files", callback_data="show_files"),
                    InlineKeyboardButton("📂 My Folders", callback_data="back_folders")
                ]
            ])
        )
    except (ButtonUrlInvalid, MessageNotModified):
        await message.reply(
            "📺 **Welcome to Aruvi!**\n\n"
            "Your personal media streaming platform.\n"
            "Upload files here, stream anywhere!\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 **QUICK START**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣ Send any media file to upload\n"
            "2️⃣ Use /web to open web player\n"
            "3️⃣ Use /login on your TV app\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📝 **COMMANDS**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "/myfiles - Your files with IDs\n"
            "/file `<id>` - Manage a file\n"
            "/folders - Browse folders\n"
            "/newfolder `<name>` - New folder\n"
            "/help - Full help guide\n\n"
            "💡 After uploading, you'll get the **File ID**\n"
            "Use `/file <id>` to rename, move, or delete."
        )


@tg_client.on_message(filters.command("help") & filters.private)
async def help_command(client, message: Message):
    """Show help message."""
    await message.reply(
        "📖 **Aruvi Help**\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📤 **UPLOADING FILES**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Simply send any video, audio, image or document to me.\n"
        "I'll save it to your library for streaming.\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📋 **COMMANDS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "**General:**\n"
        "• /start - Welcome message\n"
        "• /help - This help message\n"
        "• /web - Get authenticated web link\n"
        "• /login - Get/verify login code for TV\n"
        "• /logout_all - Invalidate all active sessions\n\n"
        
        "**File Management:**\n"
        "• /myfiles - List your recent files with IDs\n"
        "• /file `<id>` - Manage a specific file\n"
        "  ↳ Rename, Move, Download, Delete, Share\n\n"
        
        "**Folder Management:**\n"
        "• /folders - Browse all folders\n"
        "• /newfolder `<name>` - Create a folder\n"
        "• /deletefolder `<name>` - Delete a folder\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎛 **INTERACTIVE ACTIONS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "When you tap buttons, I'll ask for input:\n"
        "• **Rename** - Send new name (60s timeout)\n"
        "• **Create Folder** - Send folder name\n"
        "• **Delete** - Tap confirm or cancel\n"
        "• **Move** - Select destination folder\n\n"
        "💡 Send /cancel to abort any action\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📁 **SUPPORTED FILES**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• 🎬 Videos: MP4, MKV, AVI, MOV, WEBM\n"
        "• 🎵 Audio: MP3, FLAC, AAC, OGG, WAV\n"
        "• 🖼 Images: JPG, PNG, GIF, WEBP\n"
        "• 📄 Documents: PDF, TXT, DOCX, etc.\n"
        "• ⚠️ Max size: 2GB per file\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📺 **TV & WEB STREAMING**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• Use /web to get a secure link\n"
        "• Use /login on TV app to connect\n"
        "• Watch progress syncs across devices\n"
    )


@tg_client.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client, message: Message):
    """Cancel the current interactive action (rename, create folder, etc.)."""
    client.cancel_listener(str(message.chat.id))
    await message.reply("❌ Cancelled.")


@tg_client.on_message(filters.command("myfiles") & filters.private)
async def myfiles_command(client, message: Message):
    """List user's recent files."""
    async with async_session() as db:
        result = await db.execute(
            select(File)
            .where(File.user_id == (
                select(User.id).where(User.telegram_id == message.from_user.id).scalar_subquery()
            ))
            .order_by(File.created_at.desc())
            .limit(10)
        )
        files = result.scalars().all()
    
    if not files:
        await message.reply(
            "📭 You haven't uploaded any files yet.\n\n"
            "Send me a video, audio, or document to get started!"
        )
        return
    
    text = "📁 **Your Recent Files:**\n\n"
    
    for f in files:
        emoji = {"video": "🎬", "audio": "🎵", "document": "📄", "image": "🖼"}.get(f.file_type, "📎")
        text += f"{emoji} `{f.id}` | {md_safe(f.file_name)}\n   └ {format_size(f.file_size)}"
        if f.duration:
            text += f" • {format_duration(f.duration)}"
        text += "\n\n"
    
    text += "💡 Use /file <id> to manage a file"
    
    from pyrogram.errors import ButtonUrlInvalid, MessageNotModified
    try:
        await message.reply(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📁 My Folders", callback_data="back_folders")],
                [await get_web_app_button(message.from_user.id, "🌐 Open Web")]
            ])
        )
    except (ButtonUrlInvalid, MessageNotModified):
        await message.reply(text)


@tg_client.on_message(filters.command("folders") & filters.private)
async def folders_command(client, message: Message):
    """Show folder structure."""
    async with async_session() as db:
        # Get user
        user_result = await db.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.reply("Please use /start first.")
            return
        
        # Get root folders
        result = await db.execute(
            select(Folder)
            .where(Folder.user_id == user.id, Folder.parent_id.is_(None))
            .order_by(Folder.name)
        )
        folders = result.scalars().all()
    
    if not folders:
        await message.reply(
            "📁 You don't have any folders yet.\n\n"
            "Create one with /newfolder <name>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Create Folder", callback_data="create_folder")]
            ])
        )
        return
    
    buttons = []
    for f in folders:
        buttons.append([
            InlineKeyboardButton(f"📂 {f.name[:60]}", callback_data=f"folder:{f.id}")
        ])
    buttons.append([InlineKeyboardButton("➕ Create Folder", callback_data="create_folder")])
    
    await message.reply(
        "📁 **Your Folders:**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@tg_client.on_message(filters.command("newfolder") & filters.private)
async def newfolder_command(client, message: Message):
    """Create a new folder."""
    if len(message.command) < 2:
        await message.reply("Usage: /newfolder <folder_name>")
        return
    
    folder_name = " ".join(message.command[1:]).strip()[:255]
    
    async with async_session() as db:
        # Get user
        user_result = await db.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.reply("Please use /start first.")
            return
        
        # Check if folder exists
        existing = await db.execute(
            select(Folder).where(
                Folder.user_id == user.id,
                Folder.name == folder_name,
                Folder.parent_id.is_(None)
            )
        )
        if existing.scalar_one_or_none():
            await message.reply(f"❌ Folder **{folder_name}** already exists.")
            return
        
        # Create folder
        folder = Folder(user_id=user.id, name=folder_name)
        db.add(folder)
        await db.commit()
    
    await message.reply(f"✅ Folder **{folder_name}** created!")


@tg_client.on_message(filters.command("web") & filters.private)
async def web_command(client, message: Message):
    """Get authenticated web interface link."""
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
    )
    
    token = create_access_token(message.from_user.id, version=user.auth_version)
    web_url = f"{settings.web_base_url}/auth?token={token}"

    await message.reply(
        "🌐 **Web Interface**\n\n"
        "Click the link below to access your files:\n"
        f"👉 {web_url}\n\n"
        "__(Link expires in 7 days)__"
    )


@tg_client.on_message(filters.command("drive") & filters.private)
@_log_exceptions
async def drive_command(client, message: Message):
    """Connect or check Google Drive status."""
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
    )

    if user.gdrive_token:
        await message.reply(
            "☁️ **Google Drive Connected**\n\n"
            "Your Google Drive is already linked.\n"
            "Use the ☁️ **Save to Drive** button on any file to upload it.",
        )
        return

    auth_url = gdrive_mod.generate_auth_url(user.telegram_id)
    await message.reply(
        "☁️ **Google Drive Setup**\n\n"
        "Connect your Google account to save files directly to your Drive.\n\n"
        f"[Click here to connect]({auth_url})\n\n"
        "After authorizing, come back and use the ☁️ **Save to Drive** button.",
        disable_web_page_preview=True,
    )


@tg_client.on_message(filters.command("login") & filters.private)
@_log_exceptions
async def login_command(client, message: Message):
    _log.info("login_command called by user %s", message.from_user.id)
    """
    Handle login command.
    Usage:
    /login <CODE> - Link TV/Web session
    /login - Generate code to enter on device
    """
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
    )

    # Check if code is provided (TV/Web -> User flow)
    if len(message.command) > 1:
        code_input = message.command[1].strip().upper()
        
        async with async_session() as db:
            # Atomic claim: UPDATE WHERE telegram_id IS NULL prevents two
            # users claiming the same code at once.
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            result = await db.execute(
                update(LoginCode)
                .where(LoginCode.code == code_input)
                .where(LoginCode.expires_at > now)
                .where(LoginCode.telegram_id.is_(None))
                .values(telegram_id=message.from_user.id)
            )
            if result.rowcount == 1:
                await db.commit()
                await message.reply(
                    "✅ **Success!**\n"
                    "You have successfully logged in on your TV.\n"
                    "You can now put your phone away and enjoy watching! 🍿"
                )
                return
            # Claim failed — check why
            result2 = await db.execute(select(LoginCode).where(LoginCode.code == code_input))
            login_code = result2.scalar_one_or_none()
            if not login_code:
                await message.reply("❌ **Invalid code.**\nPlease check the code displayed on your TV.")
            elif login_code.expires_at < now:
                await message.reply("❌ **Code expired.**\nPlease generate a new one on your TV.")
            else:
                await message.reply("❌ **Code already used.**")
        return

    # Use secrets for cryptographically strong random number generation.
    # LoginCode.code is UNIQUE and shared with codes minted by the TV/device
    # flow, so the rare collision must be retried instead of 500-ing to the
    # user.
    alphabet = string.ascii_uppercase + string.digits
    login_code = None
    for _ in range(5):
        code = ''.join(secrets.choice(alphabet) for _ in range(6))

        async with async_session() as db:
            login_code = LoginCode(
                code=code,
                telegram_id=message.from_user.id,
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)
            )
            db.add(login_code)
            try:
                await db.commit()
                break
            except IntegrityError:
                await db.rollback()
                login_code = None
                continue

    if login_code is None:
        await message.reply("❌ Failed to generate a login code. Please try again.")
        return

    await message.reply(
        "🔑 **Your Login Code:**\n\n"
        f"`{code}`\n\n"
        "Enter this code on the login screen.\n"
        "__(Expires in 10 minutes)__"
    )

    return

@tg_client.on_message(filters.command("logout_all") & filters.private)
async def logout_all_command(client, message: Message):
    """
    Invalidate all active sessions for the current user.
    """
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
    )
    
    await message.reply(
        "⚠️ **Confirm Global Logout**\n\n"
        "Are you sure you want to log out from **ALL** devices?\n"
        "This will invalidate your session on:\n"
        "• Web App\n"
        "• Android TV\n"
        "• Mobile App",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, Logout", callback_data="logout_all_confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="logout_all_cancel")
            ]
        ])
    )

# ============== File Handler ==============

@tg_client.on_message(filters.private & (filters.video | filters.audio | filters.document | filters.photo))
@_log_exceptions
async def handle_file(client, message: Message):
    _log.info("handle_file from user %s: %s", message.from_user.id, message.document.file_name if message.document else "?")
    """Handle uploaded files - forward to channel and save to DB."""
    # Get or create user
    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
    )
    
    # Determine file type and extract metadata
    if message.video:
        media = message.video
        file_type = "video"
    elif message.audio:
        media = message.audio
        file_type = "audio"
    elif message.document:
        media = message.document
        file_type = classify_file_type(getattr(media, "file_name", None), getattr(media, "mime_type", None))
    elif message.photo:
        media = message.photo  # types.Photo is a single full-size object, not a list
        file_type = "image"
    else:
        return
    
    status_msg = await message.reply("📥 Processing file...")
    
    forwarded = None
    try:
        # Upload dedup: re-sending the same media must not create a second
        # storage-channel copy + library row — reply with the existing one.
        from sqlalchemy import select as _sel
        async with async_session() as db:
            dup = (await db.execute(
                _sel(File).where(File.user_id == user.id, File.file_unique_id == media.file_unique_id)
            )).scalar_one_or_none()
            if dup is not None:
                emoji = {"video": "🎬", "audio": "🎵", "document": "📄", "image": "🖼"}.get(file_type, "📎")
                await status_msg.edit(
                    f"✅ **Already in your library**\n\n"
                    f"{emoji} **{md_safe(dup.file_name)}**\n"
                    f"🆔 File ID: `{dup.id}`\n"
                    f"📦 Size: {format_size(dup.file_size)}\n\n"
                    f"💡 Use `/file {dup.id}` to manage this file"
                )
                return

        # Forward to storage channel
        forwarded = await forward_to_storage_channel(message)
        
        # Extract file info
        raw_filename = getattr(media, "file_name", None) or f"{file_type}_{message.id}" + (".jpg" if file_type == "image" else "")
        file_info = {
            "file_id": media.file_id,
            "file_unique_id": media.file_unique_id,
            "file_name": sanitize_filename(raw_filename),
            "file_size": media.file_size,
            "mime_type": getattr(media, "mime_type", None) or ("image/jpeg" if file_type == "image" else None),
            "duration": getattr(media, "duration", None),
            "width": getattr(media, "width", None),
            "height": getattr(media, "height", None),
            "thumbnail_file_id": media.thumbs[0].file_id if getattr(media, "thumbs", None) else None,
        }
        
        # Save to database
        async with async_session() as db:
            file = File(
                user_id=user.id,
                channel_message_id=forwarded.id,
                file_type=file_type,
                **file_info
            )
            db.add(file)
            await db.commit()
            await db.refresh(file)
        
        # Build response
        emoji = {"video": "🎬", "audio": "🎵", "document": "📄", "image": "🖼"}.get(file_type, "📎")
        
        response = (
            f"✅ **File saved!**\n\n"
            f"{emoji} **{md_safe(file_info['file_name'])}**\n"
            f"🆔 File ID: `{file.id}`\n"
            f"📦 Size: {format_size(file_info['file_size'])}\n"
            f"🎭 Type: {file_type}\n"
        )
        
        if file_info['duration']:
            response += f"⏱ Duration: {format_duration(file_info['duration'])}\n"
        
        response += f"\n📁 Folder: / (root)\n\n"
        response += f"💡 Use `/file {file.id}` to manage this file"
        
        await status_msg.edit(
            response,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✏️ Rename", callback_data=f"renamefile:{file.id}"),
                    InlineKeyboardButton("📂 Move", callback_data=f"move:{file.id}"),
                ],
                [
                    InlineKeyboardButton("📥 Download", callback_data=f"downloadfile:{file.id}"),
                    InlineKeyboardButton("🗑 Delete", callback_data=f"delfile:{file.id}"),
                ],
                [
                    InlineKeyboardButton("☁️ Save to Drive", callback_data=f"savetodrive:{file.id}"),
                    InlineKeyboardButton("🔗 Share", callback_data=f"sharefile:{file.id}"),
                ],
            ])
        )
        
    except Exception as e:
        # The channel copy exists before the DB row — if the insert failed,
        # delete the copy or it stays orphaned in the storage channel forever.
        if forwarded is not None:
            try:
                await delete_from_storage_channel(forwarded.id)
            except Exception:
                _log.warning("bot: orphaned storage msg %s (cleanup failed)", forwarded.id)
        await status_msg.edit(f"❌ Failed to process file: {str(e)}")


# ============== Callback Query Handlers ==============

@tg_client.on_callback_query()
@_log_exceptions
async def handle_callback(client, callback: CallbackQuery):
    _log.info("handle_callback: %s from user %s", callback.data, callback.from_user.id)
    """Handle inline button callbacks."""
    data = callback.data
    
    if data == "logout_all_confirm":
        # Perform global logout
        async with async_session() as db:
            result = await db.execute(select(User).where(User.telegram_id == callback.from_user.id))
            user = result.scalar_one_or_none()
            
            if user:
                user.auth_version += 1
                await db.commit()
                await callback.message.edit(
                    "✅ **All sessions invalidated!**\n"
                    "You have been successfully logged out from all web, TV, and mobile devices."
                )
            else:
                await callback.answer("User not found", show_alert=True)
                return
        await callback.answer()
        
    elif data == "logout_all_cancel":
        # Cancel logout
        await callback.message.edit("❌ **Global logout cancelled.**")
        await callback.answer()

    elif data == "get_web_link":
        # Fallback for old messages - show link and also provide Mini App button
        from pyrogram.errors import ButtonUrlInvalid, MessageNotModified
        async with async_session() as db:
            v_result = await db.execute(
                select(User.auth_version).where(User.telegram_id == callback.from_user.id)
            )
            version = v_result.scalar_one_or_none() or 0
        token = create_access_token(callback.from_user.id, version=version)
        web_url = f"{settings.web_base_url}/auth?token={token}"
        text = (
            f"🌐 **Web Interface**\n\n"
            f"👉 {web_url}\n\n"
            "__(Link valid for 7 days — use logout-all to revoke early)__\n\n"
            "💡 Tap the button below to open directly:"
        )
        try:
            await callback.message.reply(
                text,
                reply_markup=InlineKeyboardMarkup([
                    [await get_web_app_button(callback.from_user.id, "🚀 Open Mini App")]
                ])
            )
        except (ButtonUrlInvalid, MessageNotModified):
            await callback.message.reply(text)
        await callback.answer()
        
    elif data == "show_files":
        # Show recent files similar to /myfiles command
        async with async_session() as db:
            result = await db.execute(
                select(File)
                .where(File.user_id == (
                    select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery()
                ))
                .order_by(File.created_at.desc())
                .limit(10)
            )
            files = result.scalars().all()
        
        if not files:
            await callback.message.reply(
                "📭 You haven't uploaded any files yet.\n\n"
                "Send me a video, audio, or document to get started!"
            )
            await callback.answer()
            return
        
        text = "📁 **Your Recent Files:**\n\n"
        
        for f in files:
            emoji = {"video": "🎬", "audio": "🎵", "document": "📄", "image": "🖼"}.get(f.file_type, "📎")
            text += f"{emoji} `{f.id}` | {md_safe(f.file_name)}\n   └ {format_size(f.file_size)}\n\n"
        
        text += "💡 Use /file <id> to manage a file"
        
        from pyrogram.errors import ButtonUrlInvalid, MessageNotModified
        try:
            await callback.message.reply(
                text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📂 My Folders", callback_data="back_folders")],
                    [await get_web_app_button(callback.from_user.id, "🌐 Open Web")]
                ])
            )
        except (ButtonUrlInvalid, MessageNotModified):
            await callback.message.reply(text)
        await callback.answer()
        
    elif data == "create_folder":
        # Interactive folder creation using listener
        await callback.message.reply(
            "📁 **Create New Folder**\n\n"
            "Send me the folder name:\n"
            "__(or send /cancel to abort)__"
        )
        await callback.answer()
        
        try:
            # Wait for user's reply (60 second timeout)
            reply = await client.wait_for_message(
                chat_id=callback.message.chat.id,
                filters=filters.incoming & filters.text,  # bot's OWN replies must never resolve the flow
                timeout=60
            )
            
            if reply.text and reply.text.startswith("/cancel"):
                await reply.reply("❌ Folder creation cancelled.")
                return
            
            folder_name = (reply.text or "").strip()[:255]
            
            if not folder_name:
                await reply.reply("❌ Invalid folder name.")
                return
            
            # Create folder
            async with async_session() as db:
                user_result = await db.execute(
                    select(User).where(User.telegram_id == callback.from_user.id)
                )
                user = user_result.scalar_one_or_none()
                
                if not user:
                    await reply.reply("Please use /start first.")
                    return
                
                # Check if exists
                existing = await db.execute(
                    select(Folder).where(
                        Folder.user_id == user.id,
                        Folder.name == folder_name,
                        Folder.parent_id.is_(None)
                    )
                )
                if existing.scalar_one_or_none():
                    await reply.reply(f"❌ Folder **{folder_name}** already exists.")
                    return
                
                folder = Folder(user_id=user.id, name=folder_name)
                db.add(folder)
                await db.commit()
            
            await reply.reply(f"✅ Folder **{folder_name}** created!")
            
        except asyncio.TimeoutError:
            await callback.message.reply("⏱ Timed out. Please try again.")
        except ListenerCanceled:
            await callback.message.reply("❌ Cancelled.")
        except Exception as e:
            await callback.message.reply(f"❌ Error: {str(e)}")

    elif data == "back_folders":
        # Show root folders (mirror of /folders)
        async with async_session() as db:
            user_result = await db.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                await callback.answer("Please use /start first.", show_alert=True)
                return

            result = await db.execute(
                select(Folder)
                .where(Folder.user_id == user.id, Folder.parent_id.is_(None))
                .order_by(Folder.name)
            )
            folders = result.scalars().all()

        text = "📂 **My Folders**\n\n"
        buttons = []
        for f in folders:
            buttons.append([
                InlineKeyboardButton(f"📂 {f.name[:60]}", callback_data=f"folder:{f.id}")
            ])
        if not folders:
            text += "No folders yet.\nCreate one with the button below or /newfolder <name>"
        buttons.append([InlineKeyboardButton("➕ Create Folder", callback_data="create_folder")])

        try:
            await callback.message.edit(text, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            await callback.message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))
        await callback.answer()

    elif data.startswith("folder:"):
        folder_id = int(data.split(":")[1])

        async with async_session() as db:
            user_result = await db.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await callback.answer("Please use /start first.", show_alert=True)
                return

            result = await db.execute(
                select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id)
            )
            folder = result.scalar_one_or_none()
            if not folder:
                await callback.answer("Folder not found", show_alert=True)
                return

            subfolders = (await db.execute(
                select(Folder)
                .where(Folder.user_id == user.id, Folder.parent_id == folder.id)
                .order_by(Folder.name)
            )).scalars().all()

            files = (await db.execute(
                select(File)
                .where(File.user_id == user.id, File.folder_id == folder.id)
                .order_by(File.created_at.desc())
                .limit(20)
            )).scalars().all()

        text = f"📂 **{folder.name}**\n\n"
        buttons = []
        for sf in subfolders:
            buttons.append([
                InlineKeyboardButton(f"📂 {sf.name}", callback_data=f"folder:{sf.id}")
            ])
        for f in files:
            emoji = {"video": "🎬", "audio": "🎵", "document": "📄", "image": "🖼"}.get(f.file_type, "📎")
            buttons.append([
                InlineKeyboardButton(f"{emoji} {f.file_name[:40]}", callback_data=f"showfile:{f.id}")
            ])
        if not subfolders and not files:
            text += "This folder is empty."
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_folders")])

        try:
            await callback.message.edit(text, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            await callback.message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))
        await callback.answer()

    elif data.startswith("showfile:"):
        file_id = int(data.split(":")[1])

        async with async_session() as db:
            user_result = await db.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await callback.answer("Please use /start first.", show_alert=True)
                return

            result = await db.execute(
                select(File).where(File.id == file_id, File.user_id == user.id)
            )
            file = result.scalar_one_or_none()

        if not file:
            await callback.answer("File not found or you don't have access.", show_alert=True)
            return

        emoji = {"video": "🎬", "audio": "🎵", "document": "📄", "image": "🖼"}.get(file.file_type, "📎")
        text = (
            f"{emoji} **{md_safe(file.file_name)}**\n\n"
            f"📦 Size: {format_size(file.file_size)}\n"
            f"🎭 Type: {file.file_type}\n"
        )
        if file.duration:
            text += f"⏱ Duration: {format_duration(file.duration)}\n"

        share_btn = InlineKeyboardButton("🔗 Share", callback_data=f"sharefile:{file.id}")
        if file.public_hash:
            text += f"\n🔗 **Public Link:**\n`{settings.web_base_url}/api/stream/s/{file.public_hash}`\n"
            share_btn = InlineKeyboardButton("🔗 Unshare", callback_data=f"unsharefile:{file.id}")

        from pyrogram.errors import ButtonUrlInvalid, MessageNotModified
        try:
            await callback.message.edit(
                text,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✏️ Rename", callback_data=f"renamefile:{file.id}"),
                        InlineKeyboardButton("📂 Move", callback_data=f"move:{file.id}"),
                    ],
                    [
                        InlineKeyboardButton("📥 Download", callback_data=f"downloadfile:{file.id}"),
                        InlineKeyboardButton("🗑 Delete", callback_data=f"delfile:{file.id}"),
                    ],
                    [
                        InlineKeyboardButton("☁️ Save to Drive", callback_data=f"savetodrive:{file.id}"),
                        share_btn,
                    ],
                    [InlineKeyboardButton("🔙 Back", callback_data="back_folders")],
                ])
            )
        except (ButtonUrlInvalid, MessageNotModified):
            await callback.message.reply(text)
        await callback.answer()

    elif data.startswith("renamefile:"):
        file_id = int(data.split(":")[1])
        
        async with async_session() as db:
            result = await db.execute(select(File).where(File.id == file_id, File.user_id == (
                    select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery()
                )))
            file = result.scalar_one_or_none()
            
            if not file:
                await callback.answer("File not found", show_alert=True)
                return
            
            current_name = file.file_name
        
        await callback.message.reply(
            f"✏️ **Rename File**\n\n"
            f"Current name: `{md_safe(current_name)}`\n\n"
            "Send me the new name:\n"
            "__(or send /cancel to abort)__"
        )
        await callback.answer()
        
        try:
            reply = await client.wait_for_message(
                chat_id=callback.message.chat.id,
                filters=filters.incoming & filters.text,  # bot's OWN replies must never resolve the flow
                timeout=60
            )
            
            if reply.text and reply.text.startswith("/cancel"):
                await reply.reply("❌ Rename cancelled.")
                return
            
            new_name = reply.text.strip() if reply.text else None
            
            if not new_name:
                await reply.reply("❌ Invalid name.")
                return
            
            async with async_session() as db:
                result = await db.execute(select(File).where(File.id == file_id, File.user_id == (
                    select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery()
                )))
                file = result.scalar_one_or_none()
                
                if file:
                    file.file_name = sanitize_filename(new_name)
                    await db.commit()
                    await reply.reply(f"✅ File renamed to **{md_safe(file.file_name)}**")
                else:
                    await reply.reply("❌ File not found.")
                    
        except asyncio.TimeoutError:
            await callback.message.reply("⏱ Timed out. Please try again.")
        except ListenerCanceled:
            await callback.message.reply("❌ Cancelled.")
    
    elif data.startswith("delfile:"):
        file_id = int(data.split(":")[1])
        
        async with async_session() as db:
            result = await db.execute(select(File).where(File.id == file_id, File.user_id == (
                    select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery()
                )))
            file = result.scalar_one_or_none()
            
            if not file:
                await callback.answer("File not found", show_alert=True)
                return
                
            file_name = file.file_name
        
        # Ask for confirmation
        await callback.message.edit(
            f"🗑 **Delete File?**\n\n"
            f"Are you sure you want to delete:\n"
            f"`{md_safe(file_name)}`\n\n"
            "⚠️ This action cannot be undone!",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirmdelfile:{file_id}"),
                    InlineKeyboardButton("❌ Cancel", callback_data="canceldel"),
                ]
            ])
        )
        await callback.answer()
        
    elif data.startswith("confirmdelfile:"):
        file_id = int(data.split(":")[1])
        
        async with async_session() as db:
            result = await db.execute(select(File).where(File.id == file_id, File.user_id == (
                    select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery()
                )))
            file = result.scalar_one_or_none()
            
            if not file:
                await callback.answer("File not found", show_alert=True)
                return
            
            file_name = file.file_name
            channel_msg_id = file.channel_message_id
            
            # Delete from database first — if commit fails, Telegram file is safe
            invalidate_message_cache(channel_msg_id)
            await db.delete(file)
            await db.commit()
        
        # Best-effort cleanup from Telegram channel
        try:
            from .telegram import delete_from_storage_channel
            await delete_from_storage_channel(channel_msg_id)
        except Exception:
            pass
        
        await callback.message.edit(f"✅ File **{md_safe(file_name)}** deleted successfully!")
        await callback.answer("File deleted", show_alert=True)
        
    elif data.startswith("renamefolder:"):
        folder_id = int(data.split(":")[1])
        
        async with async_session() as db:
            result = await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == (
                    select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery()
                )))
            folder = result.scalar_one_or_none()
            
            if not folder:
                await callback.answer("Folder not found", show_alert=True)
                return
            
            current_name = folder.name
        
        await callback.message.reply(
            f"✏️ **Rename Folder**\n\n"
            f"Current name: `{md_safe(current_name)}`\n\n"
            "Send me the new name:\n"
            "__(or send /cancel to abort)__"
        )
        await callback.answer()
        
        try:
            reply = await client.wait_for_message(
                chat_id=callback.message.chat.id,
                filters=filters.incoming & filters.text,  # bot's OWN replies must never resolve the flow
                timeout=60
            )
            
            if reply.text and reply.text.startswith("/cancel"):
                await reply.reply("❌ Rename cancelled.")
                return
            
            new_name = reply.text.strip() if reply.text else None
            
            if not new_name:
                await reply.reply("❌ Invalid name.")
                return
            
            async with async_session() as db:
                result = await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == (
                    select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery()
                )))
                folder = result.scalar_one_or_none()
                
                if folder:
                    folder.name = new_name
                    await db.commit()
                    await reply.reply(f"✅ Folder renamed to **{new_name}**")
                else:
                    await reply.reply("❌ Folder not found.")
                    
        except asyncio.TimeoutError:
            await callback.message.reply("⏱ Timed out. Please try again.")
        except ListenerCanceled:
            await callback.message.reply("❌ Cancelled.")

    elif data.startswith("delfolder:"):
        folder_id = int(data.split(":")[1])
        
        async with async_session() as db:
            result = await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == (
                    select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery()
                )))
            folder = result.scalar_one_or_none()
            
            if not folder:
                await callback.answer("Folder not found", show_alert=True)
                return
            
            folder_name = folder.name
            
            # Check if folder has files
            files_count = await db.execute(
                select(func.count()).where(File.folder_id == folder_id)
            )
            count = files_count.scalar() or 0
        
        # Ask for confirmation
        text = (
            f"🗑 **Delete Folder?**\n\n"
            f"Folder: **{folder_name}**\n"
        )
        
        if count > 0:
            text += f"\n⚠️ This folder contains **{count} file(s)**.\nFiles will be moved to root folder."
        
        await callback.message.edit(
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirmdelfolder:{folder_id}"),
                    InlineKeyboardButton("❌ Cancel", callback_data="back_folders"),
                ]
            ])
        )
        await callback.answer()
        
    elif data.startswith("confirmdelfolder:"):
        folder_id = int(data.split(":")[1])
        
        async with async_session() as db:
            result = await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == (
                    select(User.id).where(User.telegram_id == callback.from_user.id).scalar_subquery()
                )))
            folder = result.scalar_one_or_none()
            
            if not folder:
                await callback.answer("Folder not found", show_alert=True)
                return
            
            folder_name = folder.name
            
            # Move files to root first
            from sqlalchemy import update
            await db.execute(
                update(File)
                .where(File.folder_id == folder_id)
                .values(folder_id=None)
            )
            
            # Delete folder
            await db.delete(folder)
            await db.commit()
        
        await callback.message.edit(f"✅ Folder **{folder_name}** deleted successfully!")
        await callback.answer("Folder deleted", show_alert=True)
    
    elif data.startswith("sharefile:"):
        file_id = int(data.split(":")[1])
        
        async with async_session() as db:
            # Verify ownership
            user_result = await db.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                await callback.answer("Please use /start first", show_alert=True)
                return
            
            result = await db.execute(
                select(File).where(File.id == file_id, File.user_id == user.id)
            )
            file = result.scalar_one_or_none()
            
            if not file:
                await callback.answer("File not found", show_alert=True)
                return
            
            # Generate public hash only if one doesn't already exist
            if not file.public_hash:
                file.public_hash = secrets.token_hex(16)
            await db.commit()
            await db.refresh(file)
            
            public_url = f"{settings.web_base_url}/api/stream/s/{file.public_hash}"
        
        await callback.message.reply(
            f"🔗 **Public Link Generated!**\n\n"
            f"Stream URL:\n`{public_url}`\n\n"
            "Anyone with this link can stream the file.\n"
            "Use the button below to revoke access.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Unshare", callback_data=f"unsharefile:{file_id}")]
            ])
        )
        await callback.answer("Public link created!", show_alert=True)
    
    elif data.startswith("unsharefile:"):
        file_id = int(data.split(":")[1])
        
        async with async_session() as db:
            # Verify ownership
            user_result = await db.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                await callback.answer("Please use /start first", show_alert=True)
                return
            
            result = await db.execute(
                select(File).where(File.id == file_id, File.user_id == user.id)
            )
            file = result.scalar_one_or_none()
            
            if not file:
                await callback.answer("File not found", show_alert=True)
                return
            
            file.public_hash = None
            await db.commit()
        
        await callback.message.reply(
            "🔗 **Public link revoked!**\n\n"
            "The file is no longer publicly accessible.\n"
            "You can generate a new link anytime.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Share", callback_data=f"sharefile:{file_id}")]
            ])
        )
        await callback.answer("Public link revoked!", show_alert=True)
    
    elif data.startswith("move:"):
        file_id = int(data.split(":")[1])

        async with async_session() as db:
            user_result = await db.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await callback.answer("Please use /start first", show_alert=True)
                return

            result = await db.execute(
                select(File).where(File.id == file_id, File.user_id == user.id)
            )
            file = result.scalar_one_or_none()
            if not file:
                await callback.answer("File not found", show_alert=True)
                return

            file_name = file.file_name
            current_folder_id = file.folder_id

            folders_result = await db.execute(
                select(Folder)
                .where(Folder.user_id == user.id, Folder.parent_id.is_(None))
                .order_by(Folder.name)
            )
            folders = folders_result.scalars().all()

        text = (
            f"📂 **Move File**\n\n"
            f"`{md_safe(file_name)}`\n\n"
            "Select destination folder:"
        )
        buttons = []

        is_root = current_folder_id is None
        buttons.append([
            InlineKeyboardButton(
                f"{'✅ ' if is_root else ''}📁 / (Root)",
                callback_data=f"movehere:{file_id}:0"
            )
        ])

        for f in folders:
            is_current = f.id == current_folder_id
            buttons.append([
                InlineKeyboardButton(
                    f"{'✅ ' if is_current else ''}📂 {f.name}",
                    callback_data=f"movehere:{file_id}:{f.id}"
                )
            ])

        buttons.append([InlineKeyboardButton("➕ New Folder", callback_data=f"createmovefolder:{file_id}")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="canceldel")])

        await callback.message.edit(text, reply_markup=InlineKeyboardMarkup(buttons))
        await callback.answer()

    elif data.startswith("movehere:"):
        parts = data.split(":")
        file_id = int(parts[1])
        folder_id = int(parts[2]) if parts[2] != "0" else None

        async with async_session() as db:
            user_id = await _resolve_user_id(db, callback.from_user.id)
            if not user_id:
                await callback.answer("Please use /start first", show_alert=True)
                return

            result = await db.execute(select(File).where(File.id == file_id, File.user_id == user_id))
            file = result.scalar_one_or_none()
            if not file:
                await callback.answer("File not found", show_alert=True)
                return

            folder_label = "/ (Root)"
            if folder_id is not None:
                folder_result = await db.execute(
                    select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
                )
                folder = folder_result.scalar_one_or_none()
                if not folder:
                    await callback.answer("Folder not found", show_alert=True)
                    return
                folder_label = f"📁 {folder.name[:60]}"

            file.folder_id = folder_id
            await db.commit()
            file_name = file.file_name

        await callback.message.edit(
            f"✅ **File moved!**\n\n"
            f"`{md_safe(file_name)}`\n"
            f"→ {folder_label}"
        )
        await callback.answer("File moved successfully!", show_alert=True)

    elif data.startswith("createmovefolder:"):
        file_id = int(data.split(":")[1])

        await callback.message.reply(
            "📁 **Create & Move**\n\n"
            "Send me the folder name to create and move the file into:\n"
            "__(or send /cancel to abort)__"
        )
        await callback.answer()

        try:
            reply = await client.wait_for_message(
                chat_id=callback.message.chat.id,
                filters=filters.incoming & filters.text,  # bot's OWN replies must never resolve the flow
                timeout=60
            )

            if reply.text and reply.text.startswith("/cancel"):
                await reply.reply("❌ Cancelled.")
                return

            folder_name = (reply.text or "").strip()[:255]
            if not folder_name:
                await reply.reply("❌ Invalid folder name.")
                return

            async with async_session() as db:
                # The flow initiator, not whoever's text resolved the listener
                # (identical in private chats; matters for forwarded buttons).
                user_result = await db.execute(
                    select(User).where(User.telegram_id == callback.from_user.id)
                )
                user = user_result.scalar_one_or_none()
                if not user:
                    await reply.reply("Please use /start first.")
                    return

                existing = await db.execute(
                    select(Folder).where(
                        Folder.user_id == user.id,
                        Folder.name == folder_name,
                        Folder.parent_id.is_(None)
                    )
                )
                if existing.scalar_one_or_none():
                    await reply.reply(f"❌ Folder **{folder_name}** already exists.")
                    return

                folder = Folder(user_id=user.id, name=folder_name)
                db.add(folder)
                await db.commit()
                await db.refresh(folder)

                result = await db.execute(
                    select(File).where(File.id == file_id, File.user_id == user.id)
                )
                file = result.scalar_one_or_none()
                if file:
                    file.folder_id = folder.id
                    await db.commit()

            await reply.reply(f"✅ Folder **{folder_name}** created and file moved!")

        except asyncio.TimeoutError:
            await callback.message.reply("⏱ Timed out. Please try again.")
        except ListenerCanceled:
            await callback.message.reply("❌ Cancelled.")
        except Exception as e:
            await callback.message.reply(f"❌ Error: {str(e)}")

    elif data.startswith("downloadfile:"):
        file_id = int(data.split(":")[1])

        await callback.answer("🔗 Generating link...")

        async with async_session() as db:
            user_result = await db.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await callback.message.edit("❌ Please use /start first.")
                return

            result = await db.execute(
                select(File).where(File.id == file_id, File.user_id == user.id)
            )
            file = result.scalar_one_or_none()
            if not file:
                await callback.message.edit("❌ File not found.")
                return

            file_name = file.file_name
            file_size = file.file_size
            file_type = file.file_type

        token = create_download_token(callback.from_user.id, file_id, version=user.auth_version)
        from urllib.parse import quote
        download_url = f"{settings.web_base_url}/api/stream/dl?id={file_id}&token={quote(token, safe='')}"

        emoji = {"video": "🎬", "audio": "🎵", "document": "📄", "image": "🖼"}.get(file_type, "📎")
        await callback.message.edit(
            f"{emoji} **{md_safe(file_name)}**\n"
            f"📦 {format_size(file_size)}\n\n"
            f"🔗 **Download Link:**\n"
            f"{download_url}\n\n"
            "Tap the link above or copy it to your browser to download.\n"
            "__(Link expires in 30 days)__"
        )

    elif data.startswith("savetodrive:"):
        file_id = int(data.split(":")[1])
        await callback.answer("☁️ Processing...")

        async with async_session() as db:
            user_result = await db.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await callback.message.edit("❌ Please use /start first.")
                return

            result = await db.execute(
                select(File).where(File.id == file_id, File.user_id == user.id)
            )
            file = result.scalar_one_or_none()
            if not file:
                await callback.message.edit("❌ File not found.")
                return

            channel_msg_id = file.channel_message_id
            file_name = file.file_name
            file_size = file.file_size
            mime_type = file.mime_type or "application/octet-stream"
            token_json = user.gdrive_token

        if not token_json:
            auth_url = gdrive_mod.generate_auth_url(callback.from_user.id)
            await callback.message.edit(
                "☁️ **Google Drive Not Connected**\n\n"
                "You need to connect your Google account first.\n\n"
                f"[Click here to connect]({auth_url})\n\n"
                "After authorizing, return here and tap **Save to Drive** again.",
                disable_web_page_preview=True,
            )
            return

        await callback.message.edit(
            f"☁️ **Uploading to Google Drive...**\n\n"
            f"📄 `{file_name}`\n"
            f"📦 {format_size(file_size)}\n\n"
            "⏳ Connecting to Google Drive..."
        )

        # Run upload in background so the bot stays responsive
        async def _do_gdrive_upload():
            try:
                token_dict = json.loads(token_json)
                msg = await tg_client.get_messages(
                    settings.telegram_storage_channel_id,
                    channel_msg_id,
                )
                if not msg:
                    try:
                        await callback.message.edit("❌ File no longer available in Telegram storage.")
                    except Exception:
                        pass
                    return

                has_media = any((
                    getattr(msg, "video", None),
                    getattr(msg, "document", None),
                    getattr(msg, "audio", None),
                ))
                if not has_media:
                    try:
                        await callback.message.edit("❌ Message has no streamable media.")
                    except Exception:
                        pass
                    return

                # build_service refreshes OAuth tokens and ensure_aruvi_folder
                # issues Drive list/create calls — both synchronous httplib2
                # round-trips that would freeze the event loop (and every
                # active stream) for the duration.
                def _connect_drive():
                    service = gdrive_mod.build_service(token_dict)
                    return service, gdrive_mod.ensure_aruvi_folder(service)
                service, folder_id = await asyncio.to_thread(_connect_drive)

                try:
                    await callback.message.edit(
                        f"☁️ **Uploading to Google Drive...**\n\n"
                        f"📄 `{file_name}`\n"
                        f"📦 {format_size(file_size)}\n\n"
                        "📤 Streaming to Drive..."
                    )
                except Exception:
                    pass

                async def _progress(uploaded, total, phase="Uploading to Google Drive"):
                    pct = uploaded * 100 // total if total else 0
                    bars = "▓" * (pct // 10) + "░" * (10 - pct // 10)
                    try:
                        await callback.message.edit(
                            f"☁️ **{phase}...**\n\n"
                            f"📄 `{file_name}`\n"
                            f"📦 {format_size(file_size)}\n\n"
                            f"`[{bars}] {pct}%`\n"
                            f"📤 {format_size(uploaded)} / {format_size(total)}"
                        )
                    except Exception:
                        pass

                link = await gdrive_mod.upload_streaming(
                    token_dict,
                    msg,
                    file_name,
                    mime_type,
                    file_size,
                    folder_id,
                    progress_callback=_progress,
                )

                # Persist refreshed token back to DB
                async with async_session() as db:
                    u_result = await db.execute(
                        select(User).where(User.telegram_id == callback.from_user.id)
                    )
                    u = u_result.scalar_one_or_none()
                    if u:
                        if token_dict.get("refresh_token"):
                            u.gdrive_token = json.dumps(token_dict)
                        else:
                            u.gdrive_token = None
                        await db.commit()

                try:
                    await callback.message.edit(
                        f"✅ **Uploaded to Google Drive!**\n\n"
                        f"📄 `{file_name}`\n"
                        f"📁 Folder: **Aruvi**\n\n"
                        f"🔗 [Open in Drive]({link})",
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass

                if not token_dict.get("refresh_token"):
                    try:
                        await callback.message.reply(
                            "⚠️ Your Google Drive authorization has expired. "
                            "Send /drive to reconnect for future uploads."
                        )
                    except Exception:
                        pass

            except gdrive_mod.TokenExpiredError:
                _log.warning("GDrive token expired for user %s", callback.from_user.id)
                async with async_session() as db:
                    u_result = await db.execute(
                        select(User).where(User.telegram_id == callback.from_user.id)
                    )
                    u = u_result.scalar_one_or_none()
                    if u:
                        u.gdrive_token = None
                        await db.commit()
                try:
                    await callback.message.edit(
                        "❌ **Google Drive authorization expired.**\n\n"
                        "Your connection has been revoked. Send /drive to reconnect."
                    )
                except Exception:
                    pass

            except Exception as e:
                _log.exception("GDrive upload failed for file %s", file_id)
                try:
                    await callback.message.edit(
                        f"❌ **Upload failed.**\n\n"
                        f"File: `{file_name}`\n"
                        f"Error: {str(e)}\n\n"
                        "Please try again later."
                    )
                except Exception:
                    pass

        # Multi-minute upload task — must be referenced or GC can kill it
        # mid-upload (asyncio only keeps weak refs to tasks).
        from .utils import spawn_background
        spawn_background(_do_gdrive_upload())

    elif data == "canceldel":
        await callback.message.edit("❌ Deletion cancelled.")
        await callback.answer()


# ============== File Action Command ==============

@tg_client.on_message(filters.command("file") & filters.private)
async def file_command(client, message: Message):
    """Manage a specific file by ID."""
    if len(message.command) < 2:
        await message.reply("Usage: /file <file_id>")
        return
    
    try:
        file_id = int(message.command[1])
    except ValueError:
        await message.reply("❌ Invalid file ID.")
        return
    
    async with async_session() as db:
        # Get user
        user_result = await db.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.reply("Please use /start first.")
            return
        
        # Get file
        result = await db.execute(
            select(File).where(File.id == file_id, File.user_id == user.id)
        )
        file = result.scalar_one_or_none()
    
    if not file:
        await message.reply("❌ File not found or you don't have access.")
        return
    
    emoji = {"video": "🎬", "audio": "🎵", "document": "📄", "image": "🖼"}.get(file.file_type, "📎")
    
    text = (
        f"{emoji} **{md_safe(file.file_name)}**\n\n"
        f"📦 Size: {format_size(file.file_size)}\n"
        f"🎭 Type: {file.file_type}\n"
    )
    
    if file.duration:
        text += f"⏱ Duration: {format_duration(file.duration)}\n"
    
    if file.public_hash:
        public_url = f"{settings.web_base_url}/api/stream/s/{file.public_hash}"
        text += f"\n🔗 **Public Link:**\n`{public_url}`\n"
        share_btn = InlineKeyboardButton("🔗 Unshare", callback_data=f"unsharefile:{file.id}")
    else:
        share_btn = InlineKeyboardButton("🔗 Share", callback_data=f"sharefile:{file.id}")
    
    await message.reply(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ Rename", callback_data=f"renamefile:{file.id}"),
                InlineKeyboardButton("📂 Move", callback_data=f"move:{file.id}"),
            ],
            [
                InlineKeyboardButton("📥 Download", callback_data=f"downloadfile:{file.id}"),
                InlineKeyboardButton("🗑 Delete", callback_data=f"delfile:{file.id}"),
            ],
            [
                InlineKeyboardButton("☁️ Save to Drive", callback_data=f"savetodrive:{file.id}"),
                share_btn,
            ],
        ])
    )


@tg_client.on_message(filters.command("deletefolder") & filters.private)
async def deletefolder_command(client, message: Message):
    """Delete a folder by name."""
    if len(message.command) < 2:
        await message.reply("Usage: /deletefolder <folder_name>")
        return
    
    folder_name = " ".join(message.command[1:]).strip()[:255]
    
    async with async_session() as db:
        # Get user
        user_result = await db.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.reply("Please use /start first.")
            return
        
        # Find folder
        result = await db.execute(
            select(Folder).where(
                Folder.user_id == user.id,
                Folder.name == folder_name
            )
        )
        folder = result.scalar_one_or_none()
    
    if not folder:
        await message.reply(f"❌ Folder **{folder_name}** not found.")
        return
    
    # Show confirmation
    await message.reply(
        f"🗑 **Delete Folder?**\n\n"
        f"Folder: **{folder_name}**\n\n"
        "Files in this folder will be moved to root.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirmdelfolder:{folder.id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="canceldel"),
            ]
        ])
    )

