"""Mapper: VGN/VAG-Nuernberg Live-Abfahrten -> CanonicalRecord (DATA-25, Tier A).

Bildet das raw-dict des ``adapters.vgn.fetch_vgn_departures`` (Halt + schlanke
Abfahrts-dicts inkl. Echtzeitprognose) auf den kanonischen Envelope ab. Wieder-
verwendung von ``TransitDeparturePayload`` (Phase 19, wie HVV-Geofox), da die
Form identisch ist: ``stop_id`` + ``departures``.

KRITISCH (GOV-02/03): Im Gegensatz zu HVV-Geofox ist die VAG/VGN-Echtzeit-API
OFFEN unter Creative Commons Attribution 4.0 (opendata.vag.de) -> ``license_id =
CC_BY_4_0``, ``license_tier = A`` (sauber verwertbar, NICHT Tier C). Reine Live-
Anzeige, KEIN Archiv. ``retrieved_at`` wird injiziert (keine Systemuhr im Mapper);
``observed_at`` stammt aus ``as_of`` (Metadata.Timestamp des Abfahrtsmonitors).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
)
from infranode.normalization.payloads import TransitDeparturePayload

_VGN_ATTRIBUTION = "Verkehrs-Aktiengesellschaft Nürnberg (VAG) / VGN"
_CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"


def _parse_as_of(raw: dict) -> datetime | None:
    """``as_of`` (Metadata.Timestamp, ISO) als aware datetime oder None (rein)."""
    text = raw.get("as_of")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def map_vgn_departures(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    city_slug: str = "nuernberg",
) -> CanonicalRecord:
    """Bildet VGN-Live-Abfahrten auf einen ``CanonicalRecord`` ab (Tier A, CC-BY).

    Die normalisierten ``departures`` (je Abfahrt line/direction/in_minutes/
    delay_s/alerts/product) wandern in den ``TransitDeparturePayload``. Tier A
    (CC-BY 4.0, offen), KEIN Archiv (reine Live-Daten).
    """
    return CanonicalRecord(
        city_slug=city_slug,
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.VGN,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text=_VGN_ATTRIBUTION, license_url=_CC_BY_URL),
        payload=TransitDeparturePayload(
            stop_id=raw.get("stop_id"),
            departures=raw.get("departures", []),
        ),
    )
