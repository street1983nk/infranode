"""Reiner Mapper map_public_tender (DATA-21, öffentliche Auftragsvergabe).

Bildet ein vom Adapter (``adapters.oeffentlichevergabe.parse_ocds_release``)
geparstes OCDS-Notice-dict deterministisch auf einen ``CanonicalRecord`` mit
``PublicTenderPayload`` (``kind="public_tender"``) ab. Quelle ist der Datenservice
Öffentlicher Einkauf (oeffentlichevergabe.de, Beschaffungsamt des BMI), CC0 =
Tier A.

Die Stadt-Zuordnung passiert NICHT hier, sondern in
``infranode.tenders.matching``; der Mapper nimmt den bereits aufgelösten
``slug`` und die ``match``-Liste (``buyer_city`` | ``place_of_performance``) als
Argumente und schreibt sie ins Payload. ``buyer_city`` trägt den
(slugifizierten) Stadt-Bezug, ``nuts`` den NUTS-3-Code des Auftraggebers.

Rein: kein I/O, kein Logging, kein Wall-Clock. Der ``retrieved_at``-Zeitanker
wird injiziert; ``observed_at`` wird aus dem ``publication_date`` der
Bekanntmachung abgeleitet (falls parsbar, sonst None). Geo liegt nicht vor
(``geo=None``).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    PublicTenderPayload,
    SourceId,
)

# CC Zero 1.0 (Public Domain). Verbatim deckungsgleich mit
# SOURCE_LICENSE["oeffentlichevergabe"] / DATA-LICENSES.md (Lizenz-Drift-Gate).
_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
_ATTRIBUTION = (
    "Datenservice Oeffentlicher Einkauf (oeffentlichevergabe.de) "
    "/ Beschaffungsamt des BMI"
)

# Stabile Notice-URL auf der Plattform (aus der fachlichen notice_id abgeleitet).
_NOTICE_URL_PREFIX = "https://oeffentlichevergabe.de/notices/"


def _parse_observed_at(value: str | None) -> datetime | None:
    """Parst einen ISO-8601-Publikationszeitpunkt defensiv (unparsbar -> None).

    Rein und ohne Wall-Clock: nur ``datetime.fromisoformat`` (das den OCDS-ISO-
    String inkl. Zeitzone versteht). Ein fehlender/ungueltiger Wert ergibt None.
    Die kanonische UTC-Vereinheitlichung übernimmt der ``CanonicalRecord``-
    Validator.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _source_url(notice: dict) -> str | None:
    """Leitet eine stabile Notice-URL aus der notice_id ab (oder None)."""
    notice_id = notice.get("notice_id")
    if isinstance(notice_id, str) and notice_id.strip():
        return f"{_NOTICE_URL_PREFIX}{notice_id.strip()}"
    return None


def map_public_tender(
    notice: dict,
    *,
    slug: str,
    match: list[str],
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet ein OCDS-Notice-dict auf einen Tier-A-``CanonicalRecord`` ab.

    ``slug`` ist der bereits aufgelöste Register-Stadt-Slug (Stadt-Zuordnung in
    ``tenders.matching``), ``match`` die Herkunfts-Liste (``buyer_city`` |
    ``place_of_performance``). Beide werden ins ``PublicTenderPayload``
    geschrieben. ``buyer_city`` trägt den Slug-Bezug, ``nuts`` den NUTS-3-Code
    des Auftraggebers (``buyer_region`` aus dem geparsten Notice-dict).

    Rein: kein I/O. ``observed_at`` aus ``publication_date`` (falls parsbar);
    ``retrieved_at`` injiziert; ``geo=None``. Quelle CC0 = Tier A.
    """
    payload = PublicTenderPayload(
        notice_id=notice.get("notice_id"),
        notice_version=notice.get("notice_version"),
        notice_type=notice.get("notice_type"),
        status=notice.get("status"),
        title=notice.get("title"),
        buyer_name=notice.get("buyer_name"),
        buyer_city=slug,
        buyer_postal_code=notice.get("buyer_postal_code"),
        nuts=notice.get("buyer_region"),
        cpv=notice.get("cpv"),
        value=notice.get("value"),
        currency=notice.get("currency"),
        publication_date=notice.get("publication_date"),
        deadline=notice.get("deadline"),
        award_date=notice.get("award_date"),
        match=list(match),
        source_url=_source_url(notice),
    )

    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=_parse_observed_at(notice.get("publication_date")),
        retrieved_at=retrieved_at,
        source=SourceId.OEFFENTLICHEVERGABE,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text=_ATTRIBUTION, license_url=_CC0_URL),
        payload=payload,
    )
