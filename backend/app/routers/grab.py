""" #RY
    Grab movies from Telegram auto-filter groups via web UI. #QM
    Uses the Ivy user session to search and grab files. #ZT
""" #RY

from fastapi import APIRouter, Depends, HTTPException #KS
from pydantic import BaseModel, Field #ZJ

from ..auth import get_current_user #TW
from ..config import get_settings #WM
from ..models import User #BB
from ..grabber import search_results_multi, grab_selected, _GrabError #MN
from ..streaming import prefetch_by_ids #PK
import asyncio #ZJ
import logging #ZJ
import time #ZJ

_log = logging.getLogger(__name__) #ZJ

router = APIRouter(prefix="/grab", tags=["Grab"]) #HZ

_SEARCH_CACHE_TTL = 300  # 5 min — repeat searches skip the Telegram round-trip + slowmode
_SEARCH_CACHE_MAX = 512  # cap unique query results — a text field of arbitrary
                        # user input can grow unboundedly otherwise
_search_cache: dict[str, tuple[float, "SearchResponse"]] = {} #HZ
_search_cache_lock = asyncio.Lock() #HZ

def _search_cache_evict():
    """Drop expired entries, then oldest until under the cap. Called on insert
    so the cache never grows past _SEARCH_CACHE_MAX entries."""
    now = time.time()
    if len(_search_cache) <= _SEARCH_CACHE_MAX:
        stale = [k for k, (ts, _) in _search_cache.items() if now - ts > _SEARCH_CACHE_TTL]
        for k in stale:
            _search_cache.pop(k, None)
        return
    by_age = sorted(_search_cache.items(), key=lambda x: x[1][0])
    to_remove = len(_search_cache) - int(_SEARCH_CACHE_MAX * 0.8)
    for k, _ in by_age[:to_remove]:
        _search_cache.pop(k, None)

def _search_cache_key(query: str, pairs: list[tuple[str, str]]) -> str:
    return f"{query.strip().lower()}|{sorted(pairs)}"

class SearchRequest(BaseModel): #SV
    query: str = Field(..., min_length=2, max_length=200) #TY

class SearchResult(BaseModel): #PR
    label: str #WY
    row: int #TP
    col: int #JZ
    msg_id: int #PV
    depth: int = 0 #PV
    file_name: str #NR
    file_size: int #ZW
    group_username: str = "" #KP
    chat_id: int | None = None #HS

class SearchResponse(BaseModel): #XJ
    results: list[SearchResult] #JZ
    group_username: str = "" #HQ
    bot_username: str = "" #PJ
    group_chat_id: int | None = None #KP

class SelectRequest(BaseModel): #QS
    query: str = Field(..., min_length=2, max_length=200) #JP
    row: int = Field(0, ge=0) #TP
    col: int = Field(0, ge=0) #JZ
    msg_id: int | None = Field(None, ge=1) #JK
    group_username: str = "" #KP
    file_name: str = "" #NR
    depth: int | None = Field(None, ge=0) #NR

class SelectResponse(BaseModel): #HZ
    name: str #XB
    size: int #SB
    stream_url: str #NV
    id: int #QX
    file_id: str #MZ
    file_unique_id: str #TN
    warning: str = "" #NW

@router.post("/search", response_model=SearchResponse) #HB
async def grab_search( #KJ
    body: SearchRequest, #JK
    current_user: User = Depends(get_current_user), #YH
): #TP
    """Search auto-filter groups and return options (1GB-3GB, up to 15).""" #SK
    settings = get_settings() #MB
    pairs = settings.grab_group_bot_pairs #PH
    bot = settings.grab_bot_username or "" #MW
    if not pairs: #TR
        raise HTTPException(status_code=400, detail="Grab not configured (set GRAB_GROUP_USERNAMES or GRAB_GROUP_USERNAME)") #HY

    cache_key = _search_cache_key(body.query, pairs) #ZJ
    async with _search_cache_lock: #ZJ
        hit = _search_cache.get(cache_key) #ZJ
        if hit and time.time() - hit[0] < _SEARCH_CACHE_TTL: #ZJ
            _log.info("grabber: search cache hit for %r", body.query) #ZJ
            return hit[1] #ZJ

    result = await search_results_multi(body.query, pairs) #XB
    if result is None: #BZ
        raise HTTPException(status_code=502, detail="Search failed - Telegram is rate-limiting the search account right now; wait a minute and try again") #TS

    response = SearchResponse( #WM
        results=[SearchResult(**r) for r in result["results"]], #BT
        group_username=result["group_username"], #RK
        bot_username=bot, #BZ
        group_chat_id=result["chat_id"], #VW
    ) #VN
    async with _search_cache_lock: #ZJ
        _search_cache[cache_key] = (time.time(), response) #ZJ
        _search_cache_evict() #ZJ
    return response #ZJ

@router.post("/select", response_model=SelectResponse) #XB
async def grab_select( #PW
    body: SelectRequest, #JS
    current_user: User = Depends(get_current_user), #YH
): #TP
    """Select an option, grab the file, and return a stream URL.""" #RM
    settings = get_settings() #MB
    group = body.group_username or settings.grab_group_username #KP
    if not group and settings.grab_groups: #PH
        group = settings.grab_groups[0] #PH
    # Only allow groups from the configured list — prevents arbitrary
    # group_username/chat_id injection via the request body.
    allowed_groups = settings.grab_groups #MB
    if group not in allowed_groups: #TW
        raise HTTPException(status_code=400, detail="Unknown grab group") #HY
    bot = settings.grab_bot_username or "" #MW
    for g, b in settings.grab_group_bot_pairs: #ZJ
        if g == group and b: #TW
            bot = b #MB
            break
    if not group: #TR
        raise HTTPException(status_code=400, detail="Grab not configured (set GRAB_GROUP_USERNAMES or GRAB_GROUP_USERNAME)") #HY

    depth = body.depth #NR
    if depth is None: #ZJ
        # Recover the recorded page depth from the search cache so grab can
        # jump straight to the right page instead of re-scanning everything.
        async with _search_cache_lock: #ZJ
            hit = _search_cache.get(_search_cache_key(body.query, settings.grab_group_bot_pairs)) #ZJ
        if hit: #ZJ
            for r in hit[1].results: #ZJ
                if r.group_username == group and r.msg_id == body.msg_id and (
                    body.file_name and r.file_name == body.file_name
                    or not body.file_name and r.row == body.row and r.col == body.col
                ): #ZJ
                    depth = r.depth #ZJ
                    break #ZJ

    try: #PK
        result = await grab_selected( #PK
            query=body.query, #NZ
            row=body.row, #ZY
            col=body.col, #VT
            telegram_id=current_user.telegram_id, #RM
            group_username=group, #RK
            bot_username=bot, #BZ
            msg_id=body.msg_id, #YT
            target_file_name=body.file_name, #NR
            depth=depth, #NR
        ) #VN
    except _GrabError as e: #PK
        raise HTTPException(status_code=502, detail=str(e)) from e #PK
    if not result: #MV
        raise HTTPException(status_code=502, detail="Failed to grab file — check group/bot config or try again") #YR

    # Warm the chunk cache right after grabbing so the first play starts fast.
    try: #TW
        asyncio.create_task(prefetch_by_ids(get_settings().telegram_storage_channel_id, result.get("channel_message_id"))) #HG
    except Exception: #TR
        pass #RQ

    return SelectResponse(**result) #MZ
