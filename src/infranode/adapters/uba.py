"""Keyloser UBA-Adapter fetch_air_uba (DATA-10, Tier A).

Laedt Luftqualitaets-Messwerte vom keylosen Umweltbundesamt-
Air-Data-API ueber den gepoolten httpx-Client. Zwei-Schritt-Flow:

1. ``GET /stations/json`` liefert alle Messstationen; der Adapter waehlt die
   geografisch naechste Station zu (``lat``, ``lon``) per einfacher Grad-Distanz
   (kein Haversine, vgl. ``autobahn._within_bbox``: Don't-Hand-Roll).
2. ``GET /measures/json`` liefert je v3-Komponente (PM10/PM2.5/NO2/O3/SO2) die
   Stundenwerte; der Adapter nimmt je Komponente den juengsten Messzeitpunkt.

Rueckgabe ist ein flaches raw-dict, das auf das bestehende ``AirQualityPayload``
passt: ``slug``/``station_id``/``lat``/``lon``/``observed_at``/``pm10``/``pm25``/
``no2``/``o3``/``so2`` (fehlender Wert -> ``None``, T-07-IN).

KRITISCH (Lizenz-Klassifikation): UBA ist Tier A (offene Lizenz) und wird ueber
die Route ``/air-uba`` (archivierter Tier-A-Bestand) sowie ueber den aelteren,
nicht persistierten Pfad ``/air`` ausgeliefert. UBA ist die einzige
Luftqualitaetsquelle und liefert alle fuenf Schadstoffe.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (T-07-IN, SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon
stammen aus dem validierten Register und fliessen nur als Query-Parameter ein.
Das verschachtelte UBA-measures-Format wird defensiv gelesen (keine festen
Index-Zugriffe ohne Guard): ein fehlerhaftes/leeres Feld liefert ``None`` statt
einen KeyError/IndexError auszuloesen.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import httpx

# Host hartkodiert (T-07-IN SSRF): nur diese eine oeffentliche UBA-Instanz.
# 2026-06-13: UBA-Luftdaten-API umgezogen. Der alte Host www.umweltbundesamt.de
# /api/air_data antwortet mit 301 auf luftdaten.umweltbundesamt.de/api/air-data
# (Unterstrich -> Bindestrich); der Adapter folgt Redirects bewusst nicht (SSRF),
# daher lief er ins Leere. Neue Basis verifiziert: stations/components/measures = 200.
_BASE = "https://luftdaten.umweltbundesamt.de/api/air-data/v3"

# v3-Komponenten-IDs (Adapter-lokal). Korrektes Schema: 1=PM10, 9=PM2,5,
# 5=NO2, 3=O3, 4=SO2. Wert-Key im raw-dict je Komponente. Am 2026-06-26 live gegen
# components/json (autoritativ) und measures/json verifiziert (Station 143).
# Das frühere Mapping (pm25=5, no2=3, o3=7) war falsch und lieferte systematisch
# vertauschte Werte (pm25 zog NO2, no2 zog O3, o3 zog den leeren BaP-Kanal).
# SO2 (component 4) wird an vielen Stationen stuendlich nicht gemessen
# (scope 2 leer) -> so2=None ist dort ehrlich korrekt, kein Bug.
_COMPONENTS: dict[str, int] = {"pm10": 1, "pm25": 9, "no2": 5, "o3": 3, "so2": 4}

# Stunden-Mittelwert-Scope (UBA scope-id 2). Adapter-lokal hartkodiert.
_SCOPE = 2


def _deg_distance(alat: float, alon: float, blat: float, blon: float) -> float:
    """Einfache breitengrad-korrigierte Grad-Distanz fuer die Stationsauswahl.

    Bewusst KEIN Haversine (Don't-Hand-Roll, vgl. autobahn._within_bbox): fuer die
    grobe Auswahl der naechsten Messstation reicht eine euklidische Grad-Distanz
    mit ``cos(lat)``-korrigierter Laengen-Achse.
    """
    cos_lat = math.cos(math.radians(alat))
    dlat = blat - alat
    dlon = (blon - alon) * cos_lat
    return math.hypot(dlat, dlon)


def _nearest_station(
    stations: dict, lat: float, lon: float
) -> tuple[str, float, float]:
    """Waehlt aus dem /stations/json-Body die naechste Station zu (lat, lon).

    ``indices`` ist die Spaltennamen-Liste, ``data`` ein dict
    ``station_id -> Werte-Array`` in ``indices``-Reihenfolge. Defensive Lesung:
    Stationen ohne gueltige Koordinaten werden uebersprungen.
    """
    indices = stations.get("indices") or []
    try:
        lon_idx = indices.index("station longitude")
        lat_idx = indices.index("station latitude")
    except ValueError:
        # Format unerwartet -> keine Auswahl moeglich.
        raise httpx.HTTPError("UBA /stations/json: erwartete Spalten fehlen") from None

    best_id: str | None = None
    best_lat = best_lon = 0.0
    best_dist = float("inf")

    for station_id, row in (stations.get("data") or {}).items():
        if not isinstance(row, list) or len(row) <= max(lon_idx, lat_idx):
            continue
        try:
            slon = float(row[lon_idx])
            slat = float(row[lat_idx])
        except (TypeError, ValueError):
            continue
        dist = _deg_distance(lat, lon, slat, slon)
        if dist < best_dist:
            best_dist = dist
            best_id = str(station_id)
            best_lat = slat
            best_lon = slon

    if best_id is None:
        raise httpx.HTTPError("UBA /stations/json: keine Station mit Koordinaten")

    return best_id, best_lat, best_lon


def _latest_value(measures: dict, station_id: str) -> tuple[float | None, str | None]:
    """Liest defensiv den juengsten Messwert + Zeitpunkt aus dem measures-Body.

    ``data`` ist ``station_id -> {datetime: [component_id, scope_id, value, ...]}``.
    Rueckgabe (value, observed_at_iso) des spaetesten datetime-Schluessels; bei
    leerem/fehlerhaftem Body ``(None, None)`` statt KeyError/IndexError (T-07-IN).
    """
    by_time = (measures.get("data") or {}).get(station_id) or {}
    if not isinstance(by_time, dict) or not by_time:
        return None, None

    latest_key = max(by_time.keys())
    row = by_time.get(latest_key)
    if not isinstance(row, list) or len(row) < 3:
        return None, None

    raw_value = row[2]
    try:
        value: float | None = float(raw_value)
    except (TypeError, ValueError):
        value = None

    # UBA-Zeitstempel "YYYY-MM-DD HH:MM:SS" -> ISO-8601 UTC.
    observed_at: str | None = None
    try:
        observed_at = (
            datetime.strptime(latest_key, "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=UTC)
            .isoformat()
        )
    except (TypeError, ValueError):
        observed_at = None

    return value, observed_at


async def fetch_air_uba(
    http: httpx.AsyncClient, *, slug: str, lat: float, lon: float
) -> dict:
    """Holt UBA-Luftqualitaet (2-Step) und liefert das flache raw-dict.

    Schritt 1 ``GET {_BASE}/stations/json`` (``lang=de``): naechste Station zu
    (``lat``, ``lon``). Schritt 2 ``GET {_BASE}/measures/json`` je v3-Komponente
    (PM10/PM2.5/NO2/O3/SO2) mit Tagesfenster: juengster Stundenwert je Komponente.

    Rueckgabe-Keys (exakt das, was ``map_air_uba`` erwartet): ``slug``,
    ``station_id`` (UBA-Station-ID als ``str``), ``lat``, ``lon`` (Station-Geo),
    ``observed_at`` (juengster Messzeitpunkt) sowie ``pm10``/``pm25``/``no2``/
    ``o3``/``so2`` (fehlender Wert -> ``None``). Der Host ist hartkodiert (SSRF-Schutz,
    T-07-IN); ``resp.raise_for_status()`` ist Pflicht (STALE-ON-ERROR-Pfad).
    """
    stations_resp = await http.get(f"{_BASE}/stations/json", params={"lang": "de"})
    stations_resp.raise_for_status()
    station_id, station_lat, station_lon = _nearest_station(
        stations_resp.json(), lat, lon
    )

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    raw: dict = {
        "slug": slug,
        "station_id": station_id,
        "lat": station_lat,
        "lon": station_lon,
        "observed_at": None,
        "pm10": None,
        "pm25": None,
        "no2": None,
        "o3": None,
        "so2": None,
    }

    latest_observed: str | None = None
    for key, component_id in _COMPONENTS.items():
        measures_resp = await http.get(
            f"{_BASE}/measures/json",
            params={
                "date_from": today,
                "time_from": "1",
                "date_to": today,
                "time_to": "24",
                "station": station_id,
                "component": str(component_id),
                "scope": str(_SCOPE),
            },
        )
        measures_resp.raise_for_status()
        value, observed_at = _latest_value(measures_resp.json(), station_id)
        raw[key] = value
        if observed_at is not None and (
            latest_observed is None or observed_at > latest_observed
        ):
            latest_observed = observed_at

    raw["observed_at"] = latest_observed
    return raw
