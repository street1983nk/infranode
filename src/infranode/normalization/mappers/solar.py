"""Reiner PVGIS-Solar-Mapper map_solar (DATA-38, GOV-03).

Uebersetzt das flache PVGIS-raw-dict deterministisch in einen ``CanonicalRecord``
mit ``SolarPayload``. Die Funktion ist rein: kein HTTP, kein Logging, kein
``datetime.now()`` (der ``retrieved_at``-Zeitstempel wird keyword-only injiziert,
damit Tests deterministisch bleiben).

``observed_at`` bleibt bewusst ``None``: PVGIS liefert ein klimatologisches
Mehrjahresmittel, keinen Messzeitpunkt; der Bezugszeitraum steht als
``period_start``/``period_end`` im Payload (record_id faellt damit auf
``retrieved_at`` zurueck, ARCH-02).

KRITISCH (GOV-03): PVGIS-Daten sind aufbereitet (InfraNode normiert auf 1 kWp bei
optimalem Winkel und formt das Schema um), daher traegt die Attribution
``modified=True`` und den wortgenauen PVGIS-Hinweis. Lizenz und Tier sind
hartkodiert: EU-Reuse-Policy (EC_REUSE, faktisch CC BY 4.0, frei nutzbar mit
Quellenangabe) = Tier A.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SolarPayload,
    SourceId,
)

_PVGIS_URL = (
    "https://joint-research-centre.ec.europa.eu/"
    "photovoltaic-geographical-information-system-pvgis_en"
)


def map_solar(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe PVGIS-Solar-Kennzahlen auf einen ``CanonicalRecord`` ab.

    ``retrieved_at`` wird injiziert (kein ``datetime.now()`` im Mapper), damit das
    Ergebnis deterministisch und voll testbar bleibt. Die Join-Keys ``ags``/
    ``wikidata_qid`` werden aus dem Register durchgereicht (Default ``None``).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=GeoPoint(lat=raw["lat"], lon=raw["lon"]),
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.SOLAR,
        license_id=LicenseId.EC_REUSE,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="PVGIS © European Communities, 2001-2026",
            license_url=_PVGIS_URL,
            modified=True,
        ),
        payload=SolarPayload(
            annual_irradiation_kwh_m2=raw.get("annual_irradiation_kwh_m2"),
            annual_yield_kwh_kwp=raw.get("annual_yield_kwh_kwp"),
            optimal_slope_deg=raw.get("optimal_slope_deg"),
            optimal_azimuth_deg=raw.get("optimal_azimuth_deg"),
            peakpower_kwp=raw.get("peakpower_kwp"),
            system_loss_pct=raw.get("system_loss_pct"),
            radiation_db=raw.get("radiation_db"),
            period_start=raw.get("period_start"),
            period_end=raw.get("period_end"),
            monthly=raw.get("monthly") or [],
        ),
    )
