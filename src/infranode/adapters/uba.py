"""Keyloser UBA-Adapter fetch_air_uba (DATA-10, Tier A).

Lädt Luftqualitäts-Messwerte vom keylosen Umweltbundesamt-
Air-Data-API über den gepoolten httpx-Client. Zwei-Schritt-Flow:

1. ``GET /stations/json`` liefert alle Messstationen; der Adapter sortiert sie
   nach Grad-Distanz zu (``lat``, ``lon``) (kein Haversine, vgl.
   ``autobahn._within_bbox``: Don't-Hand-Roll) und hält die N nächsten.
2. ``GET /measures/json`` liefert je v3-Komponente (PM10/PM2.5/NO2/O3/SO2) die
   Stundenwerte; der Adapter nimmt je Komponente den jüngsten Messzeitpunkt.

KRITISCH (Audit K4): Nicht jede Station misst jede Komponente. Verkehrsnahe
Stationen führen z.B. kein O3. Würde für ALLE Komponenten nur die EINE
nächste Station abgefragt, fielen o3/so2 unnötig auf ``None``, obwohl eine
Nachbarstation wenige Kilometer weiter den Wert hat. Daher fährt der Adapter
PRO Komponente eine Fallback-Kaskade über die ``_FALLBACK_STATIONS`` nächsten
Stationen, bis ein aktueller Wert gefunden ist. Findet keine nahe Station eine
Komponente (typisch SO2), bleibt der Wert ehrlich ``None``.

Rückgabe ist ein flaches raw-dict, das auf das bestehende ``AirQualityPayload``
passt: ``slug``/``station_id``/``lat``/``lon``/``observed_at``/``pm10``/``pm25``/
``no2``/``o3``/``so2`` (fehlender Wert -> ``None``, T-07-IN).

KRITISCH (Lizenz-Klassifikation): UBA ist Tier A (offene Lizenz) und wird über
die Route ``/air-uba`` (archivierter Tier-A-Bestand) sowie über den älteren,
nicht persistierten Pfad ``/air`` ausgeliefert. UBA ist die einzige
Luftqualitätsquelle und liefert alle fünf Schadstoffe.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (T-07-IN, SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon
stammen aus dem validierten Register und fließen nur als Query-Parameter ein.
Das verschachtelte UBA-measures-Format wird defensiv gelesen (keine festen
Index-Zugriffe ohne Guard): ein fehlerhaftes/leeres Feld liefert ``None`` statt
einen KeyError/IndexError auszulösen.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import httpx

# Host hartkodiert (T-07-IN SSRF): nur diese eine öffentliche UBA-Instanz.
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
# SO2 (component 4) wird an vielen Stationen stündlich nicht gemessen
# (scope 2 leer) -> so2=None ist dort ehrlich korrekt, kein Bug.
_COMPONENTS: dict[str, int] = {"pm10": 1, "pm25": 9, "no2": 5, "o3": 3, "so2": 4}

# Stunden-Mittelwert-Scope (UBA scope-id 2). Adapter-lokal hartkodiert.
_SCOPE = 2

# Anzahl der nächsten Stationen, über die je Komponente eine Fallback-Kaskade
# fährt (Audit K4). 5 deckt den typischen Fall ab, dass die nächste Station
# eine Komponente (z.B. O3 an Verkehrsstationen) nicht misst, eine Nachbarstation
# wenige km weiter aber schon. Höher = mehr Requests bei Lücken, daher gedeckelt.
_FALLBACK_STATIONS = 5


def _deg_distance(alat: float, alon: float, blat: float, blon: float) -> float:
    """Einfache breitengrad-korrigierte Grad-Distanz für die Stationsauswahl.

    Bewusst KEIN Haversine (Don't-Hand-Roll, vgl. autobahn._within_bbox): für die
    grobe Auswahl der nächsten Messstation reicht eine euklidische Grad-Distanz
    mit ``cos(lat)``-korrigierter Längen-Achse.
    """
    cos_lat = math.cos(math.radians(alat))
    dlat = blat - alat
    dlon = (blon - alon) * cos_lat
    return math.hypot(dlat, dlon)


def _nearest_stations(
    stations: dict, lat: float, lon: float, *, limit: int
) -> list[tuple[str, float, float]]:
    """Liefert die ``limit`` nächsten Stationen zu (lat, lon), nach Distanz sortiert.

    ``indices`` ist die Spaltennamen-Liste, ``data`` ein dict
    ``station_id -> Werte-Array`` in ``indices``-Reihenfolge. Defensive Lesung:
    Stationen ohne gültige Koordinaten werden übersprungen. Rückgabe je Station
    ``(station_id, lat, lon)``; die erste ist die nächste (Audit K4: Basis für
    die Pro-Komponenten-Fallback-Kaskade).
    """
    indices = stations.get("indices") or []
    try:
        lon_idx = indices.index("station longitude")
        lat_idx = indices.index("station latitude")
    except ValueError:
        # Format unerwartet -> keine Auswahl möglich.
        raise httpx.HTTPError("UBA /stations/json: erwartete Spalten fehlen") from None

    candidates: list[tuple[float, str, float, float]] = []
    for station_id, row in (stations.get("data") or {}).items():
        if not isinstance(row, list) or len(row) <= max(lon_idx, lat_idx):
            continue
        try:
            slon = float(row[lon_idx])
            slat = float(row[lat_idx])
        except (TypeError, ValueError):
            continue
        dist = _deg_distance(lat, lon, slat, slon)
        candidates.append((dist, str(station_id), slat, slon))

    if not candidates:
        raise httpx.HTTPError("UBA /stations/json: keine Station mit Koordinaten")

    candidates.sort(key=lambda c: c[0])
    return [(sid, slat, slon) for _, sid, slat, slon in candidates[:limit]]


def _nearest_station(
    stations: dict, lat: float, lon: float
) -> tuple[str, float, float]:
    """Naechste Station zu (lat, lon) als ``(station_id, lat, lon)``.

    Dünner Kompatibilitäts-Wrapper um ``_nearest_stations`` (limit=1) für
    Aufrufer, die genau die EINE nächste Station brauchen (z.B. der
    Quality-Backfill, der je Komponente kein Nachbarstation-Fallback fahrt).
    """
    return _nearest_stations(stations, lat, lon, limit=1)[0]


def _latest_value(measures: dict, station_id: str) -> tuple[float | None, str | None]:
    """Liest defensiv den jüngsten Messwert + Zeitpunkt aus dem measures-Body.

    ``data`` ist ``station_id -> {datetime: [component_id, scope_id, value, ...]}``.
    Rückgabe (value, observed_at_iso) des spätesten datetime-Schlüssels; bei
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
    """Holt UBA-Luftqualität (2-Step) und liefert das flache raw-dict.

    Schritt 1 ``GET {_BASE}/stations/json`` (``lang=de``): die ``_FALLBACK_STATIONS``
    nächsten Stationen zu (``lat``, ``lon``). Schritt 2 ``GET {_BASE}/measures/json``
    je v3-Komponente (PM10/PM2.5/NO2/O3/SO2) mit Tagesfenster: jüngster Stundenwert
    je Komponente, PRO Komponente über die Nachbarstationen kaskadiert (Audit K4),
    bis ein Wert gefunden ist.

    Rückgabe-Keys (exakt das, was ``map_air_uba`` erwartet): ``slug``,
    ``station_id`` (UBA-Station-ID der NÄCHSTEN Station als ``str``), ``lat``,
    ``lon`` (Geo der nächsten Station, stabiler record_id-Schlüssel),
    ``observed_at`` (jüngster Messzeitpunkt über alle gefüllten Komponenten)
    sowie ``pm10``/``pm25``/``no2``/``o3``/``so2`` (fehlender Wert -> ``None``).
    Der Host ist hartkodiert (SSRF-Schutz, T-07-IN); ``resp.raise_for_status()``
    ist Pflicht (STALE-ON-ERROR-Pfad).
    """
    stations_resp = await http.get(f"{_BASE}/stations/json", params={"lang": "de"})
    stations_resp.raise_for_status()
    nearest = _nearest_stations(
        stations_resp.json(), lat, lon, limit=_FALLBACK_STATIONS
    )

    # Die nächste Station bestimmt station_id/Geo (stabiler record_id-Schlüssel,
    # ARCH-02); die weiteren dienen nur dem Pro-Komponenten-Fallback.
    primary_id, primary_lat, primary_lon = nearest[0]

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    raw: dict = {
        "slug": slug,
        "station_id": primary_id,
        "lat": primary_lat,
        "lon": primary_lon,
        "observed_at": None,
        "pm10": None,
        "pm25": None,
        "no2": None,
        "o3": None,
        "so2": None,
    }

    latest_observed: str | None = None
    for key, component_id in _COMPONENTS.items():
        # Fallback-Kaskade je Komponente: erste Station, die einen Wert liefert,
        # gewinnt. SO2 darf weiterhin ehrlich None bleiben, wenn keine nahe
        # Station es misst (Audit K4).
        for station_id, _slat, _slon in nearest:
            value, observed_at = await _fetch_component(
                http, station_id=station_id, component_id=component_id, today=today
            )
            if value is None:
                continue
            raw[key] = value
            if observed_at is not None and (
                latest_observed is None or observed_at > latest_observed
            ):
                latest_observed = observed_at
            break

    raw["observed_at"] = latest_observed
    return raw


async def _fetch_component(
    http: httpx.AsyncClient,
    *,
    station_id: str,
    component_id: int,
    today: str,
) -> tuple[float | None, str | None]:
    """Holt den jüngsten Stundenwert einer Komponente an EINER Station.

    Kapselt den ``GET {_BASE}/measures/json``-Call (Tagesfenster, scope-id 2) und
    die defensive Wert-Extraktion. Rückgabe ``(value, observed_at)``; fehlt der
    Wert an dieser Station, ``(None, None)`` -> die Kaskade in ``fetch_air_uba``
    probiert die nächste Station.
    """
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
            # Audit-156: index=id explizit. Die UBA-API liefert "id" zwar bereits
            # als Default (im request-Echo sichtbar), aber _latest_value verlässt
            # sich auf data->station_id->{datetime:[...]}; explizit setzen härtet
            # gegen eine stille Default-Änderung der Quelle.
            "index": "id",
        },
    )
    measures_resp.raise_for_status()
    return _latest_value(measures_resp.json(), station_id)
