"""Reiner StaDa-Mapper ``map_station_catalog`` (DATA-36, CC BY 4.0, Tier A).

Übersetzt das je Stadt gefilterte StaDa-raw-dict (``{slug, stations}``, gebaut
in der Route aus ``adapters.stada.fetch_all_stations`` + ags-Filter)
deterministisch in einen ``CanonicalRecord`` mit ``StationCatalogPayload``. Rein:
kein HTTP, kein Logging, kein ``datetime.now()`` (``retrieved_at`` injiziert).

Der Katalog wird unverändert durchgereicht (kein Merge), daher ``modified=False``.
Lizenz CC BY 4.0, Attribution wortgenau "Deutsche Bahn AG" (muss verbatim in
DATA-LICENSES.md + SOURCE_LICENSE stehen, T-11-SRC-DRIFT).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
    StationCatalogPayload,
)

_CC_BY_4_0_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_station_catalog(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Bildet den Bahnhofs-Katalog einer Stadt auf einen ``CanonicalRecord`` ab.

    ``modified=False`` (Stammdaten unverändert). ``observed_at=None`` (kein
    Messzeitpunkt). ``lat``/``lon`` (Stadtkoordinate aus dem Register) werden,
    falls vorhanden, als ``geo`` gesetzt.
    """
    stations = raw.get("stations", [])
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.STADA,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Deutsche Bahn AG", license_url=_CC_BY_4_0_URL, modified=False
        ),
        payload=StationCatalogPayload(
            station_count=len(stations),
            stations=stations,
        ),
    )
