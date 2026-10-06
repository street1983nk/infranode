"""Reiner SPERRINFOSYS-Mapper ``map_sperrinfosys_road_events`` (Tier A DL-DE/BY).

Übersetzt das rohe Adapter-dict (``slug``/``events``) deterministisch in einen
``CanonicalRecord`` mit ``RoadEventPayload`` (``city_source="sperrinfosys"``).
Rein: kein HTTP, kein Logging, keine Systemuhr (``retrieved_at`` injiziert).

Die sachsenweiten Sperrungen des SPERRINFOSYS (Freistaat Sachsen / LISt GmbH,
Mobilithek-Offer -2102129055146091928, [VERIFIED 2026-07-02]) stehen unter
Datenlizenz Deutschland Namensnennung 2.0: ``license_id=DL_DE_BY_2_0``,
``license_tier=A``. Die dreiteilige Attribution ist VERBATIM-verbindlich
(wortgleich in ``registry/source_specs.py`` und ``DATA-LICENSES.md``,
T-11-SRC-DRIFT): Namensnennung + Lizenz-Link + Veränderungshinweis.
``modified=True`` ist PFLICHT: die Koordinaten wurden von EPSG:25833 nach
WGS84 reprojiziert (Veränderungshinweis nach DL-DE/BY 2.0). Die Einzel-Events
tragen Zeit und Geometrie im Payload, daher ``observed_at=None`` und
``geo=None``.
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

# Alter deutscher Event-Key -> kanonischer englischer Key (Abkündigung
# 2026-08-01). Der Adapter dupliziert bereits beim Holen; der Backfill hier
# schließt die Übergangslücke für Roh-Antworten aus dem Redis-Cache, die vor
# dem Deploy entstanden sind und nur die deutschen Keys tragen (Muster
# mappers/tree_cadastre.py). Gesetzt wird nur, wenn der neue Key fehlt.
_CANONICAL_KEYS: dict[str, str] = {
    "art": "event_type",
    "typ": "closure_type",
    "grund": "reason",
    "von": "start",
    "bis": "end",
    "strasse": "street",
    "strassenklasse": "road_class",
    "ortslage": "location",
    "umleitung_ueber": "diversion_via",
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


def map_sperrinfosys_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe SPERRINFOSYS-Road-Events auf einen ``CanonicalRecord`` ab.

    Die ``events`` (Sperrungen, VKZ-gefiltert je Stadt) wandern unverändert in
    den ``RoadEventPayload`` (``city_source="sperrinfosys"``). Der
    ``retrieved_at``-Zeitstempel wird injiziert (keine Systemuhr im Mapper);
    ``ags``/``wikidata_qid`` kommen aus dem Register (Default ``None``).
    ``attribution.modified=True`` weil die Koordinaten reprojiziert wurden.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.SPERRINFOSYS,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Freistaat Sachsen / LISt GmbH (SPERRINFOSYS)",
            license_url=_DL_DE_BY_URL,
            modified=True,
        ),
        payload=RoadEventPayload(
            city_source="sperrinfosys",
            events=_backfill_events(raw.get("events", [])),
        ),
    )
