"""Reiner MobiData-BW-Road-Event-Mapper (DATA-15, Tier A DL-DE/BY).

Übersetzt das rohe Adapter-dict (``slug``/``events`` aus
``adapters/mobidata_bw.py``) deterministisch in einen ``CanonicalRecord`` mit
``RoadEventPayload`` (``city_source="mobidata_bw"``). Die Funktion ist rein: kein
HTTP, kein XML-Parse, keine Systemuhr. Der ``retrieved_at``-Zeitstempel wird
keyword-only injiziert, damit Tests deterministisch bleiben.

Der landesweite BW-DATEX-II-Feed (MobiData BW, Verkehrsministerium Baden-
Württemberg) steht unter der Datenlizenz Deutschland Namensnennung 2.0:
``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (kennzeichnet die permissive
Lizenz zur korrekten Attribution und Weiternutzung, T-9-03 / Verifikation 09-06)
und die wortgenaue Attribution
"Verkehrsministerium Baden-Württemberg / MobiData BW". Verkehrs-
ereignisse tragen ihre Zeit/Geometrie je Event, daher ``observed_at=None`` und
``geo=None`` (keine strikte Geometry-Validierung, RESEARCH Pitfall 6).
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


def map_mobidata_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe MobiData-Road-Events auf einen ``CanonicalRecord`` (Tier A) ab.

    Die ``events`` (Baustellen/Sperrungen, DATA-15) wandern unverändert in den
    ``RoadEventPayload`` (``city_source="mobidata_bw"``). Der ``retrieved_at``-
    Zeitstempel wird injiziert (keine Systemuhr im Mapper), damit das Ergebnis
    deterministisch bleibt. Die Join-Keys ``ags``/``wikidata_qid`` werden aus dem
    Register durchgereicht (Default ``None``). Verkehrsereignisse tragen ihre
    Zeit/Geometrie je Event, daher bewusst ``observed_at=None`` und ``geo=None``.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.MOBIDATA_BW,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Verkehrsministerium Baden-Württemberg / MobiData BW",
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="mobidata_bw",
            events=raw.get("events", []),
        ),
    )
