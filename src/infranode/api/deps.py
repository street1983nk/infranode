"""FastAPI-Abhängigkeiten.

Liefert die per Lifespan in ``app.state`` gesetzten Ressourcen: den
Redis-Client und den prozessweiten, gepoolten httpx-AsyncClient (RES-01).
Wächst später (Cache-Helper, Rate-Limit-Kontext, ResilientSourceClient).
"""

from __future__ import annotations

from fastapi import Request


def get_redis(request: Request):
    """Liefert den per Lifespan gesetzten Redis-Client aus dem App-State."""
    return request.app.state.redis


def get_http_client(request: Request):
    """Liefert den per Lifespan gesetzten, gepoolten httpx-AsyncClient (RES-01)."""
    return request.app.state.http


def get_resilient_client(request: Request):
    """Liefert den prozessweiten ResilientSourceClient (Fassade RES-01..05).

    Der Client wird einmalig im Lifespan an ``app.state.resilient_client``
    abgelegt und teilt eine prozessweite ``BreakerRegistry``
    (``app.state.breakers``). So lebt der Breaker-State request-uebergreifend:
    ein in Request A geöffneter Breaker bleibt in Request B offen (RES-04). Die
    Fassade ist die EINE Einstiegsfunktion für alle Quellen-Adapter ab Phase 4.
    """
    return request.app.state.resilient_client
