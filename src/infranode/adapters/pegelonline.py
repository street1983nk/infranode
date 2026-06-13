"""Keyloser PEGELONLINE-Adapter fetch_water_level (DATA-11, Tier A).

Laedt Pegelstaende vom keylosen PEGELONLINE-REST-Dienst der
Wasserstrassen- und Schifffahrtsverwaltung des Bundes (WSV) ueber den gepoolten
httpx-Client. Zwei-Schritt-Flow:

1. ``GET /stations.json`` liefert alle Pegel-Stationen mit Koordinaten; der
   Adapter waehlt die geografisch naechste Station zu (``lat``, ``lon``) per
   einfacher breitengrad-korrigierter Grad-Distanz (kein Haversine, vgl.
   ``autobahn._within_bbox``: Don't-Hand-Roll).
2. ``GET /stations/{uuid}/W/currentmeasurement.json`` liefert den aktuellen
   Wasserstand (``timestamp``/``value``) der gewaehlten Station.

KRITISCH (DATA-11, Pitfall 3 / Teilabdeckung): PEGELONLINE deckt nur Staedte an
Bundeswasserstrassen ab. Liegt KEINE Station innerhalb der Naehe-Toleranz (z.B.
Binnenstadt), liefert der Adapter ``{"slug": slug, "station": None}`` und wirft
NICHT. Die Route mappt ``station is None`` ehrlich auf ``source_status="no_data"``
(200, KEIN 5xx).

Rueckgabe bei vorhandener Station ist ein flaches raw-dict, das auf das
``WaterLevelPayload`` passt: ``slug``/``station``/``uuid``/``value``/``unit``/
``observed_at``/``water``. Das echte Antwortfeld heisst ``value``; defensives
``.get("value")`` faengt fehlende Felder ab (T-07-IN).

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (T-07-IN, SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon
stammen aus dem validierten Register und fliessen nur in die Stationsauswahl ein,
die ``uuid`` stammt ausschliesslich aus der ``/stations.json``-Antwort (nie
User-Input).
"""

from __future__ import annotations

import math

import httpx

# Host hartkodiert (T-07-IN SSRF): nur diese eine oeffentliche PEGELONLINE-Instanz.
_BASE = "https://www.pegelonline.wsv.de/webservices/rest-api/v2"

# Naehe-Toleranz in Grad (~55 km): Stationen weiter weg gelten als "keine nahe
# Station" -> Teilabdeckung (Pitfall 3, Binnenstadt). Eine Bundeswasserstrasse in
# der Stadt liegt deutlich darunter; eine ferne Station darueber.
_MAX_DEG = 0.5


def _deg_distance(alat: float, alon: float, blat: float, blon: float) -> float:
    """Einfache breitengrad-korrigierte Grad-Distanz fuer die Stationsauswahl.

    Bewusst KEIN Haversine (Don't-Hand-Roll, vgl. autobahn._within_bbox): fuer die
    grobe Auswahl der naechsten Pegel-Station reicht eine euklidische Grad-Distanz
    mit ``cos(lat)``-korrigierter Laengen-Achse.
    """
    cos_lat = math.cos(math.radians(alat))
    dlat = blat - alat
    dlon = (blon - alon) * cos_lat
    return math.hypot(dlat, dlon)


def _nearest(stations: list, lat: float, lon: float) -> dict | None:
    """Waehlt die naechste Station zu (lat, lon) aus der /stations.json-Liste.

    Defensive Lesung: Stationen ohne gueltige Koordinaten werden uebersprungen.
    Liegt die naechste Station weiter als ``_MAX_DEG`` entfernt, gilt sie als
    "keine nahe Station" -> ``None`` (Pitfall 3, Teilabdeckung).
    """
    best: dict | None = None
    best_dist = float("inf")

    for station in stations:
        if not isinstance(station, dict):
            continue
        try:
            slat = float(station["latitude"])
            slon = float(station["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        dist = _deg_distance(lat, lon, slat, slon)
        if dist < best_dist:
            best_dist = dist
            best = station

    if best is None or best_dist > _MAX_DEG:
        return None
    return best


async def fetch_water_level(
    http: httpx.AsyncClient, *, slug: str, lat: float, lon: float
) -> dict:
    """Holt den keylosen PEGELONLINE-Pegelstand (2-Step) als flaches raw-dict.

    Schritt 1 ``GET {_BASE}/stations.json``: naechste Station zu (``lat``,
    ``lon``). Liegt keine Station innerhalb der Naehe-Toleranz, liefert die
    Funktion ``{"slug": slug, "station": None}`` und wirft NICHT (Pitfall 3,
    Teilabdeckung). Schritt 2 ``GET {_BASE}/stations/{uuid}/W/
    currentmeasurement.json``: aktueller Wasserstand der gewaehlten Station.

    Rueckgabe-Keys (exakt das, was ``map_water_level`` erwartet): ``slug``,
    ``station`` (longname bzw. ``None``), ``uuid``, ``value`` (cm), ``unit``,
    ``observed_at`` (Mess-timestamp) und ``water`` (Gewaesser-longname). Der Host
    ist hartkodiert (SSRF-Schutz, T-07-IN); ``resp.raise_for_status()`` ist
    Pflicht (STALE-ON-ERROR-Pfad).
    """
    stations_resp = await http.get(f"{_BASE}/stations.json")
    stations_resp.raise_for_status()
    station = _nearest(stations_resp.json(), lat, lon)

    # Pitfall 3 (Teilabdeckung): keine nahe Station -> no_data, kein Fehler.
    if station is None:
        return {"slug": slug, "station": None}

    uuid = station["uuid"]
    measure_resp = await http.get(f"{_BASE}/stations/{uuid}/W/currentmeasurement.json")
    measure_resp.raise_for_status()
    measurement = measure_resp.json()

    return {
        "slug": slug,
        "station": station.get("longname"),
        "uuid": uuid,
        "value": measurement.get("value"),
        "unit": "cm",
        "observed_at": measurement.get("timestamp"),
        "water": (station.get("water") or {}).get("longname"),
    }
