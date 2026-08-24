"""
Router package initialization.
"""
from .files import router as files_router
from .folders import router as folders_router
from .streaming import router as streaming_router
from .auth import router as auth_router
from .tv import router as tv_router
from .admin import router as admin_router
from .gdrive import router as gdrive_router
from .legal import router as legal_router
from .diagnostic import router as diagnostic_router
from .grab import router as grab_router
from .subtitles import router as subtitles_router
from .setup import router as setup_router

__all__ = ["files_router", "folders_router", "streaming_router", "auth_router", "tv_router", "admin_router", "gdrive_router", "legal_router", "diagnostic_router", "grab_router", "subtitles_router", "setup_router"]
