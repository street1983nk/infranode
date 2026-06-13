"""Mapper: HVV-Geofox-GTI Live-Abfahrten -> CanonicalRecord (DATA-24, Tier C).

Bildet das raw-dict des ``adapters.hvv_geofox.fetch_hvv_departures`` (Station +
schlanke Abfahrts-dicts inkl. Verspätung und Linien-Störungshinweisen) auf den
kanonischen Envelope ab. Wiederverwendung von ``TransitDeparturePayload`` (Phase
19), da die Form identisch ist: ``stop_id`` + ``departures`` (Liste schlanker
dicts).

KRITISCH (GOV-02/03): Geofox ist Tier C (live-only). Die Lizenz ist nicht offen
(registrierungspflichtige HVV-API) -> ``license_id = UNKNOWN``, reine Live-
Anzeige, KEIN Archiv. Die Attribution nennt HVV/Geofox als Quelle (Pflicht).
``retrieved_at`` wird injiziert (keine Systemuhr im Mapper).
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

_HVV_ATTRIBUTION = "Hamburger Verkehrsverbund GmbH (HVV) / Geofox"


def map_hvv_departures(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    city_slug: str = "hamburg",
) -> CanonicalRecord:
    """Bildet HVV-Geofox-Live-Abfahrten auf einen ``CanonicalRecord`` ab (Tier C).

    Die normalisierten ``departures`` (je Abfahrt: line/direction/in_minutes/
    delay_s/alerts) wandern in den ``TransitDeparturePayload``. Tier C live-only,
    Lizenz UNKNOWN (Geofox nicht offen), KEIN Archiv.
    """
    return CanonicalRecord(
        city_slug=city_slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.HVV_GEOFOX,
        license_id=LicenseId.UNKNOWN,
        license_tier=LicenseTier.C,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text=_HVV_ATTRIBUTION, license_url=None),
        payload=TransitDeparturePayload(
            stop_id=raw.get("stop_id"),
            departures=raw.get("departures", []),
        ),
    )
