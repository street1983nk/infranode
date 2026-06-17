"""Reiner KBA-Mapper map_vehicle_registrations (Pkw-Bestand, DL-DE/BY 2.0, Tier A).

Bildet die schlanke Zulassungsbezirk-Zeile aus dem SQLite-Reader
(``archive.kba_db.read_vehicle_registrations``) deterministisch auf einen
``CanonicalRecord`` mit ``VehicleRegistrationPayload`` ab. Rein: kein HTTP, kein
Logging, kein ``datetime.now()`` (``retrieved_at`` wird injiziert).

Das Kraftfahrt-Bundesamt fuehrt im Datensatz nur Anteile (Prozent), keine
absoluten E-Auto-Zahlen; ``bev_estimated`` wird hier aus ``pkw_total`` und
``bev_share`` abgeleitet (klar als abgeleitet gekennzeichnet, ``modified=False``
fuer die unveraenderten Quell-Anteile). Lizenz DL-DE/BY 2.0, Attribution
wortgenau "Kraftfahrt-Bundesamt (KBA)" (muss verbatim in DATA-LICENSES.md +
SOURCE_LICENSE stehen).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
    VehicleRegistrationPayload,
)

# DL-DE/BY 2.0 (Datenlizenz Deutschland Namensnennung 2.0, govdata.de).
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def _bev_estimated(pkw_total: int | None, bev_share: float | None) -> int | None:
    """Leitet die absolute BEV-Zahl aus Gesamtbestand und BEV-Anteil ab.

    Beide Werte noetig; sonst ``None`` (ehrliche Degradation, keine 0). Rundet
    kaufmaennisch auf eine ganze Zahl.
    """
    if pkw_total is None or bev_share is None:
        return None
    return round(pkw_total * bev_share / 100)


def map_vehicle_registrations(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet eine KBA-Zulassungsbezirk-Zeile auf einen ``CanonicalRecord`` ab.

    ``row`` ist die vom SQLite-Reader gelieferte schlanke Zeile (``pkw_total``/
    ``bev_share``/``electric_share``/``plugin_hybrid_share``/``district``/
    ``district_key``/``reference_period``). Der ``retrieved_at``-Zeitstempel wird
    injiziert (kein ``datetime.now()`` im Mapper), damit das Ergebnis
    deterministisch bleibt. Die Join-Keys ``ags``/``wikidata_qid`` werden aus dem
    Register durchgereicht (Default ``None``). ``geo`` bleibt ``None`` (Bezirk-
    /Stadtebene); ``observed_at`` bleibt ``None`` (der Berichtszeitpunkt steht im
    Payload).
    """
    pkw_total = row.get("pkw_total")
    bev_share = row.get("bev_share")
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.KBA,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Kraftfahrt-Bundesamt (KBA)",
            license_url=_DL_DE_BY_URL,
            modified=False,
        ),
        payload=VehicleRegistrationPayload(
            pkw_total=pkw_total,
            electric_share=row.get("electric_share"),
            bev_share=bev_share,
            plugin_hybrid_share=row.get("plugin_hybrid_share"),
            bev_estimated=_bev_estimated(pkw_total, bev_share),
            district=row.get("district"),
            district_key=row.get("district_key"),
            reference_period=row.get("reference_period"),
        ),
    )
