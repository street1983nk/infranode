"""Keyloser Denkmal-WFS-Adapter fetch_heritage (DATA-OSM-Tier-2, Denkmallisten).

Denkmalschutz ist in Deutschland LANDESsache: jedes Bundesland führt eine eigene
Denkmalliste, oft als WFS. Es gibt KEINEN bundesweiten Endpunkt. Daher ist der
Adapter foederiert: ``DENKMAL_WFS`` mappt das Bundesland-Kürzel
(``CityRegistryEntry.state``) auf eine WFS-Konfiguration. Ein neues Land erweitert
die Abdeckung automatisch (``registry.coverage`` leitet die Städte daraus ab).

Stand: Berlin (verifiziert, GeoJSON-WFS, DL-DE/Zero 2.0). Weitere Länder folgen,
sobald ihr WFS verifiziert ist (Hamburg liefert nur GML, NRW eigenes Schema ->
eigene Parser-Logik nötig; Bayern CC-BY-ND = NICHT nutzbar, fail-closed).

Sicherheit (T-SSRF): Host + typeName stammen ausschließlich aus der hartkodierten
``DENKMAL_WFS``-Registry (KEIN User-Input; ``state`` kommt aus dem validierten
Register). DoS-Schutz: ``count`` cappt die Feature-Zahl (analog Overpass
``out center``). Der Adapter ist rein (kein Cache/Breaker; das liefert die
Fassade); ``resp.raise_for_status()`` ist Pflicht (STALE-ON-ERROR-Pfad).
"""

from __future__ import annotations

import math
from typing import NamedTuple

import httpx

# Obergrenze der je Anfrage geladenen Denkmal-Features (DoS-/Groessenschutz). Die
# Antwort liefert Repräsentativpunkte, nicht die rohen (großen) Polygone.
_COUNT_CAP = 500

# DL-DE/BY 2.0 (Namensnennung) verlangt eine dreiteilige Quellenangabe inkl.
# Lizenz-URL; der URL steht je Quelle in ``license_url`` und wandert in die
# Attribution. Stadtstaaten-WFS (Berlin/Hamburg) sind bereits stadtscharf; ein
# Flächenland-WFS (BW/HE) liefert das GANZE Land -> ``bbox_filter=True`` grenzt
# per Stadt-Umkreis ein (Muster BORIS/land-values).
_BBOX_CRS = "urn:ogc:def:crs:EPSG::4326"


class DenkmalSource(NamedTuple):
    """WFS-Konfiguration eines Bundeslandes (Denkmalliste).

    ``fields`` nennt die Property-Schlüssel, die je Objekt über lat/lon hinaus
    ausgeliefert werden. ``license_id``/``license_tier``/``attribution``/
    ``license_url`` sind je Land verschieden (Berlin DL-DE/Zero, BW/HE/HH
    DL-DE/BY) und wandern in den CanonicalRecord. ``output_format`` ist der
    WFS-``outputFormat``-Wert (Hamburg spricht nur ``application/geo+json``).
    ``bbox_filter`` grenzt bei Flächenländern räumlich auf die Stadt ein.
    """

    url: str
    typename: str
    fields: tuple[str, ...]
    license_id: str
    license_tier: str
    attribution: str
    license_url: str
    output_format: str = "application/json"
    bbox_filter: bool = False


_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


# Bundesland-Kürzel -> WFS-Konfiguration. Nur verifizierte, offen lizenzierte
# Länder (fail-closed). Alle Endpunkte HTTP-verifiziert (GetCapabilities +
# GetFeature) 2026-07-02.
DENKMAL_WFS: dict[str, DenkmalSource] = {
    # Berlin (Stadtstaat): GetCapabilities-verifiziert 2026-06-26, DL-DE/Zero.
    "BE": DenkmalSource(
        url="https://gdi.berlin.de/services/wfs/denkmale",
        typename="denkmale:denkmale",
        fields=("typ", "link"),
        license_id="dl_de_zero_2_0",
        license_tier="A",
        attribution="Geoportal Berlin / Landesdenkmalamt Berlin, Denkmaldatenbank",
        license_url=_DL_DE_ZERO_URL,
    ),
    # Hamburg (Stadtstaat -> WFS bereits stadtscharf, kein bbox). Nur
    # ``application/geo+json``. typeName ``de.hh.up:gebaeude`` = Einzeldenkmale
    # (Gebäude); weitere typeNames (ensembles/symbolhaft) bewusst ausgelassen,
    # damit ein Objekt-Typ konsistent bleibt.
    "HH": DenkmalSource(
        url="https://geodienste.hamburg.de/HH_WFS_Denkmalschutz",
        typename="de.hh.up:gebaeude",
        fields=("bezeichnung", "bautyp", "baujahr", "info"),
        license_id="dl_de_by_2_0",
        license_tier="A",
        attribution="Freie und Hansestadt Hamburg, Denkmalschutzamt",
        license_url=_DL_DE_BY_URL,
        output_format="application/geo+json",
    ),
    # Baden-Württemberg (Flächenland -> bbox auf die Stadt). WFS-Proxy des LGL,
    # DL-DE/BY 2.0 (wörtlich in den Capabilities). typeName ohne Namensraum.
    "BW": DenkmalSource(
        url=(
            "https://owsproxy.lgl-bw.de/owsproxy/wfs/"
            "WFS_LAD_Kulturdenkmale_Bau_Kunstdenkmalpflege"
        ),
        typename="v_bau_kunstdenkmalpflege_kulturdenkmale",
        fields=("info",),
        license_id="dl_de_by_2_0",
        license_tier="A",
        attribution="Landesamt für Denkmalpflege im Regierungspräsidium Stuttgart",
        license_url=_DL_DE_BY_URL,
        bbox_filter=True,
    ),
    # Hessen (Flächenland -> bbox auf die Stadt). DenkXweb-WFS, DL-DE/BY 2.0
    # (geoportal.hessen.de/spatial-objects/342). typeName ``denkx:baudenkmal``.
    "HE": DenkmalSource(
        url="https://geodienste.denkx.de/geoserver/denkx/wfs",
        typename="denkx:baudenkmal",
        fields=("siteName", "siteDesignation", "publicationSource"),
        license_id="dl_de_by_2_0",
        license_tier="A",
        attribution="Landesamt für Denkmalpflege Hessen",
        license_url=_DL_DE_BY_URL,
        bbox_filter=True,
    ),
}


def _city_bbox_radius_deg(population: int | None) -> float:
    """Bounding-Box-Radius (Grad) aus der Einwohnerzahl (Muster BORIS).

    Größere Städte = größeres Stadtgebiet -> größerer Umkreis, geklammert auf
    [0.06, 0.30] Grad. Bewusst grob (Stadtkern-Umkreis, kein amtlicher Grenz-
    schnitt); ehrlich per ``truncated`` markiert, wenn der Umkreis mehr Denkmale
    enthält als ``_COUNT_CAP``.
    """
    pop = population or 0
    return min(0.30, max(0.06, 0.05 + pop / 16_000_000))


def _bbox_param(lat: float, lon: float, radius_deg: float) -> str:
    """WFS-2.0-``bbox``-Parameter in EPSG:4326 (Achsenreihenfolge lat,lon,crs).

    Die Längen-Halbkante wird mit ``1/cos(lat)`` gestreckt, damit die Box am
    Boden näherungsweise quadratisch bleibt (Muster BORIS, 2026-07-02 für
    denkx/LGL verifiziert: beide akzeptieren lat,lon mit explizitem CRS-URI).
    """
    dlat = radius_deg
    cos_lat = math.cos(math.radians(lat)) or 1.0
    dlon = radius_deg / cos_lat
    return f"{lat - dlat},{lon - dlon},{lat + dlat},{lon + dlon},{_BBOX_CRS}"


def _representative_point(geometry: dict | None) -> tuple[float | None, float | None]:
    """Mittelt alle Koordinaten einer GeoJSON-Geometrie zu einem Punkt (lat, lon).

    Denkmale sind oft (Multi-)Polygone; statt der großen Polygonringe liefern wir
    einen Repräsentativpunkt (Schwerpunkt der Stützpunkte). GeoJSON-Koordinaten
    sind ``[lon, lat]``. Robuste, defensive Rekursion über verschachtelte Listen.
    """
    if not isinstance(geometry, dict):
        return (None, None)
    lons: list[float] = []
    lats: list[float] = []

    def _collect(coords) -> None:
        if (
            isinstance(coords, (list, tuple))
            and len(coords) >= 2
            and isinstance(coords[0], (int, float))
            and isinstance(coords[1], (int, float))
        ):
            lons.append(float(coords[0]))
            lats.append(float(coords[1]))
            return
        if isinstance(coords, (list, tuple)):
            for part in coords:
                _collect(part)

    _collect(geometry.get("coordinates"))
    if not lons:
        return (None, None)
    return (round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6))


async def fetch_heritage(
    http: httpx.AsyncClient,
    *,
    slug: str,
    state: str,
    lat: float | None = None,
    lon: float | None = None,
    population: int | None = None,
) -> dict:
    """Holt Denkmale eines Bundeslandes per WFS GetFeature (GeoJSON, WGS84).

    ``state`` (Bundesland-Kürzel aus dem Register) wählt die WFS-Konfiguration;
    ein nicht abgedecktes Land löst ein ``KeyError`` aus (die Route prüft jedoch
    vorher ``is_covered`` und liefert dann ``not_covered``, sodass dieser Pfad nur
    für abgedeckte Länder erreicht wird).

    Bei Flächenländern (``bbox_filter=True``) liefert der Landes-WFS das GANZE
    Land; ``lat``/``lon``/``population`` grenzen dann per Stadt-Umkreis-``bbox``
    auf die Stadt ein (Muster BORIS). Stadtstaaten (Berlin/Hamburg) sind bereits
    stadtscharf und brauchen keinen bbox-Parameter.

    Rückgabe-Keys (das, was ``map_heritage`` erwartet): ``slug``, ``state``,
    ``fields``, ``license_id``/``license_tier``/``attribution``/``license_url``
    und ``features`` (rohe GeoJSON-FeatureCollection-Einträge).
    """
    src = DENKMAL_WFS[state]
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": src.typename,
        "count": str(_COUNT_CAP),
        "outputFormat": src.output_format,
        "srsName": "EPSG:4326",
    }
    # Flächenland: nur mit vorhandener Stadtkoordinate räumlich eingrenzen.
    # Fehlt sie (defensiv), fällt der Aufruf auf die ungefilterte (getruncte)
    # Landesliste zurück statt zu scheitern.
    if src.bbox_filter and lat is not None and lon is not None:
        params["bbox"] = _bbox_param(lat, lon, _city_bbox_radius_deg(population))
    resp = await http.get(src.url, params=params)
    resp.raise_for_status()
    data = resp.json()
    return {
        "slug": slug,
        "state": state,
        "fields": list(src.fields),
        "license_id": src.license_id,
        "license_tier": src.license_tier,
        "attribution": src.attribution,
        "license_url": src.license_url,
        "features": data.get("features", []),
        # Echter Gesamtbestand laut WFS (numberMatched, Audit 220) fuer ehrliche
        # Truncation; kann "unknown" sein -> dann None.
        "total_available": _coerce_count(data.get("numberMatched")),
    }


def _coerce_count(value) -> int | None:
    """WFS-``numberMatched`` defensiv zu ``int`` (oder ``None`` bei ``unknown``)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
