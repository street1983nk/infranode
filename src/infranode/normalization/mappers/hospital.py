"""Reiner Krankenhaus-Stammdaten-Mapper map_hospital (DATA-25a, GOV-03, Pitfall 6).

Uebersetzt das flache Destatis-Krankenhausverzeichnis-raw-dict (GENESIS 23111,
www-genesis.destatis.de) deterministisch in einen ``CanonicalRecord`` mit
``HospitalPayload`` (kind=hospital). Die Funktion ist rein: kein HTTP, kein
Logging, kein ``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird
keyword-only injiziert, damit Tests deterministisch bleiben.

KRITISCH (Lizenz-Klassifikation GOV-02): Krankenhaus-Stammdaten sind Tier A
(offene Lizenz), ``source=SourceId.GENESIS`` (EVAS 23111, gleiche Quelle wie die
Demografie, Finding W-1), ``license_id=DL_DE_BY_2_0``, ``license_tier=A``.

KRITISCH (RESEARCH Pitfall 6, T-08-LIC): Das Krankenhausverzeichnis traegt einen
EXAKTEN Destatis-Custom-Lizenz-Wortlaut, NICHT pauschal DL-DE/BY oder CC-BY. Die
Attribution muss diesen Wortlaut wortgenau fuehren:
``"Die Daten sind ohne Einschraenkung nutzbar: ..."`` (echte Umlaute in der
Prosa-Attribution).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    HospitalPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# DL-DE/BY 2.0 (Datenlizenz Deutschland Namensnennung 2.0, govdata.de).
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"

# RESEARCH Pitfall 6 (T-08-LIC): exakter Destatis-Custom-Wortlaut des
# Krankenhausverzeichnisses. Echte Umlaute (Prosa-Attribution), wortgenau, da der
# Mapper-/Doc-Test exakt diesen String asserted.
_DESTATIS_WORTLAUT = (
    "Die Daten sind ohne Einschränkung nutzbar: Vervielfältigung und "
    "Verbreitung der Daten, auch auszugsweise, sind mit Quellenangabe gestattet."
)


def map_hospital(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Destatis-Krankenhaus-Stammdaten auf einen ``CanonicalRecord`` ab.

    Der ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (ARCH-02,
    Default ``None``). ``geo`` bleibt ``None`` (Stadtebene); ``observed_at``
    bleibt ``None`` (das Stichdatum steht im Payload ``reference_date``).

    KRITISCH (GOV-02/03, Pitfall 6): ``source=GENESIS`` (EVAS 23111),
    ``license_id=DL_DE_BY_2_0``, ``license_tier=A``; die Attribution traegt PFLICHT
    den exakten Destatis-Custom-Wortlaut (NICHT pauschal DL-DE/BY) plus die Quelle.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.GENESIS,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=(
                _DESTATIS_WORTLAUT
                + " Quelle: Statistisches Bundesamt, Krankenhausverzeichnis"
            ),
            license_url=_DL_DE_BY_URL,
        ),
        payload=HospitalPayload(
            count=raw.get("count", 0),
            hospitals=raw.get("hospitals", []),
            reference_date=raw.get("reference_date"),
        ),
    )
