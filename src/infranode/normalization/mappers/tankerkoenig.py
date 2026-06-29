"""Reiner Tankerkönig-Mapper ``map_fuel_prices`` (Spritpreise, CC BY 4.0, Tier A).

Übersetzt das aggregierte Tankerkönig-raw-dict (aus
``adapters.tankerkoenig.fetch_fuel_prices``) deterministisch in einen
``CanonicalRecord`` mit ``FuelPricePayload``. Rein: kein HTTP, kein Logging, kein
``datetime.now()`` (``retrieved_at`` wird injiziert).

Die Stadt-Aggregate (avg/min je Sorte) sind aus den Einzelpreisen VERRECHNET
(Durchschnitt/Minimum), daher ``modified=True``. Lizenz CC BY 4.0, Attribution
wortgenau "Tankerkoenig (creativecommons.tankerkoenig.de), MTS-K" (muss verbatim
in DATA-LICENSES.md + SOURCE_LICENSE stehen).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    FuelPricePayload,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
)

_CC_BY_4_0_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_fuel_prices(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Bildet die aggregierten Spritpreise einer Stadt auf einen ``CanonicalRecord`` ab.

    ``lat``/``lon`` stammen aus dem Register (die Kennzahl aggregiert Tankstellen im
    Umkreis dieser Koordinate). ``modified=True``, weil die Stadt-Aggregate aus den
    Einzelpreisen berechnet sind.
    """
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.TANKERKOENIG,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Tankerkoenig (creativecommons.tankerkoenig.de), MTS-K",
            license_url=_CC_BY_4_0_URL,
            modified=True,
        ),
        payload=FuelPricePayload(
            radius_km=raw.get("radius_km"),
            station_count=raw.get("station_count", 0),
            open_count=raw.get("open_count", 0),
            avg_e5=raw.get("avg_e5"),
            avg_e10=raw.get("avg_e10"),
            avg_diesel=raw.get("avg_diesel"),
            min_e5=raw.get("min_e5"),
            min_e10=raw.get("min_e10"),
            min_diesel=raw.get("min_diesel"),
            stations=raw.get("stations", []),
        ),
    )
