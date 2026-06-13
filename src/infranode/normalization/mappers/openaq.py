"""Reiner OpenAQ-Luftqualitaets-Mapper map_openaq_air (DATA-02, GOV-01).

Uebersetzt das flache OpenAQ-raw-dict deterministisch in einen ``CanonicalRecord``
mit ``AirQualityPayload``. Die Funktion ist rein: kein HTTP, kein Logging, kein
``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird keyword-only injiziert,
damit Tests deterministisch bleiben.

KRITISCH (B-1, GOV-01): ``license_id`` ist ``LicenseId.UNKNOWN`` und NICHT pauschal
CC-BY. Die OpenAQ-Lizenz variiert pro Provider/Location; ein pauschales CC-BY-Tag
waere falsch und verletzte GOV-01. ``UNKNOWN`` ist der ehrliche Tag, konsistent mit
dem DATA-LICENSES.md-Eintrag "Lizenz je Provider variabel, Tier C, nicht
``license_tier`` ist ``LicenseTier.C`` (live-only, Tier C).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    AirQualityPayload,
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
)

_OPENAQ_URL = "https://openaq.org/"


def map_openaq_air(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe OpenAQ-Luftdaten auf einen ``CanonicalRecord`` ab.

    ``observed_at`` kommt aus dem OpenAQ-Messzeitpunkt (nicht None). Der
    ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im Mapper),
    damit das Ergebnis deterministisch und voll testbar bleibt. ``license_id`` ist
    ``UNKNOWN`` (B-1), ``license_tier`` ist ``C`` (live-only). Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``); ``AirQualityPayload.station_id`` wird aus ``raw["location_id"]``
    (echte OpenAQ-Stations-ID) gesetzt und dient als fachlicher Schluessel fuer
    ``record_id`` (ARCH-02).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=GeoPoint(lat=raw["lat"], lon=raw["lon"]),
        observed_at=raw.get("observed_at"),
        retrieved_at=retrieved_at,
        source=SourceId.OPENAQ,
        license_id=LicenseId.UNKNOWN,
        license_tier=LicenseTier.C,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="OpenAQ (Lizenz je Provider variabel, siehe DATA-LICENSES.md)",
            license_url=_OPENAQ_URL,
        ),
        payload=AirQualityPayload(
            station_id=raw.get("location_id"),
            pm10=raw.get("pm10"),
            no2=raw.get("no2"),
            pm25=raw.get("pm25"),
            o3=raw.get("o3"),
            so2=raw.get("so2"),
        ),
    )
