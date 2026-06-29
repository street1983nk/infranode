"""Reiner Bremen-Mobilithek-Mapper (DATA-31, Tier A DL-DE/BY, Live).

Übersetzt das rohe Adapter-dict aus ``adapters/mobilithek_datex2.py``
(``parse_datex2_situations`` -> ``{"slug","events","as_of"}``) deterministisch in
einen ``CanonicalRecord`` mit ``RoadEventPayload`` (Bremen Baustellen/
Arbeitsstellen, SituationPublication). Schablone ist ``mappers/mobilithek_koeln``:
rein (kein HTTP, kein XML-Parse, keine Systemuhr), ``retrieved_at`` keyword-only
injiziert. Der Bremen-Feed (Verkehrsmanagementzentrale Bremen) steht unter der
Datenlizenz Deutschland Namensnennung 2.0: ``license_id=DL_DE_BY_2_0``,
``license_tier=A``. Attribution wortgenau "Freie Hansestadt Bremen" (muss exakt
in SOURCE_LICENSE / DATA-LICENSES.md stehen).

Reine Live-Daten -> ``geo=None`` (Geo je Event im Payload); ``observed_at`` aus
der DATEX-II ``publicationTime`` (``as_of``) falls vorhanden, sonst ``None``.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    RoadEventPayload,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_BREMEN_ATTRIBUTION = "Freie Hansestadt Bremen"


def _parse_as_of(raw: dict) -> datetime | None:
    """Liest ``as_of`` (DATEX-II publicationTime) als aware ``datetime`` oder None."""
    text = raw.get("as_of")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def map_bremen_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet Bremen-Baustellen (situation) auf einen ``CanonicalRecord`` ab (Tier A).

    Die ``events`` (Baustellen/Arbeitsstellen, BBox-gefiltert um Bremen) wandern in
    den ``RoadEventPayload`` (``city_source="bremen_baustellen"``). ``observed_at``
    aus der DATEX-II ``publicationTime`` (``as_of``) falls vorhanden.
    ``retrieved_at`` injiziert (keine Systemuhr im Mapper).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.BREMEN_BAUSTELLEN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_BREMEN_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="bremen_baustellen",
            events=raw.get("events", []),
        ),
    )
