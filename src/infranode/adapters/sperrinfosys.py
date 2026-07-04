"""SPERRINFOSYS-Sachsen-Adapter ``fetch_sperrinfosys_road_events`` (Tier A).

Liefert die landesweiten Baustellen/Sperrungen des Freistaats Sachsen keylos
aus dem SPERRINFOSYS der LISt GmbH (GeoJSON-ZIP, DL-DE/BY 2.0, Mobilithek-Offer
-2102129055146091928):

  www.list.smwa.sachsen.de/gdi/download/baustelleninfo/Baustelleninfo_Sachsen_geojson.zip

EINE sachsenweite Quelle speist zwei Städte: der ``Verwaltungskennziffer``-Filter
(VKZ, ``_SLUG_VKZ``) trennt Dresden (0014612) und Leipzig (0014713).

[VERIFIED 2026-07-04] Echte ZIP-Struktur inspiziert:
- Members: ``Baustelleninfo_Sperrungen_Sachsen.geojson`` (~3 MB) und
  ``Baustelleninfo_Umleitungen_Sachsen.geojson`` (~8 MB); genutzt wird NUR die
  Sperrungen-Datei (Umleitungen sind reine Routen-Geometrien ohne Mehrwert je
  Event, das Feld ``Umleitung_ueber`` steht bereits in den Sperrungen-Props).
- Encoding UTF-8, CRS ``EPSG:25833`` (ETRS89 / UTM Zone 33N, Koordinaten in
  Metern), Geometrie durchgehend ``LineString`` (1454 Features, Dresden 175,
  Leipzig 73 am Prüftag).
- Properties je Feature (defensiv via ``.get``): ``Verwaltungskennziffer``,
  ``Sperrung_Art_Klartext``, ``Sperrung_Typ_Klartext``, ``Sperrung_Grund``,
  ``Sperrung_von``/``Sperrung_bis`` (TT.MM.JJJJ), ``Strasse``,
  ``Strassenklasse``, ``Ortslage``, ``Umleitung_ueber`` (optional).

Reprojektion: EPSG:25833 -> WGS84 über ``utm33_to_wgs84`` (inverse transversale
Mercator-Projektion nach Snyder, stdlib ``math``, KEIN pyproj). Genauigkeit im
Meter-Bereich, für Karten-Pins ausreichend. Reprojektion = Veränderung -> der
Mapper setzt ``attribution.modified=True`` (DL-DE/BY-2.0-Pflicht).

Sicherheit: URL komplett hartkodiert, ``slug`` nur Key der ``_SLUG_VKZ``-
Allowlist (T-Q-01 SSRF). Body-Cap VOR dem ZipFile-Open plus
``ZipInfo.file_size``-Cap VOR ``zf.read`` (T-Q-02 Zip-Bomb); NIE ``extractall``,
alles in ``io.BytesIO`` im Speicher. Kaputtes ZIP/GeoJSON -> leere Events statt
500 (T-Q-04).
"""

from __future__ import annotations

import io
import json
import math
import zipfile

import httpx

# Hartkodierte Quelle (T-Q-01 SSRF: kein User-Input in der URL). Seit 2026-07
# leitet http per 301 auf https um; der Shared-Client folgt Redirects nicht,
# daher direkt die https-URL (live verifiziert: 200, ~2,5 MB).
_ZIP_URL = (
    "https://www.list.smwa.sachsen.de/gdi/download/baustelleninfo/"
    "Baustelleninfo_Sachsen_geojson.zip"
)

# VKZ-Allowlist: Stadt-Slug -> Verwaltungskennziffer (str-Vergleich, führende
# Nullen bleiben erhalten). [VERIFIED 2026-07-04] gegen die echte ZIP.
_SLUG_VKZ = {"dresden": "0014612", "leipzig": "0014713"}

# T-Q-02 Zip-Bomb-Schutz: Body-Cap VOR ZipFile-Open (echte ZIP ~2.5 MB) und
# Member-Cap (ZipInfo.file_size) VOR zf.read (echte Sperrungen-Datei ~3 MB).
_MAX_ZIP_BYTES = 32 * 1024 * 1024
_MAX_MEMBER_BYTES = 128 * 1024 * 1024

# GeoJSON-Member mit den Sperrungen (Namens-Match statt hartem Index, siehe
# fetch unten; dieser Name ist der [VERIFIED]-Stand).
_SPERRUNGEN_MEMBER_HINT = "sperrungen"


def utm33_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """ETRS89/UTM Zone 33N (EPSG:25833) -> WGS84 ``(lat, lon)``, Snyder-Reihen.

    Inverse transversale Mercator-Projektion: Zentralmeridian 15 Grad Ost,
    Maßstab k0=0.9996, false easting 500000 m, GRS80/WGS84-Ellipsoid (für
    diesen Zweck identisch). Gegenstück zur Vorwärtsformel
    ``ingest.boris_shapefile.wgs84_to_utm32`` (dort Zone 32). Footpoint-Breite
    per Reihenentwicklung, dann Snyder-Korrekturterme; Genauigkeit im
    Meter-Bereich (Owner-Vorgabe, reicht für Karten-Pins).
    """
    a = 6378137.0
    f = 1 / 298.257223563
    k0 = 0.9996
    lon0 = math.radians(15.0)
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    x = easting - 500000.0
    m = northing / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    t1 = math.tan(phi1) ** 2
    c1 = ep2 * cos_phi1**2
    n1 = a / math.sqrt(1 - e2 * sin_phi1**2)
    r1 = a * (1 - e2) / (1 - e2 * sin_phi1**2) ** 1.5
    d = x / (n1 * k0)

    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720
    )
    lon = (
        lon0
        + (
            d
            - (1 + 2 * t1 + c1) * d**3 / 6
            + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120
        )
        / cos_phi1
    )
    return (math.degrees(lat), math.degrees(lon))


def _first_coordinate(geometry: dict | None) -> tuple[float | None, float | None]:
    """Liest die erste Koordinate ``(x, y)`` defensiv aus einer GeoJSON-Geometrie.

    Point -> die Koordinate selbst, LineString -> erster Stützpunkt,
    MultiLineString -> erster Stützpunkt der ersten Linie, sonst ``(None, None)``.
    """
    if not isinstance(geometry, dict):
        return (None, None)
    coords = geometry.get("coordinates")
    gtype = geometry.get("type")
    if gtype == "Point":
        pair = coords
    elif gtype == "LineString":
        pair = coords[0] if isinstance(coords, list) and coords else None
    elif gtype == "MultiLineString":
        first_line = coords[0] if isinstance(coords, list) and coords else None
        pair = first_line[0] if isinstance(first_line, list) and first_line else None
    else:
        pair = None
    if (
        isinstance(pair, (list, tuple))
        and len(pair) >= 2
        and isinstance(pair[0], (int, float))
        and isinstance(pair[1], (int, float))
    ):
        return (float(pair[0]), float(pair[1]))
    return (None, None)


def _to_wgs84(x: float | None, y: float | None) -> tuple[float | None, float | None]:
    """Reprojiziert ``(x, y)`` aus EPSG:25833 nach WGS84 ``(lat, lon)``.

    Plausibilitäts-Guard: Werte, die schon wie Grad aussehen (``abs(x) <= 180``
    und ``abs(y) <= 90``), werden NICHT reprojiziert, sondern als GeoJSON-
    übliches ``[lon, lat]``-Paar gelesen (defensiv gegen einen stillen
    CRS-Wechsel der Quelle auf WGS84).
    """
    if x is None or y is None:
        return (None, None)
    if abs(x) <= 180 and abs(y) <= 90:
        return (y, x)
    return utm33_to_wgs84(x, y)


def _read_sperrungen_features(content: bytes) -> list[dict]:
    """Liest die Sperrungen-Features gehärtet aus den ZIP-Bytes (kein extractall).

    Voraussetzung: ``len(content)`` wurde bereits gegen ``_MAX_ZIP_BYTES``
    geprüft (Aufrufer-Vertrag). Der Sperrungen-Member wird defensiv per
    Namens-Match gefunden (``sperrungen`` + ``.geojson``, case-insensitiv);
    sein ``ZipInfo.file_size`` wird VOR ``zf.read`` gegen ``_MAX_MEMBER_BYTES``
    geprüft (T-Q-02). Kaputtes ZIP/GeoJSON -> leere Liste (T-Q-04, kein 500).
    """
    if not content or not content.startswith(b"PK"):
        return []
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return []
    with zf:
        member = next(
            (
                info
                for info in zf.infolist()
                if _SPERRUNGEN_MEMBER_HINT in info.filename.lower()
                and info.filename.lower().endswith(".geojson")
            ),
            None,
        )
        if member is None or member.file_size > _MAX_MEMBER_BYTES:
            return []
        try:
            data = json.loads(zf.read(member))
        except (KeyError, ValueError, zipfile.BadZipFile):
            return []
    features = data.get("features") if isinstance(data, dict) else None
    return features if isinstance(features, list) else []


async def fetch_sperrinfosys_road_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Holt die sachsenweiten Sperrungen und filtert sie auf die Stadt (VKZ).

    ``lat``/``lon`` sind vertragskonform Teil der Signatur (ungenutzt: der
    Stadt-Filter läuft über die Verwaltungskennziffer, nicht über Geometrie).
    Rückgabe: ``slug`` + ``events`` (je Sperrung ein schlankes dict mit
    Art/Typ/Grund, Zeitraum, Straße/Ortslage, Umleitung + lat/lon in WGS84).
    Leere ``events`` -> die Route antwortet ehrlich ``no_data``.
    """
    vkz = _SLUG_VKZ.get(slug)
    if vkz is None:
        return {"slug": slug, "events": []}

    resp = await http.get(_ZIP_URL)
    resp.raise_for_status()
    content = resp.content
    if len(content) > _MAX_ZIP_BYTES:
        # T-Q-02 DoS: zu großer Body -> leere Events (kein OOM, kein ZipFile).
        return {"slug": slug, "events": []}

    events: list[dict] = []
    for feature in _read_sperrungen_features(content):
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            continue
        if str(props.get("Verwaltungskennziffer")) != vkz:
            continue
        x, y = _first_coordinate(feature.get("geometry"))
        feat_lat, feat_lon = _to_wgs84(x, y)
        events.append(
            {
                "art": props.get("Sperrung_Art_Klartext"),
                "typ": props.get("Sperrung_Typ_Klartext"),
                "grund": props.get("Sperrung_Grund"),
                "von": props.get("Sperrung_von"),
                "bis": props.get("Sperrung_bis"),
                "strasse": props.get("Strasse"),
                "strassenklasse": props.get("Strassenklasse"),
                "ortslage": props.get("Ortslage"),
                "umleitung_ueber": props.get("Umleitung_ueber"),
                "lat": feat_lat,
                "lon": feat_lon,
            }
        )
    return {"slug": slug, "events": events}
