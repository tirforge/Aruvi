"""
Internet subtitle search + download.

Subliminal powers the keyless providers (addic7ed, tvsubtitles, podnapisi...).
OpenSubtitles.com is handled by a small in-house client because subliminal's
provider paginates every result page (huge + 400 blips) and its download
requires a username/password login — while the REST API works with just an
API key (free tier: 5 subs/day anonymous).
"""
import os
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import subliminal
from babelfish import Language, LanguageReverseError
from guessit import guessit as _guessit
from subliminal.video import Movie, Episode

from ..database import get_db
from ..models import File, User
from ..auth import get_current_user
from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/subtitles", tags=["Subtitles"])

_OS_URL = "https://api.opensubtitles.com/api/v1"

# dogpile-cache 1.5.0 changed CacheRegion internals; subliminal's unconfigured
# `region` breaks on the first get_or_create unless we back it explicitly.
_configured_region = False


def _ensure_region() -> None:
    global _configured_region
    if _configured_region:
        return
    try:
        subliminal.cache.region.configure(
            "dogpile.cache.memory",
            expiration_time=86400,
            arguments={"expiration_time": 86400},
        )
        _configured_region = True
    except Exception:
        logger.warning("subliminal region already configured", exc_info=True)


def _subliminal_providers() -> list[str]:
    """Configured keyless providers only — OpenSubtitles.com is handled in-house."""
    return [p for p in settings.subtitle_providers if p != "opensubtitlescom"]


def _os_enabled() -> bool:
    return bool(settings.opensubtitles_api_key)


_KEYS = {
    "resolution", "source", "video_codec", "audio_codec", "release_group",
    "format", "edition", "proper_count", "stream", "video_profile",
}


def _video_from_name(name: str) -> object:
    """Build a subliminal Movie/Episode from a stored file name via guessit."""
    info = _guessit(name)
    base_title = info.get("title") or info.get("series") or os.path.splitext(os.path.basename(name))[0]
    kwargs = {k: v for k, v in info.items() if k in _KEYS and v is not None}
    year = kwargs.pop("year", None) or info.get("year")
    common = dict(year=int(year)) if year else {}

    if info.get("type") == "episode":
        season = info.get("season")
        eps = info.get("episode")
        if eps is None:
            eps = [1]
        elif not isinstance(eps, list):
            eps = [eps]
        try:
            season = int(season or 1)
            eps = [int(e) for e in eps if e is not None] or [1]
        except (TypeError, ValueError):
            season, eps = 1, [1]
        return Episode(name, series=base_title, season=season, episodes=eps, **common, **kwargs)

    return Movie(name, title=base_title, **common, **kwargs)


def _flatten_id(subtitle) -> str:
    sid = getattr(subtitle, "id", None)
    if isinstance(sid, (tuple, list)):
        return "/".join(str(x) for x in sid)
    return str(sid)


def _serialize(subtitle, video) -> dict:
    lang: Optional[Language] = getattr(subtitle, "language", None)
    try:
        score = subliminal.compute_score(subtitle, video)
    except Exception:
        score = 0
    fmt = getattr(subtitle, "format", None) or "srt"
    name = getattr(subtitle, "name", None) or _flatten_id(subtitle)
    try:
        matches = sorted(getattr(subtitle, "matches", set()) or set())
    except Exception:
        matches = []
    return {
        "provider": getattr(subtitle, "provider_name", "unknown"),
        "id": _flatten_id(subtitle),
        "name": name,
        "language": lang.alpha2 if lang else "unknown",
        "language_name": lang.name if lang else "Unknown",
        "score": score,
        "format": fmt,
        "matches": matches,
    }


# ---- OpenSubtitles.com in-house client (API-key only, free tier) ----


def _os_headers() -> dict:
    return {
        "Api-Key": settings.opensubtitles_api_key,
        "User-Agent": "TelePlay v1.0",
        "Accept": "*/*",
    }


def _os_lang_code() -> str:
    """OpenSubtitles.com expects a bare code like 'en'."""
    code = settings.subtitle_languages[0] if settings.subtitle_languages else "en"
    try:
        lang = Language.fromietf(code)
    except (LanguageReverseError, ValueError):
        return "en"
    alpha2 = getattr(lang, "alpha2", None)
    if not alpha2 or len(alpha2) > 3:
        return "en"
    return alpha2


async def _os_search(title: str | None, year: int | None,
                     season: int | None = None, episode: int | None = None) -> list[dict]:
    """Query api.opensubtitles.com /subtitles (single page). Returns serialized dicts."""
    if not title:
        return []
    params: dict = {
        "query": title,
        "languages": _os_lang_code(),
        "page": 1,
    }
    # OpenSubtitles returns 0 hits when year + season/episode are combined,
    # so only send year for movies.
    if year and season is None and episode is None:
        params["year"] = year
    if season is not None and episode is not None:
        params["season_number"] = season
        params["episode_number"] = episode

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(f"{_OS_URL}/subtitles", headers=_os_headers(), params=params)
            r.raise_for_status()
            payload = r.json()
    except Exception as exc:
        logger.warning("opensubtitlescom search failed: %s", exc)
        return []

    out: list[dict] = []
    for item in payload.get("data") or []:
        attrs = item.get("attributes") or {}
        files = attrs.get("files") or []
        sub_id = attrs.get("subtitle_id") or item.get("id")
        if not sub_id or not files:
            continue
        file_id = files[0].get("file_id")
        release = attrs.get("release") or attrs.get("slug") or f"subtitle {sub_id}"
        score = int(attrs.get("download_count") or 0)
        out.append({
            "provider": "opensubtitlescom",
            "id": str(sub_id),
            "download_id": file_id,
            "name": release,
            "language": _os_lang_code(),
            "language_name": _os_lang_code(),
            "score": score,
            "format": "srt",
            "matches": ["title"] + (["year"] if year else []),
        })
    # most popular first
    out.sort(key=lambda d: d["score"], reverse=True)
    return out


async def _os_download(sub_id: str, file_id: int | None) -> tuple[str, str]:
    """Download subtitle content via the /download endpoint. Returns (format, text)."""
    if file_id is None:
        raise HTTPException(status_code=404, detail="Subtitle has no downloadable file entry")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.post(
                f"{_OS_URL}/download",
                headers=_os_headers(),
                json={"file_id": int(file_id)},
            )
            r.raise_for_status()
            dl = r.json()
            remaining = int(dl.get("remaining") or 0)
            if remaining <= 0:
                raise HTTPException(status_code=429, detail="OpenSubtitles free download quota reached for today")
            link = dl.get("link")
            if not link:
                raise HTTPException(status_code=502, detail="OpenSubtitles returned no download link")
            content = (await client.get(link, headers=_os_headers())).content
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("opensubtitlescom download failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to download subtitle from provider")

    if not content:
        raise HTTPException(status_code=502, detail="OpenSubtitles returned empty subtitle")
    text = content.decode("utf-8", errors="replace")
    fmt = "webvtt" if text.lstrip().startswith("WEBVTT") else "srt"
    return fmt, text


# ---- Routes ----


@router.get("/search")
async def search_subtitles(
    file_id: int = Query(...),
    language: str = Query("en", description="IETF language tag, e.g. en, eng, ta"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Look up internet subtitles for a stored file's guessed title."""
    result = await db.execute(select(File).where(File.id == file_id, File.user_id == current_user.id))
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        info = _guessit(file.file_name)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Could not parse a title from this file name")

    title = info.get("title") or info.get("series")
    if not title:
        raise HTTPException(status_code=422, detail="Could not parse a title from this file name")

    candidates: list[dict] = []
    providers = _subliminal_providers()

    # Try language override (search uses the requested tag; os client uses default).
    try:
        langs = {Language.fromietf(language)}
    except (LanguageReverseError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid language: {language}")

    if providers:
        _ensure_region()
        try:
            video = _video_from_name(file.file_name)
            import asyncio
            found = await asyncio.to_thread(
                subliminal.list_subtitles, {video}, langs, providers=providers
            )
            subs = found.get(video, [])
            subs.sort(key=lambda s: subliminal.compute_score(s, video), reverse=True)
            candidates.extend(_serialize(s, video) for s in subs)
        except Exception as exc:
            logger.warning("subtitle search failed: %s", exc)
            # Non-fatal: fall through to the OpenSubtitles client.

    if _os_enabled():
        is_ep = info.get("type") == "episode"
        candidates.extend(
            await _os_search(
                title,
                info.get("year") or None,
                season=info.get("season") or None if is_ep else None,
                episode=info.get("episode") or None if is_ep else None,
            )
        )

    # De-dupe identical (provider, id)
    seen = set()
    unique = []
    for cand in candidates:
        key = (cand["provider"], cand["id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(cand)
    unique.sort(key=lambda c: c.get("score") or 0, reverse=True)

    return {
        "file_id": file_id,
        "language": language,
        "providers": providers + (["opensubtitlescom"] if _os_enabled() else []),
        "guessed": {
            "type": "episode" if info.get("type") == "episode" else "movie",
            "title": title,
            "season": info.get("season"),
            "episode": info.get("episode"),
            "year": info.get("year"),
        },
        "subtitles": unique,
    }


@router.get("/content")
async def subtitle_content(
    file_id: int = Query(...),
    provider: str = Query(...),
    subtitle_id: str = Query(...),
    download_id: Optional[int] = Query(None),
    language: str = Query("en"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a specific subtitle and return SRT/VTT text."""
    result = await db.execute(select(File).where(File.id == file_id, File.user_id == current_user.id))
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    if provider == "opensubtitlescom":
        if not _os_enabled():
            raise HTTPException(status_code=400, detail="OpenSubtitles API key not configured")
        fmt, text = await _os_download(subtitle_id, download_id)
        return {"provider": provider, "layer_id": subtitle_id, "format": fmt, "text": text}

    _ensure_region()
    try:
        langs = {Language.fromietf(language)}
    except (LanguageReverseError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid language: {language}")

    try:
        video = _video_from_name(file.file_name)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Could not parse a title from this file name")

    import asyncio

    try:
        found = await asyncio.to_thread(subliminal.list_subtitles, {video}, langs, providers=[provider])
    except Exception as exc:
        logger.warning("subtitle lookup for provider %s failed: %s", provider, exc)
        raise HTTPException(status_code=502, detail="Subtitle provider unreachable")

    target = None
    for sub in found.get(video, []):
        if _flatten_id(sub) == subtitle_id:
            target = sub
            break
    if target is None:
        raise HTTPException(status_code=404, detail="Subtitle no longer available from that provider")

    try:
        await asyncio.to_thread(subliminal.download_subtitles, [target])
    except Exception as exc:
        logger.warning("subtitle download failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to download subtitle from provider")

    content = target.content or b""
    try:
        text = target.text
    except Exception:
        text = content.decode("utf-8", errors="replace")

    fmt = (getattr(target, "format", None) or "srt").lower()
    if fmt not in ("srt", "webvtt"):
        if text and text.lstrip().startswith("WEBVTT"):
            fmt = "webvtt"
        else:
            fmt = "srt"

    return {"provider": target.provider_name, "layer_id": subtitle_id, "format": fmt, "text": text}