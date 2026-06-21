"""Rate-Limiting fuer den oeffentlichen MCP-Endpunkt (Security-Haertung 2026-06-21).

Der Remote-MCP-Server (``mcp.infranode.dev/mcp``, streamable-http) lief bis hier
OHNE eigene Drosselung: Caddy reicht 1:1 durch und die slowapi-Limiter der
FastAPI-App greifen nur auf dem API-Pfad, nicht auf dem MCP-Service. Ein Client
konnte den MCP-Endpunkt also ungebremst haemmern (jeder Tool-Call loest zudem
einen API-Aufruf aus, der die Upstream-Last vervielfacht).

Diese Middleware drosselt pro echter Client-IP mit einem In-Memory-Moving-Window
(``limits``-Library, bereits via slowapi vorhanden). In-Memory genuegt, weil der
MCP-Server als EIN Prozess/Container laeuft (kein Multi-Worker-Sharing noetig);
ein Neustart leert die Fenster, was bei einem reinen Schutzlimit unkritisch ist.
Die echte Client-IP kommt wie in der API zuerst aus ``CF-Connecting-IP`` (von
Cloudflare verbindlich gesetzt), dann aus ``X-Forwarded-For[0]``, sonst dem Peer.
"""

from __future__ import annotations

import os

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Default-Budget pro IP fuer den MCP-Endpunkt. Bewusst knapper als das API-IP-
# Budget (ein MCP-Tool-Call ist teurer: er erzeugt einen Upstream-API-Aufruf).
# Per INFRANODE_MCP_RATE_LIMIT (limits-Format "<zahl>/<einheit>") ueberschreibbar.
_DEFAULT_LIMIT = "60/minute"


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
        self._limiter = MovingWindowRateLimiter(MemoryStorage())
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
