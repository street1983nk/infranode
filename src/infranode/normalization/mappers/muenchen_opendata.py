"""Reiner München-Mapper map_muenchen_road_events (DATA-15, Tier A DL-DE/BY).

Übersetzt das rohe Adapter-dict (``slug``/``events``) deterministisch in einen
``CanonicalRecord`` mit ``RoadEventPayload``. Die Funktion ist rein: kein HTTP,
keine Log-Aufrufe, keine Systemuhr. Der ``retrieved_at``-Zeitstempel wird
keyword-only injiziert, damit Tests deterministisch bleiben.

Die Baustellendaten der Landeshauptstadt München (CKAN-Paket
``baustellen_4_weeks_opendata`` auf opendata.muenchen.de, GeoJSON via WFS auf
geoportal.muenchen.de, [VERIFIED 2026-06-10]) sind unter der Datenlizenz
Deutschland Namensnennung 2.0 verfuegbar:
``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (kennzeichnet die permissive
Lizenz zur korrekten Attribution und Weiternutzung, T-9-03) und die wortgenaue
Attribution "Landeshauptstadt München". Die Einzel-Events tragen ihre Zeit und
Geometrie im Payload, daher ``observed_at=None`` und ``geo=None``.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    ParkingPayload,
    RoadEventPayload,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_muenchen_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Münchner Road-Events auf einen ``CanonicalRecord`` (Tier A) ab.

    Die ``events`` (Baustellen/Sperrungen, DATA-15) wandern unverändert in den
    ``RoadEventPayload`` (``city_source="muenchen_baustellen"``). Der
    ``retrieved_at``-Zeitstempel wird injiziert (keine Systemuhr im Mapper), damit
    das Ergebnis deterministisch bleibt. Die Join-Keys ``ags``/``wikidata_qid``
    werden aus dem Register durchgereicht (Default ``None``). Verkehrsereignisse
    tragen ihre Zeit/Geometrie je Event, daher bewusst ``observed_at=None`` und
    ``geo=None`` (keine strikte Geometry-Validierung, Pitfall 6).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.MUENCHEN_BAUSTELLEN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Landeshauptstadt München",
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="muenchen_baustellen",
            events=raw.get("events", []),
        ),
    )


def map_muenchen_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet den Münchner Parkhaus-Standortkatalog auf einen ``CanonicalRecord`` ab.

    Die ``facilities`` (Parkhaus-Standorte, DATA-40) wandern unverändert in den
    ``ParkingPayload``. STATISCHER Standortkatalog der Landeshauptstadt München
    (CKAN-Paket ``parkhaeuser-munchen`` auf opendata.muenchen.de, [VERIFIED
    2026-06-23]), KEINE Live-Belegung. Datenlizenz Deutschland Namensnennung 2.0
    (``license_id=DL_DE_BY_2_0``, ``license_tier=A``), wortgenaue Attribution
    "Landeshauptstadt München". Die Standorte tragen ihre Koordinaten je Eintrag,
    daher ``observed_at=None`` und ``geo=None``. ``retrieved_at`` wird injiziert
    (keine Systemuhr im Mapper), damit das Ergebnis deterministisch bleibt.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.MUENCHEN_PARKHAEUSER,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Landeshauptstadt München",
            license_url=_DL_DE_BY_URL,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )
