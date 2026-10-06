"""Reiner Baumkataster-Mapper map_trees (DATA-OSM-Tier-2, Baumkataster).

Übersetzt rohe Baum-WFS-Features (GeoJSON-Punkte) deterministisch in einen
``CanonicalRecord`` mit ``PoiPayload`` (``poi_type="trees"``). Je Baum der Punkt
(lat/lon) plus die je Stadt konfigurierten Attribute (Art, Pflanzjahr, Höhe,
Straße, Bezirk). Lizenz/Attribution kommen pro Stadt aus dem raw-dict (Berlin:
DL-DE/Zero 2.0, Tier A). Rein: kein HTTP/Logging/now().
"""

from __future__ import annotations

from datetime import datetime

from infranode.adapters.baumkataster import _COUNT_CAP
from infranode.adapters.denkmal import _representative_point
from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    PoiPayload,
    SourceId,
)

_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"

# Roh-WFS-Feldname -> kanonischer englischer Item-Key (Abkündigung 2026-08-01).
# Der Backfill liegt bewusst im Mapper (nicht im Adapter), damit auch gecachte/
# persistierte Roh-Features die kanonischen Keys erhalten; die rohen Keys bleiben
# als abgekündigte Duplikate mit identischem Wert stehen (Muster koeln_arcgis).
_CANONICAL_KEYS: dict[str, str] = {
    # Berlin / Hamburg / Kiel: deutscher Trivialname der Baumart.
    "art_dtsch": "species",
    "art_deutsch": "species",
    "Baumart": "species",
    # Botanischer Name.
    "art_bot": "species_botanical",
    "Baumart__bot._": "species_botanical",
    # Gattung (deutsch), Pflanzjahr, Kronendurchmesser in Metern (Kiel).
    "gattung_deutsch": "genus",
    "pflanzjahr": "planting_year",
    "Kronendurchmesser__m_": "crown_diameter_m",
}


def map_trees(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Baumkataster-WFS-Features auf einen ``CanonicalRecord`` ab.

    Jedes Feature (Punkt) wird auf ein schlankes dict (lat/lon + konfigurierte
    Felder) reduziert; ein Feld wird nur gesetzt, wenn der Baum es trägt (kein
    null-Rauschen). ``count`` ist immer ``len(items)`` (gedeckelte Stichprobe,
    siehe Adapter). Bäume sind statisch, daher ``observed_at=None``; der
    ``retrieved_at``-Zeitstempel wird injiziert.
    """
    fields = raw.get("fields", [])
    items = []
    # Der Cap greift hier ein zweites Mal, nicht nur im Adapter (dort als
    # WFS-count-Parameter): gecachte Roh-Antworten aus der Zeit vor einer
    # Cap-Senkung tragen noch mehr Features, und seit die Items die
    # kanonischen Keys zusätzlich zu den abgekündigten Rohnamen führen,
    # sprengt die alte Menge das Actions-Limit (Berlin gemessen 111 KB).
    for feature in raw["features"][:_COUNT_CAP]:
        lat, lon = _representative_point(feature.get("geometry"))
        props = feature.get("properties", {}) or {}
        item: dict = {"lat": lat, "lon": lon}
        for field in fields:
            value = props.get(field)
            if value is not None:
                # Nur noch der kanonische englische Key; der rohe Quell-Key war
                # seit 2026-08-01 abgekündigt und ist zum 2026-08-31 entfernt.
                # Felder ohne Mapping (schon englisch) behalten ihren Namen.
                canonical = _CANONICAL_KEYS.get(field)
                if canonical is not None:
                    item[canonical] = value
                else:
                    item[field] = value
        items.append(item)

    total = raw.get("total_available")
    # truncated bleibt ehrlich, auch wenn total_available fehlt: dann verrät
    # der oben angewendete Cap allein schon, dass gekürzt wurde.
    truncated = len(raw["features"]) > len(items) or (
        total is not None and total > len(items)
    )

    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.TREE_CADASTRE,
        license_id=LicenseId(raw["license_id"]),
        license_tier=LicenseTier(raw["license_tier"]),
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=raw["attribution"],
            # license_url ist je Stadt verschieden (Berlin DL-DE/Zero, Hamburg
            # DL-DE/BY, Kiel CC-BY); Fallback auf DL-DE/Zero fuer Alt-Aufrufer.
            license_url=raw.get("license_url", _DL_DE_ZERO_URL),
        ),
        payload=PoiPayload(
            poi_type="trees",
            count=len(items),
            total_available=total,
            truncated=truncated,
            items=items,
        ),
    )
