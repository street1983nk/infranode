"""Walking-Skeleton-Demo-Routen (FND-03/04/05).

Beweist jeden Cross-Cutting-Concern end-to-end:
- /health  -> Redis-Ping + Status (FND-05)
- /ping    -> Correlation-ID in meta + JSON-Log mit request_id (FND-03/05)
- /echo    -> typvalidierter Query (löst 400-Envelope bei Fehler aus, FND-04)
- /_boom   -> erzwungener UpstreamError (beweist 503-Envelope, FND-04)
"""

from __future__ import annotations

import structlog
from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Request

from infranode import __version__

from ..errors import UpstreamError

router = APIRouter()
log = structlog.get_logger()


@router.get("/health")
async def health(request: Request) -> dict:
    """Liveness/Readiness inkl. Redis-Ping (Ping nur hier, nicht im Lifespan)."""
    redis = request.app.state.redis
    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"status": "ok", "version": __version__, "redis": redis_ok}


@router.get("/ping")
async def ping() -> dict:
    """Erzeugt eine JSON-Log-Zeile mit request_id und gibt die ID im meta zurück."""
    log.info("ping_received")
    return {"data": {"pong": True}, "meta": {"correlation_id": correlation_id.get()}}


@router.get("/echo")
async def echo(n: int) -> dict:
    """Echo eines int-Query; nicht-int löst RequestValidationError -> 400 aus."""
    return {"data": {"n": n}, "meta": {"correlation_id": correlation_id.get()}}


@router.get("/_boom")
async def boom() -> dict:
    """Walking-Skeleton: beweist die einheitliche Error-Envelope (503)."""
    raise UpstreamError(
        "Simulated upstream failure",
        hint="This route exists only to test error mapping.",
    )
