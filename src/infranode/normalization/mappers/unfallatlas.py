"""Reiner Unfallatlas-Mapper map_accidents (Verkehrsunfälle, DL-DE/BY 2.0, Tier A).

Bildet das Jahres-Aggregat aus dem SQLite-Reader (``archive.unfallatlas_db.
read_accidents``) deterministisch auf einen ``CanonicalRecord`` mit
``AccidentPayload`` ab. Rein: kein HTTP, kein ``datetime.now()`` (injiziert).

Lizenz DL-DE/BY 2.0, Attribution wortgenau "Statistische Ämter des Bundes und
der Länder, Unfallatlas" (muss verbatim in DATA-LICENSES.md + SOURCE_LICENSE
stehen). ``observed_at``/``geo`` bleiben ``None`` (Jahres-Aggregat je Kreis).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    AccidentPayload,
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_accidents(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet ein Unfall-Jahres-Aggregat auf einen ``CanonicalRecord`` ab.

    ``row`` ist das vom SQLite-Reader gelieferte dict (total/fatal/serious/light/
    with_*/reference_year/district_key). Der ``retrieved_at``-Zeitstempel wird
    injiziert (kein ``datetime.now()`` im Mapper). GOV-02/03: ``source=
    UNFALLATLAS``, ``license_id=DL_DE_BY_2_0``, Tier A.
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.UNFALLATLAS,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Statistische Ämter des Bundes und der Länder, Unfallatlas",
            license_url=_DL_DE_BY_URL,
        ),
        payload=AccidentPayload(
            reference_year=row.get("reference_year"),
            total=row.get("total"),
            fatal=row.get("fatal"),
            serious=row.get("serious"),
            light=row.get("light"),
            with_bicycle=row.get("with_bicycle"),
            with_pedestrian=row.get("with_pedestrian"),
            with_car=row.get("with_car"),
            with_motorcycle=row.get("with_motorcycle"),
            district_key=row.get("district_key"),
        ),
    )
