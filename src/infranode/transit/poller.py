"""Hintergrund-Poller fuer GTFS-RT (Phase 19, Plan 04, RESEARCH Pattern 1).

Der Poller parst den GTFS-RT-Feed (~68 MB) EINMAL je Kadenz und legt die kompakten,
indizierten Updates in Redis ab (``transit/store.store_updates_indexed``). Der
Request-Pfad liest danach NUR aus Redis (kein 68-MB-Parse pro Request, kein
CPU-Spike/OOM auf der 4-GB-Box, T-19-REQPARSE). Der Poller laeuft als langlebiger
asyncio-Task im Lifespan (``main.py`` ``_schedule``/``bg_tasks``), NIE im
Request-Pfad.

Robustheit: eine Iteration, die mit einer Exception scheitert (Upstream down,
Parse-Fehler), darf den Task NICHT crashen - sie wird geloggt (``log.warning``),
und nach ``interval_s`` Sekunden laeuft die naechste Iteration. ``CancelledError``
(Shutdown im Lifespan-finally) wird durchgereicht (sauberes Beenden).
"""

from __future__ import annotations

import asyncio

import structlog

from infranode.adapters.gtfs_rt import fetch_gtfs_rt_feed, parse_trip_updates
from infranode.transit.store import store_rt_source, store_updates_indexed

log = structlog.get_logger()


async def _fetch_with_fallback(
    app, *, source: str, abo_id: str | None
) -> tuple[bytes | None, str | None]:
    """Holt den RT-Feed und faellt von ``mobilithek_delfi`` auf ``gtfs_de`` zurueck.

    Primaerquelle ``mobilithek_delfi`` (DELFI ueber Mobilithek-mTLS): liefert sie
    keine Bytes (no_data/disabled) ODER scheitert sie (Upstream-Fehler), wird der
    keylose gtfs.de-Backup-Feed gezogen ("schalte um und gtfs als backup"). Gibt
    ``(body, used_source)`` zurueck, damit der Read-Pfad die korrekte Attribution
    (DELFI e.V. vs gtfs.de) waehlen kann. Andere Quellen (gtfs_de) ohne Fallback.
    """
    http = app.state.http
    mtls = getattr(app.state, "mobilithek_http", None)
    if source == "mobilithek_delfi":
        try:
            feed = await fetch_gtfs_rt_feed(
                http, mtls, source="mobilithek_delfi", abo_id=abo_id
            )
        except Exception as exc:  # noqa: BLE001 - DELFI-Fehler -> Backup, kein Crash
            log.warning("gtfs_rt_delfi_failed_fallback_gtfs_de", error=str(exc))
            feed = None
        if feed is not None:
            return feed, "mobilithek_delfi"
        # Backup: keyloser gtfs.de-Feed (raise_for_status faengt die Aussenschleife).
        feed = await fetch_gtfs_rt_feed(http, None, source="gtfs_de", abo_id=None)
        return feed, "gtfs_de"

    feed = await fetch_gtfs_rt_feed(http, mtls, source=source, abo_id=abo_id)
    return feed, source


async def gtfs_rt_poller(
    app,
    *,
    interval_s: int = 45,
    source: str,
    abo_id: str | None,
) -> None:
    """Endlosschleife: holt+parst den Feed je Kadenz und legt ihn nach Redis.

    Je Iteration: ``fetch_gtfs_rt_feed`` -> bei ``None`` (no_data/disabled) wird
    der Store uebersprungen; bei ``bytes`` -> ``parse_trip_updates`` ->
    ``store_updates_indexed``. Eine Exception in einer Iteration crasht den Task
    NICHT (``log.warning``, weiter nach ``asyncio.sleep(interval_s)``).
    ``CancelledError`` (Shutdown) wird durchgereicht.
    """
    while True:
        try:
            # Multi-Worker-Guard: bei uvicorn --workers laeuft dieser Poller in
            # JEDEM Worker. Ein per-Tick Redis-Lock (SET NX EX) stellt sicher, dass
            # pro Intervall nur EIN Worker tatsaechlich pollt (kein redundanter
            # Upstream-Fetch). TTL < interval -> laeuft vor dem naechsten Tick ab;
            # faellt der Halter aus, uebernimmt naechsten Tick ein anderer Worker
            # (selbstheilend, kein dauerhafter Leader). Redis-Fehler -> poll
            # trotzdem (Graceful Degradation, nie Crash).
            should_poll = True
            try:
                should_poll = bool(
                    await app.state.redis.set(
                        "lock:gtfs_rt_poll",
                        b"1",
                        nx=True,
                        ex=max(1, interval_s - 5),
                    )
                )
            except Exception:
                should_poll = True
            if should_poll:
                feed, used_source = await _fetch_with_fallback(
                    app, source=source, abo_id=abo_id
                )
                if feed is not None:
                    updates = parse_trip_updates(feed)
                    await store_updates_indexed(app.state.redis, updates, ttl=90)
                    # Provenance des Stands fuer die Read-Pfad-Attribution.
                    await store_rt_source(
                        app.state.redis, used_source or source, ttl=90
                    )
        except asyncio.CancelledError:
            # Shutdown (Lifespan-finally cancelt die bg_tasks): sauber beenden.
            raise
        except Exception as exc:  # noqa: BLE001 - eine Iteration darf nie crashen
            log.warning("gtfs_rt_poll_failed", error=str(exc), source=source)
        await asyncio.sleep(interval_s)


def maybe_start_gtfs_rt_poller(app, settings, schedule) -> None:
    """Startet den Poller-Task NUR bei aktivem Toggle + aufloesbarer Quelle.

    Aufloesbarkeit (RESEARCH Pattern 7):
    - ``enable_gtfs_rt`` muss True sein,
    - Quelle ``gtfs_de``: immer aufloesbar (keylos),
    - Quelle ``mobilithek_delfi``: nur mit mTLS-Client (``app.state.mobilithek_http``)
      UND ``transit_rt_delfi_abo_id`` (Settings-Allowlist, SSRF) - sonst kein Task
      (Graceful Degradation = disabled).

    Bei deaktiviertem Toggle (Default) wird KEIN Task erzeugt (bg_tasks
    unveraendert), der bestehende App-Start bleibt unveraendert.
    """
    if not getattr(settings, "enable_gtfs_rt", False):
        return

    source = getattr(settings, "transit_rt_source", "gtfs_de")
    abo_id = getattr(settings, "transit_rt_delfi_abo_id", None)

    if source == "mobilithek_delfi":
        mobilithek_http = getattr(app.state, "mobilithek_http", None)
        if mobilithek_http is None or not abo_id:
            # Quelle nicht aufloesbar: ohne Cert/Abo kein Pull -> kein Task.
            return

    schedule(gtfs_rt_poller(app, interval_s=45, source=source, abo_id=abo_id))
