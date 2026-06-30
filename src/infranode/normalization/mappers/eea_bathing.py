"""Reiner EEA-Badegewaesser-Mapper map_bathing_water (Badegewaesserqualitaet).

Uebersetzt das flache raw-dict aus ``fetch_bathing_water`` deterministisch in einen
``CanonicalRecord`` mit ``BathingWaterPayload``. Die Funktion ist rein: kein HTTP,
kein Logging, kein ``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird
keyword-only injiziert (Determinismus).

Lizenz: CC-BY 4.0 (Tier A). Die Attribution nennt sowohl die Europaeische
Umweltagentur (EEA) als auch die EU-Badegewaesserrichtlinie 2006/7/EG. Die Werte
werden unveraendert durchgereicht (nur ortsnah gefiltert) -> ``modified`` bleibt
beim Default.

KRITISCH (Pitfall 4, Ehrlichkeit): Badegewaesser liegen ORTSNAH (Umland), NICHT
stadtgenau; ``distance_km`` je Stelle weist das aus. ``geo`` bleibt ``None``.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    BathingWaterPayload,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
)

_CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_bathing_water(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe EEA-Badegewaesserdaten auf einen ``CanonicalRecord`` ab.

    ``observed_at`` bleibt ``None`` (EEA liefert eine Jahres-Saisonbewertung, keinen
    Messzeitpunkt; ``season_year`` steht im Payload). Der ``retrieved_at``-Zeitstempel
    wird injiziert. Die Join-Keys ``ags``/``wikidata_qid`` kommen aus dem Register.
    ``geo=None`` (Pitfall 4: ortsnah, nicht stadtgenau).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.EEA_BATHING,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=(
                "European Environment Agency (EEA), Bathing Water Directive 2006/7/EC"
            ),
            license_url=_CC_BY_URL,
        ),
        payload=BathingWaterPayload(
            season_year=raw.get("season_year"),
            count=raw.get("count", 0),
            counts=raw.get("counts", {}),
            sites=raw.get("sites", []),
            truncated=raw.get("truncated", False),
        ),
    )
