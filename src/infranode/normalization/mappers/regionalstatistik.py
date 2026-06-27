"""Reiner Regionalstatistik-Mapper (DATA-37, DL-DE/BY 2.0, Tier A).

Bildet die Reader-Zeilen aus ``archive.regionalstatistik_db`` deterministisch auf
einen ``CanonicalRecord`` ab: ``map_tax_rates`` (Realsteuer-Hebesaetze, Tabelle
71231) und ``map_business_registrations`` (Gewerbean-/-abmeldungen, Tabelle
52311). Rein: kein HTTP, kein Logging, kein ``datetime.now()`` (``retrieved_at``
wird injiziert).

Quelle ist der GENESIS-Webservice der Statistischen Aemter des Bundes und der
Laender (regionalstatistik.de). Lizenz DL-DE/BY 2.0, Attribution wortgenau
"Statistische Ämter des Bundes und der Länder" (muss verbatim in DATA-LICENSES.md
+ SOURCE_LICENSE stehen, T-11-SRC-DRIFT). Die Werte sind unveraenderte
Quell-Kennzahlen (``modified=False``); ``geo`` bleibt ``None`` (Gemeinde-/
Kreisebene), ``observed_at`` bleibt ``None`` (Stichtag/Jahr steht im Payload).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    BusinessRegistrationsPayload,
    CanonicalRecord,
    InsolvenciesPayload,
    LicenseId,
    LicenseTier,
    SourceId,
    TaxRatesPayload,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_ATTRIBUTION = "Statistische Ämter des Bundes und der Länder"


def _record(slug: str, payload, *, retrieved_at, ags, wikidata_qid) -> CanonicalRecord:
    """Baut den gemeinsamen CanonicalRecord-Envelope beider Regionalstatistik-Mapper."""
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.REGIONALSTATISTIK,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
            modified=False,
        ),
        payload=payload,
    )


def map_tax_rates(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Hebesatz-Zeile einer Stadt auf einen ``CanonicalRecord`` ab (71231).

    ``row`` ist das vom Reader gelieferte dict (``gewerbesteuer``/``grundsteuer_a``/
    ``grundsteuer_b``/``grundsteuer_c``/``stichtag``). ``retrieved_at`` wird
    injiziert (kein ``datetime.now()`` im Mapper). Die Join-Keys ``ags``/
    ``wikidata_qid`` werden aus dem Register durchgereicht.
    """
    payload = TaxRatesPayload(
        gewerbesteuer_hebesatz=row.get("gewerbesteuer"),
        grundsteuer_a=row.get("grundsteuer_a"),
        grundsteuer_b=row.get("grundsteuer_b"),
        grundsteuer_c=row.get("grundsteuer_c"),
        stichtag=row.get("stichtag"),
    )
    return _record(
        slug, payload, retrieved_at=retrieved_at, ags=ags, wikidata_qid=wikidata_qid
    )


def map_business_registrations(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Gewerbeanzeigen-Zeile einer Stadt auf einen ``CanonicalRecord`` ab.

    ``row`` ist das vom Reader gelieferte dict (``anmeldungen``/``abmeldungen``/
    ``saldo``/``jahr``, Tabelle 52311). ``retrieved_at`` wird injiziert. Die
    Join-Keys ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht.
    """
    payload = BusinessRegistrationsPayload(
        anmeldungen=row.get("anmeldungen"),
        abmeldungen=row.get("abmeldungen"),
        saldo=row.get("saldo"),
        jahr=row.get("jahr"),
    )
    return _record(
        slug, payload, retrieved_at=retrieved_at, ags=ags, wikidata_qid=wikidata_qid
    )


def map_insolvencies(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Insolvenz-Zeile einer Stadt auf einen ``CanonicalRecord`` ab.

    ``row`` ist das vom Reader gelieferte dict (``unternehmensinsolvenzen``/
    ``uebrige_schuldner_insolvenzen``/``jahr``, Tabellen 52411-02 ISV006 + 52411-03
    ISV007). ``retrieved_at`` wird injiziert (kein ``datetime.now()`` im Mapper).
    Die Join-Keys ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht.
    """
    payload = InsolvenciesPayload(
        unternehmensinsolvenzen=row.get("unternehmensinsolvenzen"),
        uebrige_schuldner_insolvenzen=row.get("uebrige_schuldner_insolvenzen"),
        jahr=row.get("jahr"),
    )
    return _record(
        slug, payload, retrieved_at=retrieved_at, ags=ags, wikidata_qid=wikidata_qid
    )
