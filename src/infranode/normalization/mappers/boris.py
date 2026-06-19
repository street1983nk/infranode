"""Reiner BORIS-Mapper ``map_land_values`` (amtliche Bodenrichtwerte, Tier A).

Bildet die aggregierte Bodenrichtwert-Zeile aus dem SQLite-Reader
(``archive.boris_db.read_land_values``) deterministisch auf einen
``CanonicalRecord`` mit ``LandValuesPayload`` ab. Rein: kein HTTP, kein Logging,
kein ``datetime.now()`` (``retrieved_at`` wird injiziert).

Quelle ist BORIS (Bodenrichtwert-Informationssystem der Gutachterausschuesse),
foederiert je Bundesland. Lizenz + wortgenaue Attribution werden je Land getragen
(die Zeile aus dem Store fuehrt ``license_id``/``attribution``/``license_url``
mit, da die Lizenzen je Land variieren; Berlin = DL-DE/Zero 2.0). Die Werte sind
unveraenderte Quell-Kennzahlen (``modified=False``); ``geo`` bleibt ``None``
(aggregiert ueber das Stadtgebiet), ``observed_at`` bleibt ``None`` (der
Bewertungsstichtag steht im Payload).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LandValuesPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)


def map_land_values(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die aggregierte BORIS-Kennzahl einer Stadt auf einen Record ab.

    ``row`` ist das vom SQLite-Reader gelieferte dict (``brw_median_eur_m2``/
    ``brw_min_eur_m2``/``brw_max_eur_m2``/``zone_count``/``stichtag``/
    ``bbox_radius_deg`` + ``license_id``/``attribution``/``license_url``). Der
    ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Lizenz wird aus der
    Zeile uebernommen (je Land verschieden); der Tier ist fuer alle offenen
    Lizenzen A.
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.BORIS,
        license_id=LicenseId(row["license_id"]),
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=row["attribution"],
            license_url=row["license_url"],
            modified=False,
        ),
        payload=LandValuesPayload(
            brw_median_eur_m2=row["brw_median_eur_m2"],
            brw_min_eur_m2=row["brw_min_eur_m2"],
            brw_max_eur_m2=row["brw_max_eur_m2"],
            zone_count=row["zone_count"],
            stichtag=row["stichtag"],
            bbox_radius_deg=row["bbox_radius_deg"],
        ),
    )
