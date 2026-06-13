"""Redis-Connection-Lifecycle (Pitfall 6).

Der Pool wird lazy erstellt (kein Connect beim Boot), damit ``docker compose
up`` nicht an einer Start-Race scheitert. Ein Ping erfolgt nur im
/health-Handler, nicht beim Lifespan-Start. Verwendet ``redis.asyncio``
(nicht das tote ``aioredis``).
"""

from __future__ import annotations

import redis.asyncio as aioredis


def create_redis_pool(url: str) -> aioredis.Redis:
    """Erstellt einen lazy Redis-Client mit Connection-Pool (kein Boot-Connect)."""
    return aioredis.from_url(url, encoding="utf-8", decode_responses=True)


async def close_redis_pool(client: aioredis.Redis | None) -> None:
    """Schliesst den Redis-Client samt Pool sauber."""
    if client is not None:
        await client.aclose()
