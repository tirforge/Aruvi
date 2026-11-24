"""orjson-backed JSON response used as the app's default encoder.

Why not ``fastapi.responses.ORJSONResponse``? FastAPI 0.165 deprecates it in
favour of declaring a response model, where Pydantic serialises straight to
JSON bytes. Aruvi's routers largely return plain dicts (no response_model), so
the default path would be stdlib ``json.dumps`` — ~6x slower on a 400-file
``/api/files`` payload (``scripts/bench_json.py``) and ~8% larger.

This is a two-line subclass: FastAPI still owns content negotiation and the
JSON-safe encoding of values; orjson only replaces the final byte encoding.
Delete it once the hot routers declare response models.
"""

from __future__ import annotations

from typing import Any

import orjson
from fastapi.responses import JSONResponse


class OrjsonResponse(JSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)
