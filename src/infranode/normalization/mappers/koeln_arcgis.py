"""Reiner Koeln-Verkehrs-Mapper map_koeln_road_events (DATA-15, Tier A DL-DE/BY).

Uebersetzt das rohe Adapter-dict (``slug``/``events``) deterministisch in einen
``CanonicalRecord`` mit ``RoadEventPayload``. Die Funktion ist rein: kein HTTP,
keine Log-Aufrufe, keine Systemuhr. Der ``retrieved_at``-Zeitstempel wird
keyword-only injiziert, damit Tests deterministisch bleiben.

Die Koeln-Verkehrsdaten (Stadt Koeln) sind unter der Datenlizenz Deutschland
Namensnennung 2.0 verfuegbar: ``license_id=DL_DE_BY_2_0``, ``license_tier=A``
(kennzeichnet die permissive Lizenz zur korrekten Attribution und Weiternutzung,
T-9-03) und die wortgenaue Attribution der Stadt (mit Umlaut, der Attributions-
Text darf echte Umlaute tragen). Die Einzel-Events tragen ihre Zeit und
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

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


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
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Stadt Köln",
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="koeln_verkehr",
            events=raw.get("events", []),
        ),
    )
