"""Keyloser BORIS-Bodenrichtwerte-Adapter (DATA-35, Tier A).

BORIS (Bodenrichtwert-Informationssystem der Gutachterausschüsse) stellt die
amtlichen Bodenrichtwerte (BRW, EUR/m2 für Bauland) als offene Geodaten bereit.
BORIS-D ist ein Länder-Gemeinschaftsprojekt, aber die Dienste sind FOEDERIERT:
je Bundesland ein eigener WFS mit EIGENEM Schema. Deshalb mappt ``BORIS_WFS`` ein
Bundesland-Kürzel (``CityRegistryEntry.state``) auf eine WFS-Config; ein
Landes-WFS deckt alle Register-Städte dieses Landes ab.

Das Modul ist die EINZIGE Quelle der BORIS-Abdeckung: ``registry.coverage`` leitet
``PARTIAL_COVERAGE["land-values"]`` aus ``BORIS_WFS`` + Register ab (keine
duplizierte Slug-Liste). Die WFS-Abfrage läuft NUR im Bulk-Ingest
(``ingest.boris``), NIE im Request-Pfad (die Route liest aus der SQLite).

Aggregation (Owner-Entscheidung 2026-06-19): pro Stadt eine Kennzahl
(Median/Min/Max des Bauland-BRW + Zonenzahl + Stichtag) über eine Bounding-Box um
das Stadtzentrum (``bbox_radius_deg`` macht den Umkreis transparent, kein amtlicher
Stadtgrenzen-Schnitt). Stichtagsdaten (jährlich) -> Bulk-Ingest, kein Live-WFS.

Zwei Antwortformate (``output_format``), beide über ``bbox`` in EPSG:4326
(Achsenreihenfolge lat,lon, von allen angebundenen WFS akzeptiert):
- ``geojson``: Berlin (deegree-WFS mit GeoJSON-Output, Property ``brw``).
- ``gml``: die AdV-konformen Landes-WFS (Hessen/Niedersachsen/Bremen), nur GML.
  Geparst wird mit stdlib ``ElementTree`` über LOKALE Tag-Namen (die
  Namespace-URIs unterscheiden sich je Land, die lokalen Elementnamen
  ``bodenrichtwert``/``entwicklungszustand``/``art`` sind einheitlich).

Bauland-Filter: nur Bauland zählt (Wohnen/Misch/Gewerbe), Wald/Wasser/
Landwirtschaft (BRW nahe 0) fallen heraus. Berlin über die Nutzungsart
(``usage_field``-Präfix W/M/G), die AdV-WFS über den Entwicklungszustand
(``entwicklung_field`` == "B" baureifes Land).

Sicherheit (T-9-02 SSRF): Der WFS-Host steht je Config hartkodiert; die
Bounding-Box wird ausschließlich aus (``lat``/``lon``) gebaut, nie aus einem
User-Host. Der Slug stammt aus dem Register-Allowlist, nie roher User-Input.

DoS-Schutz (T-9-DOS): Seiten-Cap (``_MAX_PAGES``), XML-Größen-Guard
(``_MAX_GML_BYTES``, T-9-01) vor dem Parsen.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from statistics import median
from xml.etree.ElementTree import ParseError, fromstring  # noqa: S405

import httpx

logger = logging.getLogger(__name__)

# Seiten-Cap (T-9-DOS): max. _MAX_PAGES * page_size Zonen je Stadt.
_MAX_PAGES = 60
_GEOJSON_PAGE = 1000
# GML trägt die Polygon-Geometrie mit (propertyName unzuverlässig je Server) ->
# kleinere Seiten + großzügiger Byte-Guard (nur Offline-Ingest, kein Request-Pfad).
_GML_PAGE = 500
_MAX_GML_BYTES = 96 * 1024 * 1024
_TIMEOUT_S = 120.0
_BBOX_CRS = "urn:ogc:def:crs:EPSG::4326"


@dataclass(frozen=True)
class BorisWfsConfig:
    """WFS-Config eines Bundeslandes (BORIS, föderiert je Land).

    ``output_format``: ``"geojson"`` (Berlin) oder ``"gml"`` (AdV-Landes-WFS).
    ``value_field`` ist bei GeoJSON der Property-Name, bei GML der LOKALE
    Elementname des Wertes. ``feature_localname`` (nur GML) ist der lokale Name des
    Feature-Elements (z.B. ``BR_BodenrichtwertZonal``). Lizenz/Attribution werden je
    Land getragen (variieren) und vom Mapper unverändert in den Record übernommen.

    Bauland-Filter (eines von beiden): ``usage_field`` (Nutzungsart-Präfix in
    ``building_prefixes``, Berlin) ODER ``entwicklung_field`` (Entwicklungszustand
    in ``building_codes``, AdV-WFS). Ist keiner gesetzt, zählt jede Zone.
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
    feature_localname: str = ""
    usage_field: str | None = None
    building_prefixes: tuple[str, ...] = ("W", "M", "G")
    entwicklung_field: str | None = None
    building_codes: tuple[str, ...] = ()
    extra_params: dict[str, str] = field(default_factory=dict)
    # Räumliche Eingrenzung auf die Stadt: "bbox" (Umkreis-Bounding-Box) oder
    # "ags" (OGC-Filter auf den amtlichen Gemeindeschlüssel; exakt, für WFS ohne
    # bbox-Unterstützung). Bei "ags": ``ags_filter_kind`` = "flat" (ein Feld
    # ``ags_value_ref`` == 8-stelliger AGS, Thüringen) oder "bb_nested" (AdV-
    # Brandenburg, verschachtelter kreis+gemeinde-Pfad). ``namespaces`` ist der
    # WFS-NAMESPACES-Parameter (Brandenburg-Pflicht). ``stichtag_field`` (lokaler
    # Tag) erlaubt das Filtern auf den JÜNGSTEN Stichtag je Stadt (gemischte
    # Jahrgänge im selben Layer).
    filter_mode: str = "bbox"
    ags_filter_kind: str = ""
    ags_value_ref: str = ""
    namespaces: str = ""
    stichtag_field: str | None = None
    # True, wenn der Landes-WFS NORMIERTE Bodenrichtwerte liefert (auf 1000 m2/
    # GFZ 1.0 normiert, "nicht zur Wertermittlung geeignet"; Hamburg). Solche Werte
    # sind NICHT cross-city-vergleichbar -> als Methoden-Hinweis im Payload führen.
    normalized: bool = False


# Attribution-Wortlaute je Land (DL-DE verlangt Namensnennung). Verbatim auch in
# DATA-LICENSES.md.
BORIS_WFS: dict[str, BorisWfsConfig] = {
    # Berlin (Stadtstaat) [VERIFIED 2026-06-19] - GeoJSON, Nutzungsart-Filter.
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
    # Hessen [VERIFIED 2026-06-19] - AdV-GML, Entwicklungszustand-Filter (B=Bauland).
    # Jahrgang in der URL; 2024 ist der aktuell publizierte Stichtag.
    "HE": BorisWfsConfig(
        url="https://www.gds.hessen.de/wfs2/boris/cgi-bin/brw/2024/wfs",
        type_names="boris:BR_BodenrichtwertZonal",
        value_field="bodenrichtwert",
        stichtag="2024-01-01",
        license_id="dl_de_zero_2_0",
        attribution=(
            "Hessische Verwaltung für Bodenmanagement und Geoinformation (HVBG)"
        ),
        license_url="https://www.govdata.de/dl-de/zero-2-0",
        land="Hessen",
        output_format="gml",
        feature_localname="BR_BodenrichtwertZonal",
        entwicklung_field="entwicklungszustand",
        building_codes=("B",),
    ),
    # Niedersachsen [VERIFIED 2026-06-19] - AdV-GML (LGLN-Doorman, noauth).
    "NI": BorisWfsConfig(
        url="https://opendata.lgln.niedersachsen.de/doorman/noauth/boris_wfs",
        type_names="boris:BR_BodenrichtwertZonal",
        value_field="bodenrichtwert",
        stichtag="2026-01-01",
        license_id="dl_de_by_2_0",
        attribution=(
            "Landesamt für Geoinformation und Landesvermessung Niedersachsen (LGLN)"
        ),
        license_url="https://www.govdata.de/dl-de/by-2-0",
        land="Niedersachsen",
        output_format="gml",
        feature_localname="BR_BodenrichtwertZonal",
        entwicklung_field="entwicklungszustand",
        building_codes=("B",),
    ),
    # Bremen [VERIFIED 2026-06-19] - AdV-GML (LGLN-Doorman; enthält auch NI-Zonen,
    # die bbox um Bremen grenzt sie raus).
    "HB": BorisWfsConfig(
        url="https://opendata.lgln.niedersachsen.de/doorman/noauth/borishb_2026_wfs",
        type_names="boris:BR_BodenrichtwertZonal",
        value_field="bodenrichtwert",
        stichtag="2026-01-01",
        license_id="dl_de_by_2_0",
        attribution="Landesamt GeoInformation Bremen",
        license_url="https://www.govdata.de/dl-de/by-2-0",
        land="Bremen",
        output_format="gml",
        feature_localname="BR_BodenrichtwertZonal",
        entwicklung_field="entwicklungszustand",
        building_codes=("B",),
    ),
    # Brandenburg [VERIFIED 2026-06-19] - AdV-GML, KEIN bbox (Exception) -> exakter
    # AGS-Filter (verschachtelter kreis+gemeinde-Pfad). Gemischte Jahrgänge ->
    # jüngster Stichtag clientseitig. Bauland via entwicklungszustand=1000.
    "BB": BorisWfsConfig(
        url="https://isk.geobasis-bb.de/ows/boris_wfs",
        type_names="br:BR_Bodenrichtwert",
        value_field="bodenrichtwert",
        stichtag="2026-01-01",
        license_id="dl_de_by_2_0",
        attribution="GeoBasis-DE/LGB (Land Brandenburg)",
        license_url="https://www.govdata.de/dl-de/by-2-0",
        land="Brandenburg",
        output_format="gml",
        feature_localname="BR_Bodenrichtwert",
        entwicklung_field="entwicklungszustand",
        building_codes=("1000",),
        stichtag_field="stichtag",
        filter_mode="ags",
        ags_filter_kind="bb_nested",
        namespaces=(
            "xmlns(br,http://www.adv-online.de/namespaces/adv/br/3.0),"
            "xmlns(adv,http://www.adv-online.de/namespaces/adv/gid/7.1)"
        ),
    ),
    # Thüringen [VERIFIED 2026-06-19] - vBORIS-GML, flacher AGS-Filter (GEMEINDE =
    # 8-stellig). Gemischte Jahrgänge -> jüngster Stichtag clientseitig. Bauland
    # via ENTWICKLUNGSZUSTAND=1000 (UPPERCASE-Felder).
    "TH": BorisWfsConfig(
        url="https://www.geoproxy.geoportal-th.de/geoproxy/services/boris/vBORIS_simple_wfs",
        type_names="boris:bodenrichtwertzone",
        value_field="BODENRICHTWERT",
        stichtag="2026-01-01",
        license_id="dl_de_by_2_0",
        attribution=(
            "Thüringer Landesamt für Bodenmanagement und Geoinformation (TLBG)"
        ),
        license_url="https://www.govdata.de/dl-de/by-2-0",
        land="Thüringen",
        output_format="gml",
        feature_localname="bodenrichtwertzone",
        entwicklung_field="ENTWICKLUNGSZUSTAND",
        building_codes=("1000",),
        stichtag_field="STICHTAG",
        filter_mode="ags",
        ags_filter_kind="flat",
        ags_value_ref="GEMEINDE",
    ),
    # Mecklenburg-Vorpommern [VERIFIED 2026-06-19] - MapServer-GML, bbox-4326. Die
    # Bauland-Layer sind nach Nutzung getrennt (kein Entwicklungszustand-Filter
    # nötig); Wertfeld ``brwkon``. Ein Stichtag (2024). Lizenz CC BY 4.0.
    "MV": BorisWfsConfig(
        url="https://www.geodaten-mv.de/dienste/bodenrichtwerte_wfs",
        type_names=(
            "boris:wohnbauflaeche,boris:gewerbliche_bauflaeche,"
            "boris:gemischte_bauflaeche,boris:sonderbauflaeche,"
            "boris:bebaute_flaeche_im_aussenbereich"
        ),
        value_field="brwkon",
        stichtag="2024-01-01",
        license_id="cc_by_4_0",
        attribution=(
            "Gutachterausschüsse für Grundstückswerte in "
            "Mecklenburg-Vorpommern (GeoPortal.MV)"
        ),
        license_url="https://creativecommons.org/licenses/by/4.0/",
        land="Mecklenburg-Vorpommern",
        output_format="gml",
        feature_localname=(
            "wohnbauflaeche,gewerbliche_bauflaeche,gemischte_bauflaeche,"
            "sonderbauflaeche,bebaute_flaeche_im_aussenbereich"
        ),
    ),
    # Hamburg [VERIFIED 2026-06-19] - GML (GeoJSON kaputt), bbox-4326. NUR NORMIERTE
    # Bodenrichtwerte (auf 1000 m2/GFZ 1.0 normiert, "nicht zur Wertermittlung
    # geeignet" - grober Indikator). Bauland-Layer nach Nutzung getrennt (efh/mfh/
    # bh/gh/pl). Wertfeld ``minimaler_normierter_brw``. Ein Stichtag (2026).
    "HH": BorisWfsConfig(
        url="https://geodienste.hamburg.de/HH_WFS_UEKnormierteBodenrichtwerte",
        type_names=(
            "app:lgv_brw_uek_efh,app:lgv_brw_uek_mfh,app:lgv_brw_uek_bh,"
            "app:lgv_brw_uek_gh,app:lgv_brw_uek_pl"
        ),
        value_field="minimaler_normierter_brw",
        stichtag="2026-01-01",
        license_id="dl_de_by_2_0",
        attribution=(
            "Freie und Hansestadt Hamburg, Landesbetrieb Geoinformation "
            "und Vermessung (LGV)"
        ),
        license_url="https://www.govdata.de/dl-de/by-2-0",
        land="Hamburg",
        output_format="gml",
        feature_localname=(
            "lgv_brw_uek_efh,lgv_brw_uek_mfh,lgv_brw_uek_bh,"
            "lgv_brw_uek_gh,lgv_brw_uek_pl"
        ),
        normalized=True,  # nur normierte BRW (nicht cross-city-vergleichbar)
    ),
}


@dataclass(frozen=True)
class BorisShapefileConfig:
    """Download-Config eines Bundeslandes OHNE offenen WFS (NW/ST, nur Shapefile).

    Reine Daten (kein pyshp-Import hier - der läuft NUR im Offline-Ingest
    ``ingest.boris_shapefile``, nie im Live-Request-Pfad). ``shp_glob`` wählt die
    relevante .shp im ZIP (z.B. der Bauland-Layer bei ST). ``ags_field`` (dbf) ist
    der 8-stellige Gemeindeschlüssel für den Stadt-Filter (NW); ist er ``None``
    (ST hat kein AGS-Feld), wird über die Geometrie-Bounding-Box gefiltert.
    ``value_decimal_comma`` behandelt das deutsche Dezimalkomma (NW: "1,1").
    """

    url: str
    shp_glob: str
    value_field: str
    license_id: str
    attribution: str
    license_url: str
    land: str
    value_decimal_comma: bool = False
    ags_field: str | None = None
    entwicklung_field: str | None = None
    building_codes: tuple[str, ...] = ()
    crs_epsg: int = 25832


# Bundesländer OHNE offenen WFS, aber mit offenem Shapefile-Download (DATA-35,
# Welle 4). Coverage wird zusammen mit BORIS_WFS abgeleitet.
BORIS_SHAPEFILE: dict[str, BorisShapefileConfig] = {
    # NRW [VERIFIED 2026-06-19] - landesweites Shapefile (~212 MB), AGS-Feld GESL,
    # Bauland via ENTW='B', BRW mit Dezimalkomma. dl-de/zero.
    "NW": BorisShapefileConfig(
        url=(
            "https://www.opengeodata.nrw.de/produkte/infrastruktur_bauen_wohnen/"
            "boris/BRW/BRW_EPSG25832_Shape.zip"
        ),
        shp_glob="*.shp",
        value_field="BRW",
        value_decimal_comma=True,
        ags_field="GESL",
        entwicklung_field="ENTW",
        building_codes=("B",),
        license_id="dl_de_zero_2_0",
        attribution="Land NRW / GeoBasis NRW",
        license_url="https://www.govdata.de/dl-de/zero-2-0",
        land="Nordrhein-Westfalen",
    ),
    # Sachsen-Anhalt [VERIFIED 2026-06-19] - ZIP (~47 MB) mit eigenem Bauland-Layer
    # (bereits ENTWZ='B' gefiltert), KEIN AGS-Feld -> Stadt-Filter per Geometrie-
    # Bounding-Box. dl-de/by.
    "ST": BorisShapefileConfig(
        url=(
            "https://geodatenportal.sachsen-anhalt.de/gfds/datei/anzeigen/"
            "id/646905,501/BRW_20260101.ZIP"
        ),
        shp_glob="*BRW_Bauland*.shp",
        value_field="BRW",
        ags_field=None,
        license_id="dl_de_by_2_0",
        attribution="© GeoBasis-DE / LVermGeo LSA, dl-de/by-2-0",
        license_url="https://www.govdata.de/dl-de/by-2-0",
        land="Sachsen-Anhalt",
    ),
}


def city_bbox_radius_deg(population: int | None) -> float:
    """Leitet den Bounding-Box-Radius (Grad, Breitenrichtung) aus der Einwohnerzahl ab.

    Größere Städte = größeres Stadtgebiet -> größerer Umkreis. Geklammert
    auf [0.06, 0.30] Grad (~6.7 bis ~33 km Halbkante Nord-Süd), damit Kleinstädte
    nicht über-, Metropolen (Berlin ~0.25 Grad) nicht unterdeckt werden. Bewusst
    grob: aggregiert über einen Stadtkern-Umkreis, keinen amtlichen Grenzschnitt.
    """
    pop = population or 0
    return min(0.30, max(0.06, 0.05 + pop / 16_000_000))


def _bbox(lat: float, lon: float, radius_deg: float) -> str:
    """Baut den WFS-2.0-bbox-Parameter in EPSG:4326 (Achsenreihenfolge lat,lon).

    Die Längen-Halbkante wird mit ``1/cos(lat)`` gestreckt, damit die Box am Boden
    annähernd quadratisch bleibt. [VERIFIED 2026-06-19]: alle angebundenen WFS
    akzeptieren die lat,lon-Reihenfolge mit explizitem CRS-URI.
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


def _is_building_land_geojson(cfg: BorisWfsConfig, props: dict) -> bool:
    """True, wenn die GeoJSON-Zone Bauland ist (Nutzungsart-Präfix, Berlin).

    Ohne ``usage_field`` gilt jede Zone. Sonst zählen nur Zonen, deren
    Nutzungsart-Text mit einem ``building_prefixes``-Buchstaben beginnt (W/M/G).
    """
    if cfg.usage_field is None:
        return True
    usage = props.get(cfg.usage_field)
    if not isinstance(usage, str) or not usage:
        return False
    return usage[:1] in cfg.building_prefixes


def _localname(tag: str) -> str:
    """Lokaler Elementname ohne Namespace ('{uri}brw' -> 'brw')."""
    return tag.rsplit("}", 1)[-1]


def _fetch_geojson_values(
    client: httpx.Client, cfg: BorisWfsConfig, *, bbox: str
) -> tuple[list[float], bool]:
    """Holt die Bauland-BRW-Werte (EUR/m2) per GeoJSON, paginiert (Berlin).

    Liefert ``(Werte, truncated)``. ``truncated`` ist ``True``, wenn der Seiten-Cap
    ``_MAX_PAGES`` erreicht wurde, OHNE dass die letzte Seite leer/teilgefuellt war
    (also noch weitere Zonen vorlägen) - statt die Kappung still zu verschweigen.
    """
    property_name = cfg.value_field
    if cfg.usage_field is not None:
        property_name = f"{cfg.value_field},{cfg.usage_field}"

    values: list[float] = []
    start_index = 0
    truncated = False
    for _ in range(_MAX_PAGES):
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": cfg.type_names,
            "outputFormat": "application/json",
            "propertyName": property_name,
            "count": _GEOJSON_PAGE,
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
            if val is not None and _is_building_land_geojson(cfg, props):
                values.append(val)
        if len(features) < _GEOJSON_PAGE:
            break
        start_index += _GEOJSON_PAGE
    else:
        # Schleife voll durchlaufen, ohne dass eine Seite teilgefüllt war
        # -> die letzte Seite war voll, es hätten weitere Zonen folgen können.
        truncated = True
    return values, truncated


def _parse_gml_page(
    cfg: BorisWfsConfig, xml_bytes: bytes
) -> tuple[list[tuple[float, str | None]], int]:
    """Parst eine GML-Seite (stdlib): liefert ((Wert, Stichtag)-Liste, #Features).

    Größen-Guard (T-9-01) vor dem Parsen; ungültiges XML -> ([], 0). Je Feature
    (lokaler Name ``feature_localname``) werden Wert (``value_field``), ggf.
    Entwicklungszustand (``entwicklung_field``) und ggf. Stichtag (``stichtag_field``)
    per LOKALEM Tag-Namen gelesen; Nicht-Bauland (entwicklung nicht in
    ``building_codes``) und <=0 fallen weg. Der Stichtag wird durchgereicht, damit
    der Aufrufer auf den jüngsten Jahrgang filtern kann.
    """
    if not xml_bytes or len(xml_bytes) > _MAX_GML_BYTES:
        return [], 0
    try:
        root = fromstring(xml_bytes)  # noqa: S314 - Guard oben, stdlib (T-9-01)
    except ParseError:
        return [], 0

    # feature_localname kann eine Komma-Liste sein (Länder mit mehreren
    # Bauland-Layern, z.B. MV wohnbaufläche,gewerbliche_bauflaeche,...).
    feature_names = frozenset(cfg.feature_localname.split(","))

    rows: list[tuple[float, str | None]] = []
    n_features = 0
    for feature in root.iter():
        if _localname(feature.tag) not in feature_names:
            continue
        n_features += 1
        raw_value: str | None = None
        entwicklung: str | None = None
        stichtag: str | None = None
        for el in feature.iter():
            ln = _localname(el.tag)
            if ln == cfg.value_field:
                raw_value = el.text
            elif cfg.entwicklung_field and ln == cfg.entwicklung_field:
                entwicklung = (el.text or "").strip()
            elif cfg.stichtag_field and ln == cfg.stichtag_field:
                stichtag = (el.text or "").strip()
        val = _to_float(raw_value)
        if val is None:
            continue
        if cfg.entwicklung_field and entwicklung not in cfg.building_codes:
            continue
        rows.append((val, stichtag))
    return rows, n_features


def _latest_stichtag_values(
    rows: list[tuple[float, str | None]],
) -> tuple[list[float], str | None]:
    """Reduziert (Wert, Stichtag)-Zeilen auf die Werte des JÜNGSTEN Stichtags.

    Liefert (Werte, jüngster-Stichtag). Ist kein Stichtag vorhanden (alle ``None``,
    z.B. Single-Jahrgang-Layer), werden alle Werte behalten und der Stichtag ist
    ``None`` (der Aufrufer fällt auf ``cfg.stichtag`` zurück). ISO-Datumsstrings
    sortieren lexikografisch korrekt.
    """
    stichtage = [s for _, s in rows if s]
    if not stichtage:
        return [v for v, _ in rows], None
    newest = max(stichtage)
    return [v for v, s in rows if s == newest], newest


def _paginate_gml(
    client: httpx.Client, cfg: BorisWfsConfig, base_params: dict
) -> tuple[list[tuple[float, str | None]], bool]:
    """Paginiert eine GML-GetFeature-Abfrage -> ((Wert, Stichtag)-Zeilen, truncated).

    ``truncated`` ist ``True``, wenn der Seiten-Cap ``_MAX_PAGES`` erreicht wurde,
    ohne dass eine Seite weniger als ``_GML_PAGE`` Features hatte (es hätten also
    weitere Features gefolgt) - die stille Kappung wird so sichtbar gemacht.
    """
    rows: list[tuple[float, str | None]] = []
    start_index = 0
    truncated = False
    for _ in range(_MAX_PAGES):
        params = {
            **base_params,
            "count": _GML_PAGE,
            "startIndex": start_index,
            **cfg.extra_params,
        }
        resp = client.get(cfg.url, params=params)
        resp.raise_for_status()
        page_rows, n_features = _parse_gml_page(cfg, resp.content)
        rows.extend(page_rows)
        if n_features < _GML_PAGE:
            break
        start_index += _GML_PAGE
    else:
        truncated = True
    return rows, truncated


def _fetch_gml_values(
    client: httpx.Client, cfg: BorisWfsConfig, *, bbox: str
) -> tuple[list[float], str | None, bool]:
    """Holt die Bauland-BRW-Werte per GML+bbox (AdV-Landes-WFS, ein Jahrgang).

    Liefert ``(Werte, Stichtag, truncated)``.
    """
    rows, truncated = _paginate_gml(
        client,
        cfg,
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": cfg.type_names,
            "bbox": bbox,
        },
    )
    values, stichtag = _latest_stichtag_values(rows)
    return values, stichtag, truncated


def _build_ags_filter(cfg: BorisWfsConfig, ags: str) -> str:
    """Baut den OGC-Filter (fes 2.0) für den Stadt-Filter über den AGS.

    ``flat``: ein Feld == 8-stelliger AGS (Thüringen ``GEMEINDE``). ``bb_nested``:
    AdV-Brandenburg, getrennt nach ``adv:kreis`` (AGS-Stellen 4-5) und
    ``adv:gemeinde`` (Stellen 6-8). Jeweils zusätzlich Bauland
    (``entwicklung_field`` == ``building_codes[0]``); der jüngste Stichtag wird
    NICHT im Filter, sondern clientseitig (``_latest_stichtag_values``) gewählt.
    """
    fes = 'xmlns:fes="http://www.opengis.net/fes/2.0"'
    code = cfg.building_codes[0] if cfg.building_codes else ""

    def eq(ref: str, literal: str) -> str:
        return (
            f"<fes:PropertyIsEqualTo><fes:ValueReference>{ref}</fes:ValueReference>"
            f"<fes:Literal>{literal}</fes:Literal></fes:PropertyIsEqualTo>"
        )

    clauses: list[str] = []
    if cfg.ags_filter_kind == "bb_nested":
        base = "br:gemeinde/adv:AX_Gemeindekennzeichen"
        clauses.append(eq(f"{base}/adv:kreis", ags[3:5]))
        clauses.append(eq(f"{base}/adv:gemeinde", ags[5:8]))
        # AdV-Brandenburg verlangt den br:-Namespace-Präfix in der ValueReference
        # (der GML-Parser nutzt dagegen den lokalen Namen ohne Präfix).
        if cfg.entwicklung_field and code:
            clauses.append(eq(f"br:{cfg.entwicklung_field}", code))
    else:  # flat (Thüringen): unqualifizierte Feldnamen
        clauses.append(eq(cfg.ags_value_ref, ags))
        if cfg.entwicklung_field and code:
            clauses.append(eq(cfg.entwicklung_field, code))

    inner = "".join(clauses)
    if len(clauses) > 1:
        inner = f"<fes:And>{inner}</fes:And>"
    return f"<fes:Filter {fes}>{inner}</fes:Filter>"


def _fetch_ags_values(
    client: httpx.Client, cfg: BorisWfsConfig, *, ags: str
) -> tuple[list[float], str | None, bool]:
    """Holt die Bauland-BRW-Werte EINER Stadt per OGC-AGS-Filter (BB, TH).

    Liefert ``(Werte, Stichtag, truncated)``.
    """
    base_params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": cfg.type_names,
        "filter": _build_ags_filter(cfg, ags),
    }
    if cfg.namespaces:
        base_params["namespaces"] = cfg.namespaces
    rows, truncated = _paginate_gml(client, cfg, base_params)
    values, stichtag = _latest_stichtag_values(rows)
    return values, stichtag, truncated


def _fetch_brw_values(
    client: httpx.Client,
    cfg: BorisWfsConfig,
    *,
    bbox: str,
    ags: str | None,
) -> tuple[list[float], str | None, bool]:
    """Dispatch nach ``filter_mode`` (ags) bzw. ``output_format`` (geojson | gml).

    Rückgabe ``(Werte, aufgelöster-Stichtag, truncated)``; Stichtag ``None`` ->
    Aufrufer nutzt ``cfg.stichtag``. ``truncated`` meldet den Seiten-Cap.
    """
    if cfg.filter_mode == "ags":
        if not ags:
            return [], None, False
        return _fetch_ags_values(client, cfg, ags=ags)
    if cfg.output_format == "geojson":
        values, truncated = _fetch_geojson_values(client, cfg, bbox=bbox)
        return values, None, truncated
    if cfg.output_format == "gml":
        return _fetch_gml_values(client, cfg, bbox=bbox)
    raise ValueError(f"BORIS output_format '{cfg.output_format}' nicht unterstuetzt")


def fetch_city_land_values(
    client: httpx.Client,
    *,
    slug: str,
    state: str,
    lat: float,
    lon: float,
    population: int | None = None,
    ags: str | None = None,
) -> dict | None:
    """Aggregiert die Bodenrichtwerte EINER Stadt zu einer Kennzahl (live, Ingest).

    Schlägt das Bundesland in ``BORIS_WFS`` nach (kein Eintrag -> ``None``, Stadt
    ist nicht abgedeckt) und holt alle Bauland-BRW-Werte: per Bounding-Box um
    (``lat``/``lon``) ODER, bei ``filter_mode="ags"`` (WFS ohne bbox), per exaktem
    OGC-Filter auf den amtlichen Gemeindeschlüssel ``ags``. Liefert ein schlankes
    dict (genau die Spalten, die ``ingest.boris`` schreibt und ``map_land_values``
    erwartet) oder ``None``, wenn kein Eintrag/keine Werte vorliegen.

    ``bbox_radius_deg`` ist ``None`` im AGS-Modus (exakter Stadtschnitt, kein
    Umkreis); im bbox-Modus der genutzte Radius (Methoden-Transparenz).
    """
    cfg = BORIS_WFS.get(state)
    if cfg is None:
        return None

    radius = city_bbox_radius_deg(population)
    values, resolved_stichtag, truncated = _fetch_brw_values(
        client, cfg, bbox=_bbox(lat, lon, radius), ags=ags
    )
    if not values:
        return None

    if truncated:
        # Seiten-Cap erreicht: die Aggregation deckt nicht alle Zonen ab. Sichtbar
        # machen (Log + Payload-Flag), statt eine Teilmenge still als vollständig
        # auszuweisen (Audit 2026-06-29).
        logger.warning(
            "BORIS-Paginierung fuer %s (%s) am Seiten-Cap (_MAX_PAGES=%d) gekappt; "
            "Aggregation unvollstaendig (truncated=True).",
            slug,
            state,
            _MAX_PAGES,
        )

    return {
        "slug": slug,
        "state": state,
        "brw_median_eur_m2": round(median(values), 2),
        "brw_min_eur_m2": round(min(values), 2),
        "brw_max_eur_m2": round(max(values), 2),
        "zone_count": len(values),
        "stichtag": resolved_stichtag or cfg.stichtag,
        "bbox_radius_deg": None if cfg.filter_mode == "ags" else round(radius, 4),
        "normalized": cfg.normalized,
        "truncated": truncated,
        "license_id": cfg.license_id,
        "attribution": cfg.attribution,
        "license_url": cfg.license_url,
    }
