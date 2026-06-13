"""Reiner Bundeswahl-Mapper map_election auf CanonicalRecord (DATA-20, Pitfall 7).

Uebersetzt ein flaches Wahlergebnis-raw-dict deterministisch in einen
``CanonicalRecord`` mit ``ElectionResultPayload`` (kind=election_result). Die
Funktion ist rein: kein HTTP, kein Logging, kein ``datetime.now()``. Der
``retrieved_at``-Zeitstempel wird keyword-only injiziert, damit Tests
deterministisch bleiben (analog map_flood).

KRITISCH (Lizenz-Klassifikation GOV-02): Bundeswahl ist Tier A (offene Lizenz),
``source=BUNDESWAHL``, ``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (DL-DE/BY 2.0).

KRITISCH (GOV-03, RESEARCH Pitfall 7): Die Granularitaet wird ehrlich als
"teilweise" ausgewiesen (Wahlkreis/Kreis-Ebene, Stadt nur teilweise abbildbar,
nur kreisfreie Staedte stadtscharf). Sowohl der Payload (``granularity``) als
auch die Attribution tragen PFLICHT das Wort "teilweise"; der Mapper-Test
asserted ``granularity == "teilweise"``.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    ElectionResultPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# DL-DE/BY 2.0 (Datenlizenz Deutschland, Namensnennung 2.0).
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_election(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet ein rohes Bundeswahl-Ergebnis auf einen ``CanonicalRecord`` ab.

    Der ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``). ``geo`` bleibt ``None`` (kein Geo je Wahlkreis); ``observed_at``
    bleibt ``None`` (Ergebnis-Layer ohne Mess-Zeitstempel, der Wahltermin steht
    im Payload-Feld ``election``).

    KRITISCH (Pitfall 7, GOV-03): Die Attribution traegt PFLICHT die Quelle
    "Die Bundeswahlleiterin" UND den Hinweis, dass die Stadt-Granularitaet nur
    "teilweise" abbildbar ist (Wahlkreis/Kreis-Ebene). Der Payload weist
    ``granularity="teilweise"`` aus.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.BUNDESWAHL,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=(
                "Die Bundeswahlleiterin, Granularitaet: Wahlkreis/Kreis, "
                "Stadt teilweise"
            ),
            license_url=_DL_DE_BY_URL,
        ),
        payload=ElectionResultPayload(
            election=raw.get("election"),
            granularity="teilweise",
            area_name=raw.get("area_name"),
            # [VERIFIED 2026-06-10] kerg2-Wahlbeteiligung (Prozent-String mit
            # Dezimal-KOMMA aus der Waehlende-Zeile), optional/additiv.
            turnout=raw.get("turnout"),
            results=raw.get("results", []),
        ),
    )
