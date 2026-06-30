"""DB-FaSta-Adapter fetch_station_facilities (Aufzug-/Rolltreppen-Status).

Laedt den Echtzeit-Betriebsstatus der Aufzuege und Rolltreppen an deutschen
Bahnhoefen (DB InfraGO) aus der DB-FaSta-API (DB API Marketplace) und filtert die
Anlagen auf das Stadtgebiet. Das Ergebnis ist ein flaches raw-dict, das
``map_station_facilities`` erwartet.

KEY-GATED: Die FaSta-API verlangt einen kostenlosen DB-API-Marketplace-Schluessel
(Plan "Free4All"). Ohne ``db_fasta_client_id``/``db_fasta_api_key`` ist die Quelle
deaktiviert (die Route liefert ``source_status=disabled``); der Owner legt den
Schluessel an und setzt die beiden Secrets in der Box-.env. Die Header
``DB-Client-Id``/``DB-Api-Key`` sind der Marketplace-Standard.

KRITISCH (Pitfall 4): Anlagen liegen an Bahnhoefen im Stadtgebiet (Bbox-Filter
ueber ``geocoordX``/``geocoordY``); ``distance_km`` je Anlage weist das aus.
``state`` ist ACTIVE/INACTIVE/UNKNOWN, ``stateExplanation`` traegt die Begruendung.

Sicherheit (T-07-IN): Host operator-konfigurierbar, Credentials erscheinen NIE im
Rueckgabe-dict. ``raise_for_status`` schlaegt 5xx als ``httpx.HTTPError`` an die
Fassade durch (STALE-ON-ERROR).
"""

from __future__ import annotations

import math

import httpx

_BASE = "https://apis.deutschebahn.com/db-api-marketplace/apis/fasta/v2/facilities"

# Umkreis um die Stadt (~20 km): Bahnhoefe liegen im/am Stadtgebiet.
_LAT_DELTA = 0.18
_LON_DELTA = 0.28

_MAX_FACILITIES = 200


def _km(alat: float, alon: float, blat: float, blon: float) -> float:
    """Grobe Distanz in km (breitengrad-korrigierte Grad-Distanz x 111)."""
    cos_lat = math.cos(math.radians(alat))
    dlat = blat - alat
    dlon = (blon - alon) * cos_lat
    return round(math.hypot(dlat, dlon) * 111.0, 1)


def _to_float(value: object) -> float | None:
    """Parst ein Koordinatenfeld defensiv zu float (oder None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_station_facilities(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    client_id: str,
    api_key: str,
    base_url: str = _BASE,
) -> dict:
    """Holt den Aufzug-/Rolltreppen-Status im Stadtgebiet (DB FaSta).

    Fragt die FaSta-API mit den Marketplace-Headern ab, filtert die Anlagen auf
    eine Bounding-Box um (``lat``, ``lon``), sortiert nach Distanz und deckelt auf
    ``_MAX_FACILITIES``. Gibt das flache raw-dict zurueck, das
    ``map_station_facilities`` erwartet.

    Rueckgabe-Keys: ``slug``, ``count``, ``truncated``, ``counts`` (je Status),
    ``facilities`` (je Anlage equipmentnumber/type/state/state_explanation/
    description/stationnumber/lat/lon/distance_km). Keine Anlage im Umkreis ->
    ``count=0`` (ehrliches no_data). Credentials erscheinen NIE in der Rueckgabe.
    """
    resp = await http.get(
        base_url,
        headers={"DB-Client-Id": client_id, "DB-Api-Key": api_key},
    )
    resp.raise_for_status()
    body = resp.json()
    # FaSta liefert je nach Variante eine Liste ODER {"facilities": [...]}.
    if isinstance(body, dict):
        entries = body.get("facilities") or []
    elif isinstance(body, list):
        entries = body
    else:
        entries = []

    facilities: list[dict] = []
    counts: dict[str, int] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        flat = _to_float(item.get("geocoordY"))
        flon = _to_float(item.get("geocoordX"))
        if flat is None or flon is None:
            continue
        if abs(flat - lat) > _LAT_DELTA or abs(flon - lon) > _LON_DELTA:
            continue
        state = item.get("state")
        key = str(state).lower() if state else "unknown"
        counts[key] = counts.get(key, 0) + 1
        facilities.append(
            {
                "equipmentnumber": item.get("equipmentnumber"),
                "type": item.get("type"),
                "state": state,
                "state_explanation": item.get("stateExplanation"),
                "description": item.get("description"),
                "stationnumber": item.get("stationnumber"),
                "lat": flat,
                "lon": flon,
                "distance_km": _km(lat, lon, flat, flon),
            }
        )

    facilities.sort(key=lambda f: f["distance_km"])
    count = len(facilities)
    return {
        "slug": slug,
        "count": count,
        "truncated": count > _MAX_FACILITIES,
        "counts": counts,
        "facilities": facilities[:_MAX_FACILITIES],
    }
