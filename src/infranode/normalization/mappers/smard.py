"""Reiner SMARD-Mapper map_smard (Strommarktdaten, CC BY 4.0, Tier A).

Übersetzt das flache SMARD-raw-dict (aus ``adapters.smard.fetch_smard``)
deterministisch in einen ``CanonicalRecord`` mit ``PowerPayload``. Rein: kein
HTTP, kein Logging, kein ``datetime.now()`` (``retrieved_at`` wird injiziert).

SMARD-Daten werden unverändert übernommen (kein Verrechnen), daher
``modified=False``. Lizenz CC BY 4.0, Attribution wortgenau "Bundesnetzagentur |
SMARD.de" (muss verbatim in DATA-LICENSES.md + SOURCE_LICENSE stehen).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    PowerPayload,
    SourceId,
)

_CC_BY_4_0_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_smard(
    slug: str,
    raw: dict,
    *,
    measure: str,
    unit: str,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Bildet einen SMARD-Tageswert auf einen ``CanonicalRecord`` ab.

    ``measure`` ist "load" (Stromverbrauch/Netzlast, je Regelzone) oder "price"
    (Day-ahead-Großhandelspreis, bundesweit). ``unit`` z.B. "MWh" bzw. "EUR/MWh".
    ``lat``/``lon`` stammen aus dem Register (die Kennzahl ist regional, wird aber
    der Stadt zugeordnet).
    """
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=slug,
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.SMARD,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundesnetzagentur | SMARD.de",
            license_url=_CC_BY_4_0_URL,
            modified=False,
        ),
        payload=PowerPayload(
            measure=measure,
            value=raw.get("value"),
            unit=unit,
            region=raw.get("region"),
            series_date=raw.get("series_date"),
        ),
    )
