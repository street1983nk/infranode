"""Reine Autobahn-Mapper: Verkehr (DATA-07/08) + Webcams (DATA-22), Tier A DL-DE/BY.

Übersetzt das rohe Adapter-dict (``slug``/``roadworks``/``warnings``)
deterministisch in einen ``CanonicalRecord`` mit ``TrafficEventPayload``. Die
Funktion ist rein: kein HTTP, kein Logging, kein ``datetime.now()``. Der
``retrieved_at``-Zeitstempel wird keyword-only injiziert, damit Tests
deterministisch bleiben.

Die Autobahn-Daten (Datenbasis BASt, bereitgestellt von der Autobahn GmbH) sind
unter der Datenlizenz Deutschland Namensnennung 2.0 verfuegbar:
``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (kennzeichnet die permissive
Lizenz zur korrekten Attribution und Weiternutzung) und die wortgenaue Attribution
"Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH" (mit ß). Verkehrsereignisse
tragen ihre Zeit im Payload, daher ``observed_at=None``; ``geo`` ist ``None`` (die
Einzel-Events tragen ihre Koordinaten in den roadworks/warnings-Items).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
    TrafficEventPayload,
    WebcamPayload,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_autobahn_traffic(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Autobahn-Verkehrsdaten auf einen ``CanonicalRecord`` (Tier A) ab.

    ``roadworks`` (DATA-07 Baustellen) und ``warnings`` (DATA-08 Verkehrslage)
    bleiben getrennt im ``TrafficEventPayload``. Verkehrsereignisse tragen ihre
    Zeit im Payload, daher ist ``observed_at`` ``None``; der ``retrieved_at``-
    Zeitstempel wird injiziert (kein ``datetime.now()`` im Mapper), damit das
    Ergebnis deterministisch bleibt. Die Join-Keys ``ags``/``wikidata_qid`` werden
    aus dem Register durchgereicht (Default ``None``). Autobahn ist ein
    Event-Strom über das ganze Stadtgebiet, daher bewusst KEIN ``station_id``;
    die feingranulare ``identifier`` liegt je Event in ``roadworks``/``warnings``.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.AUTOBAHN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
            license_url=_DL_DE_BY_URL,
        ),
        payload=TrafficEventPayload(
            roadworks=raw.get("roadworks", []),
            warnings=raw.get("warnings", []),
        ),
    )


def map_autobahn_webcams(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Autobahn-Webcam-Daten auf einen ``CanonicalRecord`` (Tier A) ab.

    Spiegelt ``map_autobahn_traffic``, trägt aber einen ``WebcamPayload``
    (``count`` = Anzahl, ``webcams`` = schlanke dicts mit imageurl/coordinate/title).
    Die Funktion ist rein: kein HTTP, kein Logging, kein ``datetime.now()``; der
    ``retrieved_at``-Zeitstempel wird keyword-only injiziert.

    Webcams sind ein Live-Bild-Feature (Decision 3): die Route gibt das Live-Bild
    direkt aus. Das ist eine Feature-Entscheidung (Bild-Live), KEIN Tier-Downgrade:
    das ``license_tier`` bleibt ``A`` und die Lizenz DL-DE/BY
    (``SourceId.AUTOBAHN``), mit derselben
    wortgenauen Attribution "Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH"
    wie ``map_autobahn_traffic``. ``geo``/``observed_at`` sind ``None`` (die
    Einzel-Webcams tragen ihre Koordinaten im Payload).
    """
    webcams = raw.get("webcams", [])
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.AUTOBAHN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
            license_url=_DL_DE_BY_URL,
        ),
        payload=WebcamPayload(count=len(webcams), webcams=webcams),
    )
