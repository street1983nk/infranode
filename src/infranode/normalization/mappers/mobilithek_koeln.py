"""Reine Köln-Mobilithek-Mapper (LIVE-06/07, Tier A DL-DE/Zero, Phase 20).

Übersetzt die rohen Adapter-dicts aus ``adapters/mobilithek_datex2.py``
deterministisch in einen ``CanonicalRecord``:
- ``map_koeln_traffic_flow``: ``measurements`` (Köln Verkehrslage dynamisch,
  MeasuredDataPublication) -> ``TrafficFlowPayload`` (LIVE-06).
- ``map_koeln_road_events``: ``events`` (Köln Baustellen/Ereignisse,
  SituationPublication) -> ``RoadEventPayload`` (LIVE-07).

Schablone ist ``mappers/mobidata_bw.py`` (exakt): rein (kein HTTP, kein XML-Parse,
keine Systemuhr), ``retrieved_at`` keyword-only injiziert (deterministisch). Die
Köln-Feeds stehen unter der Datenlizenz Deutschland Zero 2.0 (verifiziert
2026-06-26: Köln stellt seine Verkehrs-/Umweltzonen-Daten auf
offenedaten-koeln.de durchgängig unter DL-DE/Zero bereit, z.B.
"Verkehrsbeeintraechtigungen Stadt Koeln" und "Umweltzone Koeln"):
``license_id=DL_DE_ZERO_2_0``, ``license_tier=A`` (permissiv, KEINE
Namensnennungspflicht). Attribution "Stadt Köln" bleibt informativ erhalten
(wortgenau wie SOURCE_LICENSE / DATA-LICENSES.md).

Reine Live-Daten -> ``geo=None`` (der dynamische Feed trägt nur ID-Referenzen
bzw. Geo je Event); ``observed_at`` aus der DATEX-II ``publicationTime`` (``as_of``)
falls vorhanden, sonst ``None`` (ehrlich, keine Systemuhr).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    RoadEventPayload,
    SourceId,
    TrafficFlowPayload,
)

_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"
_KOELN_ATTRIBUTION = "Stadt Köln"


def _parse_as_of(raw: dict) -> datetime | None:
    """Liest ``as_of`` (DATEX-II publicationTime) als aware ``datetime`` oder None.

    Rein (keine Systemuhr). Ein nicht-parsebarer/fehlender Wert -> ``None``
    (ehrlich, kein Fehler).
    """
    text = raw.get("as_of")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def map_koeln_traffic_flow(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Köln-Verkehrslage (measured) auf einen ``CanonicalRecord`` ab.

    Die ``measurements`` (je Messpunkt station_id + speed/flow, LIVE-06) wandern
    in den ``TrafficFlowPayload``. ``station_id`` trägt die erste Messpunkt-ID
    (oder None). ``observed_at`` aus der DATEX-II ``publicationTime`` (``as_of``)
    falls vorhanden. ``retrieved_at`` injiziert (keine Systemuhr im Mapper).
    """
    measurements = raw.get("measurements", [])
    station_id = measurements[0].get("station_id") if measurements else None
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.KOELN_TRAFFIC_FLOW,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_KOELN_ATTRIBUTION,
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=TrafficFlowPayload(
            station_id=station_id,
            measurements=measurements,
        ),
    )


def map_koeln_road_events(
    raw: dict,
    *,
    source: SourceId = SourceId.KOELN_BAUSTELLEN_LIVE,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet Köln-Baustellen/Ereignisse (situation) auf einen ``CanonicalRecord`` ab.

    Die ``events`` (Baustellen/Ereignisse, LIVE-07) wandern in den
    ``RoadEventPayload`` (``city_source="koeln"``). ``source`` wählt die
    SourceId je Route (Baustellen vs. Ereignisse, Default
    ``KOELN_BAUSTELLEN_LIVE``). ``observed_at`` aus der DATEX-II
    ``publicationTime`` (``as_of``) falls vorhanden. ``retrieved_at`` injiziert
    (keine Systemuhr im Mapper).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=source,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_KOELN_ATTRIBUTION,
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=RoadEventPayload(
            city_source="koeln",
            events=raw.get("events", []),
        ),
    )
