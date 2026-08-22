"""Content-type-filtered gzip compression for single-shot text responses.

Starlette's GZipMiddleware compresses ANY response when the client sends
Accept-Encoding: gzip — including streamed video/audio (massive wasted CPU
per chunk, and range/206 semantics break). This middleware only compresses
complete JSON/HTML/text bodies (API payloads), passes streamed bodies and
non-200/206 responses through untouched. Large static assets (SPA bundle,
vendored player) are served PRECOMPRESSED by main.serve_spa instead.
"""
import gzip

# Only these get compressed — never media, never octet-stream.
COMPRESSIBLE_TYPES = frozenset({
    "application/json",
    "text/html",
    "text/plain",
    "text/css",
    "application/javascript",
    "application/manifest+json",
})


def _content_type(start_message) -> str:
    for k, v in start_message.get("headers", []):
        if k.lower() == b"content-type":
            return v.decode("latin-1").split(";")[0].strip().lower()
    return ""


class CompressibleGZipMiddleware:
    """Buffers the response start until the (single-shot) body is known, then
    emits start+body together — compressed when worthwhile."""

    def __init__(self, app, minimum_size: int = 1024):
        self.app = app
        self.minimum_size = minimum_size

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        accept = b""
        for k, v in scope.get("headers", []):
            if k.lower() == b"accept-encoding":
                accept = v
                break
        if b"gzip" not in accept:
            await self.app(scope, receive, send)
            return

        state = {}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["start"] = message
                state["compress"] = (
                    message["status"] == 200
                    and _content_type(message) in COMPRESSIBLE_TYPES
                )
                return

            if message["type"] == "http.response.body":
                if message.get("more_body"):
                    # Streamed response — flush the original start message
                    # unmodified and forward chunks raw.
                    if "start" in state:
                        await send(state.pop("start"))
                    await send(message)
                    return

                body = message.get("body", b"")
                if state.get("compress") and len(body) >= self.minimum_size:
                    compressed = gzip.compress(body, compresslevel=6)
                    if len(compressed) < len(body):
                        start = state.pop("start")
                        headers = [
                            (k, v) for k, v in start.get("headers", [])
                            if k.lower() != b"content-length"
                        ]
                        headers += [
                            (b"content-length", str(len(compressed)).encode()),
                            (b"content-encoding", b"gzip"),
                            (b"vary", b"accept-encoding"),
                        ]
                        start["headers"] = headers
                        await send(start)
                        await send({"type": "http.response.body", "body": compressed})
                        return
                if "start" in state:
                    await send(state.pop("start"))
                await send(message)
                return

            await send(message)

        await self.app(scope, receive, send_wrapper)
        # App finished without a terminal body message (defensive) — the ASGI
        # spec requires one, but never leave a start message unsent.
        if "start" in state:
            await send(state.pop("start"))
            await send({"type": "http.response.body", "body": b""})
