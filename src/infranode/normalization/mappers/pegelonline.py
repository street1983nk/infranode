"""Reiner PEGELONLINE-Pegel-Mapper map_water_level (DATA-11, GOV-01/03, Tier A).

Uebersetzt das flache PEGELONLINE-raw-dict deterministisch in einen
``CanonicalRecord`` mit ``WaterLevelPayload`` (kind=water_level). Die Funktion ist
rein: kein HTTP, kein Logging, kein ``datetime.now()``. Der ``retrieved_at``-
Zeitstempel wird keyword-only injiziert, damit Tests deterministisch bleiben.

KRITISCH (Lizenz-Klassifikation GOV-02): PEGELONLINE ist Tier A (offene Lizenz),
``license_id=DL_DE_ZERO_2_0``, ``license_tier=A``. Der Record wird ueber die Route
``/water-level`` ausgeliefert, ABER nur wenn eine Station gefunden wurde
(Binnenstadt liefert no_data).

KRITISCH (GOV-03): Datenlizenz Deutschland Zero 2.0 verlangt KEINE
Namensnennungspflicht; die Attribution wird dennoch gefuehrt ("PEGELONLINE / WSV")
und traegt KEIN ``modified`` (Daten nicht aufbereitet).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
    WaterLevelPayload,
)

# Datenlizenz Deutschland Zero 2.0 (keine Namensnennungspflicht).
_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"


def map_water_level(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe PEGELONLINE-Pegeldaten auf einen ``CanonicalRecord`` ab.

    ``observed_at`` kommt aus dem Mess-Zeitstempel (``raw["observed_at"]``); der
    ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``). ``geo`` bleibt ``None`` (Stadtebene, kein Stations-Geo). Die
    Attribution traegt KEIN ``modified`` (DL-DE/Zero, GOV-03).

    Diese Funktion wird NUR aufgerufen, wenn eine Station gefunden wurde; der
    no_data-Pfad (``raw["station"] is None``) wird bereits in der Route abgefangen.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=raw.get("observed_at"),
        retrieved_at=retrieved_at,
        source=SourceId.PEGELONLINE,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="PEGELONLINE / WSV",
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=WaterLevelPayload(
            station=raw.get("station"),
            water=raw.get("water"),
            value=raw.get("value"),
            unit=raw.get("unit"),
        ),
    )
