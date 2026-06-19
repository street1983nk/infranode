"""ResilientSourceClient: die zentrale fetch-Fassade (Integration RES-01..05).

Diese Klasse verschmilzt die einzelnen Resilienz-Schichten zu EINER Funktion,
die Phase 4+ pro Quellen-Adapter trivial konsumiert:

- RES-01/05 (Pool + User-Agent): der gepoolte ``httpx.AsyncClient`` aus
  ``app.state.http`` wird durchgereicht; der Quellen-Adapter erhaelt ihn als
  einzigen I/O-Kanal.
- RES-02/03 (Cache-Aside + SWR + Single-Flight): jeder Read laeuft durch
  ``cache_get_or_set`` (genau ein Upstream-Call bei HIT/Single-Flight).
- RES-04 (per-Source-Breaker): die Upstream-Coroutine wird pro Quelle durch den
  ``CircuitBreaker`` der ``BreakerRegistry`` geschuetzt. Eine tote Quelle trippt
  nur ihren eigenen Breaker und blockiert weder andere Quellen noch die
  Gesamt-Response (T-03-10).

Fallback-Politik (T-03-10/12): faellt der Upstream aus (Breaker OPEN ODER
``httpx.HTTPError``), liefert die Fassade einen vorhandenen (auch abgelaufenen)
Cache-Eintrag als ``STALE-ON-ERROR`` zurueck. Existiert kein Cache, liefert sie
``(None, STALE-ON-ERROR)`` statt zu blockieren oder einen Stacktrace zu leaken;
der aufrufende API-Layer (Phase 4) entscheidet, ob daraus ein ``UpstreamError``
(503) wird. ``fetch`` blockiert nie und wirft keinen ungemappten Upstream-Fehler.

``fetch_fn`` ist eine reine parameterlose async-Funktion, die der Quellen-Adapter
liefert (kennt weder Cache noch Breaker). So bleibt der Adapter schlank und die
gesamte Resilienz steckt in dieser Fassade.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import orjson
import structlog

from ..infra.cache import cache_get_or_set
from ..infra.metrics import incr_cache_status
from .breaker import BreakerOpen, BreakerRegistry
from .types import CacheStatus

log = structlog.get_logger()


async def _last_cache(redis, key: str):
    """Liest den (auch abgelaufenen) Cache-Value bytes-sicher; None bei Miss/Fehler.

    Graceful Degradation (T-03-09): jeder Redis-Fehler -> None statt Raise. Der
    Value-Container ist derselbe wie in ``infra/cache._store`` (payload +
    fresh_until/stale_until); base64-gewrappte bytes werden zurueck dekodiert.
    """
    try:
        raw = await redis.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            raw = raw.encode()
        value = orjson.loads(raw)
    except Exception:
        return None
    payload = value.get("payload") if isinstance(value, dict) else None
    if isinstance(payload, dict) and "__b64__" in payload and len(payload) == 1:
        import base64

        return base64.b64decode(payload["__b64__"])
    return payload


# Per-Source-Cache-TTL (fresh_s, stale_s). Quellen mit langsam wechselnden
# Live-Daten bekommen ein langes Fresh-Fenster (weniger Upstream-Calls) und ein
# sehr langes Stale-Fenster (Stale-Serving statt 503, wenn der Upstream 429t/down
# ist). Default = bisheriges Verhalten (60s fresh, ~120s stale via Pad).
_DEFAULT_TTL: tuple[float, float] = (60.0, 120.0)
_SOURCE_TTL: dict[str, tuple[float, float]] = {
    "openaq": (900.0, 21600.0),
    "pegelonline": (300.0, 7200.0),
    "dwd": (600.0, 7200.0),
    # POIs (OSM/Overpass) aendern sich praktisch nie -> sehr lange TTL, damit das
    # stark rate-limitierte oeffentliche Overpass nur selten abgefragt wird.
    "overpass": (86400.0, 604800.0),
    # GENESIS-Regionalstatistik liefert JAHRESWERTE und ist sehr traege (~25s je
    # Abruf). Sehr lange TTL (24h frisch / 30d stale), damit der taegliche
    # Akkrual-Timer den Cache dauerhaft warm haelt und Clients praktisch nie den
    # kalten Abruf treffen (sonst "sende Anfrage..." sekundenlang).
    "genesis": (86400.0, 2592000.0),
    # StaDa-Bahnhofskatalog ist Stammdaten (aendert sich praktisch nie) und wird
    # als EINE bundesweite Liste geholt + je Stadt gefiltert -> sehr lange TTL
    # (24h frisch / 30d stale), ein Abruf bedient alle 84 Staedte aus dem Cache.
    "stada": (86400.0, 2592000.0),
}


class ResilientSourceClient:
    """Fassade: kombiniert Pool + Cache + SWR + Single-Flight + Breaker zu fetch().

    Args:
        http: prozessweiter, gepoolter ``httpx.AsyncClient`` (app.state.http).
        redis: redis.asyncio-kompatibler Client (app.state.redis).
        breakers: prozessweite ``BreakerRegistry`` (app.state.breakers). Default:
            eine frische Registry (Breaker-State lebt dann nur fuer diese
            Instanz; in der App wird eine geteilte Registry injiziert, damit der
            Breaker-State request-uebergreifend lebt).
        schedule: plant die SWR-Background-Refresh-Coroutine (Default: der
            asyncio-Task-Halter aus ``cache_get_or_set``).
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        redis,
        breakers: BreakerRegistry | None = None,
        schedule: Callable[[Awaitable], None] | None = None,
    ) -> None:
        self._http = http
        self._redis = redis
        self._breakers = breakers if breakers is not None else BreakerRegistry()
        self._schedule = schedule

    async def fetch(
        self,
        source: str,
        key: str,
        fetch_fn: Callable[[], Awaitable],
    ):
        """Hole Daten der Quelle ``source`` unter ``key`` (resilient, nie blockierend).

        Reihenfolge: Cache (HIT/STALE/MISS) um eine Breaker-geschuetzte
        Upstream-Coroutine. Bei OPEN-Breaker oder Upstream-Fehler -> last-cache-
        Fallback (STALE-ON-ERROR) bzw. ``(None, STALE-ON-ERROR)``.

        Returns:
            ``(payload, status)``-Tupel (nie None). ``status`` ist ein
            ``CacheStatus``-String (HIT/MISS/STALE/STALE-ON-ERROR).
        """
        breaker = self._breakers.get(source)
        # Optionale Redis-Persistenz des Breaker-States (RedisBreakerRegistry, C-2026):
        # hydrate ZIEHT den prozessuebergreifenden State vor der Entscheidung, persist
        # SCHREIBT ihn nach jedem record_*. Duck-Typing -> die schlanke in-memory
        # BreakerRegistry (Tests/Fallback) bleibt voellig unveraendert (keine Methoden).
        hydrate = getattr(self._breakers, "hydrate", None)
        persist = getattr(self._breakers, "persist", None)
        if hydrate is not None:
            await hydrate(source, breaker)

        async def refresh():
            # Breaker pro Quelle, aber EIN geteilter Pool (RES-01/04).
            if not breaker.allow_request():
                raise BreakerOpen(source)
            try:
                result = await fetch_fn()
            except Exception:
                breaker.record_failure()
                if persist is not None:
                    await persist(source, breaker)
                raise
            breaker.record_success()
            if persist is not None:
                await persist(source, breaker)
            return result

        try:
            ttl_fresh, ttl_stale = _SOURCE_TTL.get(source, _DEFAULT_TTL)
            result = await cache_get_or_set(
                self._redis,
                key,
                ttl=ttl_fresh,
                ttl_stale=ttl_stale,
                fetch=refresh,
                schedule=self._schedule,
            )
            # Cache-Status-Counter am EINZIGEN Chokepoint (OPS-02). result[1] ist
            # der rohe Status-str (HIT/MISS/STALE); incr_cache_status ist intern
            # try/except-gekapselt (13-01) und kann den fetch-Pfad nie blockieren.
            # NOCH IM try-Block, damit das except-Verhalten unten unveraendert bleibt.
            await incr_cache_status(self._redis, result[1])
            return result
        except (BreakerOpen, httpx.HTTPError) as exc:
            # Upstream tot ODER Breaker offen: last-cache-Fallback statt Block.
            stale = await _last_cache(self._redis, key)
            log.info(
                "resilient_fetch_fallback",
                source=source,
                key=key,
                has_stale=stale is not None,
                error=type(exc).__name__,
            )
            # Auch der Fallback-Pfad zaehlt am Chokepoint (STALE-ON-ERROR-Bucket).
            await incr_cache_status(self._redis, CacheStatus.STALE_ON_ERROR)
            return stale, CacheStatus.STALE_ON_ERROR
