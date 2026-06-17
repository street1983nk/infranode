"""Redis-persistente Breaker-Registry (RES-04 Upgrade, 2026-06-14).

Die in-process ``BreakerRegistry`` verliert ihren Zustand bei jedem Deploy/
Neustart und teilt ihn nicht zwischen mehreren Uvicorn-Workern: ein in Worker A
oder vor einem Deploy getrippter Breaker startet danach wieder CLOSED und
hammert die kranke Quelle erneut, bis er erneut 5x failt. Diese Unterklasse
spiegelt den Breaker-State je Quelle write-through nach Redis und hydriert ihn
vor jedem Zugriff zurueck, sodass OPEN/HALF_OPEN Deploys und Worker-Grenzen
ueberlebt (der im Code vorgesehene Upgrade-Pfad, breaker.py-Docstring T-03-13).

Wichtig (Uhr): der persistierte ``opened_at`` ist nur prozessuebergreifend
sinnvoll, wenn er eine WALL-CLOCK-Zeit ist. Daher injiziert diese Registry
``time.time`` (statt des ``time.monotonic``-Defaults der Basisklasse) in jeden
erzeugten ``CircuitBreaker``; der Cooldown-Vergleich (now - opened_at >= cooldown)
bleibt damit ueber Prozesse hinweg korrekt.

Graceful Degradation (RES-Kernprinzip): jeder Redis-Fehler in hydrate/persist
degradiert still zum reinen in-memory-Verhalten (nur ``type(exc).__name__``
geloggt, nie ``str(exc)``). Der Breaker funktioniert also auch ohne Redis weiter,
nur eben wieder prozess-lokal.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import orjson
import structlog

from .breaker import BreakerRegistry, BreakerState, CircuitBreaker

log = structlog.get_logger()

# State-Schluessel je Quelle. Eigener Namespace, getrennt von den Cache-Keys
# (source:{name}:v1:...), damit ein Breaker-State nie mit Nutzdaten kollidiert.
_KEY_PREFIX = "breaker:state:"

# TTL des persistierten States: nach einem Tag ohne jeden Zugriff verfaellt der
# Eintrag (eine seit 24h unberuehrte Quelle startet sauber CLOSED). Ein aktiver
# OPEN-Breaker wird bei jedem record_* neu geschrieben und verlaengert die TTL.
_STATE_TTL = 86400

# Per-Source-Cooldown (Sekunden) fuer fragile/zeitweise gestoerte Upstreams
# (Selbstheilung statt manuellem Toggle, 2026-06-14). Der OPEN-Breaker dieser
# Quellen probt den kranken Upstream nur alle N Sekunden EINMAL (HALF_OPEN-Probe)
# statt nach dem 30s-Default: wenig Fehler-Laerm waehrend einer laengeren Stoerung,
# aber garantierte automatische Erholung, sobald der Upstream zurueck ist. So muss
# eine Behoerden-API mit Wartungsfenstern (z.B. api.hamburg.de) NICHT mehr von Hand
# per enable_*-Toggle abgeschaltet werden. Quellen ohne Eintrag behalten 30s.
_FRAGILE_SOURCE_COOLDOWN: dict[str, float] = {
    "hamburg_verkehrslage": 1800.0,  # api.hamburg.de hatte Wartungs-/Stoerfenster
    "hamburg_baustellen": 1800.0,
    "uba": 900.0,  # UBA-Upstream zickt periodisch (503), erholt sich langsam
    "openaq": 900.0,
    "pegelonline": 600.0,
}


class RedisBreakerRegistry(BreakerRegistry):
    """``BreakerRegistry`` mit write-through-Persistenz des Breaker-States in Redis.

    Args:
        redis: redis.asyncio-kompatibler Client (app.state.redis).
        failure_threshold/cooldown: wie Basisklasse.
        now: injizierbare Uhr; Default ``time.time`` (WALL-CLOCK, prozess-
            uebergreifend gueltig), NICHT der monotonic-Default der Basisklasse.
    """

    def __init__(
        self,
        redis,
        failure_threshold: int = 5,
        cooldown: float = 30.0,
        *,
        now: Callable[[], float] = time.time,
        cooldowns: dict[str, float] | None = None,
    ) -> None:
        super().__init__(
            failure_threshold=failure_threshold,
            cooldown=cooldown,
            now=now,
            cooldowns=cooldowns if cooldowns is not None else _FRAGILE_SOURCE_COOLDOWN,
        )
        self._redis = redis

    @staticmethod
    def _key(source: str) -> str:
        return f"{_KEY_PREFIX}{source}"

    async def hydrate(self, source: str, breaker: CircuitBreaker) -> None:
        """Laedt den persistierten State aus Redis in den in-memory Breaker.

        Redis ist die Quelle der Wahrheit (Multi-Worker-Konvergenz). Fehlt der
        Eintrag oder ist er unlesbar, bleibt der in-memory Breaker unveraendert
        (frischer Worker -> CLOSED). Still degradierend bei jedem Redis-Fehler.
        """
        try:
            raw = await self._redis.get(self._key(source))
        except Exception as exc:  # noqa: BLE001 - Redis-Fehler -> in-memory-Fallback
            log.debug("breaker_hydrate_failed", source=source, error=type(exc).__name__)
            return
        if raw is None:
            return
        try:
            if isinstance(raw, str):
                raw = raw.encode()
            data = orjson.loads(raw)
            breaker.state = BreakerState(data["state"])
            breaker.opened_at = data["opened_at"]
            breaker.failure_count = int(data["failure_count"])
        except (ValueError, KeyError, TypeError) as exc:
            # Defekter Eintrag: ignorieren statt crashen (in-memory bleibt gueltig).
            log.debug(
                "breaker_hydrate_parse_failed",
                source=source,
                error=type(exc).__name__,
            )

    async def persist(self, source: str, breaker: CircuitBreaker) -> None:
        """Schreibt den aktuellen Breaker-State write-through nach Redis (best-effort).

        Wird nach jedem record_success/record_failure aufgerufen, damit der naechste
        Worker/der naechste Request den State sieht. Still degradierend.
        """
        payload = orjson.dumps(
            {
                "state": breaker.state.value,
                "opened_at": breaker.opened_at,
                "failure_count": breaker.failure_count,
            }
        )
        try:
            await self._redis.set(self._key(source), payload, ex=_STATE_TTL)
        except Exception as exc:  # noqa: BLE001 - Persist-Verlust ist nicht fatal
            log.debug("breaker_persist_failed", source=source, error=type(exc).__name__)
