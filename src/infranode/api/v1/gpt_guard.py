"""Rate-Limit für ChatGPT-GPT-Action-Traffic (Muster: mcp/ratelimit.py).

Warum ein EIGENES Limit: ALLE Nutzer des InfraNode-GPTs kommen serverseitig
über WENIGE OpenAI-Egress-IPs (openai.com/chatgpt-actions.json). Damit ein
einzelner Power-Nutzer nicht das gemeinsame IP-Budget aller ChatGPT-Nutzer
leert, stehen die OpenAI-Ranges auf der INFRANODE_RATELIMIT_ALLOWLIST
(Bypass von slowapi-IP-Limit + AbuseGuard, gleiches Muster wie
Anthropic-Egress beim MCP-Server). Dieses Modul ist der BACKSTOP dazu: ein
Moving-Window-Limit je GPT-NUTZER (ephemere OpenAI-Nutzer-Kennung, Fallback
Konversation/GPT/IP) mit demselben Default wie der MCP-Endpunkt (480/min,
INFRANODE_LIMIT_GPT). Storage in Redis (über Worker geteilt), Fallback
In-Memory wie beim MCP-Limiter.

Spoofing: Die OpenAI-Header sind fälschbar, aber ein Spoofer ohne
allowlistete IP unterliegt weiterhin dem normalen IP-Limit; dieses Limit
kommt nur ZUSÄTZLICH dazu (kein Bypass-Vektor, s. infra/gpt_actions.py).
"""

from __future__ import annotations

import logging

from limits import parse
from limits.storage import MemoryStorage, storage_from_string
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from infranode.api.v1.ratelimit import real_client_ip
from infranode.config import Settings
from infranode.infra.gpt_actions import gpt_rate_ident, is_gpt_action

logger = logging.getLogger(__name__)


def _make_storage(settings: Settings):
    """Redis-Storage (über Worker geteilt); Fallback In-Memory, s. mcp/ratelimit."""
    uri = settings.limit_storage_uri or settings.redis_url
    try:
        # Kurze Timeouts: check() darf bei nicht erreichbarem Redis nicht bis zum
        # OS-Default blockieren (lokaler Start ohne Redis), sonst hängt der
        # App-Start statt auf In-Memory zu fallen. memory:// ignoriert die kwargs.
        storage = storage_from_string(
            uri, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        if storage.check():
            return storage
        logger.warning(
            "GPT-Guard: Redis (%s) nicht erreichbar, In-Memory-Fallback "
            "(pro-Prozess, nicht worker-geteilt).",
            uri,
        )
    except Exception as exc:  # noqa: BLE001 - jeder Storage-Init-Fehler -> Fallback
        logger.warning(
            "GPT-Guard: Redis-Storage-Init fehlgeschlagen (%s): %s", uri, exc
        )
    return MemoryStorage()


class GPTActionLimitMiddleware(BaseHTTPMiddleware):
    """Moving-Window-Limit je GPT-Nutzer; feuert NUR bei GPT-Action-Requests."""

    def __init__(self, app, limit: str | None = None) -> None:  # noqa: ANN001 - Starlette-App
        super().__init__(app)
        s = Settings()
        effective = limit if limit is not None else s.limit_gpt
        self._item = parse(effective) if effective else None
        self._limiter = (
            MovingWindowRateLimiter(_make_storage(s)) if self._item else None
        )
        self._retry_after = str(self._item.get_expiry()) if self._item else "60"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Nur echte Datenrouten drosseln; Health/Docs/Admin bleiben unberührt.
        if (
            self._limiter is None
            or not request.url.path.startswith("/api/v1/")
            or not is_gpt_action(request.headers)
        ):
            return await call_next(request)

        ident = gpt_rate_ident(request.headers, real_client_ip(request))
        if not self._limiter.hit(self._item, "gpt", ident):
            # Lokaler Import wie im AbuseGuard (vermeidet Zyklen beim Modul-Load).
            from infranode.api.errors import _envelope

            response = _envelope(
                429,
                "rate_limited",
                "GPT action rate limit exceeded.",
                hint=(
                    "Zu viele Anfragen aus dieser ChatGPT-Sitzung. Bitte den "
                    "Retry-After-Header beachten."
                ),
            )
            response.headers["Retry-After"] = self._retry_after
            return response

        return await call_next(request)
