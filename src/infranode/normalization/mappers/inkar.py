"""Reiner INKAR-Mapper ``map_indicators`` (BBSR-Indikatoren, DL-DE/BY 2.0, Tier A).

Bildet die Indikator-Zeilen aus dem SQLite-Reader
(``archive.inkar_db.read_indicators``) deterministisch auf einen
``CanonicalRecord`` mit ``IndicatorsPayload`` ab. Rein: kein HTTP, kein Logging,
kein ``datetime.now()`` (``retrieved_at`` wird injiziert).

Quelle ist das Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR) /
INKAR (Indikatoren und Karten zur Raum- und Stadtentwicklung). Lizenz DL-DE/BY
2.0, Attribution wortgenau "Bundesinstitut für Bau-, Stadt- und Raumforschung
(BBSR), INKAR" (muss verbatim in DATA-LICENSES.md + SOURCE_LICENSE stehen). Die
Werte sind unveränderte Quell-Kennzahlen (``modified=False``); ``geo`` bleibt
``None`` (Kreis-/Stadtebene), ``observed_at`` bleibt ``None`` (das Jahr steht je
Indikator im Payload).
"""

from __future__ import annotations

import re
from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    IndicatorsPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"

# INKAR führt die Einheit nur im name-String als Klammerzusatz "(in %)" / "(in EUR)"
# (Audit 2026-06-29). Wir extrahieren sie zusätzlich in ein strukturiertes unit-Feld.
_UNIT_RE = re.compile(r"\(in\s+([^)]+)\)", re.IGNORECASE)


def _extract_unit(name: object) -> str | None:
    """Liest die Einheit aus dem INKAR-Indikatornamen ("(in %)" -> "%"); sonst None."""
    if not isinstance(name, str):
        return None
    match = _UNIT_RE.search(name)
    return match.group(1).strip() if match else None


def map_indicators(
    slug: str,
    rows: list[dict],
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die INKAR-Indikator-Zeilen einer Stadt auf einen ``CanonicalRecord`` ab.

    ``rows`` ist die vom SQLite-Reader gelieferte Liste schlanker dicts
    (``gruppe``/``name``/``value``/``year``/``category``). Der ``retrieved_at``-
    Zeitstempel wird injiziert (kein ``datetime.now()`` im Mapper), damit das
    Ergebnis deterministisch bleibt. Die Join-Keys ``ags``/``wikidata_qid`` werden
    aus dem Register durchgereicht (Default ``None``).
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.INKAR,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR), INKAR",
            license_url=_DL_DE_BY_URL,
            modified=False,
        ),
        payload=IndicatorsPayload(
            indicator_count=len(rows),
            # Einheit zusätzlich strukturiert je Indikator (aus dem name-String).
            indicators=[
                {**row, "unit": _extract_unit(row.get("name"))} for row in rows
            ],
        ),
    )
