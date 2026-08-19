"""
File-type classification shared by the grabber, bot file handler, and
serialization paths. A file is classified by mime type first (Telegram usually
attaches accurate mime to documents), falling back to the file extension for
files Telegram labels generically (application/octet-stream etc.).

This is what keeps e.g. a shared .mkv — delivered by the delivery bot as a
*document* with video/x-matroska (or octet-stream) — from showing up as
"document" in the UI instead of "video".
"""
import os

_VIDEO_EXT = {
    ".mkv", ".mp4", ".avi", ".webm", ".mov", ".m4v", ".ts", ".m2ts", ".mts",
    ".flv", ".wmv", ".mpg", ".mpeg", ".vob", ".ogv", ".3gp", ".divx", ".f4v",
    ".rm", ".rmvb", ".asf", ".tp", ".mxf",
}

_AUDIO_EXT = {
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".oga", ".weba",
    ".wma", ".alac", ".ape", ".aiff", ".au", ".mid", ".midi", ".amr", ".mka",
    ".ac3", ".dts", ".eac3", ".wv",
}

_IMAGE_EXT = {
    ".jpg", ".jpeg", ".jfif", ".png", ".gif", ".webp", ".bmp", ".svg",
    ".heic", ".heif", ".avif", ".tiff", ".tif", ".ico",
}


def classify_file_type(file_name: str | None, mime_type: str | None) -> str:
    """Return 'video' | 'audio' | 'image' | 'document' for a file."""
    mime = (mime_type or "").lower()
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("image/"):
        return "image"

    ext = os.path.splitext(file_name or "")[1].lower()
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _AUDIO_EXT:
        return "audio"
    if ext in _IMAGE_EXT:
        return "image"
    return "document"
