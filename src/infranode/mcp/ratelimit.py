"""Rate-Limiting fuer den oeffentlichen MCP-Endpunkt (Security-Haertung 2026-06-21).

Der Remote-MCP-Server (``mcp.infranode.dev/mcp``, streamable-http) lief bis hier
OHNE eigene Drosselung: Caddy reicht 1:1 durch und die slowapi-Limiter der
FastAPI-App greifen nur auf dem API-Pfad, nicht auf dem MCP-Service. Ein Client
konnte den MCP-Endpunkt also ungebremst haemmern (jeder Tool-Call loest zudem
einen API-Aufruf aus, der die Upstream-Last vervielfacht).

Diese Middleware drosselt pro echter Client-IP mit einem Moving-Window
(``limits``-Library, bereits via slowapi vorhanden). Der Storage liegt in REDIS
(``INFRANODE_REDIS_URL``), damit das Budget ueber mehrere MCP-Replicas GETEILT
ist (horizontale Skalierung): liefen N Replicas mit je eigenem In-Memory-Fenster,
ver-N-fachte sich das effektive Limit. Ist Redis nicht erreichbar (z.B. lokaler
stdio-Betrieb ohne Redis), faellt die Middleware auf einen prozesslokalen
In-Memory-Speicher zurueck, damit der Server trotzdem startet (Schutzlimit, kein
harter State). Die echte Client-IP kommt wie in der API zuerst aus
``CF-Connecting-IP`` (von Cloudflare verbindlich gesetzt), dann aus
``X-Forwarded-For[0]``, sonst dem Peer.
"""

from __future__ import annotations

import logging
import os

from limits import parse
from limits.storage import MemoryStorage, storage_from_string
from limits.strategies import MovingWindowRateLimiter
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Default-Budget pro IP fuer den MCP-Endpunkt. Per INFRANODE_MCP_RATE_LIMIT
# (limits-Format "<zahl>/<einheit>") ueberschreibbar. Owner 2026-06-24: von 60 auf
# 240/min angehoben, damit Discovery-Flows (get_city_overview -> mehrere gezielte
# Tool-Calls) fluessig laufen, ohne ans Limit zu stossen (Zielgroesse bis Jahresende
# klar < 1000 Nutzer, daher unkritisch). Der Overview-Snapshot buendelt seine
# Highlights serverseitig in EINEN API-Aufruf (kein Vervielfachen der Upstream-Last)
# und ist parallel + zeitgedeckelt. Bleibt bewusst ein Schutz-Limit gegen Hammering.
_DEFAULT_LIMIT = "240/minute"


def _make_storage():
    """Redis-Storage fuer geteilte Budgets ueber Replicas; Fallback In-Memory.

    storage_from_string verbindet lazy; ``check()`` pingt Redis und gibt bei
    nicht erreichbarem Server False zurueck (wirft nicht). Nur dann der
    prozesslokale Fallback, damit ein versehentlich fehlendes Redis den
    lokalen/stdio-MCP-Server nicht am Start hindert.
    """
    url = os.environ.get("INFRANODE_REDIS_URL", "redis://redis:6379/0")
    try:
        # Kurze Connect-/Read-Timeouts: ohne sie kann check() bei nicht
        # aufloesbarem/erreichbarem Host (lokaler stdio-Betrieb ohne Redis, oder
        # ISP-DNS-Hijack des Compose-Servicenamens "redis") bis zum OS-Default
        # blockieren -> der MCP-Server-Start haengt. So faellt check() schnell auf
        # False und wir nehmen den In-Memory-Fallback. memory:// ignoriert die
        # kwargs (kein Netz), daher unschaedlich.
        storage = storage_from_string(
            url, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        if storage.check():
            return storage
        logger.warning(
            "MCP rate-limit: Redis (%s) nicht erreichbar, In-Memory-Fallback "
            "(pro-Prozess, nicht replica-geteilt).",
            url,
        )
    except Exception as exc:  # noqa: BLE001 - jeder Storage-Init-Fehler -> Fallback
        logger.warning(
            "MCP rate-limit: Redis-Storage-Init fehlgeschlagen (%s), "
            "In-Memory-Fallback: %s",
            url,
            exc,
        )
    return MemoryStorage()


def client_ip(request: Request) -> str:
    """Echte Client-IP: CF-Connecting-IP -> X-Forwarded-For[0] -> Peer.

    Identische Quelle wie ``infranode.api.v1.ratelimit.real_client_ip``; hier
    eigenstaendig gehalten, damit der MCP-Server nicht den FastAPI-/slowapi-Pfad
    importieren muss. Vertrauenswuerdig nur unter der CF-only-Firewall (sonst
    koennte ein Angreifer CF-Connecting-IP faelschen, s. DEPLOYMENT.md Abschnitt 2).
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


class MCPRateLimitMiddleware:
    """ASGI-Middleware: drosselt HTTP-Requests pro Client-IP (Moving Window).

    Reines ASGI (nicht BaseHTTPMiddleware), damit der SSE-/Streaming-Pfad des
    MCP-Transports unangetastet durchlaeuft: bei erlaubten Requests wird ``app``
    direkt mit den Originalen ``receive``/``send`` aufgerufen, der Stream also nie
    gepuffert. Nur der Ablehnungsfall (429) erzeugt eine eigene Antwort.
    """

    def __init__(self, app: ASGIApp, limit: str | None = None) -> None:
        self.app = app
        self._limiter = MovingWindowRateLimiter(_make_storage())
        self._item = parse(
            limit or os.environ.get("INFRANODE_MCP_RATE_LIMIT", _DEFAULT_LIMIT)
        )
        # Fenster in Sekunden fuer den Retry-After-Header.
        self._retry_after = str(self._item.get_expiry())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Lifespan/WebSocket unberuehrt durchreichen.
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        ip = client_ip(request)
        # hit() zaehlt den Request und gibt False zurueck, sobald das Budget
        # erschoepft ist. Namespace "mcp" trennt die Buckets sauber.
        if not self._limiter.hit(self._item, "mcp", ip):
            response = JSONResponse(
                {
                    "error": "rate_limited",
                    "message": "MCP rate limit exceeded.",
                    "hint": "Bitte den Retry-After-Header beachten.",
                },
                status_code=429,
                headers={"Retry-After": self._retry_after},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
