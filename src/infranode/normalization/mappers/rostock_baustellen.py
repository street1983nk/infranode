"""Reiner Rostock-Mapper map_rostock_road_events (road-events, Tier A CC0).

Uebersetzt das rohe Adapter-dict (``slug``/``events``) deterministisch in einen
``CanonicalRecord`` mit ``RoadEventPayload`` (``city_source="rostock_roadworks"``).
Rein: kein HTTP, kein Logging, keine Systemuhr (``retrieved_at`` injiziert).

Die Baustellen der Hanse- und Universitaetsstadt Rostock (OpenData.HRO,
[VERIFIED 2026-07-17]) stehen unter CC0-1.0 (keine Namensnennungspflicht):
``license_id=CC0``, ``license_tier=A``, Attribution "Hanse- und Universitaetsstadt
Rostock". Die Einzel-Events tragen Zeit und Geometrie im Payload, daher
``observed_at=None`` und ``geo=None``.
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

_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"

# Alter deutscher Event-Key -> kanonischer englischer Key (Abkündigung
# 2026-08-01). Der Adapter dupliziert bereits beim Holen; der Backfill hier
# schließt die Übergangslücke für Roh-Antworten aus dem Redis-Cache, die vor
# dem Deploy entstanden sind und nur die deutschen Keys tragen (Muster
# mappers/tree_cadastre.py). Gesetzt wird nur, wenn der neue Key fehlt.
_CANONICAL_KEYS: dict[str, str] = {
    "beschreibung": "description",
    "sparte": "sector",
    "einschraenkung": "restriction",
    "strasse": "street",
    "abschnitt_von": "section_from",
    "abschnitt_nach": "section_to",
    "baubeginn": "start",
    "bauende": "end",
}


def _backfill_events(events: list[dict]) -> list[dict]:
    """Liest alte deutsche Keys auf die kanonischen um und entfernt sie danach.

    Die deutschen Namen waren seit 2026-08-01 abgekündigt und sind zum
    2026-08-31 aus der Ausgabe entfernt. Roh-Antworten aus dem Redis-Cache, die
    vor dem Deploy entstanden sind, tragen sie noch; darum bleibt die Umschrift
    (gesetzt wird nur, wenn der neue Key fehlt), aber der alte Key verlässt das
    Item und erscheint nicht mehr in der API-Antwort.
    """
    result: list[dict] = []
    for event in events:
        item = dict(event)
        for old, new in _CANONICAL_KEYS.items():
            if old in item:
                value = item.pop(old)
                if new not in item:
                    item[new] = value
        result.append(item)
    return result


def map_rostock_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Rostocker Road-Events auf einen ``CanonicalRecord`` (Tier A) ab.

    Die ``events`` (Baustellen) wandern unveraendert in den ``RoadEventPayload``
    (``city_source="rostock_roadworks"``). Der ``retrieved_at``-Zeitstempel wird
    injiziert (keine Systemuhr im Mapper). Verkehrsereignisse tragen ihre Zeit/
    Geometrie je Event, daher ``observed_at`` None und ``geo`` None.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.ROSTOCK_ROADWORKS,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Hanse- und Universitätsstadt Rostock",
            license_url=_CC0_URL,
        ),
        payload=RoadEventPayload(
            city_source="rostock_roadworks",
            events=_backfill_events(raw.get("events", [])),
        ),
    )
