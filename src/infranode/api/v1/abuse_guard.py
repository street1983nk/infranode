"""Abuse-Guard gegen VERTEILTE Bots (Scraping-Haertung).

Das slowapi-IP-Limit (``ratelimit.py``, 120/min + 3000/h pro IP) bremst eine
EINZELNE IP. Ein Botnet oder Cloud-Range mit vielen IPs umgeht es. Diese
Middleware ergaenzt zwei billige, fruehe Schutzschichten VOR dem feinen IP-Limit:

1. **Aggregiertes Subnetz-Limit** pro /24 (IPv4) bzw. /64 (IPv6): bremst, wenn aus
   EINEM Subnetz untypisch viel Verkehr kommt. Bewusst hoch (Default 1200/min =
   ~10x das IP-Burst), damit legitime NAT-/Campus-Nutzer hinter einer gemeinsamen
   IP nicht getroffen werden. Storage in Redis (ueber Replicas geteilt; Fallback
   In-Memory, falls Redis nicht erreichbar) wie beim MCP-Limiter.
2. **Optionaler Cloudflare-Bot-Score-Block**: lehnt Anfragen mit ``cf-bot-score``
   unter einem Schwellwert (``bot_score_min``, 0 = aus) mit 403 ab. Der Header
   existiert nur mit Cloudflare Bot Management/Enterprise; bei Free/Pro fehlt er,
   dann ist der Check ein No-op-Hook, der automatisch wirksam wird, sobald Scores
   verfuegbar sind.

Die echte Client-IP kommt aus ``real_client_ip`` (CF-Connecting-IP -> XFF[0] ->
Peer), identisch zum slowapi-Limiter (Vertrauen unter der CF-only-Firewall).
"""

from __future__ import annotations

import ipaddress
import logging

from limits import parse
from limits.storage import MemoryStorage, storage_from_string
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from infranode.api.v1.ratelimit import real_client_ip
from infranode.config import Settings

logger = logging.getLogger(__name__)


def subnet_of(ip_str: str, v4_prefix: int, v6_prefix: int) -> str:
    """Subnetz-Schluessel der IP (/v4_prefix bzw. /v6_prefix); IP selbst bei Fehler."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return ip_str
    prefix = v4_prefix if isinstance(ip, ipaddress.IPv4Address) else v6_prefix
    return str(ipaddress.ip_network(f"{ip_str}/{prefix}", strict=False))


def _make_storage(settings: Settings):
    """Redis-Storage (ueber Replicas geteilt); Fallback In-Memory, s. mcp/ratelimit."""
    uri = settings.limit_storage_uri or settings.redis_url
    try:
        # Kurze Connect-/Read-Timeouts: sonst kann check() bei nicht erreichbarem
        # Redis (lokaler Start ohne Redis, DNS-Hijack des Compose-Servicenamens)
        # bis zum OS-Default blockieren -> App-Start haengt, statt auf den
        # In-Memory-Fallback zu fallen. memory:// ignoriert die kwargs (kein Netz).
        storage = storage_from_string(
            uri, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        if storage.check():
            return storage
        logger.warning(
            "AbuseGuard: Redis (%s) nicht erreichbar, In-Memory-Fallback "
            "(pro-Prozess, nicht replica-geteilt).",
            uri,
        )
    except Exception as exc:  # noqa: BLE001 - jeder Storage-Init-Fehler -> Fallback
        logger.warning(
            "AbuseGuard: Redis-Storage-Init fehlgeschlagen (%s): %s", uri, exc
        )
    return MemoryStorage()


class AbuseGuardMiddleware(BaseHTTPMiddleware):
    """Subnetz-Rate-Limit + optionaler CF-Bot-Score-Block (laeuft vor dem IP-Limit)."""

    def __init__(self, app) -> None:  # noqa: ANN001 - Starlette-App
        super().__init__(app)
        s = Settings()
        self._bot_score_min = s.bot_score_min
        self._v4 = s.subnet_ipv4_prefix
        self._v6 = s.subnet_ipv6_prefix
        self._item = parse(s.limit_subnet) if s.limit_subnet else None
        self._limiter = (
            MovingWindowRateLimiter(_make_storage(s)) if self._item else None
        )
        self._retry_after = str(self._item.get_expiry()) if self._item else "60"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        from infranode.api.errors import _envelope

        # 1. Optionaler Bot-Score-Block (No-op ohne cf-bot-score-Header).
        if self._bot_score_min > 0:
            raw = request.headers.get("cf-bot-score")
            if raw:
                try:
                    score: int | None = int(raw)
                except ValueError:
                    score = None
                if score is not None and score < self._bot_score_min:
                    return _envelope(
                        403,
                        "bot_blocked",
                        "Request blocked by bot protection.",
                        hint="Automatisierter Zugriff erkannt (niedriger Bot-Score).",
                    )

        # 2. Aggregiertes Subnetz-Limit gegen verteilte Bots.
        if self._limiter is not None:
            net = subnet_of(real_client_ip(request), self._v4, self._v6)
            if not self._limiter.hit(self._item, "subnet", net):
                response = _envelope(
                    429,
                    "rate_limited",
                    "Subnet rate limit exceeded.",
                    hint=(
                        "Zu viele Anfragen aus diesem Netzbereich. Bitte den "
                        "Retry-After-Header beachten."
                    ),
                )
                response.headers["Retry-After"] = self._retry_after
                return response

        return await call_next(request)
