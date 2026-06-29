"""Keyloser destination.one/eT4.META-Event-Adapter fetch_events (DATA-16).

Lädt Stadt-Events über die eT4.META-REST-Such-API (destination.one) über den
gepoolten httpx-Client. Die Experience ``open-data`` ist FREI zugänglich, es
gibt KEINEN licensekey (Support-Bestätigung destination.one, G. Geiger,
2026-06-10; davor war der Adapter fälschlich account-gated gebaut).

Sicherheit (T-10-SSRF, Tampering): Der Host ist in ``_BASE`` hartkodiert, nie aus
User-/Upstream-Input. Es gibt keine dynamische Ziel-URL.

DoS-Schutz (T-10-DOS): ``limit`` (Default 200) ist ein harter Cap in der Query;
Cache/SWR/Single-Flight/Breaker liefert die Resilienz-Fassade.

Stadt-Bezug + Zukunftsfilter (D-07), beide LIVE VERIFIZIERT 2026-06-10:
``latitude``/``longitude`` + ``sortby=distance`` sortieren die Treffer nach
Nähe zur Stadt (das ``city``-Feld der Items ist zu dünn belegt für einen
Feldfilter); ``q=start:[<date_from> TO *]`` filtert serverseitig auf kommende
Events (Lucene-Range auf das Start-Datum; ``mode=next-month`` wird von der API
ignoriert). Der Mapper-Datums-Guard ist der zweite Backstop.

Feld-Layout (LIVE VERIFIZIERT 2026-06-10 gegen meta.et4.de, KEIN [ASSUMED]
mehr): Items tragen ``title``, Termine in ``timeIntervals`` (Liste von
``{start, end, tz}``), Geo unter ``geo.main.latitude/longitude``, Venue in
``name``, Stadt in ``city`` und die Pro-Record-Lizenz in der ``attributes``-
Liste als ``{"key": "license", "value": "CC0|CC-BY|CC-BY-SA"}`` (GOV-04-
Quelle). ACHTUNG: ``media_objects`` haben ein EIGENES ``license``-Feld je Bild,
das von der Datensatz-Lizenz abweichen kann; Medien werden hier bewusst NICHT
übernommen (nur Datensatz-Felder, keine Bild-URLs).

Die Antwort wird defensiv per ``.get()``/``[]``-Fallback gelesen; fehlende/
unbekannte Felder führen NICHT zu einem Crash, sondern zu ``None``.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.
"""

from __future__ import annotations

import math

import httpx

# Host hartkodiert (T-10-SSRF): nur diese eine eT4.META-Such-Instanz mit dem
# dokumentierten JSON-Standard-Template (Pfad-Form live verifiziert 2026-06-10);
# nie roher User-/Upstream-Host.
_BASE = "https://meta.et4.de/rest.ashx/search/ET2014A.json/"

# Öffentlicher Open-Data-Pool von destination.one (LIVE VERIFIZIERT 2026-06-10:
# 61.716 Events, kein Key; Support-Mail G. Geiger).
_EXPERIENCE = "open-data"

# Umland-Cutoff (D-07-Verschärfung): ``sortby=distance`` holt die nächsten
# Events, kappt aber nichts, sodass grenznahes Umland mitkommt (live beobachtet:
# Teltow/Neuenhagen unter Berlin). Ein Distanz-Radius um den Stadt-Bezugspunkt
# verwirft Events außerhalb. 25 km deckt die flächengrößten Städte
# (Berlin/Hamburg) vollständig ab und entfernt Nachbarstaedte/Umland (z.B.
# Potsdam ~27 km). GRENZE (ehrlich): ein Punkt-Radius kann eine flächige Stadt
# nicht exakt umreißen; direkt an der Stadtgrenze liegende Vororte können
# verbleiben. Ein engerer Radius würde echte Stadtrand-Events kappen (mehr
# unnötiges null) und ist daher bewusst nicht gewählt.
_DEFAULT_RADIUS_KM = 25.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Grosskreis-Distanz in km zwischen zwei WGS84-Punkten (rein, deterministisch)."""
    earth_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * earth_km * math.asin(math.sqrt(a))


def _first_interval_bounds(item: dict) -> tuple[str | None, str | None]:
    """Liest (date_from, date_to) aus ``timeIntervals`` (frueheste/spaeteste).

    Items können mehrere Intervalle tragen (Serien-Events); wir reduzieren auf
    die Gesamtspanne min(start)..max(end or start). Defekte Einträge (kein
    dict / kein start) werden übersprungen (Pitfall 3, kein Crash).
    """
    starts: list[str] = []
    ends: list[str] = []
    for iv in item.get("timeIntervals") or []:
        if not isinstance(iv, dict):
            continue
        start = iv.get("start")
        if not start:
            continue
        starts.append(start)
        ends.append(iv.get("end") or start)
    if not starts:
        return None, None
    return min(starts), max(ends)


def _license_from_attributes(item: dict) -> str | None:
    """Liest die Pro-Record-Lizenz aus der ``attributes``-Liste (GOV-04-Quelle).

    Bevorzugt ``licenseurl`` (kanonische CC-URL, von ``map_license`` robust
    erkannt), fällt auf das ``license``-Kürzel zurück.
    """
    license_short: str | None = None
    license_url: str | None = None
    for attr in item.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        if attr.get("key") == "license":
            license_short = attr.get("value")
        elif attr.get("key") == "licenseurl":
            license_url = attr.get("value")
    return license_url or license_short


async def fetch_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    date_from: str | None = None,
    limit: int = 200,
    offset: int = 0,
    radius_km: float = _DEFAULT_RADIUS_KM,
) -> dict:
    """Holt destination.one-Events für eine Stadt als raw-dict (keylos).

    GETtet AUSSCHLIESSLICH gegen den hartkodierten ``_BASE``-Host (SSRF-Guard
    T-10-SSRF). ``type=Event`` filtert auf Events, ``latitude``/``longitude`` +
    ``sortby=distance`` holen die nächstgelegenen Events zur Stadt, ``limit``
    ist der DoS-Cap. ``date_from`` (ISO-Datum, von der Route injiziert, keine
    Systemuhr im Adapter) filtert serverseitig via ``q=start:[date_from TO *]``
    auf kommende Events (D-07); ohne ``date_from`` bleibt nur der Mapper-Guard.

    ``radius_km`` ist der Umland-Cutoff (D-07): Events mit Geo außerhalb des
    Radius um ``(lat, lon)`` werden verworfen (sonst kommt grenznahes Umland
    über ``sortby=distance`` mit). Events OHNE verwertbares Geo lassen sich
    nicht beurteilen und bleiben (``sortby=distance`` hält sie nah).

    Die Felder sind live verifiziert (Modul-Docstring); gelesen wird trotzdem
    defensiv per ``.get()``/``[]``-Fallback. Rückgabe-Keys (exakt das, was
    ``map_destination_one_events`` erwartet): ``slug`` und ``events`` mit je
    ``title``/``date_from``/``date_to``/``location``/``lat``/``lon``/
    ``license_raw``. Ein 5xx schlägt via ``resp.raise_for_status()`` als
    ``httpx.HTTPError`` durch (STALE-ON-ERROR).
    """
    params: dict = {
        "experience": _EXPERIENCE,
        "type": "Event",  # [VERIFIED 2026-06-10] Event-Filter
        "latitude": lat,  # [VERIFIED 2026-06-10] Distanz-Bezugspunkt
        "longitude": lon,
        "sortby": "distance",  # [VERIFIED 2026-06-10] nächste Events zuerst
        "limit": limit,  # DoS-Cap / Pagination
        "offset": offset,
    }
    if date_from:
        # [VERIFIED 2026-06-10] Lucene-Range auf das Event-Startdatum.
        params["q"] = f"start:[{date_from} TO *]"

    resp = await http.get(_BASE, params=params)
    resp.raise_for_status()

    body = resp.json()
    items = body.get("items") or []
    events: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        date_from_raw, date_to_raw = _first_interval_bounds(it)
        geo_main = (it.get("geo") or {}).get("main") or {}
        ev_lat = geo_main.get("latitude") if isinstance(geo_main, dict) else None
        ev_lon = geo_main.get("longitude") if isinstance(geo_main, dict) else None
        # Umland-Cutoff (D-07): nur Events MIT verwertbarem Geo lassen sich
        # räumlich beurteilen; liegt ihr Geo außerhalb des Radius, werden sie
        # verworfen. Geo-lose Events bleiben (bool ist int -> explizit ausschließen).
        if (
            isinstance(ev_lat, (int, float))
            and not isinstance(ev_lat, bool)
            and isinstance(ev_lon, (int, float))
            and not isinstance(ev_lon, bool)
            and _haversine_km(lat, lon, ev_lat, ev_lon) > radius_km
        ):
            continue
        # Venue (name) vor Stadt (city): präziser Ortsbezug, Stadt als Fallback.
        location = it.get("name") or it.get("city")
        events.append(
            {
                "title": it.get("title"),
                "date_from": date_from_raw,
                "date_to": date_to_raw,
                "location": location,
                "lat": ev_lat,
                "lon": ev_lon,
                "license_raw": _license_from_attributes(it),  # GOV-04-Quelle
            }
        )

    return {"slug": slug, "events": events}
