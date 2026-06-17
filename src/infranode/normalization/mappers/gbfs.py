"""Reiner GBFS-Sharing-Mapper ``map_sharing`` (DATA-33, Tier A).

Uebersetzt das aggregierte GBFS-raw-dict (aus ``adapters.gbfs.fetch_sharing``)
deterministisch in einen ``CanonicalRecord`` mit ``SharingPayload``. Rein: kein
HTTP, kein Logging, kein ``datetime.now()`` (``retrieved_at`` wird injiziert).

Die Stadt-Kennzahlen (vehicles_available etc.) sind aus den Einzelfahrzeugen/
Stationen VERRECHNET (Summen, BBox-Filter), daher ``modified=True``.

Lizenz: Primaerquelle Nextbike ist CC0 (Tier A); je Anbieter wird die Lizenz im
Adapter fail-closed gegen die Tier-A-Allowlist geprueft und im Payload je Anbieter
ausgewiesen. Die record-weite Lizenz traegt die Primaerquelle CC0, Attribution
wortgenau "nextbike GmbH / GBFS (CC0)" (muss verbatim in DATA-LICENSES.md +
SOURCE_LICENSE stehen).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SharingPayload,
    SourceId,
)

_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def map_sharing(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Bildet den aggregierten GBFS-Sharing-Snapshot auf einen ``CanonicalRecord`` ab.

    ``lat``/``lon`` stammen aus dem Register (die Kennzahl aggregiert Fahrzeuge/
    Stationen im Umkreis dieser Koordinate). ``modified=True``, weil die Stadt-
    Aggregate aus den Einzelfahrzeugen berechnet sind. ``observed_at=None`` (der
    Snapshot ist live, der Zeitbezug steckt in ``retrieved_at``).
    """
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.GBFS,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="nextbike GmbH / GBFS (CC0)",
            license_url=_CC0_URL,
            modified=True,
        ),
        payload=SharingPayload(
            radius_km=raw.get("radius_km"),
            vehicles_available=raw.get("vehicles_available", 0),
            free_floating_available=raw.get("free_floating_available", 0),
            docked_available=raw.get("docked_available", 0),
            station_count=raw.get("station_count", 0),
            providers=raw.get("providers", []),
        ),
    )
