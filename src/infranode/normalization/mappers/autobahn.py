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

# Ballast-Denylist (DATA-07/08): Felder, die der rohe Autobahn-App-Feed pro Event
# mitliefert, die aber fuer API-/LLM-Konsumenten wertlos sind und die Response
# aufblaehen. Die Roh-Geometrie (``geometry``) allein ist ~1,2 KB je Item; bei einer
# stark belasteten Stadt (Koeln, ~150+ roadworks) summiert sich das auf ~305 KB und
# sprengt das GPT-Actions-Limit (~100 KB). ``routeRecommendation``/``footer``/``icon``/
# ``display_type``/``lorryParkingFeatureIcons``/``startLcPosition``/``point``/``future``
# sind reine App-UI-Interna ohne fachlichen Wert. Wir LASSEN diese Felder nur WEG
# (Denylist), wir schreiben KEINE Werte um: alle behaltenen Felder bleiben byte-
# identisch. Denylist statt Allowlist, damit unbekannte, aber nuetzliche Felder
# erhalten bleiben; kuenftiger Ballast wird durch Ergaenzen dieser Menge entfernt.
_BALLAST_FIELDS = frozenset(
    {
        "geometry",
        "routeRecommendation",
        "footer",
        "lorryParkingFeatureIcons",
        "icon",
        "display_type",
        "startLcPosition",
        "point",
        "future",
    }
)


# Default-Obergrenze fuer roadworks in der Response. Koeln hat live ~178 Baustellen;
# selbst nach dem Slimming (geometry/Ballast weg) sind das ~160 KB und sprengen das
# GPT-Actions-Limit (~100 KB, verifiziert 2026-07-06). Wir kappen auf die
# _MAX_ROADWORKS wichtigsten (blockierende zuerst) und weisen die Kappung EHRLICH aus
# (``roadworks_total``/``roadworks_truncated``, KEINE stille Kappung). warnings bleiben
# ungekappt: sie sind der fachliche Kern der Verkehrslage (aktuelle Staus) und live
# deutlich weniger als roadworks.
_MAX_ROADWORKS = 50


def _is_blocked(item: dict) -> bool:
    """Ehrliche Bool-Interpretation des Autobahn-Feld ``isBlocked`` (Roh-String).

    Der Feed liefert ``isBlocked`` als String ``"true"``/``"false"`` (selten Bool);
    eine truthy-Pruefung auf den Roh-String waere falsch (``"false"`` ist truthy).
    """
    return str(item.get("isBlocked")).strip().lower() == "true"


def _slim_event(item: dict) -> dict:
    """Gibt ein NEUES dict ohne die Ballast-Felder zurueck (reine Funktion).

    Entfernt ausschliesslich die Schluessel aus ``_BALLAST_FIELDS`` (Denylist); alle
    uebrigen Felder werden byte-identisch uebernommen, insbesondere die Stau-
    Anreicherung ``congestion`` (nicht in der Denylist) und unbekannte Zusatzfelder.
    Das Eingabe-dict wird NICHT mutiert. Es werden nur Felder weggelassen, keine
    Werte umgeschrieben.
    """
    return {k: v for k, v in item.items() if k not in _BALLAST_FIELDS}


# DATA-08 Stau-Klassifizierung: ``abnormalTrafficType`` ist das ehrliche Quell-Feld
# des Autobahn-warning-Feeds (INRIX-gespeist, DATEX-Stau-Typ). Wir labeln es nur in
# eine grobe Stufe (kein Erfinden von Werten):
#   QUEUING/STATIONARY -> "stau" (Stau/stehender Verkehr),
#   SLOW -> "stockend", HEAVY -> "dicht", UNSPECIFIED -> "unspezifisch".
_CONGESTION_LEVELS = {
    "STATIONARY_TRAFFIC": "stau",
    "QUEUING_TRAFFIC": "stau",
    "SLOW_TRAFFIC": "stockend",
    "HEAVY_TRAFFIC": "dicht",
    "UNSPECIFIED_ABNORMAL_TRAFFIC": "unspezifisch",
}


def _classify_congestion(warning: dict) -> dict | None:
    """Ehrliche Stau-Klassifizierung einer Autobahn-``warning`` (oder ``None``).

    Liest das Quell-Feld ``abnormalTrafficType`` und labelt es über
    ``_CONGESTION_LEVELS``. ``delay_minutes`` aus ``delayTimeValue`` (Reisezeit-
    verlust, nur > 0), ``blocked`` aus ``isBlocked``. Eine Warnung OHNE bekannten
    ``abnormalTrafficType`` ist KEIN Stau-Ereignis (z.B. reine Gefahren-/Sperr-
    meldung) -> ``None``. Reine Klassifizierung, kein Erfinden von Werten.
    """
    raw_type = (warning.get("abnormalTrafficType") or "").strip().upper()
    level = _CONGESTION_LEVELS.get(raw_type)
    if level is None:
        return None
    out: dict = {"level": level, "abnormal_traffic_type": raw_type}
    try:
        delay = int(warning.get("delayTimeValue"))
        if delay > 0:
            out["delay_minutes"] = delay
    except (TypeError, ValueError):
        pass
    if _is_blocked(warning):
        out["blocked"] = True
    return out


def _enrich_warnings(warnings: list[dict]) -> list[dict]:
    """Reichert jede Warnung um ein ``congestion``-Feld an (wenn Stau-relevant).

    Die Original-Warnung bleibt unverändert erhalten; nur Stau-relevante Warnungen
    bekommen zusätzlich den klassifizierten ``congestion``-Block.
    """
    enriched: list[dict] = []
    for w in warnings:
        congestion = _classify_congestion(w)
        enriched.append({**w, "congestion": congestion} if congestion else w)
    return enriched


def _congestion_summary(enriched: list[dict]) -> dict | None:
    """Fasst die Stau-Ereignisse einer Stadt zusammen (oder ``None``, wenn keine).

    Zählt Stau-/Stockend-Ereignisse und gesperrte Abschnitte und nennt den größten
    Reisezeitverlust. ``None``, wenn keine Warnung Stau-relevant ist (ehrlich:
    keine Stau-Karte statt einer Null-Verdichtung).
    """
    events = [w["congestion"] for w in enriched if w.get("congestion")]
    if not events:
        return None
    delays = [e["delay_minutes"] for e in events if "delay_minutes" in e]
    return {
        "count": len(events),
        "stau": sum(1 for e in events if e["level"] == "stau"),
        "stockend": sum(1 for e in events if e["level"] == "stockend"),
        "blocked": sum(1 for e in events if e.get("blocked")),
        "max_delay_minutes": max(delays) if delays else None,
    }


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

    DATA-08 Stau: jede Verkehrswarnung wird um ein ``congestion``-Feld angereichert
    (Stau-Klassifizierung aus ``abnormalTrafficType`` + Reisezeitverlust), und
    ``congestion_summary`` verdichtet die Stau-Lage je Stadt.

    ``roadworks`` und ``warnings`` werden vor der Ausgabe von App-UI-Ballast und
    Roh-Geometrie befreit (``_slim_event``), damit die Response unter dem
    GPT-Actions-Limit (~100 KB) bleibt. Reihenfolge zwingend: erst
    ``_enrich_warnings`` (fuegt ``congestion`` hinzu), dann ``_slim_event`` (behaelt
    ``congestion``, da nicht in der Denylist), dann ``_congestion_summary`` aus den
    geslimmten, angereicherten Warnungen. Nur Weglassen, kein Umschreiben von Werten.

    ``roadworks`` werden zusaetzlich auf die ``_MAX_ROADWORKS`` wichtigsten gekappt
    (blockierende zuerst), da Slimming allein bei stark belasteten Staedten (Koeln
    ~178 Baustellen) nicht unter das GPT-Actions-Limit kommt. Die Kappung wird ehrlich
    ausgewiesen (``roadworks_total``/``roadworks_truncated``), kein stiller Cap.
    ``warnings`` (aktuelle Staus) bleiben ungekappt.
    """
    slimmed_roadworks = [_slim_event(r) for r in raw.get("roadworks", [])]
    roadworks_total = len(slimmed_roadworks)
    # Blockierende Baustellen zuerst (stabile Sortierung erhaelt sonst die
    # Original-Reihenfolge), dann auf _MAX_ROADWORKS kappen.
    ranked_roadworks = sorted(slimmed_roadworks, key=lambda r: not _is_blocked(r))
    roadworks = ranked_roadworks[:_MAX_ROADWORKS]
    roadworks_truncated = roadworks_total > _MAX_ROADWORKS
    warnings = [_slim_event(w) for w in _enrich_warnings(raw.get("warnings", []))]
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
            roadworks=roadworks,
            warnings=warnings,
            roadworks_total=roadworks_total,
            roadworks_truncated=roadworks_truncated,
            congestion_summary=_congestion_summary(warnings),
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
