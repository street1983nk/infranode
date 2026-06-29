"""Redis-persistente Breaker-Registry (RES-04 Upgrade, 2026-06-14).

Die in-process ``BreakerRegistry`` verliert ihren Zustand bei jedem Deploy/
Neustart und teilt ihn nicht zwischen mehreren Uvicorn-Workern: ein in Worker A
oder vor einem Deploy getrippter Breaker startet danach wieder CLOSED und
hammert die kranke Quelle erneut, bis er erneut 5x failt. Diese Unterklasse
spiegelt den Breaker-State je Quelle write-through nach Redis und hydriert ihn
vor jedem Zugriff zurück, sodass OPEN/HALF_OPEN Deploys und Worker-Grenzen
überlebt (der im Code vorgesehene Upgrade-Pfad, breaker.py-Docstring T-03-13).

Wichtig (Uhr): der persistierte ``opened_at`` ist nur prozessübergreifend
sinnvoll, wenn er eine WALL-CLOCK-Zeit ist. Daher injiziert diese Registry
``time.time`` (statt des ``time.monotonic``-Defaults der Basisklasse) in jeden
erzeugten ``CircuitBreaker``; der Cooldown-Vergleich (now - opened_at >= cooldown)
bleibt damit über Prozesse hinweg korrekt.

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

from infranode.registry.source_specs import (
    FRAGILE_SOURCE_COOLDOWN as _REGISTRY_COOLDOWN,
)

from .breaker import BreakerRegistry, BreakerState, CircuitBreaker

log = structlog.get_logger()

# State-Schlüssel je Quelle. Eigener Namespace, getrennt von den Cache-Keys
# (source:{name}:v1:...), damit ein Breaker-State nie mit Nutzdaten kollidiert.
_KEY_PREFIX = "breaker:state:"

# TTL des persistierten States: nach einem Tag ohne jeden Zugriff verfällt der
# Eintrag (eine seit 24h unberührte Quelle startet sauber CLOSED). Ein aktiver
# OPEN-Breaker wird bei jedem record_* neu geschrieben und verlängert die TTL.
_STATE_TTL = 86400

# Per-Source-Cooldown (s) für fragile Upstreams aus der deklarativen Quellen-
# Registry (registry/source_specs.py). Quellen ohne Eintrag behalten 30s.
_FRAGILE_SOURCE_COOLDOWN: dict[str, float] = dict(_REGISTRY_COOLDOWN)


class RedisBreakerRegistry(BreakerRegistry):
    """``BreakerRegistry`` mit write-through-Persistenz des Breaker-States in Redis.

    Args:
        redis: redis.asyncio-kompatibler Client (app.state.redis).
        failure_threshold/cooldown: wie Basisklasse.
        now: injizierbare Uhr; Default ``time.time`` (WALL-CLOCK, prozess-
            übergreifend gültig), NICHT der monotonic-Default der Basisklasse.
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
        Eintrag oder ist er unlesbar, bleibt der in-memory Breaker unverändert
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
            # Defekter Eintrag: ignorieren statt crashen (in-memory bleibt gültig).
            log.debug(
                "breaker_hydrate_parse_failed",
                source=source,
                error=type(exc).__name__,
            )

    async def persist(self, source: str, breaker: CircuitBreaker) -> None:
        """Schreibt den aktuellen Breaker-State write-through nach Redis (best-effort).

        Wird nach jedem record_success/record_failure aufgerufen, damit der nächste
        Worker/der nächste Request den State sieht. Still degradierend.
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
