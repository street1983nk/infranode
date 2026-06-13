"""On-demand Auflösungsindex trip_id/route_id/stop gegen statisches GTFS.

Löst Live-RT-Bezüge (trip_id, route_id, Halte) gegen das statische DELFI-GTFS
auf. Grundlage ist das memory-konstante Zip-Entry-Streaming aus
:func:`infranode.ingest.gtfs.stream_entry` (RESEARCH Pattern 3, T-06-03/T-19-MEM):

- ``trips.txt`` ist klein -> vollständige ``{trip_id: route_id}``-Map im Speicher.
- ``stop_times.txt`` ist mehrere GB entpackt -> NIE komplett laden. Wir streamen
  zeilenweise und übernehmen NUR die Zeilen der angefragten ``trip_id``
  (Memory-Pitfall 2 aus RESEARCH; weder Voll-Lesen noch Voll-Entpacken des Zip).

Index-Strategie (RESEARCH Open Question 2, Claude's Discretion):
- (a) MVP, hier umgesetzt: pro angefragter ``trip_id`` streamend filtern. Reine
  Funktion ohne Cache/Redis; das Caching pro trip_id (lange TTL, da Statik sich
  nur beim monatlichen Refresh ändert) erfolgt im Aufrufer (Plan 19-04).
- (b) dokumentierte Folge-Option: Vorab-Index nur für die 28 Register-Städte beim
  Statik-Refresh (stop_times EINMAL streamen, je trip_id der Register-Städte über
  ``ingest.delfi.city_for_stop`` einen kompakten Index je Stadt ablegen ->
  Request-Lookup O(1) ohne GB-Scan). Wird bei Bedarf in einem Refresh-Job ergänzt.

KEIN Netz, kein Redis-Zugriff in diesen reinen Funktionen.
"""

from __future__ import annotations

from pathlib import Path

from infranode.ingest.delfi import city_for_stop
from infranode.ingest.gtfs import stream_entry
from infranode.transit.interpolation import gtfs_time_to_epoch


def build_trip_route_index(zip_path: str | Path) -> dict[str, str]:
    """Baut aus ``trips.txt`` eine ``{trip_id: route_id}``-Map.

    ``trips.txt`` ist klein genug für eine vollständige In-Memory-Map. Streamt
    den Entry zeilenweise (kein Voll-Lesen, kein Voll-Entpacken) und ist
    idempotent: ein zweiter Lauf liefert dasselbe Ergebnis (overwrite-Snapshot,
    kein Drift).
    """
    return {
        row["trip_id"]: row["route_id"] for row in stream_entry(zip_path, "trips.txt")
    }


def stop_times_for_trip(zip_path: str | Path, trip_id: str) -> list[dict]:
    """Liefert die nach ``stop_sequence`` sortierten Halte EINER ``trip_id``.

    Streamt ``stop_times.txt`` (mehrere GB) zeilenweise und übernimmt NUR die
    Zeilen der gesuchten ``trip_id``. KOMMENTAR-Pflicht (T-06-03/T-19-MEM):
    ``stop_times.txt`` wird NIE komplett geladen, nur streamend gefiltert.

    Unbekannte ``trip_id`` -> leere Liste.
    """
    out: list[dict] = []
    # stop_times.txt (mehrere GB) NIE komplett laden: nur streamend filtern.
    for row in stream_entry(zip_path, "stop_times.txt"):
        if row.get("trip_id") != trip_id:
            continue
        out.append(
            {
                "stop_id": row["stop_id"],
                "stop_sequence": int(row["stop_sequence"]),
                "arrival_time": row.get("arrival_time"),
                "departure_time": row.get("departure_time"),
            }
        )
    return sorted(out, key=lambda r: r["stop_sequence"])


def _stops_geo_index(zip_path: str | Path) -> dict[str, dict[str, float]]:
    """Baut aus ``stops.txt`` eine ``{stop_id: {lat, lon}}``-Map.

    ``stops.txt`` ist klein genug fuer eine vollstaendige In-Memory-Map (anders als
    ``stop_times.txt``). Streamt zeilenweise (kein Voll-Lesen). Zeilen ohne
    parsebare Koordinaten werden uebersprungen (ehrlich, kein Fehler).
    """
    out: dict[str, dict[str, float]] = {}
    for row in stream_entry(zip_path, "stops.txt"):
        sid = row.get("stop_id")
        if not sid:
            continue
        try:
            out[sid] = {"lat": float(row["stop_lat"]), "lon": float(row["stop_lon"])}
        except (KeyError, ValueError, TypeError):
            continue
    return out


def stops_with_geo_for_trip(
    zip_path: str | Path, trip_id: str, *, service_day_epoch: int
) -> list[dict]:
    """Liefert die Halte einer Fahrt angereichert um Geo + ``scheduled_epoch``.

    Verbindet :func:`stop_times_for_trip` (sortierte Halte mit Soll-Zeiten) mit der
    ``stops.txt``-Geo-Map und rechnet die GTFS-Soll-Zeit (``arrival_time``, sonst
    ``departure_time``, "HH:MM:SS", >24h moeglich) gegen den injizierten
    ``service_day_epoch`` in einen ``scheduled_epoch`` um (reine Funktion, keine
    Systemuhr). Halte ohne Geo ODER ohne parsebare Soll-Zeit werden uebersprungen,
    damit :func:`infranode.transit.interpolation.estimate_position` nur
    vollstaendige Halte sieht. Unbekannte ``trip_id`` -> leere Liste.
    """
    stops = stop_times_for_trip(zip_path, trip_id)
    if not stops:
        return []
    geo = _stops_geo_index(zip_path)
    enriched: list[dict] = []
    for s in stops:
        sid = s["stop_id"]
        coords = geo.get(sid)
        hms = s.get("arrival_time") or s.get("departure_time")
        if coords is None or not hms:
            continue
        try:
            scheduled = gtfs_time_to_epoch(hms, service_day_epoch=service_day_epoch)
        except (ValueError, AttributeError):
            continue
        enriched.append(
            {
                "stop_id": sid,
                "stop_sequence": s["stop_sequence"],
                "scheduled_epoch": scheduled,
                "lat": coords["lat"],
                "lon": coords["lon"],
            }
        )
    return enriched


def slug_for_trip(zip_path: str | Path, trip_id: str) -> str | None:
    """Ordnet eine ``trip_id`` über ihren ersten Halt einer Register-Stadt zu.

    Hilfsfunktion für den optionalen Vorab-Index je Stadt (RESEARCH Pattern 3b):
    nutzt :func:`infranode.ingest.delfi.city_for_stop` auf der ersten stop_id der
    Fahrt (KEIN neuer Geo-Code). Liefert den Register-Slug oder ``None`` (Fahrt
    außerhalb der 28 Register-Städte bzw. unbekannte trip_id).
    """
    stops = stop_times_for_trip(zip_path, trip_id)
    if not stops:
        return None
    return city_for_stop(stops[0]["stop_id"])
