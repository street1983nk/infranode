"""Keyloser Bundes-Klinik-Atlas-Adapter fetch_hospital_atlas (Krankenhausstandorte).

Laedt die standortgenaue Krankenhausliste des Bundes-Klinik-Atlas (BMG/IQTIG) aus
der oeffentlichen ``locations.json`` und filtert sie auf einen Umkreis um eine
Stadt. Das Ergebnis ist ein flaches raw-dict, das ``map_hospital_atlas`` erwartet.

FAIL-CLOSED (Lizenz): Der Bundes-Klinik-Atlas weist KEINE explizite offene Lizenz
aus. Bis zur Bestaetigung durch BMG/IQTIG wird die Quelle als ``unknown``/Tier C
gefuehrt UND ist per Default deaktiviert (``enable_klinik_atlas=False``); die Route
liefert dann ``source_status=disabled``. Erst nach Lizenzbestaetigung schaltet der
Owner den Toggle und (falls offen) license_id/Tier um.

``locations.json`` ist ein JSON-Array je Standort mit ``name``, ``street``,
``city``, ``zip``, ``phone``, ``mail``, ``beds_number``, ``latitude``,
``longitude`` (Strings) und ``link``. KRITISCH (Pitfall 4): die Auswahl ist
ortsnah (Bbox), ``distance_km`` je Standort weist das aus.

Sicherheit (T-07-IN): Host operator-konfigurierbar (kein User-Input);
``raise_for_status`` schlaegt 5xx als ``httpx.HTTPError`` an die Fassade durch.
"""

from __future__ import annotations

import math

import httpx

_BASE = "https://bundes-klinik-atlas.de/fileadmin/json/locations.json"

# Umkreis um die Stadt (~20 km): Krankenhaeuser liegen im/am Stadtgebiet.
_LAT_DELTA = 0.18
_LON_DELTA = 0.28

# Obergrenze der zurueckgelieferten Standorte (Payload-Schutz); echte Zahl via
# ``count`` + ``truncated``-Flag.
_MAX_HOSPITALS = 60


def _km(alat: float, alon: float, blat: float, blon: float) -> float:
    """Grobe Distanz in km (breitengrad-korrigierte Grad-Distanz x 111)."""
    cos_lat = math.cos(math.radians(alat))
    dlat = blat - alat
    dlon = (blon - alon) * cos_lat
    return round(math.hypot(dlat, dlon) * 111.0, 1)


def _to_float(value: object) -> float | None:
    """Parst ein Koordinatenfeld (String/Zahl) defensiv zu float (oder None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_hospital_atlas(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    base_url: str = _BASE,
) -> dict:
    """Holt die Krankenhausstandorte im Umkreis einer Stadt (Bundes-Klinik-Atlas).

    Laedt die ``locations.json``, filtert die Standorte auf eine Bounding-Box um
    (``lat``, ``lon``), sortiert nach Distanz und deckelt auf ``_MAX_HOSPITALS``.
    Gibt das flache raw-dict zurueck, das ``map_hospital_atlas`` erwartet.

    Rueckgabe-Keys: ``slug``, ``count`` (Gesamtzahl im Umkreis), ``truncated``,
    ``total_beds`` (Summe, falls vorhanden), ``hospitals`` (je Standort
    name/street/zip/city/beds/lat/lon/distance_km/phone/link). Keine Klinik im
    Umkreis -> ``count=0`` (ehrliches no_data). ``raise_for_status`` schlaegt 5xx
    als ``httpx.HTTPError`` durch.
    """
    resp = await http.get(base_url)
    resp.raise_for_status()
    body = resp.json()
    entries = body if isinstance(body, list) else []

    hospitals: list[dict] = []
    total_beds = 0
    have_beds = False
    for item in entries:
        if not isinstance(item, dict):
            continue
        hlat = _to_float(item.get("latitude"))
        hlon = _to_float(item.get("longitude"))
        if hlat is None or hlon is None:
            continue
        if abs(hlat - lat) > _LAT_DELTA or abs(hlon - lon) > _LON_DELTA:
            continue
        beds = item.get("beds_number")
        if isinstance(beds, int):
            total_beds += beds
            have_beds = True
        hospitals.append(
            {
                "name": item.get("name"),
                "street": item.get("street"),
                "zip": item.get("zip"),
                "city": item.get("city"),
                "beds": beds,
                "lat": hlat,
                "lon": hlon,
                "distance_km": _km(lat, lon, hlat, hlon),
                "phone": item.get("phone"),
                "link": item.get("link"),
            }
        )

    hospitals.sort(key=lambda h: h["distance_km"])
    count = len(hospitals)
    return {
        "slug": slug,
        "count": count,
        "truncated": count > _MAX_HOSPITALS,
        "total_beds": total_beds if have_beds else None,
        "hospitals": hospitals[:_MAX_HOSPITALS],
    }
