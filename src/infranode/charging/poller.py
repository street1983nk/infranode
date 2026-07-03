"""Hintergrund-Poller für die eRound-Belegungs-Deltas (DATA-42, Stufe 2).

Muster ``transit/poller.py``: langlebiger asyncio-Task im Lifespan
(``main.py`` ``_schedule``/``bg_tasks``), NIE im Request-Pfad. Je Iteration
wird das dynamische eRound-Abo gepullt (Drain-Queue: nur Änderungen seit dem
letzten Pull) und die Deltas werden in Redis akkumuliert
(``charging/store.store_point_statuses``). Der Request-Pfad
(``/cities/{slug}/charging-status``) liest danach NUR aus Redis.

Robustheit: eine scheiternde Iteration (Upstream down, Parse-Fehler) crasht
den Task NICHT (``log.warning``), nach ``interval_s`` läuft die nächste.
``CancelledError`` (Shutdown) wird durchgereicht. Ein per-Tick Redis-Lock
(SET NX EX) verhindert redundante Pulls bei mehreren Workern/Replicas; da der
Feed eine Drain-Queue ist, wäre ein Doppel-Pull kein Fehler (beide akkumulieren
ihre Teilmenge nach Redis), nur unnötiger Upstream-Traffic.
"""

from __future__ import annotations

import asyncio

import structlog

from infranode.adapters.mobilithek_afir import fetch_afir
from infranode.charging.store import store_latest_delta, store_point_statuses

log = structlog.get_logger()

#: Poll-Kadenz: 5 Minuten (Plan-Vorgabe live_5min; der Feed ist minutenfrisch,
#: die Drain-Queue puffert Änderungen zwischen den Pulls verlustfrei).
_INTERVAL_S = 300

_LOCK_KEY = "lock:eround_charging_poll"


async def eround_status_poller(app, *, abo_id: str, interval_s: int = _INTERVAL_S):
    """Endlosschleife: dyn-Abo pullen und Deltas nach Redis akkumulieren."""
    while True:
        try:
            # Multi-Worker-Guard (Muster gtfs_rt_poller): pro Intervall pollt nur
            # ein Worker; Redis-Fehler -> trotzdem pollen (Graceful Degradation).
            should_poll = True
            try:
                should_poll = bool(
                    await app.state.redis.set(
                        _LOCK_KEY, b"1", nx=True, ex=max(1, interval_s - 5)
                    )
                )
            except Exception:
                should_poll = True
            if should_poll:
                raw = await fetch_afir(
                    app.state.mobilithek_http, abo_id=abo_id, slug="eround"
                )
                points = raw.get("points") or []
                if points:
                    written = await store_point_statuses(app.state.redis, points)
                    log.info("eround_status_accumulated", points=written)
                # Snapshot IMMER schreiben (auch leer): der /live-Read-Pfad
                # pullt nie selbst (strikte Entkopplung vom Request-Worker)
                # und braucht einen frischen Stand fuer ok/no_data-Ehrlichkeit.
                await store_latest_delta(app.state.redis, raw)
        except asyncio.CancelledError:
            # Shutdown (Lifespan-finally cancelt die bg_tasks): sauber beenden.
            raise
        except Exception as exc:  # noqa: BLE001 - eine Iteration darf nie crashen
            log.warning("eround_status_poll_failed", error=type(exc).__name__)
        await asyncio.sleep(interval_s)


def maybe_start_eround_poller(app, settings, schedule) -> None:
    """Startet den Poller NUR bei aktivem Toggle + Cert + Abo-ID (Muster GTFS-RT).

    Ohne ``enable_eround_charging`` ODER ohne mTLS-Client
    (``app.state.mobilithek_http``) ODER ohne ``eround_charging_abo_id`` wird
    KEIN Task erzeugt (Graceful Degradation = die Route liefert ``disabled``/
    ``no_data``, der App-Start bleibt unverändert).
    """
    if not getattr(settings, "enable_eround_charging", False):
        return
    abo_id = getattr(settings, "eround_charging_abo_id", None)
    if getattr(app.state, "mobilithek_http", None) is None or not abo_id:
        return

    schedule(eround_status_poller(app, abo_id=abo_id))
