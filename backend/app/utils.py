import asyncio
import hmac
import re


def bearer_token_matches(auth_header: str, expected: str) -> bool:
    """Constant-time check that a Authorization header equals 'Bearer <expected>'.
    Debug/diag endpoints guard powerful operations, so the comparison must not
    leak timing information about the secret."""
    if not expected:
        return False
    return hmac.compare_digest(auth_header.encode(), f"Bearer {expected}".encode())


# Fire-and-forget tasks must be referenced somewhere, or the event loop only
# keeps a weak reference and GC can collect (and silently kill) them mid-flight.
_background_tasks: set[asyncio.Task] = set()


def spawn_background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def sanitize_filename(name: str) -> str:
    if not name:
        return "unnamed_file"

    name = name.replace("\x00", "").replace("/", "_").replace("\\", "_")
    name = re.sub(r'[<>:"|?*\x00-\x1f]', '_', name)
    name = name.strip(". ")

    if len(name) > 255:
        if "." in name:
            ext = name.rsplit(".", 1)[-1][:10]
            name = name[:255 - len(ext) - 1] + "." + ext
        else:
            name = name[:255]

    return name if name else "unnamed_file"


def md_safe(text: str) -> str:
    """Make user text safe to embed in Pyrogram's default Markdown parse mode.

    Backticks are the dangerous one: inside a `` `code span` `` an unbalanced
    backtick breaks the whole message parse (MessageParseError → send fails).
    Markdown action characters (**, [], etc.) only render oddly, so they stay.
    """
    return text.replace("`", "'") if text else text
