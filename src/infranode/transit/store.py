"""Redis-Store für kompakte, indizierte GTFS-RT-Updates (Phase 19, Plan 04).

Schreibt NUR die kompakten, vom Adapter geparsten Trip-Update-dicts in Redis,
NIE den rohen 68-MB-Feed (Anti-Pattern, RESEARCH Pitfall 1: ein roher Feed-Body
in Redis sprengt den Speicher der 4-GB-Box und macht jeden Lese-Pfad teuer). Der
Hintergrund-Poller (``transit/poller.py``) parst den Feed EINMAL je Kadenz und
ruft ``store_updates_indexed``; der Request-Pfad (``api/v1/live.py``) liest dann
NUR über die Lese-Helfer (kein Parse im Request, T-19-REQPARSE).

Key-Layout (versioniert mit ``v1``-Präfix, analog ``infra/cache.build_cache_key``,
T-19-CACHEPOISON: trip_id/stop_id/route_id sind vom Aufrufer validiert, nie ein
roher User-String):
- ``transit_rt:v1:{trip_id}``        -> orjson-serialisiertes Update-dict (SET ex)
- ``transit_rt:idx:stop:{stop_id}``  -> Set der trip_ids, die diesen Halt bedienen
- ``transit_rt:idx:route:{route_id}``-> Set der trip_ids dieser Linie

Alle Keys tragen eine TTL: ein neuer Poller-Lauf überschreibt frische Daten, und
fällt der Poller aus, verfallen veraltete Updates automatisch (nur aktuellster
Stand, CONTEXT LOCKED). KEIN Archiv-Write (Tier B, T-19-ARCHIVE): reine
Live-Daten werden NIE in das Tier-A-Archiv geschrieben.
"""

from __future__ import annotations

import orjson

# Versionierte Key-Präfixe (RESEARCH Architektur-Diagramm). Ein Schema-Wechsel
# kann v1 -> v2 ziehen, ohne Fremd-Keys flushen zu müssen.
_TRIP_PREFIX = "transit_rt:v1:"
_STOP_IDX_PREFIX = "transit_rt:idx:stop:"
_ROUTE_IDX_PREFIX = "transit_rt:idx:route:"
# Provenance des aktuell in Redis liegenden RT-Stands (DATA-34/Mobilithek-Switch):
# welcher Feed hat die letzten Updates geliefert ("mobilithek_delfi" Primär ODER
# "gtfs_de" Backup-Fallback). Der Read-Pfad wählt daraus die korrekte Attribution.
_SOURCE_KEY = "transit_rt:source"


def _trip_key(trip_id: str) -> str:
    return f"{_TRIP_PREFIX}{trip_id}"


def _stop_idx_key(stop_id: str) -> str:
    return f"{_STOP_IDX_PREFIX}{stop_id}"


def _route_idx_key(route_id: str) -> str:
    return f"{_ROUTE_IDX_PREFIX}{route_id}"


async def store_updates_indexed(
    redis, updates, *, ttl: int = 90, trip_route_index: dict | None = None
) -> None:
    """Schreibt kompakte Trip-Updates indiziert in Redis (NIE den rohen Feed).

    Je Update: ``transit_rt:v1:{trip_id}`` als orjson-Wert (SET mit ex=ttl) plus
    die Sekundär-Indizes ``idx:stop:{stop_id}`` (je Halt) und
    ``idx:route:{route_id}`` (falls route_id vorhanden) als Set der betroffenen
    trip_ids, ebenfalls mit TTL (via expire). NUR kompakte dicts; der rohe
    Feed-Body wird hier bewusst nie gespeichert (Anti-Pattern).

    Audit-Fix K7 (2026-06-29): Im echten gtfs.de-Feed ist ``trip.route_id``
    durchgehend leer, sodass der ``idx:route:``-Index nie befüllt wurde und
    ``live_transit_route_status`` IMMER ``no_data`` lieferte. Mit
    ``trip_route_index`` (``{trip_id: route_id}`` aus der statischen GTFS, vom
    Poller via ``resolver.build_trip_route_index`` gebaut) wird eine fehlende
    route_id über die ``trip_id`` aufgelöst, BEVOR indiziert wird. Die
    aufgelöste route_id wird auch ins gespeicherte Update geschrieben, damit der
    Read-Pfad sie sieht. Ist der Index leer/die trip_id unbekannt, bleibt es
    ehrlich ohne Index (no_data für diesen Trip), aber ohne Crash.
    """
    for update in updates:
        trip_id = update.get("trip_id")
        if not trip_id:
            continue

        route_id = update.get("route_id")
        # Audit-Fix K7: leere route_id aus der statischen GTFS auflösen.
        if not route_id and trip_route_index:
            resolved = trip_route_index.get(trip_id)
            if resolved:
                route_id = resolved
                update["route_id"] = resolved

        # Kompaktes dict orjson-serialisiert (NIE der rohe Feed-Body).
        await redis.set(_trip_key(trip_id), orjson.dumps(update), ex=ttl)

        if route_id:
            route_key = _route_idx_key(route_id)
            await redis.sadd(route_key, trip_id)
            await redis.expire(route_key, ttl)

        for stu in update.get("stop_time_updates", []) or []:
            stop_id = stu.get("stop_id")
            if not stop_id:
                continue
            stop_key = _stop_idx_key(stop_id)
            await redis.sadd(stop_key, trip_id)
            await redis.expire(stop_key, ttl)


async def store_rt_source(redis, source: str, *, ttl: int = 90) -> None:
    """Merkt die Quelle des aktuellen RT-Stands (Provenance für die Attribution)."""
    await redis.set(_SOURCE_KEY, source, ex=ttl)


async def read_rt_source(redis) -> str | None:
    """Liest die Provenance des aktuellen RT-Stands (oder ``None`` bei Miss)."""
    raw = await redis.get(_SOURCE_KEY)
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else str(raw)


async def get_trip_update(redis, trip_id: str) -> dict | None:
    """Liest das kompakte Update einer ``trip_id`` (oder ``None`` bei Miss)."""
    raw = await redis.get(_trip_key(trip_id))
    if raw is None:
        return None
    return orjson.loads(raw)


async def trips_for_stop(redis, stop_id: str) -> list[str]:
    """Liefert die trip_ids, die einen Halt bedienen (oder leere Liste)."""
    members = await redis.smembers(_stop_idx_key(stop_id))
    return list(members)


async def trips_for_route(redis, route_id: str) -> list[str]:
    """Liefert die trip_ids einer Linie (oder leere Liste)."""
    members = await redis.smembers(_route_idx_key(route_id))
    return list(members)
