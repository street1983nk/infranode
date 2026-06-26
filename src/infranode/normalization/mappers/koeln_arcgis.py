"""Reiner Koeln-Verkehrs-Mapper map_koeln_road_events (DATA-15, Tier A DL-DE/Zero).

Uebersetzt das rohe Adapter-dict (``slug``/``events``) deterministisch in einen
``CanonicalRecord`` mit ``RoadEventPayload``. Die Funktion ist rein: kein HTTP,
keine Log-Aufrufe, keine Systemuhr. Der ``retrieved_at``-Zeitstempel wird
keyword-only injiziert, damit Tests deterministisch bleiben.

Die Koeln-Verkehrsdaten (Stadt Koeln) stehen unter der Datenlizenz Deutschland
Zero 2.0 (verifiziert 2026-06-26 gegen den Datensatz "Verkehrsbeeintraechtigungen
Stadt Koeln" auf offenedaten-koeln.de, dl-zero-de/2.0; Koeln stellt seit Mitte
2022 standardmaessig unter DL-DE/Zero bereit): ``license_id=DL_DE_ZERO_2_0``,
``license_tier=A`` (permissiv, KEINE Namensnennungspflicht; Attribution
"Stadt Köln" bleibt informativ erhalten). Die Einzel-Events tragen ihre Zeit und
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


def map_koeln_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Koelner Road-Events auf einen ``CanonicalRecord`` (Tier A) ab.

    Die ``events`` (Baustellen/Verkehrsbeeintraechtigungen, DATA-15) wandern
    unveraendert in den ``RoadEventPayload`` (``city_source="koeln_verkehr"``).
    Der ``retrieved_at``-Zeitstempel wird injiziert (keine Systemuhr im Mapper),
    damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``). Verkehrsereignisse tragen ihre Zeit/Geometrie je Event, daher
    bewusst ``observed_at=None`` und ``geo=None``.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.KOELN_VERKEHR,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Stadt Köln",
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=RoadEventPayload(
            city_source="koeln_verkehr",
            events=raw.get("events", []),
        ),
    )
