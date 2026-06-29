"""Reiner DIVI-RKI-ICU-Mapper map_icu (DATA-25b, GOV-02/03, Pitfall 5/6).

Übersetzt das flache RKI-DIVI-raw-dict (Kreisebene, aus der RKI-GitHub-CSV)
deterministisch in einen ``CanonicalRecord`` mit ``IcuCapacityPayload``
(kind=icu_capacity). Die Funktion ist rein: kein HTTP, kein Logging, kein
``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird keyword-only injiziert,
damit Tests deterministisch bleiben.

KRITISCH (Tier-Trennung GOV-02): Die RKI-GitHub-DIVI-CSV ist Kreisebene unter
CC-BY 4.0 (RKI, DIVI-Intensivregister) und damit permissiv lizenziert (Tier A). NICHT zu
verwechseln mit der klinikscharfen DIVI-Live-API (Tier C, DB-Schutzrecht): die
läuft über ``map_icu_live`` und wird ausschließlich live durchgeleitet.

KRITISCH (GOV-03, Pitfall 6): CC-BY 4.0 verlangt die Quelle UND einen Stand. Die
Attribution trägt daher PFLICHT den Wortlaut mit "Robert Koch-Institut (RKI)"
und dem ``datum`` als Stand. ``observed_at`` bleibt ``None`` (das Stand-Datum
steht im Payload ``datum``), ``geo`` bleibt ``None`` (Kreisebene, kein Punkt-Geo).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    IcuCapacityPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# CC-BY 4.0 (RKI, DIVI-Intensivregister, GitHub-Raw-CSV, Kreisebene).
_CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_icu(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe RKI-DIVI-ICU-Kreisdaten auf einen ``CanonicalRecord`` ab.

    Der ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (ARCH-02,
    Default ``None``). ``geo`` bleibt ``None`` (Kreisebene); ``observed_at``
    bleibt ``None`` (das Stand-Datum steht im Payload ``datum``).

    KRITISCH (GOV-02/03, Pitfall 6): ``source=DIVI``, ``license_id=CC_BY_4_0``,
    ``license_tier=A``; die Attribution nennt PFLICHT das Robert Koch-Institut
    (RKI), das DIVI-Intensivregister und das ``datum`` als Stand.
    """
    datum = raw.get("datum")
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DIVI,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=(f"Robert Koch-Institut (RKI), DIVI-Intensivregister, Stand: {datum}"),
            license_url=_CC_BY_URL,
        ),
        payload=IcuCapacityPayload(
            kreis_id=raw.get("kreis_id"),
            kreis_name=raw.get("kreis_name"),
            beds_free=raw.get("beds_free"),
            beds_occupied=raw.get("beds_occupied"),
            datum=datum,
        ),
    )
