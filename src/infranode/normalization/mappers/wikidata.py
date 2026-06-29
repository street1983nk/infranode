"""Reiner Wikidata-Stammdaten-Mapper (CORE-02).

Übersetzt rohe Wikidata-Stammdaten (ein dict) deterministisch in einen
``CanonicalRecord`` mit ``CityBaseDataPayload``. Die Funktion ist rein: kein
HTTP, kein Logging, kein ``datetime.now()``. Der ``retrieved_at``-Zeitstempel
wird keyword-only injiziert, damit Tests deterministisch bleiben. Dieser Mapper
ist die Vorlage für jeden weiteren Quellen-Mapper ab Phase 4.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    CityBaseDataPayload,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
)

_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def map_wikidata_city(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Wikidata-Stammdaten auf einen ``CanonicalRecord`` ab.

    Stammdaten sind statisch, daher ist ``observed_at`` ``None``. Der
    ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch und voll testbar bleibt. Die
    Join-Keys ``ags`` und ``wikidata_qid`` werden aus dem Register durchgereicht
    (Default ``None``, damit der Mapper rein und ohne Register testbar bleibt) und
    fließen so in ``record_id``/``content_hash`` ein (ARCH-02). Stammdaten haben
    keine Mess-Station, daher kein ``station_id``.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=GeoPoint(lat=raw["lat"], lon=raw["lon"]),
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.WIKIDATA,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text="Wikidata", license_url=_CC0_URL),
        payload=CityBaseDataPayload(
            population=raw.get("population"),
            area_km2=raw.get("area"),
        ),
    )
