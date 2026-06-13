"""Eigene orjson-Response-Klasse als Ersatz fuer FastAPIs ORJSONResponse.

FastAPI hat ``fastapi.responses.ORJSONResponse`` deprecated (Serialisierung
laeuft dort jetzt ueber Pydantic, sobald ein response_model gesetzt ist). Die
Error-Handler und die ``default_response_class`` brauchen aber weiterhin eine
konkrete Response-Klasse mit orjson-Bytes-Body (der ETag-Middleware-Vertrag
in main.py haengt an deterministischen Response-Bytes). Diese Klasse ist das
dokumentierte Starlette-Muster: ``JSONResponse``-Subklasse mit ``render`` via
``orjson.dumps`` - verhaltensgleich zur alten ORJSONResponse, ohne Deprecation.
"""

from __future__ import annotations

from typing import Any

import orjson
from starlette.responses import JSONResponse


class OrjsonResponse(JSONResponse):
    """JSON-Response, die den Body mit orjson serialisiert (bytes)."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)
