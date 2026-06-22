"""Reine Stadt-Mobilithek-Mapper (LIVE-08/12, Tier A DL-DE/BY, Phase 20).

Uebersetzt die rohen Adapter-dicts aus ``adapters/mobilithek_datex2.py``
(SituationPublication, ``events``) deterministisch in einen ``CanonicalRecord``:
- ``map_berlin_traffic_messages``: Berlin Verkehrsmeldungen (SenMVKU,
  SituationPublication) -> ``RoadEventPayload`` (``city_source="berlin_senmvku"``),
  SourceId.BERLIN_VERKEHRSMELDUNGEN (LIVE-08).
- ``map_hannover_road_events``: Hannover Verkehrsmeldungen (LH Hannover, Fachbereich
  Tiefbau, SituationPublication) -> ``RoadEventPayload`` (``city_source="hannover"``),
  SourceId.HANNOVER_VERKEHRSMELDUNGEN, Attribution "Landeshauptstadt Hannover".
- ``map_koeln_lez``: Köln LowEmissionZone (MoCKiii, SituationPublication) ->
  ``RoadEventPayload`` (``city_source="koeln"``), SourceId.KOELN_LEZ_LIVE (LIVE-12).

Schablone ist ``mappers/mobilithek_koeln.py`` (exakt, Plan 04): rein (kein HTTP,
kein XML-Parse, keine Systemuhr), ``retrieved_at`` keyword-only injiziert
(deterministisch). Beide Quellen stehen unter der Datenlizenz Deutschland
Namensnennung 2.0: ``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (verifiziert,
T-20-TIER: KEIN pauschales Tier-A ueber alle Quellen, nur diese DL-DE/BY-Feeds).
Wortgenaue Attribution gemaess DATA-LICENSES.md (Berlin = SenMVKU, Köln = Stadt
Köln).

Reine Live-Daten -> ``geo=None`` (Geo je Event im Payload); ``observed_at`` aus
der DATEX-II ``publicationTime`` (``as_of``) falls vorhanden, sonst ``None``
(ehrlich, keine Systemuhr).
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
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_BERLIN_ATTRIBUTION = (
    "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt (SenMVKU)"
)
_KOELN_ATTRIBUTION = "Stadt Köln"
_HANNOVER_ATTRIBUTION = "Landeshauptstadt Hannover"


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


def map_berlin_traffic_messages(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet Berlin Verkehrsmeldungen (situation) auf einen ``CanonicalRecord`` ab.

    Die ``events`` (SenMVKU SituationPublication, LIVE-08) wandern in den
    ``RoadEventPayload`` (``city_source="berlin_senmvku"``). ``observed_at`` aus
    der DATEX-II ``publicationTime`` (``as_of``) falls vorhanden. ``retrieved_at``
    injiziert (keine Systemuhr im Mapper). Tier A, DL-DE/BY 2.0, wortgenaue
    SenMVKU-Attribution (DATA-LICENSES.md).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.BERLIN_VERKEHRSMELDUNGEN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_BERLIN_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="berlin_senmvku",
            events=raw.get("events", []),
        ),
    )


def map_hannover_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet Hannover Verkehrsmeldungen (situation) auf einen ``CanonicalRecord`` ab.

    Die ``events`` (Landeshauptstadt Hannover, Fachbereich Tiefbau:
    Baustellen/verkehrsrelevante Veranstaltungen/Verkehrsstörungen,
    SituationPublication, BBox-gefiltert um Hannover) wandern in den
    ``RoadEventPayload`` (``city_source="hannover"``). ``observed_at`` aus der
    DATEX-II ``publicationTime`` (``as_of``) falls vorhanden. ``retrieved_at``
    injiziert (keine Systemuhr im Mapper). Das Mobilithek-Angebot ist "freie
    Nutzung/Open Data" = DL-DE/BY 2.0 (Tier A, analog Bremen), Attribution
    wortgenau "Landeshauptstadt Hannover" (DATA-LICENSES.md).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.HANNOVER_VERKEHRSMELDUNGEN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_HANNOVER_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="hannover",
            events=raw.get("events", []),
        ),
    )


def map_koeln_lez(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Köln LowEmissionZone (situation) auf einen ``CanonicalRecord`` ab.

    Die ``events`` (MoCKiii SituationPublication, LIVE-12) wandern in den
    ``RoadEventPayload`` (``city_source="koeln"``). ``observed_at`` aus der
    DATEX-II ``publicationTime`` (``as_of``) falls vorhanden. ``retrieved_at``
    injiziert (keine Systemuhr im Mapper). Tier A, DL-DE/BY 2.0, Attribution
    "Stadt Köln" (DATA-LICENSES.md).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.KOELN_LEZ_LIVE,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_KOELN_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="koeln",
            events=raw.get("events", []),
        ),
    )
