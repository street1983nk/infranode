"""Reiner Bundes-Klinik-Atlas-Mapper map_hospital_atlas (Krankenhausstandorte).

Uebersetzt das flache raw-dict aus ``fetch_hospital_atlas`` deterministisch in
einen ``CanonicalRecord`` mit ``HospitalAtlasPayload``. Rein: kein HTTP, kein
Logging, kein ``datetime.now()`` (``retrieved_at`` injiziert).

FAIL-CLOSED (Lizenz): Der Bundes-Klinik-Atlas weist KEINE explizite offene Lizenz
aus -> license_id UNKNOWN, Tier C (live-only, kein Archiv), ehrlich getaggt bis
zur Bestaetigung durch BMG/IQTIG. KRITISCH (Pitfall 4): ortsnah gefiltert,
``distance_km`` je Standort; ``geo`` bleibt ``None``.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    HospitalAtlasPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_PROFILE_URL = "https://bundes-klinik-atlas.de/"


def map_hospital_atlas(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Bundes-Klinik-Atlas-Standorte auf einen ``CanonicalRecord`` ab.

    ``observed_at`` bleibt ``None`` (Stammdaten, kein Messzeitpunkt). Lizenz
    UNKNOWN/Tier C (fail-closed). Join-Keys aus dem Register. ``geo=None``
    (Pitfall 4: ortsnah, nicht stadtgenau).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.KLINIK_ATLAS,
        license_id=LicenseId.UNKNOWN,
        license_tier=LicenseTier.C,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundes-Klinik-Atlas (BMG/IQTIG)",
            license_url=_PROFILE_URL,
        ),
        payload=HospitalAtlasPayload(
            count=raw.get("count", 0),
            total_beds=raw.get("total_beds"),
            truncated=raw.get("truncated", False),
            hospitals=raw.get("hospitals", []),
        ),
    )
