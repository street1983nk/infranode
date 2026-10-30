"""Keyloser Köln-Baustellen-Adapter fetch_koeln_road_events (DATA-15, Tier A).

Die Stadt Köln hat ihren ArcGIS-Server im Oktober 2026 abgeschaltet
([VERIFIED 2026-10-28]: ``https://geoportal.stadt-koeln.de/arcgis/*`` antwortet
301 auf die Homepage, ``https://www.stadt-koeln.de/arcgis/*`` antwortet 410
Gone; im ArcGIS-Online-Katalog existiert kein Ersatz). Ersatzquelle ist der
Baustellen-WFS 2.0 (UMN MapServer) auf demselben Host, verlinkt vom
Open-Data-Portal (https://offenedaten-koeln.de/dataset/baustellen-koeln),
Lizenz unverändert DL-DE/Zero 2.0.

WFS-Eigenheiten [VERIFIED 2026-10-28] per Live-Probe:

- 15 Feature-Typen, ausschließlich Baustellenarten (``_TYPENAMES``). Die alten
  Verkehrskalender-Eventtypen (Karneval, Messen, Stadion-Events) existieren im
  WFS nicht mehr; der RSS-Feed des Portals wäre eine mögliche spätere
  Event-Ergänzung.
- EIN GetFeature mit mehreren kommaseparierten TYPENAMES liefert NUR den
  letzten Typ (der UMN MapServer merged nicht). Deshalb ein Request je Typ,
  parallel mit ``asyncio.Semaphore`` auf ``_MAX_PARALLEL`` begrenzt.
- ``SRSNAME`` wird ignoriert (bei GeoJSON komplett, bei GML nur Achsentausch):
  Koordinaten kommen IMMER in EPSG:25832 (UTM Zone 32N, x um 365000, y um
  5640000). ``_utm32n_to_wgs84`` rechnet selbst nach WGS84 um (reine
  Karney/Krüger-Reihenentwicklung, bewusst KEINE neue Dependency wie pyproj).
- Properties je Feature: ``Kategorie`` (Klartext, z. B. "Straßenbauarbeiten"),
  ``Aktenzeichen`` (ID), ``Adresse``, ``Genehmigungs-Zeitraum`` (String
  "13-10-2025 bis 31-07-2029", Format DD-MM-YYYY).
- Geometrie: Point; Flächen/Linien werden defensiv auf die erste Koordinate
  reduziert (bewährtes ``_extract_point``-Muster).

Sicherheit (T-9-02 SSRF): Host in ``_BASE`` hartkodiert; die TYPENAMES stammen
ausschließlich aus ``_TYPENAMES``; kein User-Input in der URL. DoS-Schutz:
``COUNT=_COUNT_PER_TYPE`` als harter Cap je Typ (Gegenstück zum früheren
``resultRecordCount=1000``). Datenfehler-Schutz (Phase-7/8-Konvention): jedes
Feld defensiv per ``.get(...)`` mit None-Fallback; Zeitraum-Parser und
UTM-Umrechnung fangen fehlende/kaputte Werte ab (None statt Crash).

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist
Pflicht, damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und
der STALE-ON-ERROR-Pfad greift.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from infranode.normalization.fields import clean_text

# Host hartkodiert (T-9-02 SSRF): nur dieser eine WFS-Endpunkt der Stadt Köln.
_BASE = "https://geoportal.stadt-koeln.de/wss/service/baustellen_wfs/guest"

# [VERIFIED 2026-10-28] alle 15 Feature-Typen aus den GetCapabilities des
# Baustellen-WFS (Präfix ``ms:`` wird je Request vorangestellt). NUR aus dieser
# Allowlist, nie aus User-Input (SSRF/Injection).
_TYPENAMES: tuple[str, ...] = (
    "ampelarbeiten",
    "arbeitsbuehne",
    "baustelleneinrichtung",
    "brueckenarbeiten",
    "container",
    "gleisbau",
    "gruenflaechenarbeiten",
    "hochbau",
    "kanalsanierung",
    "markierungsarbeiten",
    "notfall",
    "sondierungsarbeiten",
    "strassenbauarbeiten",
    "tunnelarbeiten",
    "versorgungsarbeiten",
)

# DoS-Deckel je Feature-Typ (Gegenstück zum früheren resultRecordCount=1000).
_COUNT_PER_TYPE = 1000

# Max. gleichzeitige Upstream-Requests (15 Typen, aber schonend zum Geoportal).
_MAX_PARALLEL = 5

# Der Genehmigungs-Zeitraum ist ein lokales Datum der Stadt Köln ->
# Europe/Berlin (tzdata ist gepinnte Dependency, löst auch auf Windows/slim).
_TZ_KOELN = ZoneInfo("Europe/Berlin")


def _utm32n_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Rechnet EPSG:25832 (ETRS89 / UTM Zone 32N) nach WGS84 ``(lat, lon)`` um.

    Reine Mathe-Funktion: inverse transversale Mercator-Projektion als
    Karney/Krüger-Reihenentwicklung in n (3. Ordnung, vgl. Karney 2011 bzw.
    Wikipedia "Transverse Mercator projection"). Genauigkeit im Zonenbereich
    weit unter 1 m; verifiziert gegen den publizierten UTM-Testvektor Zone 17
    (630084/4833438 -> 43.642566 N, 79.387139 W, Abweichung < 1 m = Rundung
    des Referenzpunkts) und exakt am Zonen-Ursprung (500000/0 -> 0 N, 9 O).
    ETRS89 (GRS80) und WGS84 unterscheiden sich in Deutschland unter 1 m, das
    ist für Baustellen-Punkte irrelevant. Bewusst keine pyproj-Dependency.
    """
    a = 6378137.0  # GRS80/WGS84 große Halbachse
    f = 1.0 / 298.257223563  # WGS84-Abplattung (GRS80 identisch bis 1e-10)
    k0 = 0.9996  # UTM-Maßstabsfaktor
    e0 = 500_000.0  # False Easting
    lon0 = math.radians(9.0)  # Mittelmeridian Zone 32
    n = f / (2.0 - f)
    big_a = a / (1.0 + n) * (1.0 + n * n / 4.0 + n**4 / 64.0)
    beta = (
        n / 2.0 - 2.0 * n**2 / 3.0 + 37.0 * n**3 / 96.0,
        n**2 / 48.0 + n**3 / 15.0,
        17.0 * n**3 / 480.0,
    )
    delta = (
        2.0 * n - 2.0 * n**2 / 3.0 - 2.0 * n**3,
        7.0 * n**2 / 3.0 - 8.0 * n**3 / 5.0,
        56.0 * n**3 / 15.0,
    )
    xi = northing / (k0 * big_a)
    eta = (easting - e0) / (k0 * big_a)
    xi_p = xi - sum(
        b * math.sin(2.0 * j * xi) * math.cosh(2.0 * j * eta)
        for j, b in enumerate(beta, start=1)
    )
    eta_p = eta - sum(
        b * math.cos(2.0 * j * xi) * math.sinh(2.0 * j * eta)
        for j, b in enumerate(beta, start=1)
    )
    chi = math.asin(math.sin(xi_p) / math.cosh(eta_p))
    lat = chi + sum(d * math.sin(2.0 * j * chi) for j, d in enumerate(delta, start=1))
    lon = lon0 + math.atan2(math.sinh(eta_p), math.cos(xi_p))
    return math.degrees(lat), math.degrees(lon)


def _parse_date(part: str) -> str | None:
    """Parst ein Datum ``DD-MM-YYYY`` defensiv nach ISO-8601 (Europe/Berlin).

    Der WFS liefert nur Kalendertage (keine Uhrzeit); ausgegeben wird lokale
    Mitternacht MIT Zeitzone (Payload-Konvention: Zeitstempel tragen immer
    eine Zeitzone). Leer/anders formatiert -> None statt Crash.
    """
    try:
        parsed = datetime.strptime(part.strip(), "%d-%m-%Y")
    except ValueError:
        return None
    return parsed.replace(tzinfo=_TZ_KOELN).isoformat()


def _parse_period(value: object) -> tuple[str | None, str | None]:
    """Zerlegt den ``Genehmigungs-Zeitraum`` defensiv in ``(start, end)``.

    [VERIFIED 2026-10-28] Format: ``"13-10-2025 bis 31-07-2029"``. Fehlendes
    Feld, fehlender ``bis``-Teil oder unparsbare Teile -> None je Seite statt
    Crash; ein einzelnes Datum ohne ``bis`` wird als Start gewertet.
    """
    if not isinstance(value, str):
        return (None, None)
    parts = value.split("bis")
    if len(parts) == 1:
        return (_parse_date(parts[0]), None)
    if len(parts) == 2:
        return (_parse_date(parts[0]), _parse_date(parts[1]))
    return (None, None)


def _extract_point(geom: object) -> tuple[float | None, float | None]:
    """Liefert ``(lat, lon)`` in WGS84 aus einer GeoJSON-Geometrie in UTM32N.

    Punkt: ``coordinates = [x, y]`` direkt. Flächen/Linien defensiv wie das
    bewährte ``_extract_point``-Muster: in die verschachtelten Listen bis zur
    ersten Koordinate absteigen. Jede abweichende Struktur oder eine nicht
    umrechenbare Koordinate -> ``(None, None)`` statt Crash (T-9-02).
    """
    if not isinstance(geom, dict):
        return (None, None)
    coords = geom.get("coordinates")
    depth = 0
    while (
        isinstance(coords, list)
        and coords
        and isinstance(coords[0], list)
        and depth < 4
    ):
        coords = coords[0]
        depth += 1
    if (
        not isinstance(coords, list)
        or len(coords) < 2
        or isinstance(coords[0], bool)
        or isinstance(coords[1], bool)
        or not isinstance(coords[0], int | float)
        or not isinstance(coords[1], int | float)
    ):
        return (None, None)
    try:
        lat, lon = _utm32n_to_wgs84(float(coords[0]), float(coords[1]))
    except (ValueError, OverflowError):
        return (None, None)
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return (None, None)
    return (lat, lon)


def _event_id(value: object) -> str | None:
    """Liest das ``Aktenzeichen`` defensiv als String-ID (None statt Crash)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return clean_text(value)


async def _fetch_layer(
    http: httpx.AsyncClient, typename: str, sem: asyncio.Semaphore
) -> list[dict]:
    """Holt EINEN Feature-Typ und reduziert ihn auf schlanke Event-dicts.

    ``raise_for_status()`` ist Pflicht: ein 5xx eines Typs lässt den gesamten
    Fetch als ``httpx.HTTPError`` zur Fassade durchschlagen (STALE-ON-ERROR
    statt Teil-Ergebnis, Verhalten wie beim alten Zwei-Layer-ArcGIS-Fetch).
    """
    params: dict[str, str | int] = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        # Nur aus der _TYPENAMES-Allowlist (SSRF/Injection); Mehrfach-TYPENAMES
        # liefert beim UMN MapServer nur den letzten Typ -> ein Typ je Request.
        "TYPENAMES": f"ms:{typename}",
        "COUNT": _COUNT_PER_TYPE,
        "outputFormat": "geojson",
    }
    async with sem:
        resp = await http.get(_BASE, params=params)
        resp.raise_for_status()
        body = resp.json()

    features = body.get("features", []) if isinstance(body, dict) else []
    events: list[dict] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            props = {}
        feature_lat, feature_lon = _extract_point(feature.get("geometry"))
        start, end = _parse_period(props.get("Genehmigungs-Zeitraum"))
        events.append(
            {
                # Kanonische Namen wie in allen anderen Datenarten
                # (Konsistenz-Audit 2026-07-25): snake_case, None statt "".
                "id": _event_id(props.get("Aktenzeichen")),
                "name": clean_text(props.get("Adresse")),
                # Maschinenlesbarer Baustellenart-Slug aus der kuratierten
                # Allowlist (ersetzt den alten Integer-Code des ArcGIS).
                "event_type": typename,
                # Klartext direkt aus der Quelle (ersetzt _ART_LABELS).
                "event_type_label": clean_text(props.get("Kategorie")),
                "start": start,
                "end": end,
                "lat": feature_lat,
                "lon": feature_lon,
            }
        )
    return events


async def fetch_koeln_road_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Holt die Kölner Baustellen aus dem Baustellen-WFS (alle 15 Typen).

    ``lat``/``lon`` sind vertragskonform Teil der Connector-Signatur
    (ungenutzt: der WFS ist bereits stadtscharf, keine BBox nötig). Die 15
    Feature-Typen werden parallel (max. ``_MAX_PARALLEL`` gleichzeitig, DoS-
    und Upstream-schonend) geholt und in stabiler ``_TYPENAMES``-Reihenfolge
    additiv zusammengeführt.

    Rückgabe-Keys (exakt das, was ``map_koeln_road_events`` erwartet): ``slug``
    und ``events`` (je Event ``id``/``name``/``event_type``/
    ``event_type_label``/``start``/``end``/``lat``/``lon``).
    """
    sem = asyncio.Semaphore(_MAX_PARALLEL)
    per_layer = await asyncio.gather(
        *(_fetch_layer(http, typename, sem) for typename in _TYPENAMES)
    )
    events = [event for layer_events in per_layer for event in layer_events]
    return {"slug": slug, "events": events}
