"""Reiner LHP-Hochwasser-Mapper map_flood (DATA-12, GOV-01/03, Pitfall 6).

Übersetzt das flache LHP-raw-dict deterministisch in einen ``CanonicalRecord``
mit ``FloodWarningPayload`` (kind=flood_warning). Die Funktion ist rein: kein
HTTP, kein Logging, kein ``datetime.now()``. Der ``retrieved_at``-Zeitstempel
wird keyword-only injiziert, damit Tests deterministisch bleiben.

KRITISCH (Tier-Trennung GOV-02): LHP ist Tier A,
``source=HOCHWASSER`` (Toggle-/Quellenname ist "lhp", License-/Record-Tag aber
HOCHWASSER), ``license_id=CC_BY_4_0``, ``license_tier=A``.

KRITISCH (GOV-03, Pitfall 6): Die CC-BY-4.0-Lizenz der Landeshochwasserportale
verlangt die Quelle UND einen Stand-Zeitstempel. Die Attribution trägt daher
PFLICHT den Wortlaut ``"Datenquelle: www.hochwasserzentralen.de, Stand: <stand>"``;
der Mapper-/Routen-Test asserted den ``"Stand:"``-String.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    FloodWarningPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# CC-BY 4.0 (Landeshochwasserportale, www.hochwasserzentralen.de).
_CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_flood(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe LHP-Hochwasserdaten auf einen ``CanonicalRecord`` ab.

    Der ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``). ``geo`` bleibt ``None`` (Stadtebene, kein Pegel-Geo);
    ``observed_at`` bleibt ``None`` (Event-Layer ohne Mess-Zeitstempel, der Stand
    steht im Payload/in der Attribution).

    KRITISCH (Pitfall 6, GOV-03): Die Attribution trägt PFLICHT den Wortlaut
    ``"Datenquelle: www.hochwasserzentralen.de, Stand: {stand}"`` (CC-BY 4.0); der
    ``"Stand:"``-Teil wird vom Mapper- und Routen-Test asserted.

    Leere ``warnings`` sind KEIN Fehler (keine aktive Warnung -> leeres Event).
    """
    stand = raw.get("stand")
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.HOCHWASSER,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=f"Datenquelle: www.hochwasserzentralen.de, Stand: {stand}",
            license_url=_CC_BY_URL,
        ),
        payload=FloodWarningPayload(
            warnings=raw.get("warnings", []),
            stand=stand,
        ),
    )
