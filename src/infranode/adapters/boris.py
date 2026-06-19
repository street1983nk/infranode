"""Keyloser BORIS-Bodenrichtwerte-Adapter (DATA-35, Tier A).

BORIS (Bodenrichtwert-Informationssystem der Gutachterausschuesse) stellt die
amtlichen Bodenrichtwerte (BRW, EUR/m2 fuer Bauland) als offene Geodaten bereit.
BORIS-D ist ein Laender-Gemeinschaftsprojekt, aber die Dienste sind FOEDERIERT:
je Bundesland ein eigener WFS, KEIN bundesweiter Single-Endpoint. Deshalb mappt
``BORIS_WFS`` ein Bundesland-Kuerzel (``CityRegistryEntry.state``) auf eine
WFS-Config; ein Landes-WFS deckt alle Register-Staedte dieses Landes ab.

Das Modul ist die EINZIGE Quelle der BORIS-Abdeckung: ``registry.coverage``
leitet ``PARTIAL_COVERAGE["land-values"]`` aus ``BORIS_WFS`` + Register ab
(keine duplizierte Slug-Liste). Die WFS-Abfrage selbst laeuft NUR im Bulk-Ingest
(``ingest.boris``), NIE im Request-Pfad (die Route liest aus der SQLite).

Aggregation (Owner-Entscheidung 2026-06-19): pro Stadt eine Kennzahl
(Median/Min/Max des BRW + Zonenzahl + Stichtag) ueber eine Bounding-Box um das
Stadtzentrum (``bbox_radius_deg`` macht den Umkreis transparent, kein amtlicher
Stadtgrenzen-Schnitt). Stichtagsdaten (jaehrlich) -> Bulk-Ingest, kein Live-WFS.

Sicherheit (T-9-02 SSRF): Der WFS-Host steht je Config hartkodiert; die
Bounding-Box wird ausschliesslich aus (``lat``/``lon``) gebaut, nie aus einem
User-Host. Der Slug stammt aus dem Register-Allowlist, nie roher User-Input.

DoS-Schutz (T-9-DOS): ``count=1000`` je Seite, harter Seiten-Cap
(``_MAX_PAGES``), ``propertyName`` laesst die Geometrie weg
(``geometry: null``) -> kleine Payload.

Berlin [VERIFIED 2026-06-19]: WFS ``gdi.berlin.de/services/wfs/brw2026``,
FeatureType ``brw2026:brw2026_vector``, GeoJSON-Output, Property ``brw``
(EUR/m2), bbox in EPSG:4326 (Achsenreihenfolge lat,lon) akzeptiert,
Lizenz DL-DE/Zero 2.0. Stichtag 01.01.2026 (Layer-Name brw2026).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median

import httpx

# Seiten-Cap (T-9-DOS): max. _MAX_PAGES * _PAGE_SIZE Zonen je Stadt.
_PAGE_SIZE = 1000
_MAX_PAGES = 60
_TIMEOUT_S = 90.0


@dataclass(frozen=True)
class BorisWfsConfig:
    """WFS-Config eines Bundeslandes (BORIS, foederiert je Land).

    ``output_format`` ist aktuell nur ``"geojson"`` implementiert (Berlin); das
    AdV/INSPIRE-GML-Schema anderer Laender wird in einer Folge-Stufe ergaenzt.
    ``license_id``/``attribution``/``license_url`` werden je Land getragen (die
    Lizenzen variieren: Berlin = DL-DE/Zero 2.0) und vom Mapper unveraendert in
    den Record uebernommen.
    """

    url: str
    type_names: str
    value_field: str
    stichtag: str
    license_id: str
    attribution: str
    license_url: str
    land: str
    output_format: str = "geojson"
    # Nutzungsart-Feld (Bodennutzung). Ist es gesetzt, wird auf Bauland gefiltert
    # (Zonen, deren Nutzungsart mit einem ``building_prefixes``-Buchstaben beginnt:
    # W=Wohnen, M=Misch/Kern, G=Gewerbe/Gemeinbedarf). So fallen Wald/Wasser/
    # Landwirtschaft/Kleingarten (BRW nahe 0) aus der Kennzahl. None = alle Zonen.
    usage_field: str | None = None
    building_prefixes: tuple[str, ...] = ("W", "M", "G")


# Bundesland-Kuerzel (CityRegistryEntry.state) -> WFS-Config. Nur verifizierte,
# erreichbare Landes-WFS. Erweiterung (BB/NW/BY/HH/HE ...) = je ein Eintrag, sobald
# FeatureType + Wertfeld + "nur aktuelle Zonen"-Query je Land verifiziert sind.
BORIS_WFS: dict[str, BorisWfsConfig] = {
    # Berlin (Stadtstaat) [VERIFIED 2026-06-19].
    "BE": BorisWfsConfig(
        url="https://gdi.berlin.de/services/wfs/brw2026",
        type_names="brw2026:brw2026_vector",
        value_field="brw",
        stichtag="2026-01-01",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Bodenrichtwerte",
        license_url="https://www.govdata.de/dl-de/zero-2-0",
        land="Berlin",
        output_format="geojson",
        usage_field="nutzung",
    ),
}

_BBOX_CRS = "urn:ogc:def:crs:EPSG::4326"


def city_bbox_radius_deg(population: int | None) -> float:
    """Leitet den Bounding-Box-Radius (Grad, Breitenrichtung) aus der Einwohnerzahl ab.

    Groessere Staedte = groesseres Stadtgebiet -> groesserer Umkreis. Geklammert
    auf [0.06, 0.30] Grad (~6.7 bis ~33 km Halbkante in Nord-Sued-Richtung), damit
    Kleinstaedte nicht ueber-, Metropolen (Berlin ~0.25 Grad) nicht unterdeckt
    werden. Bewusst grob: die Kennzahl aggregiert ueber einen Stadtkern-Umkreis,
    keinen amtlichen Stadtgrenzen-Schnitt (siehe Modul-/Payload-Docstring).
    """
    pop = population or 0
    return min(0.30, max(0.06, 0.05 + pop / 16_000_000))


def _bbox(lat: float, lon: float, radius_deg: float) -> str:
    """Baut den WFS-2.0-bbox-Parameter in EPSG:4326 (Achsenreihenfolge lat,lon).

    Die Laengen-Halbkante wird mit ``1/cos(lat)`` gestreckt, damit die Box am
    Boden annaehernd quadratisch bleibt (ein Grad Laenge ist in DE schmaler als
    ein Grad Breite). [VERIFIED 2026-06-19]: der Berlin-WFS akzeptiert die
    lat,lon-Reihenfolge mit explizitem CRS-URI.
    """
    dlat = radius_deg
    cos_lat = math.cos(math.radians(lat)) or 1.0
    dlon = radius_deg / cos_lat
    return f"{lat - dlat},{lon - dlon},{lat + dlat},{lon + dlon},{_BBOX_CRS}"


def _to_float(value: object) -> float | None:
    """Parst einen BRW-Wert defensiv zu float (None/leer/<=0/Unsinn -> None)."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        num = float(value)
    except (ValueError, TypeError):
        return None
    return num if num > 0 else None


def _is_building_land(cfg: BorisWfsConfig, props: dict) -> bool:
    """True, wenn die Zone Bauland ist (Nutzungsart beginnt mit Bauland-Praefix).

    Ohne konfiguriertes ``usage_field`` gilt jede Zone (kein Filter). Sonst zaehlen
    nur Zonen, deren Nutzungsart-Text mit einem ``building_prefixes``-Buchstaben
    beginnt (Berlin z.B. "W1 - ...", "M2 - Mischgebiet", "G - Gewerbe"); Wald/
    Wasser/Landwirtschaft/Kleingarten (LF.../SF.../S...) fallen heraus.
    """
    if cfg.usage_field is None:
        return True
    usage = props.get(cfg.usage_field)
    if not isinstance(usage, str) or not usage:
        return False
    return usage[:1] in cfg.building_prefixes


def _fetch_brw_values(
    client: httpx.Client, cfg: BorisWfsConfig, *, bbox: str
) -> list[float]:
    """Holt die BRW-Bauland-Werte (EUR/m2) in der Bounding-Box (GeoJSON, paginiert).

    Fragt den WFS mit ``propertyName=<value_field>[,<usage_field>]`` (Geometrie
    weggelassen) und ``outputFormat=application/json`` ab, paginiert ueber
    ``startIndex`` bis keine Features mehr kommen ODER der Seiten-Cap
    (``_MAX_PAGES``) greift. Jeder Wert wird defensiv geparst (``_to_float``);
    ungueltige/<=0-Werte und Nicht-Bauland-Zonen (``_is_building_land``) fallen weg.
    """
    if cfg.output_format != "geojson":  # pragma: no cover - bis GML-Land aktiv
        msg = f"BORIS output_format '{cfg.output_format}' nicht unterstuetzt"
        raise ValueError(msg)

    property_name = cfg.value_field
    if cfg.usage_field is not None:
        property_name = f"{cfg.value_field},{cfg.usage_field}"

    values: list[float] = []
    start_index = 0
    for _ in range(_MAX_PAGES):
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": cfg.type_names,
            "outputFormat": "application/json",
            "propertyName": property_name,
            "count": _PAGE_SIZE,
            "startIndex": start_index,
            "bbox": bbox,
        }
        resp = client.get(cfg.url, params=params)
        resp.raise_for_status()
        body = resp.json()
        features = body.get("features", []) if isinstance(body, dict) else []
        if not features:
            break
        for feature in features:
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") or {}
            val = _to_float(props.get(cfg.value_field))
            if val is not None and _is_building_land(cfg, props):
                values.append(val)
        if len(features) < _PAGE_SIZE:
            break
        start_index += _PAGE_SIZE
    return values


def fetch_city_land_values(
    client: httpx.Client,
    *,
    slug: str,
    state: str,
    lat: float,
    lon: float,
    population: int | None = None,
) -> dict | None:
    """Aggregiert die Bodenrichtwerte EINER Stadt zu einer Kennzahl (live, Ingest).

    Schlaegt das Bundesland in ``BORIS_WFS`` nach (kein Eintrag -> ``None``, Stadt
    ist nicht abgedeckt), baut die Bounding-Box um (``lat``/``lon``) und holt alle
    BRW-Werte. Liefert ein schlankes dict (genau die Spalten, die ``ingest.boris``
    in die SQLite schreibt und ``map_land_values`` erwartet) oder ``None``, wenn
    kein Eintrag/keine Werte vorliegen (ehrliche Degradation, kein Crash).
    """
    cfg = BORIS_WFS.get(state)
    if cfg is None:
        return None

    radius = city_bbox_radius_deg(population)
    values = _fetch_brw_values(client, cfg, bbox=_bbox(lat, lon, radius))
    if not values:
        return None

    return {
        "slug": slug,
        "state": state,
        "brw_median_eur_m2": round(median(values), 2),
        "brw_min_eur_m2": round(min(values), 2),
        "brw_max_eur_m2": round(max(values), 2),
        "zone_count": len(values),
        "stichtag": cfg.stichtag,
        "bbox_radius_deg": round(radius, 4),
        "license_id": cfg.license_id,
        "attribution": cfg.attribution,
        "license_url": cfg.license_url,
    }
