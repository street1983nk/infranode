"""Reiner DIVI-Live-ICU-Mapper map_icu_live (DATA-25b, T-08-DBR, Pitfall 4).

Uebersetzt das flache DIVI-Live-raw-dict (klinikscharfe Intensivregister-Live-API)
deterministisch in einen ``CanonicalRecord`` mit ``IcuCapacityPayload``
(kind=icu_capacity). Die Funktion ist rein: kein HTTP, kein Logging, kein
``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird keyword-only injiziert,
damit Tests deterministisch bleiben.

KRITISCH (DB-Schutzrecht, RESEARCH Pitfall 4, T-08-DBR): Die klinikscharfe
DIVI-Live-Lage ist KEINE offene Lizenz (Datenbank-Schutzrecht). Daher
``license_tier=LicenseTier.C`` (live-only) und
``license_id=LicenseId.UNKNOWN`` (ehrlicher Tag statt eines falschen pauschalen
CC-BY/DL-DE). Die Route ``/icu-live`` leitet diese Records ausschliesslich live
durch. Die Kreis-Aggregat-CSV (CC-BY 4.0, Tier A) laeuft getrennt ueber
``map_icu`` (mappers/divi.py).
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


def map_icu_live(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe DIVI-Live-ICU-Daten auf einen Tier-C-``CanonicalRecord`` ab.

    Der ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``). ``geo`` bleibt ``None`` (Kreisebene); ``observed_at`` bleibt
    ``None`` (das Stand-Datum steht im Payload ``datum``).

    [VERIFIED 2026-06-10] Die Live-API liefert keine numerische Belegung mehr;
    ``beds_free``/``beds_occupied`` bleiben ``None`` und die klinikscharfen
    Status-Einschaetzungen laufen in ``hospitals`` (bezeichnung, ort,
    letzte_meldung, status_high_care, status_ecmo).

    KRITISCH (T-08-DBR, Pitfall 4): ``source=DIVI``,
    ``license_id=LicenseId.UNKNOWN`` (keine offene Lizenz, klinikscharfes
    DB-Schutzrecht), ``license_tier=LicenseTier.C`` (live-only). Die Attribution
    traegt einen Disclaimer, dass die Daten nur live durchgeleitet werden
    (Tier C, keine dauerhafte Speicherung).
    """
    datum = raw.get("datum")
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DIVI,
        license_id=LicenseId.UNKNOWN,
        license_tier=LicenseTier.C,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=(
                "DIVI-Intensivregister (klinikscharfe Live-Lage). Datenbank-"
                "Schutzrecht: keine offene Lizenz, ausschliesslich live "
                f"durchgeleitet. Stand: {datum}"
            ),
            license_url=None,
        ),
        payload=IcuCapacityPayload(
            kreis_id=raw.get("kreis_id"),
            kreis_name=raw.get("kreis_name"),
            beds_free=raw.get("beds_free"),
            beds_occupied=raw.get("beds_occupied"),
            hospitals=raw.get("hospitals") or [],
            datum=datum,
        ),
    )
