"""Reiner Denkmal-Mapper map_heritage (DATA-OSM-Tier-2, Denkmallisten).

Übersetzt rohe Denkmal-WFS-Features (GeoJSON) deterministisch in einen
``CanonicalRecord`` mit ``PoiPayload`` (``poi_type="heritage"``). Je Objekt ein
Repräsentativpunkt (lat/lon) plus die je Land konfigurierten Property-Felder
(z.B. ``typ``, ``link``). Lizenz/Attribution kommen pro Bundesland aus dem
raw-dict (Berlin: DL-DE/Zero 2.0, Tier A). Rein: kein HTTP/Logging/now().
"""

from __future__ import annotations

from datetime import datetime

from infranode.adapters.denkmal import _COUNT_CAP, _representative_point
from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    PoiPayload,
    SourceId,
)

_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"
# Fallback nur, falls eine (ältere) raw-Quelle keine license_url mitführt;
# neue Quellen setzen sie stets explizit (Berlin Zero, BW/HE/HH DL-DE/BY).

# Roh-WFS-Feldname -> kanonischer englischer Item-Key (Abkündigung 2026-08-01).
# Der Backfill liegt bewusst im Mapper (nicht im Adapter), damit auch gecachte/
# persistierte Roh-Features die kanonischen Keys erhalten; die rohen Keys
# (inkl. der Hessen-camelCase-Keys) bleiben als abgekündigte Duplikate mit
# identischem Wert stehen (Muster koeln_arcgis). "info" und "link" sind bereits
# englisch und bleiben ohne Duplikat.
_CANONICAL_KEYS: dict[str, str] = {
    "typ": "type",
    "bezeichnung": "name",
    "bautyp": "building_type",
    "baujahr": "build_year",
    "siteName": "site_name",
    "siteDesignation": "site_designation",
    "publicationSource": "publication_source",
}


def map_heritage(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Denkmal-WFS-Features auf einen ``CanonicalRecord`` ab.

    Jedes Feature wird auf ein schlankes dict (Repräsentativpunkt + konfigurierte
    Felder) reduziert; ein Feld wird nur gesetzt, wenn das Objekt es trägt (kein
    null-Rauschen). ``count`` ist immer ``len(items)``. Denkmale sind statisch,
    daher ``observed_at=None``; der ``retrieved_at``-Zeitstempel wird injiziert.
    """
    fields = raw.get("fields", [])
    items = []
    for feature in raw["features"]:
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
    # Ehrliche Truncation: bei bekanntem Gesamtbestand direkt vergleichen; liefert
    # der WFS keine Zahl (z.B. Hamburg geo+json ohne numberMatched), aber genau
    # ``_COUNT_CAP`` Features, ist mit hoher Sicherheit abgeschnitten worden.
    truncated = (total is not None and total > len(items)) or (
        total is None and len(items) >= _COUNT_CAP
    )

    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.HERITAGE,
        license_id=LicenseId(raw["license_id"]),
        license_tier=LicenseTier(raw["license_tier"]),
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=raw["attribution"],
            license_url=raw.get("license_url", _DL_DE_ZERO_URL),
        ),
        payload=PoiPayload(
            poi_type="heritage",
            count=len(items),
            total_available=total,
            truncated=truncated,
            items=items,
        ),
    )
