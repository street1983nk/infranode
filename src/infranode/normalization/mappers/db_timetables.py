"""Reiner DB-Timetables-Mapper ``map_station_departures`` (DATA-34, CC BY 4.0, Tier A).

Übersetzt das aggregierte DB-Timetables-raw-dict (aus
``adapters.db_timetables.fetch_station_departures``) deterministisch in einen
``CanonicalRecord`` mit ``StationDeparturesPayload``. Rein: kein HTTP, kein
Logging, kein ``datetime.now()`` (``retrieved_at`` wird injiziert).

Die Abfahrtstafel ist aus Sollfahrplan + Echtzeit-Änderungen ZUSAMMENGEFÜHRT
(Merge, Verspätungsberechnung), daher ``modified=True``. Lizenz CC BY 4.0,
Attribution wortgenau "Deutsche Bahn AG" (muss verbatim in DATA-LICENSES.md +
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
    SourceId,
    StationArrivalsPayload,
    StationDeparturesPayload,
)

_CC_BY_4_0_URL = "https://creativecommons.org/licenses/by/4.0/"


def _attribution() -> Attribution:
    """Gemeinsame DB-Attribution (CC BY 4.0, modified=True: Soll+Echtzeit gemerged)."""
    return Attribution(
        text="Deutsche Bahn AG", license_url=_CC_BY_4_0_URL, modified=True
    )


def map_station_departures(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Bildet die aggregierte Live-Abfahrtstafel auf einen ``CanonicalRecord`` ab.

    ``modified=True`` (Soll + Echtzeit zusammengeführt). ``observed_at=None`` (die
    Abfahrtszeit steht je Eintrag im Payload). ``lat``/``lon`` (Stadtkoordinate aus
    dem Register) werden, falls vorhanden, als ``geo`` gesetzt.
    """
    departures = raw.get("departures", [])
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DB_TIMETABLES,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=_attribution(),
        payload=StationDeparturesPayload(
            departure_count=len(departures),
            long_distance_count=sum(1 for d in departures if d.get("long_distance")),
            departures=departures,
        ),
    )


def map_station_arrivals(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Bildet die aggregierte Live-Ankunftstafel auf einen ``CanonicalRecord`` ab.

    Spiegelbild zu ``map_station_departures`` (``modified=True``, ``observed_at=None``).
    Erwartet ``raw["arrivals"]`` (je Eintrag mit ``origin`` statt ``destination``).
    """
    arrivals = raw.get("arrivals", [])
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DB_TIMETABLES,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=_attribution(),
        payload=StationArrivalsPayload(
            arrival_count=len(arrivals),
            long_distance_count=sum(1 for a in arrivals if a.get("long_distance")),
            arrivals=arrivals,
        ),
    )
