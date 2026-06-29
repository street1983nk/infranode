"""Keyloser Köln-Events-Adapter fetch_events (DATA-16, D-06, Tier A DL-DE/Zero).

Die Stadt Köln stellt einen direkten Open-Data-Events-Feed (events-od.php, JSON)
bereit. Der Feed ist keylos, liefert nativ nur die Zukunft (aktuelles Datum + 7
Tage) und steht uniform unter der Datenlizenz Deutschland Zero 2.0
(DL-DE/Zero-2.0, verifiziert 2026-06-26 gegen "Veranstaltungen der Stadt Koeln").
Damit löst der Feed den D-07-Zukunftsfilter ohne eigene Heuristik (RESEARCH
Zeile 11/97; A4).

Antwortstruktur [VERIFIED 2026-06-10]: ``{"success": true, "count": <n>,
"items": [...]}`` (Top-Key ``items``, NICHT ``events``). Je Item: ``title``,
``beginndatum``/``endedatum`` (ISO-Datum), ``veranstaltungsort`` (Location),
``latitude``/``longitude`` (Koordinaten als STRINGS!), dazu ``strasse``/
``hausnummer``/``plz``/``link``.

Sicherheit (T-10-SSRF): Der Host ist in ``_BASE`` hartkodiert; es gibt KEINE
dynamische Ziel-URL aus User-/Upstream-Input. Köln läuft seit der Drupal-10-
Migration auf DKAN (nicht Standard-CKAN); der Direkt-Feed umgeht die abweichenden
DKAN-API-Pfade in EINEM GET (RESEARCH Pitfall 5).

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.

Datenfehler-Schutz (Phase-7/8/9-Konvention): Alle Felder werden defensiv per
``.get()`` mit None-Fallback gelesen (kein ``KeyError``); die String-Koordinaten
laufen durch ein try/except-``float()``. Je Event liefert der Adapter ein
``license_raw="dl-de-zero-2.0"``-Feld mit, damit der Mapper dieselbe
``map_license``-Logik wie destination.one nutzen kann (D-06, single source of
truth).
"""

from __future__ import annotations

import httpx

# Host hartkodiert (T-10-SSRF): nur dieser eine Köln-Open-Data-Events-Feed. Nie
# roher User-/Upstream-Host; es gibt keine dynamische Ziel-URL.
_BASE = "https://www.stadt-koeln.de/externe-dienste/open-data/events-od.php"

# Köln-Feed ist uniform DL-DE/Zero-2.0 (A4). Das license_raw je Event läuft durch
# dieselbe map_license-Funktion wie destination.one (D-06, Konsistenz).
_LICENSE_RAW = "dl-de-zero-2.0"

# Feldnamen [VERIFIED 2026-06-10] gegen den Live-Feed. Defensiv per .get()
# gelesen -> None-Fallback statt KeyError (Phase-7/8/9-Konvention).
_FIELD_TITLE = "title"  # Titel des Events
_FIELD_DATE_FROM = "beginndatum"  # Startdatum (ISO, z.B. "2026-06-10")
_FIELD_DATE_TO = "endedatum"  # Enddatum (ISO)
_FIELD_LOCATION = "veranstaltungsort"  # Ort/Veranstaltungsort
_FIELD_LAT = "latitude"  # Breitengrad als STRING
_FIELD_LON = "longitude"  # Längengrad als STRING


def _to_float(value) -> float | None:
    """Castet die String-Koordinaten des Feeds defensiv nach float (oder None)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
) -> dict:
    """Holt Köln-Events aus dem keylosen events-od.php-Feed als raw-dict.

    GETtet AUSSCHLIESSLICH gegen den hartkodierten ``_BASE``-Host (SSRF-Guard
    T-10-SSRF). ``lat``/``lon`` stehen im einheitlichen Stadt-Adapter-Vertrag,
    auch wenn der Direkt-Feed sie nicht benötigt (er ist bereits Köln-spezifisch
    und nativ Zukunft). Die Antwort trägt die Events unter dem Top-Key
    ``items`` [VERIFIED 2026-06-10]; der Adapter liest defensiv per ``.get()``
    und reduziert jedes Event auf ein schlankes dict mit ``license_raw`` (D-06:
    dieselbe map_license-Logik wie destination.one). Die String-Koordinaten
    (``latitude``/``longitude``) werden defensiv nach float gecastet.
    Rückgabe-Keys (exakt das, was ``map_koeln_events`` erwartet): ``slug`` und
    ``events``. Ein 5xx schlägt via ``resp.raise_for_status()`` als
    ``httpx.HTTPError`` durch (STALE-ON-ERROR).
    """
    resp = await http.get(_BASE)
    resp.raise_for_status()

    body = resp.json()
    # Top-Key items [VERIFIED 2026-06-10]; defensiv mit []-Fallback.
    items = body.get("items") or []
    events: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        # Phase-7/8/9-Konvention: fehlendes Feld -> None (kein KeyError).
        events.append(
            {
                "title": it.get(_FIELD_TITLE),
                "date_from": it.get(_FIELD_DATE_FROM),
                "date_to": it.get(_FIELD_DATE_TO),
                "location": it.get(_FIELD_LOCATION),
                "lat": _to_float(it.get(_FIELD_LAT)),
                "lon": _to_float(it.get(_FIELD_LON)),
                "strasse": it.get("strasse"),
                "hausnummer": it.get("hausnummer"),
                "plz": it.get("plz"),
                "link": it.get("link"),
                # D-06: uniform DL-DE/Zero (= _LICENSE_RAW "dl-de-zero-2.0"); läuft
                # durch dieselbe map_license-Logik (Kommentar-Fix Audit 2026-06-29:
                # stand vorher fälschlich "DL-DE/BY").
                "license_raw": _LICENSE_RAW,
            }
        )

    return {"slug": slug, "events": events}
