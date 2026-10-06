"""Keyloser Baumkataster-WFS-Adapter fetch_trees (DATA-OSM-Tier-2, Baumkataster).

Städtische Baumkataster sind KOMMUNALES Open Data: jede Stadt führt ihr eigenes
Kataster, meist als WFS. Es gibt keinen bundesweiten Endpunkt. Der Adapter ist
daher per STADT konfiguriert: ``BAUM_WFS`` mappt einen Stadt-Slug auf eine WFS-
Konfiguration (analog zur föderierten ``HERITAGE_WFS``, dort je Bundesland).

Stand: Berlin (verifiziert, GeoJSON-WFS, DL-DE/Zero 2.0; ~900k Straßenbäume).
Weitere Städte (Hamburg/Koeln/Frankfurt) folgen nach WFS-Verifikation.

Groessenschutz: Kataster sind sehr groß (Berlin > 900.000 Bäume); ``count``
cappt die je Anfrage geladene Feature-Zahl (Stichprobe, kein Vollabzug). Die
Antwort liefert je Baum den Punkt + ausgewählte Attribute (Art, Pflanzjahr,
Höhe, Straße, Bezirk).

Sicherheit (T-SSRF): Host + typeName stammen ausschließlich aus der hartkodierten
``BAUM_WFS``-Registry (KEIN User-Input). Rein (kein Cache/Breaker, das liefert die
Fassade); ``resp.raise_for_status()`` ist Pflicht (STALE-ON-ERROR).
"""

from __future__ import annotations

from typing import NamedTuple

import httpx

# Obergrenze der je Anfrage geladenen Baum-Features (Größen-/DoS-Schutz). Kataster
# sind sehr groß -> bewusste Stichprobe, in der Doku als gedeckelt gekennzeichnet.
# Der Cap ist so gewählt, dass der Worst-Case unter dem GPT-Actions-Antwortlimit
# (~100 KB) bleibt. Seit dem Entfernen der abgekündigten Roh-Duplikate
# (2026-08-31, angekündigt 2026-08-01) trägt jedes Item NUR die kanonischen
# englischen Keys und ist damit gut halb so groß wie zur Übergangszeit
# (Berlin-Worst-Case damals 395 B mit Duplikaten); 350 x ~220 B plus ~2 KB
# Envelope = ~79 KB, sicher unter 95 KB. Damit gilt wieder der ursprüngliche
# Cap von 350, wie beim Absenken am 2026-08-01 angekündigt. Regressionstest:
# tests/integration/test_city_tree_cadastre.py (test_worst_case_response_under_
# actions_limit). Die Truncation bleibt ehrlich (count/total_available/truncated).
_COUNT_CAP = 350


class BaumSource(NamedTuple):
    """WFS-Konfiguration eines städtischen Baumkatasters.

    ``license_url`` ist je Stadt verschieden (Berlin DL-DE/Zero, Hamburg DL-DE/BY,
    Kiel CC-BY) und wandert in die Attribution. ``output_format`` ist der WFS-
    ``outputFormat``-Wert (Hamburg spricht ``application/geo+json``, der Kiel-
    ArcGIS-WFS ``GEOJSON``).
    """

    url: str
    typename: str
    fields: tuple[str, ...]
    license_id: str
    license_tier: str
    attribution: str
    license_url: str
    output_format: str = "application/json"


_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_CC_BY_4_0_URL = "https://creativecommons.org/licenses/by/4.0/"


# Stadt-Slug -> WFS-Konfiguration. Nur verifizierte, offen lizenzierte Städte
# (fail-closed). Alle Endpunkte HTTP-verifiziert (GetFeature + Lizenz) 2026-07-17.
BAUM_WFS: dict[str, BaumSource] = {
    # Berlin: GetCapabilities + Lizenz (DL-DE/Zero 2.0) verifiziert 2026-06-26.
    "berlin": BaumSource(
        url="https://gdi.berlin.de/services/wfs/baumbestand",
        typename="baumbestand:strassenbaeume",
        fields=(
            "art_dtsch",
            "art_bot",
            "gattung_deutsch",
            "pflanzjahr",
            "baumhoehe",
            "strname",
            "bezirk",
        ),
        license_id="dl_de_zero_2_0",
        license_tier="A",
        attribution="Geoportal Berlin / Straßen- und Anlagenbaumbestand",
        license_url=_DL_DE_ZERO_URL,
    ),
    # Hamburg: Straßenbaumkataster (LGV), MultiPoint-GeoJSON, DL-DE/BY-2.0.
    # Nur ``application/geo+json`` (wie der Hamburg-Denkmal-WFS).
    "hamburg": BaumSource(
        url="https://geodienste.hamburg.de/HH_WFS_Strassenbaumkataster",
        typename="app:strassenbaumkataster",
        fields=(
            "gattung_deutsch",
            "art_deutsch",
            "pflanzjahr",
            "kronendurchmesser",
            "strasse",
            "stadtteil",
            "bezirk",
        ),
        license_id="dl_de_by_2_0",
        license_tier="A",
        attribution=(
            "Freie und Hansestadt Hamburg, Landesbetrieb Geoinformation "
            "und Vermessung (LGV)"
        ),
        license_url=_DL_DE_BY_URL,
        output_format="application/geo+json",
    ),
    # Kiel: Baeume auf staedtischem Grund (ArcGIS-WFS der LH Kiel), CC-BY-4.0
    # (AccessConstraints der Capabilities). typeName ``lhkiel:Baeume``, outputFormat
    # ``GEOJSON``. Feldnamen mit Sonderzeichen aus dem WFS uebernommen.
    "kiel": BaumSource(
        url=(
            "https://ims.kiel.de/geodatenextern/services/Stadtplan/"
            "LHKielWmsWfs/MapServer/WFSServer"
        ),
        typename="lhkiel:Baeume",
        fields=(
            "Baumart",
            "Baumart__bot._",
            "Kronendurchmesser__m_",
        ),
        license_id="cc_by_4_0",
        license_tier="A",
        attribution="Landeshauptstadt Kiel",
        license_url=_CC_BY_4_0_URL,
        output_format="GEOJSON",
    ),
}


async def fetch_trees(
    http: httpx.AsyncClient,
    *,
    slug: str,
) -> dict:
    """Holt das städtische Baumkataster per WFS GetFeature (GeoJSON, WGS84).

    ``slug`` wählt die WFS-Konfiguration; eine nicht abgedeckte Stadt löst ein
    ``KeyError`` aus (die Route prüft jedoch vorher ``is_covered`` und liefert
    dann ``not_covered``). Rückgabe-Keys (das, was ``map_trees`` erwartet):
    ``slug``, ``fields``, ``license_id``/``license_tier``/``attribution`` und
    ``features`` (rohe GeoJSON-Features, gedeckelt auf ``_COUNT_CAP``).
    """
    src = BAUM_WFS[slug]
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": src.typename,
        "count": str(_COUNT_CAP),
        "outputFormat": src.output_format,
        "srsName": "EPSG:4326",
    }
    resp = await http.get(src.url, params=params)
    resp.raise_for_status()
    data = resp.json()
    return {
        "slug": slug,
        "fields": list(src.fields),
        "license_id": src.license_id,
        "license_tier": src.license_tier,
        "attribution": src.attribution,
        "license_url": src.license_url,
        "features": data.get("features", []),
        # Echter Gesamtbestand laut WFS (numberMatched, Audit 220); "unknown" -> None.
        "total_available": _coerce_count(data.get("numberMatched")),
    }


def _coerce_count(value) -> int | None:
    """WFS-``numberMatched`` defensiv zu ``int`` (oder ``None`` bei ``unknown``)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
