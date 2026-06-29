"""Reiner Bundeswahl-Mapper map_election auf CanonicalRecord (DATA-20, Pitfall 7).

Übersetzt ein flaches Wahlergebnis-raw-dict deterministisch in einen
``CanonicalRecord`` mit ``ElectionResultPayload`` (kind=election_result). Die
Funktion ist rein: kein HTTP, kein Logging, kein ``datetime.now()``. Der
``retrieved_at``-Zeitstempel wird keyword-only injiziert, damit Tests
deterministisch bleiben (analog map_flood).

KRITISCH (Lizenz-Klassifikation GOV-02): Bundeswahl ist Tier A (offene Lizenz),
``source=BUNDESWAHL``, ``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (DL-DE/BY 2.0).

KRITISCH (GOV-03, RESEARCH Pitfall 7): Die Granularität wird ehrlich ausgewiesen.
Default ist "teilweise" (Wahlkreis/Kreis-Ebene, Stadt nur teilweise abbildbar);
Städte, deren Wahlkreise sie EXAKT abdecken (saubere Wahlkreis-Vereinigung,
Audit-Finding 47), liefert der Ingest mit ``granularity="stadt"`` (stadtgenau aus
den Wahlkreisen aggregiert). Payload (``granularity``) und Attribution tragen den
jeweiligen Wert.
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

    KRITISCH (Pitfall 7, GOV-03): Die Attribution trägt PFLICHT die Quelle
    "Die Bundeswahlleiterin". Die Granularität kommt aus ``raw["granularity"]``
    (Default "teilweise"): Städte, deren Wahlkreise sie EXAKT abdecken (saubere
    Wahlkreis-Vereinigung, Audit-Finding 47), werden als "stadt" aggregiert und
    die Attribution weist das stadtgenau aus; sonst bleibt es ehrlich "teilweise"
    (Wahlkreis/Kreis-Ebene, Stadt nur teilweise abbildbar).
    """
    granularity = raw.get("granularity") or "teilweise"
    if granularity == "stadt":
        attribution_text = (
            "Die Bundeswahlleiterin, Granularitaet: Stadt (stadtgenau aus den "
            "Wahlkreisen der Stadt aggregiert)"
        )
    else:
        attribution_text = (
            "Die Bundeswahlleiterin, Granularitaet: Wahlkreis/Kreis, Stadt teilweise"
        )
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
            text=attribution_text,
            license_url=_DL_DE_BY_URL,
        ),
        payload=ElectionResultPayload(
            election=raw.get("election"),
            granularity=granularity,
            area_name=raw.get("area_name"),
            # [VERIFIED 2026-06-10] kerg2-Wahlbeteiligung (Prozent-String mit
            # Dezimal-KOMMA): bei "teilweise" aus der Wählende-Zeile, bei "stadt"
            # aus den aufsummierten absoluten Stimmen (Waehlende/Wahlberechtigte).
            turnout=raw.get("turnout"),
            results=raw.get("results", []),
        ),
    )
