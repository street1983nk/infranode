"""Reiner Denkmal-Mapper map_heritage (DATA-OSM-Tier-2, Denkmallisten).

Uebersetzt rohe Denkmal-WFS-Features (GeoJSON) deterministisch in einen
``CanonicalRecord`` mit ``PoiPayload`` (``poi_type="heritage"``). Je Objekt ein
Repraesentativpunkt (lat/lon) plus die je Land konfigurierten Property-Felder
(z.B. ``typ``, ``link``). Lizenz/Attribution kommen pro Bundesland aus dem
raw-dict (Berlin: DL-DE/Zero 2.0, Tier A). Rein: kein HTTP/Logging/now().
"""

from __future__ import annotations

from datetime import datetime

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


def map_heritage(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Denkmal-WFS-Features auf einen ``CanonicalRecord`` ab.

    Jedes Feature wird auf ein schlankes dict (Repraesentativpunkt + konfigurierte
    Felder) reduziert; ein Feld wird nur gesetzt, wenn das Objekt es traegt (kein
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
                item[field] = value
        items.append(item)

    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DENKMAL,
        license_id=LicenseId(raw["license_id"]),
        license_tier=LicenseTier(raw["license_tier"]),
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=raw["attribution"],
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=PoiPayload(
            poi_type="heritage",
            count=len(items),
            items=items,
        ),
    )
