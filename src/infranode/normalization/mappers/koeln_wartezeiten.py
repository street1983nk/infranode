"""Reiner Koeln-Behoerden-Wartezeiten-Mapper (Quick-260705-jgt, Tier A).

Uebersetzt das rohe Adapter-dict aus ``adapters/koeln_wartezeiten.py``
deterministisch in einen ``CanonicalRecord`` mit ``OfficeWaitTimesPayload``.

Schablone ist ``mappers/mobilithek_parken.map_dortmund_parking``: rein (kein HTTP,
keine Systemuhr), ``retrieved_at`` keyword-only injiziert (deterministisch). Quelle
steht unter Datenlizenz Deutschland Zero 2.0: ``license_id=DL_DE_ZERO_2_0``,
``license_tier=A`` (offenedaten-koeln.de, kundenzentren-koeln-wartezeiten),
Attribution "Stadt Koeln".

Zero-Trust (T-Q-03): fehlende/kaputte Felder, Nicht-dict-Items, nicht-numerisches
``wartezeit_minuten`` und ein unparsebarer ``timestamp`` werden zu ``None``/Skip,
nie zu einem Fehler. Reine Live-Daten -> ``geo=None``; das record-level
``observed_at`` ist der spaeteste aware-UTC-Zeitstempel ueber alle Standorte
(oder ``None``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    OfficeWaitTimesPayload,
    SourceId,
)

_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"
_KOELN_ATTRIBUTION = "Stadt Koeln"
# Der Feed liefert lokale Zeitstempel (Europe/Berlin) ohne Zeitzonen-Angabe.
_BERLIN = ZoneInfo("Europe/Berlin")


def _parse_int(value: object) -> int | None:
    """Parst ``wartezeit_minuten`` (String) robust zu int; sonst ``None`` (rein).

    Nicht-numerische oder fehlende Werte liefern ``None`` (kein Fehler, kein 0).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        return int(text)
    except ValueError:
        return None


def _parse_local(value: object) -> datetime | None:
    """Parst "YYYY-MM-DD HH:MM:SS" (Europe/Berlin) zu aware-UTC ``datetime`` (rein).

    Ein nicht-parsebarer/fehlender Wert liefert ``None`` (ehrlich, kein Fehler).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        naive = datetime.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None
    return naive.replace(tzinfo=_BERLIN).astimezone(UTC)


def _office(item: dict) -> dict:
    """Normalisiert ein rohes Feed-Item Zero-Trust zu einem schlanken office-dict.

    ``observed_at`` wird als ISO-UTC-String (oder ``None``) gefuehrt; ``is_open``
    ist True genau dann, wenn ``status`` == "1".
    """
    observed = _parse_local(item.get("timestamp"))
    return {
        "name": item.get("title_anz"),
        "wait_minutes": _parse_int(item.get("wartezeit_minuten")),
        "is_open": item.get("status") == "1",
        "status_text": item.get("sondertext"),
        "detail_url": item.get("link"),
        "observed_at": observed.isoformat() if observed is not None else None,
    }


def map_koeln_wartezeiten(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Koeln-Wartezeiten (office-wait-times) auf einen ``CanonicalRecord``.

    Die Standorte (je Kundenzentrum/Kfz-Zulassungsstelle name + wait_minutes/
    is_open/status_text/detail_url/observed_at) wandern in den
    ``OfficeWaitTimesPayload``. ``retrieved_at`` injiziert (keine Systemuhr im
    Mapper). Das record-level ``observed_at`` ist der spaeteste aware-UTC-
    Zeitstempel ueber alle Standorte (oder ``None``). Tier A, DL-DE/Zero 2.0
    (keyloser Direkt-Feed der Stadt Koeln), Attribution "Stadt Koeln".
    """
    items = [item for item in raw.get("items", []) if isinstance(item, dict)]

    offices: list[dict] = []
    latest: datetime | None = None
    for item in items:
        observed = _parse_local(item.get("timestamp"))
        if observed is not None and (latest is None or observed > latest):
            latest = observed
        offices.append(_office(item))

    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=latest,
        retrieved_at=retrieved_at,
        source=SourceId.KOELN_WARTEZEITEN,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_KOELN_ATTRIBUTION,
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=OfficeWaitTimesPayload(offices=offices),
    )
