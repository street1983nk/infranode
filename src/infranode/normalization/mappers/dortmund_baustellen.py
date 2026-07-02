"""Reiner Dortmund-Mapper map_dortmund_road_events (DATA-15, Tier A DL-DE/Zero).

Übersetzt das rohe Adapter-dict (``slug``/``events``) deterministisch in einen
``CanonicalRecord`` mit ``RoadEventPayload`` (``city_source="dortmund_baustellen"``).
Rein: kein HTTP, kein Logging, keine Systemuhr (``retrieved_at`` injiziert).

Die tagesaktuellen Baustellen der Stadt Dortmund (Opendatasoft-Portal
open-data.dortmund.de, [VERIFIED 2026-07-02]) stehen unter Datenlizenz Deutschland
Zero 2.0 (keine Namensnennungspflicht): ``license_id=DL_DE_ZERO_2_0``,
``license_tier=A``, Attribution "Stadt Dortmund". Die Einzel-Events tragen Zeit und
Geometrie im Payload, daher ``observed_at=None`` und ``geo=None``.
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

_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"


def map_dortmund_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Dortmunder Road-Events auf einen ``CanonicalRecord`` (Tier A) ab.

    Die ``events`` (Baustellen, DATA-15) wandern unverändert in den
    ``RoadEventPayload`` (``city_source="dortmund_baustellen"``). Der
    ``retrieved_at``-Zeitstempel wird injiziert (keine Systemuhr im Mapper). Die
    Join-Keys ``ags``/``wikidata_qid`` kommen aus dem Register (Default ``None``).
    Verkehrsereignisse tragen ihre Zeit/Geometrie je Event, daher ``observed_at``
    None und ``geo`` None.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DORTMUND_BAUSTELLEN,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Stadt Dortmund",
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=RoadEventPayload(
            city_source="dortmund_baustellen",
            events=raw.get("events", []),
        ),
    )
