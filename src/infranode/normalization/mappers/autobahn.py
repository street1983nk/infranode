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

# camelCase-Rohfelder mit kanonischem snake_case-Nachfolger: abgekuendigt am
# 2026-08-01, aus der Ausgabe entfernt am 2026-08-31 (Register docs-site
# deprecations.ts, getCityTraffic). ``extent`` wird zu ``bbox`` + lat/lon.
_DEPRECATED_RAW_FIELDS = (
    "isBlocked",
    "startTimestamp",
    "delayTimeValue",
    "averageSpeed",
    "abnormalTrafficType",
    "extent",
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


def _to_float(value: object) -> float | None:
    """Zahl als float, sonst None (rein). Der Feed liefert Zahlen als String."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _bbox_and_center(
    extent: object,
) -> tuple[list[float] | None, float | None, float | None]:
    """Zerlegt das Autobahn-``extent`` in bbox + Mittelpunkt (rein).

    Der Feed liefert die Ausdehnung als Komma-String
    ``"lat1,lon1,lat2,lon2"``, also BREITE zuerst [VERIFIED 2026-07-25 an der
    Live-Antwort fuer Koeln: "51.0153...,6.9231...,51.0316...,6.9556..."]. Die
    ausgegebene ``bbox`` folgt dagegen der GeoJSON-Konvention
    ``[min_lon, min_lat, max_lon, max_lat]``, damit sie ohne Ruecksprache
    weiterverarbeitet werden kann; ``lat``/``lon`` sind der Mittelpunkt, damit
    ein Ereignis wie in allen anderen Datenarten kartierbar ist. Unbrauchbares
    Extent -> (None, None, None).
    """
    if not isinstance(extent, str):
        return None, None, None
    parts = [_to_float(p) for p in extent.split(",")]
    if len(parts) != 4:
        return None, None, None
    floats = [p for p in parts if p is not None]
    if len(floats) != 4:
        return None, None, None
    lat1, lon1, lat2, lon2 = floats
    min_lon, max_lon = sorted((lon1, lon2))
    min_lat, max_lat = sorted((lat1, lat2))
    # Auf 6 Nachkommastellen runden (~11 cm): der Mittelwert erzeugt sonst
    # Fliesskomma-Rauschen wie 6.8218499999999995 in der Antwort.
    return (
        [min_lon, min_lat, max_lon, max_lat],
        round((lat1 + lat2) / 2, 6),
        round((lon1 + lon2) / 2, 6),
    )


def _canonical_event_fields(item: dict) -> dict:
    """Kanonische snake_case-Felder zu einem Autobahn-Event (rein, additiv).

    Der Autobahn-Feed ist die einzige Quelle mit camelCase-Namen und Zahlen/
    Booleans als String (``isBlocked: "false"``). Damit dieser Endpunkt dieselbe
    Sprache spricht wie der Rest der API, kommen die Werte zusaetzlich als
    ``is_blocked`` (bool), ``start_timestamp``, ``delay_minutes`` (int),
    ``average_speed_kmh`` (float), ``abnormal_traffic_type``, ``name``,
    ``description_text`` sowie ``bbox``/``lat``/``lon`` dazu (Konsistenz-Audit
    2026-07-25). Die sechs Rohfelder mit Nachfolger sind zum 2026-08-31
    entfernt (``_DEPRECATED_RAW_FIELDS`` in ``_slim_event``); es wird nur
    umbenannt und typisiert, nie ein Wert erfunden.
    """
    out: dict = {"is_blocked": _is_blocked(item)}

    start = item.get("startTimestamp")
    if start is not None:
        out["start_timestamp"] = start

    delay = _to_float(item.get("delayTimeValue"))
    if delay is not None:
        out["delay_minutes"] = int(delay)

    speed = _to_float(item.get("averageSpeed"))
    if speed is not None:
        out["average_speed_kmh"] = speed

    raw_type = item.get("abnormalTrafficType")
    if isinstance(raw_type, str) and raw_type.strip():
        out["abnormal_traffic_type"] = raw_type.strip().upper()

    title = item.get("title")
    if isinstance(title, str) and title.strip():
        out["name"] = title.strip()

    # ``description`` ist im Feed eine Zeilenliste; als Fliesstext ist sie mit den
    # String-Beschreibungen der uebrigen Datenarten vergleichbar.
    desc = item.get("description")
    if isinstance(desc, list):
        lines = [
            line.strip() for line in desc if isinstance(line, str) and line.strip()
        ]
        if lines:
            out["description_text"] = " ".join(lines)
    elif isinstance(desc, str) and desc.strip():
        out["description_text"] = desc.strip()

    bbox, lat, lon = _bbox_and_center(item.get("extent"))
    if bbox is not None:
        out["bbox"] = bbox
        out["lat"] = lat
        out["lon"] = lon
    return out


def _slim_event(item: dict, *, ballast: frozenset[str] = _BALLAST_FIELDS) -> dict:
    """Gibt ein NEUES dict ohne die ``ballast``-Felder zurueck (reine Funktion).

    Entfernt ausschliesslich die Schluessel aus ``ballast`` (Denylist, Default
    ``_BALLAST_FIELDS``); alle uebrigen Felder werden byte-identisch uebernommen,
    insbesondere die Stau-Anreicherung ``congestion`` (nicht in der Denylist) und
    unbekannte Zusatzfelder. Das Eingabe-dict wird NICHT mutiert. Es werden nur
    Felder weggelassen, keine Werte umgeschrieben.

    Der ``ballast``-Parameter erlaubt den ``include=geometry``-Opt-in
    (quick-260706-g9q): der Aufrufer reicht ``_BALLAST_FIELDS - {"geometry"}``
    durch, um die Roh-Polyline zu erhalten; alle uebrigen Ballast-Felder bleiben
    entfernt. Bestandsaufrufe ohne ``ballast`` verhalten sich unveraendert.

    Zusaetzlich kommen die kanonischen snake_case-Felder dazu
    (``_canonical_event_fields``, Konsistenz-Audit 2026-07-25); vorhandene
    Rohfelder werden dabei NICHT ueberschrieben.
    """
    kept = {k: v for k, v in item.items() if k not in ballast}
    canonical = {
        k: v for k, v in _canonical_event_fields(item).items() if k not in kept
    }
    # Die sechs camelCase-Rohfelder mit kanonischem Nachfolger waren seit
    # 2026-08-01 abgekuendigt und sind zum 2026-08-31 entfernt; alle uebrigen
    # Rohfelder (title, subtitle, ...) bleiben unveraendert erhalten.
    for old in _DEPRECATED_RAW_FIELDS:
        kept.pop(old, None)
    return {**kept, **canonical}


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
    raw_delay = warning.get("delayTimeValue")
    if isinstance(raw_delay, (int, float, str)):
        try:
            delay = int(raw_delay)
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
    include_geometry: bool = False,
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

    ``include_geometry`` (quick-260706-g9q): der Feld-Opt-in zur Roh-Polyline
    (kein Tier-/Paginierungs-Thema). Default ``False`` -> ``geometry`` bleibt wie
    bisher entfernt (schlanke Response); ``True`` (Route bei ``include=geometry``
    bzw. ``?full=1``) behaelt ``geometry`` in roadworks UND warnings, entfernt aber
    weiterhin allen uebrigen Ballast.
    """
    ballast = _BALLAST_FIELDS - {"geometry"} if include_geometry else _BALLAST_FIELDS
    slimmed_roadworks = [
        _slim_event(r, ballast=ballast) for r in raw.get("roadworks", [])
    ]
    roadworks_total = len(slimmed_roadworks)
    # Blockierende Baustellen zuerst (stabile Sortierung erhaelt sonst die
    # Original-Reihenfolge), dann auf _MAX_ROADWORKS kappen. Seit dem Entfernen
    # des Rohfelds isBlocked (2026-08-31) traegt das geslimmte Item nur noch
    # das kanonische ``is_blocked`` (bool) aus _canonical_event_fields.
    ranked_roadworks = sorted(
        slimmed_roadworks, key=lambda r: not r.get("is_blocked", False)
    )
    roadworks = ranked_roadworks[:_MAX_ROADWORKS]
    roadworks_truncated = roadworks_total > _MAX_ROADWORKS
    warnings = [
        _slim_event(w, ballast=ballast)
        for w in _enrich_warnings(raw.get("warnings", []))
    ]
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
