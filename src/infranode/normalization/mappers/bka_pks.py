"""Reiner BKA-PKS-Mapper ``map_crime_stats`` (Kriminalstatistik, DL-DE/BY 2.0, Tier A).

Bildet die Hauptstraftatengruppen aus dem SQLite-Reader
(``archive.bka_pks_db.read_crime_stats``) deterministisch auf einen
``CanonicalRecord`` mit ``CrimeStatsPayload`` ab. Rein: kein HTTP, kein Logging,
kein ``datetime.now()`` (``retrieved_at`` wird injiziert).

Quelle ist die Polizeiliche Kriminalstatistik (PKS) des Bundeskriminalamts.
Lizenz DL-DE/BY 2.0 (Tier A), Attribution wortgenau "Polizeiliche
Kriminalstatistik (PKS) - Bundeskriminalamt" (muss verbatim in source_specs +
DATA-LICENSES.md stehen, T-11-SRC-DRIFT). Das BKA verlangt zusaetzlich die Angabe
von Berichtsjahr und Version: beide werden im Payload (``reference_year`` +
``version``) gefuehrt. ``geo`` bleibt ``None`` (Kreis-/Stadtebene),
``observed_at`` bleibt ``None`` (das Berichtsjahr steht im Payload).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    CrimeStatsPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_crime_stats(
    slug: str,
    groups: list[dict],
    *,
    reference_year: int | None,
    version: str | None,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die PKS-Gruppen einer Stadt auf einen ``CanonicalRecord`` ab.

    ``groups`` ist die vom SQLite-Reader gelieferte Liste schlanker dicts
    (``key``/``label``/``cases``/``frequency_per_100k``/``clearance_rate_pct``). Der
    ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im Mapper),
    damit das Ergebnis deterministisch bleibt. ``reference_year`` (Berichtsjahr) und
    ``version`` (PKS-Stand) sind Attributionspflicht-Felder. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default ``None``).
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.BKA_PKS,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Polizeiliche Kriminalstatistik (PKS) - Bundeskriminalamt",
            license_url=_DL_DE_BY_URL,
            modified=False,
        ),
        payload=CrimeStatsPayload(
            reference_year=reference_year,
            version=version,
            groups=groups,
        ),
    )
