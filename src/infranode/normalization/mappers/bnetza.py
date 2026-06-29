"""Reiner BNetzA-Ladesäulen-Mapper map_charging (DATA-09, GOV-01/03, Tier A).

Übersetzt das flache Adapter-dict (``slug``/``count``/``stations``)
deterministisch in einen ``CanonicalRecord`` mit ``ChargingStationPayload``. Die
Funktion ist rein: kein HTTP, kein Logging, kein ``datetime.now()``. Der
``retrieved_at``-Zeitstempel wird keyword-only injiziert, damit Tests
deterministisch bleiben.

Das BNetzA-Ladesäulenregister ist unter CC-BY 4.0 verfuegbar:
``license_id=CC_BY_4_0``, ``license_tier=A`` (kennzeichnet die permissive Lizenz
zur korrekten Attribution und Weiternutzung) und die wortgenaue Attribution
"Bundesnetzagentur.de" (Mapper-Test asserted sie, T-07-LIC). Die Einzel-Stationen
tragen ihre Koordinaten im Payload-dict, daher ``geo=None``; Stammdaten haben
keinen fachlichen Beobachtungszeitpunkt, daher ``observed_at=None``.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    ChargingStationPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_CC_BY_4_0_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_charging(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe BNetzA-Ladesäulen-Daten auf einen ``CanonicalRecord`` (Tier A) ab.

    ``count`` und ``stations`` landen im ``ChargingStationPayload``; die
    Einzel-Stationen tragen ihre Koordinaten selbst, daher ``geo=None``. Der
    ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``). ``stations`` wird defensiv per ``raw.get(...)`` gelesen
    (None-Fallback gegen ein fehlendes Feld, T-07-IN).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.BNETZA,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundesnetzagentur.de",
            license_url=_CC_BY_4_0_URL,
        ),
        payload=ChargingStationPayload(
            count=raw["count"],
            stations=raw.get("stations", []),
        ),
    )
