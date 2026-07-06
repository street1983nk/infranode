"""Reiner BBK-NINA-Mapper map_bbk_nina (§ 5 Abs. 2 UrhG, amtliches Werk, Tier A).

Uebersetzt das flache raw-dict aus ``adapters.bbk_nina`` deterministisch in einen
``CanonicalRecord`` mit ``CivilProtectionWarningPayload``. Rein: kein HTTP/Logging/
``datetime.now()`` (``retrieved_at`` injiziert).

LIZENZ-AUFLAGE: Der amtliche Warntext wird UNVERAENDERT durchgereicht, daher
``modified=False``. KEINE KI-/Maschinen-Umformulierung. Attribution wortgenau
"Bundesamt für Bevölkerungsschutz und Katastrophenhilfe (BBK)" (muss VERBATIM in
DATA-LICENSES.md + SOURCE_LICENSE stehen). Reine Live-Warnungen -> ``geo=None``,
``observed_at=None`` (kein Archiv-Write).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    CivilProtectionWarningPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# § 5 Abs. 2 UrhG (amtliches Werk, gemeinfrei; Weiterverbreitung nur unveraendert).
_URHG_URL = "https://www.gesetze-im-internet.de/urhg/__5.html"
_BBK_ATTRIBUTION = "Bundesamt für Bevölkerungsschutz und Katastrophenhilfe (BBK)"


def map_bbk_nina(
    slug: str,
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die rohen BBK-NINA-Warnungen auf einen ``CanonicalRecord`` ab.

    Der amtliche Warntext (``headline`` je Warnung) bleibt byte-identisch;
    ``Attribution.modified`` ist zwingend ``False`` (Aenderungsverbot § 5 Abs. 2
    UrhG). Tier A, ``LicenseId.AMTLICHES_WERK``, ``SourceId.BBK_NINA``. ``geo`` und
    ``observed_at`` sind ``None`` (reine Live-Warnungen, kein Archiv).
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.BBK_NINA,
        license_id=LicenseId.AMTLICHES_WERK,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_BBK_ATTRIBUTION,
            license_url=_URHG_URL,
            modified=False,
        ),
        payload=CivilProtectionWarningPayload(
            ars=raw.get("ars"),
            coverage_granularity=raw.get("coverage_granularity"),
            count=raw.get("count", 0),
            warnings=raw.get("warnings") or [],
        ),
    )
