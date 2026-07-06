"""Redis-Connection-Lifecycle (Pitfall 6).

Der Pool wird lazy erstellt (kein Connect beim Boot), damit ``docker compose
up`` nicht an einer Start-Race scheitert. Ein Ping erfolgt nur im
/health-Handler, nicht beim Lifespan-Start. Verwendet ``redis.asyncio``
(nicht das tote ``aioredis``).
"""

from __future__ import annotations

import redis.asyncio as aioredis


def create_redis_pool(
    url: str, *, max_connections: int | None = None
) -> aioredis.Redis:
    """Erstellt einen lazy Redis-Client mit Connection-Pool (kein Boot-Connect).

    ``max_connections`` deckelt (quick-260704-ust) das bisher unbegrenzte
    Socket-Wachstum des Pools; ``from_url`` reicht den kwarg an den
    ConnectionPool durch. Entscheidung: Standard-ConnectionPool mit grosszuegigem
    Cap statt BlockingConnectionPool. Der Cap soll DECKELN, nicht drosseln (der
    Normalbetrieb nutzt eine Handvoll Verbindungen, ein Treffer ist bereits eine
    Anomalie): ein harter ConnectionError des Standard-Pools faellt sauber in die
    bestehende Graceful-Degradation/503-Behandlung samt der bereits kurzen
    Redis-Socket-Timeouts. Ein BlockingConnectionPool wuerde stattdessen
    Warteschlangen von Acquire-Waitern aufbauen und damit Backpressure zurueck in
    den Event-Loop schieben, also genau den Fehlermodus, den wir anderswo
    vermeiden. Falls spaeter unter Normalbursts harte Fehler auftreten, mit
    BlockingConnectionPool + kurzem Timeout nachziehen.
    """
    kwargs: dict = {"encoding": "utf-8", "decode_responses": True}
    if max_connections is not None:
        kwargs["max_connections"] = max_connections
    return aioredis.from_url(url, **kwargs)


async def close_redis_pool(client: aioredis.Redis | None) -> None:
    """Schliesst den Redis-Client samt Pool sauber."""
    if client is not None:
        await client.aclose()
