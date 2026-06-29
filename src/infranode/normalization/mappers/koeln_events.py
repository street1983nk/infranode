"""Reiner Köln-Events-Mapper map_koeln_events (DATA-16, D-06, Tier A DL-DE/Zero).

Übersetzt das rohe Adapter-dict (``slug``/``events``) deterministisch in einen
``CanonicalRecord`` mit ``EventPayload``. Die Funktion ist rein: kein HTTP, keine
Log-Aufrufe, keine Systemuhr. Der ``retrieved_at``-Zeitstempel wird keyword-only
injiziert, damit Tests deterministisch bleiben.

Der Köln-Events-Feed (Stadt Köln) steht uniform unter der Datenlizenz
Deutschland Zero 2.0 (verifiziert 2026-06-26 gegen "Veranstaltungen der Stadt
Koeln" auf offenedaten-koeln.de, govdata.de/dl-de/zero-2-0; Köln stellt seit
Mitte 2022 standardmäßig unter DL-DE/Zero bereit). Statt das Tier hartzukodieren
(wie die Phase-9-Mapper) ruft dieser Mapper dieselbe
``map_license("dl-de-zero-2.0")``-Funktion wie der destination.one-Mapper auf
(D-06, single source of truth, REST-Regel 6) - das Ergebnis ist faktisch immer
``(DL_DE_ZERO_2_0, A)``. ``license_tier=A`` kennzeichnet die permissive Lizenz
(KEINE Namensnennungspflicht; Attribution "Stadt Köln" bleibt informativ).

Die Einzel-Events tragen ihre Zeit/Geometrie im Payload, daher ``observed_at=None``
und ``geo=None``. Der Feed ist nativ Zukunft (D-07 ohne eigene Heuristik); ein
zusätzlicher Datums-Guard ist nicht nötig.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    EventPayload,
    SourceId,
)
from infranode.normalization.mappers.licensing import map_license

_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"


def map_koeln_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Köln-Events auf einen ``CanonicalRecord`` (Tier A) ab.

    D-06: license_id/license_tier kommen aus ``map_license("dl-de-zero-2.0")``
    (dieselbe Logik wie destination.one, single source of truth) - faktisch immer
    ``(DL_DE_ZERO_2_0, A)``. Die ``events`` wandern unverändert in den
    ``EventPayload`` (``city_source="koeln_events"``). Der ``retrieved_at``-
    Zeitstempel wird injiziert (keine Systemuhr im Mapper). Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``). Events tragen ihre Zeit/Geometrie je Event, daher ``observed_at=None``
    und ``geo=None``.
    """
    # D-06: dieselbe map_license-Logik wie destination.one (Konsistenz, REST-Regel
    # 6). Ergebnis ist faktisch immer (DL_DE_ZERO_2_0, A).
    license_id, license_tier = map_license("dl-de-zero-2.0")

    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.KOELN_EVENTS,
        license_id=license_id,
        license_tier=license_tier,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Stadt Köln",
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=EventPayload(
            city_source="koeln_events",
            events=raw.get("events", []),
        ),
    )
