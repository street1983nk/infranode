"""Reiner DWD-Wetterwarnungen-Mapper map_dwd_warnings (GeoNutzV, Tier A).

Übersetzt das flache raw-dict aus ``adapters.dwd_warnings.fetch_dwd_warnings``
deterministisch in einen ``CanonicalRecord`` mit ``WeatherWarningPayload``. Rein:
kein HTTP/Logging/``datetime.now()`` (``retrieved_at`` injiziert).

Die Warnungen werden unverändert durchgereicht (kein Verrechnen), daher
``modified=False``. Attribution wortgenau "Datenbasis: Deutscher Wetterdienst"
(muss verbatim in DATA-LICENSES.md + SOURCE_LICENSE stehen).
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
    WeatherWarningPayload,
)

_GEONUTZV_URL = (
    "https://www.dwd.de/DE/service/rechtliche_hinweise/rechtliche_hinweise.html"
)


def map_dwd_warnings(
    slug: str,
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Bildet rohe DWD-Warnungen auf einen ``CanonicalRecord`` ab."""
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=slug,
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DWD_WARNINGS,
        license_id=LicenseId.GEONUTZV,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Datenbasis: Deutscher Wetterdienst",
            license_url=_GEONUTZV_URL,
            modified=False,
        ),
        payload=WeatherWarningPayload(
            count=raw.get("count", 0),
            max_level=raw.get("max_level"),
            warnings=raw.get("warnings") or [],
        ),
    )
