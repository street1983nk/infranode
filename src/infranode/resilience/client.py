"""ResilientSourceClient: die zentrale fetch-Fassade (Integration RES-01..05).

Diese Klasse verschmilzt die einzelnen Resilienz-Schichten zu EINER Funktion,
die Phase 4+ pro Quellen-Adapter trivial konsumiert:

- RES-01/05 (Pool + User-Agent): der gepoolte ``httpx.AsyncClient`` aus
  ``app.state.http`` wird durchgereicht; der Quellen-Adapter erhält ihn als
  einzigen I/O-Kanal.
- RES-02/03 (Cache-Aside + SWR + Single-Flight): jeder Read läuft durch
  ``cache_get_or_set`` (genau ein Upstream-Call bei HIT/Single-Flight).
- RES-04 (per-Source-Breaker): die Upstream-Coroutine wird pro Quelle durch den
  ``CircuitBreaker`` der ``BreakerRegistry`` geschützt. Eine tote Quelle trippt
  nur ihren eigenen Breaker und blockiert weder andere Quellen noch die
  Gesamt-Response (T-03-10).

Fallback-Politik (T-03-10/12): fällt der Upstream aus (Breaker OPEN ODER
``httpx.HTTPError``), liefert die Fassade einen vorhandenen (auch abgelaufenen)
Cache-Eintrag als ``STALE-ON-ERROR`` zurück. Existiert kein Cache, liefert sie
``(None, STALE-ON-ERROR)`` statt zu blockieren oder einen Stacktrace zu leaken;
der aufrufende API-Layer (Phase 4) entscheidet, ob daraus ein ``UpstreamError``
(503) wird. ``fetch`` blockiert nie und wirft keinen ungemappten Upstream-Fehler.

``fetch_fn`` ist eine reine parameterlose async-Funktion, die der Quellen-Adapter
liefert (kennt weder Cache noch Breaker). So bleibt der Adapter schlank und die
gesamte Resilienz steckt in dieser Fassade.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx
import orjson
import structlog

from infranode.registry.source_specs import SOURCE_TTL as _REGISTRY_TTL

from ..infra.cache import cache_get_or_set
from ..infra.metrics import incr_cache_status
from .breaker import BreakerOpen, BreakerRegistry
from .types import CacheStatus

log = structlog.get_logger()


async def _last_cache(redis, key: str):
    """Liest den (auch abgelaufenen) Cache-Value bytes-sicher; None bei Miss/Fehler.

    Graceful Degradation (T-03-09): jeder Redis-Fehler -> None statt Raise. Der
    Value-Container ist derselbe wie in ``infra/cache._store`` (payload +
    fresh_until/stale_until); base64-gewrappte bytes werden zurück dekodiert.
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


# Default-Cache-Fenster (fresh_s, stale_s) für Quellen ohne expliziten Registry-
# Eintrag: bisheriges Verhalten (60s fresh, ~120s stale via Pad).
_DEFAULT_TTL: tuple[float, float] = (60.0, 120.0)
# Per-Source-Cache-TTL (fresh_s, stale_s) aus der deklarativen Quellen-Registry
# (registry/source_specs.py). Quellen ohne Eintrag nutzen _DEFAULT_TTL.
_SOURCE_TTL: dict[str, tuple[float, float]] = dict(_REGISTRY_TTL)

# --- Outbound-Limits je Upstream (ToS-Compliance) -----------------------------
# Obergrenze gleichzeitiger Upstream-Calls je Quelle. Geteilte VM-IP -> der
# Wikidata-WDQS-Endpoint erlaubt nur ~5 parallele Queries/IP. Quellen ohne
# Eintrag: unbegrenzt (Verhalten unverändert).
_SOURCE_MAX_CONCURRENCY: dict[str, int] = {"wikidata": 5}
# Mindestabstand (Sekunden) zwischen Upstream-Calls je Quelle (Aggregat-Rate).
# DB-Timetables-ToS: <=60 Aufrufe/Minute -> >=1.0s. Quellen ohne Eintrag: kein
# Limit. Alle InfraNode-Nutzer teilen sich den DB-Key, daher Aggregat begrenzen.
_SOURCE_MIN_INTERVAL_S: dict[str, float] = {"db_timetables": 1.0}

_semaphores: dict[str, asyncio.Semaphore] = {}
_rate_locks: dict[str, asyncio.Lock] = {}
_last_call_monotonic: dict[str, float] = {}


def _source_semaphore(source: str) -> asyncio.Semaphore | None:
    """Lazy per-Source-Semaphore (None = unbegrenzt). Single-Loop-App: prozessweit."""
    limit = _SOURCE_MAX_CONCURRENCY.get(source)
    if limit is None:
        return None
    sem = _semaphores.get(source)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        _semaphores[source] = sem
    return sem


async def _pace(source: str) -> None:
    """Erzwingt den Mindestabstand zwischen Calls einer Quelle (no-op ohne Eintrag)."""
    interval = _SOURCE_MIN_INTERVAL_S.get(source)
    if not interval:
        return
    lock = _rate_locks.get(source)
    if lock is None:
        lock = asyncio.Lock()
        _rate_locks[source] = lock
    async with lock:
        wait = interval - (time.monotonic() - _last_call_monotonic.get(source, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_monotonic[source] = time.monotonic()


async def _run_limited(source: str, fetch_fn: Callable[[], Awaitable]):
    """Fuehrt ``fetch_fn`` unter Per-Source-Concurrency + Mindestabstand aus."""
    sem = _source_semaphore(source)
    if sem is None:
        await _pace(source)
        return await fetch_fn()
    async with sem:
        await _pace(source)
        return await fetch_fn()


class ResilientSourceClient:
    """Fassade: kombiniert Pool + Cache + SWR + Single-Flight + Breaker zu fetch().

    Args:
        http: prozessweiter, gepoolter ``httpx.AsyncClient`` (app.state.http).
        redis: redis.asyncio-kompatibler Client (app.state.redis).
        breakers: prozessweite ``BreakerRegistry`` (app.state.breakers). Default:
            eine frische Registry (Breaker-State lebt dann nur für diese
            Instanz; in der App wird eine geteilte Registry injiziert, damit der
            Breaker-State request-übergreifend lebt).
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
        *,
        store: bool = True,
    ):
        """Hole Daten der Quelle ``source`` unter ``key`` (resilient, nie blockierend).

        Reihenfolge: Cache (HIT/STALE/MISS) um eine Breaker-geschützte
        Upstream-Coroutine. Bei OPEN-Breaker oder Upstream-Fehler -> last-cache-
        Fallback (STALE-ON-ERROR) bzw. ``(None, STALE-ON-ERROR)``.

        Args:
            store: Wenn ``False``, läuft der Call ON-DEMAND: KEIN Redis-Read/Write,
                kein Stale-Fallback, kein SWR-Background-Refresh; nur der
                Breaker-Schutz um den Live-Call bleibt. Für Quellen, deren ToS
                das Spiegeln/Vorhalten verbieten (Tankerkoenig/MTS-K): Daten nur
                live bei Useraktion, nie zwischengespeichert (T-08-CRED-Folge).

        Returns:
            ``(payload, status)``-Tupel (nie None). ``status`` ist ein
            ``CacheStatus``-String (HIT/MISS/STALE/STALE-ON-ERROR).
        """
        breaker = self._breakers.get(source)
        # Optionale Redis-Persistenz des Breaker-States (RedisBreakerRegistry, C-2026):
        # hydrate ZIEHT den prozessübergreifenden State vor der Entscheidung, persist
        # SCHREIBT ihn nach jedem record_*. Duck-Typing -> die schlanke in-memory
        # BreakerRegistry (Tests/Fallback) bleibt völlig unverändert (keine Methoden).
        hydrate = getattr(self._breakers, "hydrate", None)
        persist = getattr(self._breakers, "persist", None)
        if hydrate is not None:
            await hydrate(source, breaker)

        async def refresh():
            # Breaker pro Quelle, aber EIN geteilter Pool (RES-01/04).
            if not breaker.allow_request():
                raise BreakerOpen(source)
            try:
                result = await _run_limited(source, fetch_fn)
            except Exception:
                breaker.record_failure()
                if persist is not None:
                    await persist(source, breaker)
                raise
            breaker.record_success()
            if persist is not None:
                await persist(source, breaker)
            return result

        if not store:
            # ON-DEMAND (kein Redis-Read/Write, kein Stale, kein SWR-Refresh): nur
            # der Live-Call hinter dem Breaker. Anbieter-ToS, die Spiegeln/Vorhalten
            # verbieten (Tankerkoenig/MTS-K), erlauben nur Live-Abruf bei Useraktion.
            try:
                result = await refresh()
                await incr_cache_status(self._redis, CacheStatus.MISS)
                return result, CacheStatus.MISS
            except (BreakerOpen, httpx.HTTPError) as exc:
                log.info(
                    "resilient_fetch_fallback",
                    source=source,
                    key=key,
                    has_stale=False,
                    error=type(exc).__name__,
                )
                await incr_cache_status(self._redis, CacheStatus.STALE_ON_ERROR)
                return None, CacheStatus.STALE_ON_ERROR

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
            # NOCH IM try-Block, damit das except-Verhalten unten unverändert bleibt.
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
            # Auch der Fallback-Pfad zählt am Chokepoint (STALE-ON-ERROR-Bucket).
            await incr_cache_status(self._redis, CacheStatus.STALE_ON_ERROR)
            return stale, CacheStatus.STALE_ON_ERROR
