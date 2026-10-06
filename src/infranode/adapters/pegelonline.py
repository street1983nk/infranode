"""Keyloser PEGELONLINE-Adapter fetch_water_level (DATA-11, Tier A).

Lädt Pegelstände vom keylosen PEGELONLINE-REST-Dienst der
Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV) über den gepoolten
httpx-Client. Zwei-Schritt-Flow:

1. ``GET /stations.json`` liefert alle Pegel-Stationen mit Koordinaten; der
   Adapter wählt die geografisch nächste Station zu (``lat``, ``lon``) per
   einfacher breitengrad-korrigierter Grad-Distanz (kein Haversine, vgl.
   ``autobahn._within_bbox``: Don't-Hand-Roll).
2. ``GET /stations/{uuid}/W/currentmeasurement.json`` liefert den aktuellen
   Wasserstand (``timestamp``/``value``) der gewählten Station.

KANDIDATEN-FALLBACK (Audit-Nachlese): die geografisch nächste Station hat nicht
immer einen aktuellen W-Messwert; ihr ``currentmeasurement.json`` liefert dann
404 (Station existiert, aber keine frische Messung). Ein 404 ist KEIN
Upstream-Ausfall, sondern "diese Station hat gerade keinen Wert". Darum probiert
der Adapter der Reihe nach die nächsten ``_MAX_CANDIDATES`` Stationen innerhalb
der Nähe-Toleranz: 404 -> nächster Kandidat, 200 -> Rückgabe dieses Kandidaten,
5xx/Transport-Fehler -> Exception schlägt durch (echter Upstream-Fehler,
503-Pfad). Liefern ALLE Kandidaten 404, gilt die Zelle als ehrliches no_data
(``station`` None), es wird NICHT geworfen.

KRITISCH (DATA-11, Pitfall 3 / Teilabdeckung): PEGELONLINE deckt nur Städte an
Bundeswasserstraßen ab. Liegt KEINE Station innerhalb der Nähe-Toleranz (z.B.
Binnenstadt), liefert der Adapter ``{"slug": slug, "station": None}`` und wirft
NICHT. Die Route mappt ``station is None`` ehrlich auf ``source_status="no_data"``
(200, KEIN 5xx).

Rückgabe bei vorhandener Station ist ein flaches raw-dict, das auf das
``WaterLevelPayload`` passt: ``slug``/``station``/``uuid``/``value``/``unit``/
``observed_at``/``water``. Das echte Antwortfeld heißt ``value``; defensives
``.get("value")`` fängt fehlende Felder ab (T-07-IN).

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (T-07-IN, SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon
stammen aus dem validierten Register und fließen nur in die Stationsauswahl ein,
die ``uuid`` stammt ausschließlich aus der ``/stations.json``-Antwort (nie
User-Input).
"""

from __future__ import annotations

import math

import httpx

# Host hartkodiert (T-07-IN SSRF): nur diese eine öffentliche PEGELONLINE-Instanz.
_BASE = "https://pegelonline.wsv.de/webservices/rest-api/v2"

# Nähe-Toleranz in Grad (~55 km): Stationen weiter weg gelten als "keine nahe
# Station" -> Teilabdeckung (Pitfall 3, Binnenstadt). Eine Bundeswasserstraße in
# der Stadt liegt deutlich darunter; eine ferne Station darüber.
_MAX_DEG = 0.5

# Anzahl der nächsten Stationen, die der Adapter der Reihe nach probiert, bevor
# er auf no_data zurückfällt. Die distanznächste Station hat nicht immer einen
# aktuellen W-Messwert (currentmeasurement 404); dann wird der nächste Pegel
# innerhalb der Nähe-Toleranz versucht. 3 deckt die live beobachteten Fälle
# (z.B. hanau) ab, ohne bei echter Teilabdeckung zu viele Requests zu erzeugen.
_MAX_CANDIDATES = 3


def _deg_distance(alat: float, alon: float, blat: float, blon: float) -> float:
    """Einfache breitengrad-korrigierte Grad-Distanz für die Stationsauswahl.

    Bewusst KEIN Haversine (Don't-Hand-Roll, vgl. autobahn._within_bbox): für die
    grobe Auswahl der nächsten Pegel-Station reicht eine euklidische Grad-Distanz
    mit ``cos(lat)``-korrigierter Längen-Achse.
    """
    cos_lat = math.cos(math.radians(alat))
    dlat = blat - alat
    dlon = (blon - alon) * cos_lat
    return math.hypot(dlat, dlon)


def _nearest(stations: list, lat: float, lon: float) -> dict | None:
    """Waehlt die nächste Station zu (lat, lon) aus der /stations.json-Liste.

    Defensive Lesung: Stationen ohne gültige Koordinaten werden übersprungen.
    Liegt die nächste Station weiter als ``_MAX_DEG`` entfernt, gilt sie als
    "keine nahe Station" -> ``None`` (Pitfall 3, Teilabdeckung).
    """
    best: dict | None = None
    best_dist = float("inf")

    for station in stations:
        if not isinstance(station, dict):
            continue
        try:
            slat = float(station["latitude"])
            slon = float(station["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        dist = _deg_distance(lat, lon, slat, slon)
        if dist < best_dist:
            best_dist = dist
            best = station

    if best is None or best_dist > _MAX_DEG:
        return None
    return best


def _nearest_candidates(
    stations: list, lat: float, lon: float, k: int = _MAX_CANDIDATES
) -> list[dict]:
    """Liefert die bis zu ``k`` nächsten Stationen innerhalb der Nähe-Toleranz.

    Defensive Lesung wie ``_nearest``: Stationen ohne gültige Koordinaten werden
    übersprungen. Es werden nur Stationen mit ``_deg_distance <= _MAX_DEG``
    berücksichtigt, aufsteigend nach Distanz sortiert und die ersten ``k``
    zurückgegeben. Leere Liste = keine nahe Station (Pitfall 3, Teilabdeckung).

    Grundlage des Kandidaten-Fallbacks in ``fetch_water_level``: die
    distanznächste Station hat nicht immer einen aktuellen W-Messwert
    (currentmeasurement 404); dann wird der nächste Kandidat probiert.
    """
    scored: list[tuple[float, dict]] = []
    for station in stations:
        if not isinstance(station, dict):
            continue
        try:
            slat = float(station["latitude"])
            slon = float(station["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        dist = _deg_distance(lat, lon, slat, slon)
        if dist <= _MAX_DEG:
            scored.append((dist, station))

    scored.sort(key=lambda item: item[0])
    return [station for _dist, station in scored[:k]]


async def fetch_water_level(
    http: httpx.AsyncClient, *, slug: str, lat: float, lon: float
) -> dict:
    """Holt den keylosen PEGELONLINE-Pegelstand (2-Step) als flaches raw-dict.

    Schritt 1 ``GET {_BASE}/stations.json``: die nächsten ``_MAX_CANDIDATES``
    Stationen zu (``lat``, ``lon``). Liegt keine Station innerhalb der
    Nähe-Toleranz, liefert die Funktion ``{"slug": slug, "station": None}`` und
    wirft NICHT (Pitfall 3, Teilabdeckung). Schritt 2 ``GET {_BASE}/stations/
    {uuid}/W/currentmeasurement.json`` je Kandidat der Reihe nach: aktueller
    Wasserstand der gewählten Station.

    Kandidaten-Fallback: liefert der currentmeasurement-Call HTTP 404, hat die
    Station gerade keinen aktuellen W-Messwert (kein Upstream-Ausfall) -> der
    nächste Kandidat wird probiert. Der erste Kandidat mit HTTP 200 wird
    zurückgegeben. Ein anderer Fehlerstatus (5xx) bzw. ein Transport-Fehler ist
    ein echter Upstream-Fehler und schlägt als ``httpx.HTTPStatusError`` durch
    (503-/STALE-ON-ERROR-Pfad), OHNE weitere Kandidaten zu probieren. Liefern
    ALLE Kandidaten 404, gilt die Zelle als ehrliches no_data
    (``{"slug": slug, "station": None}``, kein raise).

    Rückgabe-Keys (exakt das, was ``map_water_level`` erwartet): ``slug``,
    ``station`` (longname bzw. ``None``), ``uuid``, ``value`` (cm), ``unit``,
    ``observed_at`` (Mess-timestamp) und ``water`` (Gewässer-longname). Der Host
    ist hartkodiert (SSRF-Schutz, T-07-IN); ``resp.raise_for_status()`` ist
    Pflicht (STALE-ON-ERROR-Pfad).
    """
    stations_resp = await http.get(f"{_BASE}/stations.json")
    stations_resp.raise_for_status()
    candidates = _nearest_candidates(stations_resp.json(), lat, lon)

    # Pitfall 3 (Teilabdeckung): keine nahe Station -> no_data, kein Fehler.
    if not candidates:
        return {"slug": slug, "station": None}

    for station in candidates:
        uuid = station["uuid"]
        measure_resp = await http.get(
            f"{_BASE}/stations/{uuid}/W/currentmeasurement.json"
        )
        # 404 = Station ohne aktuellen W-Messwert (kein Upstream-Ausfall) ->
        # nächsten Kandidaten probieren. VOR raise_for_status prüfen, damit 5xx
        # (echter Fehler) weiterhin als httpx.HTTPStatusError durchschlägt.
        if measure_resp.status_code == 404:
            continue
        measure_resp.raise_for_status()
        measurement = measure_resp.json()

        return {
            "slug": slug,
            "station": station.get("longname"),
            "uuid": uuid,
            "value": measurement.get("value"),
            "unit": await _fetch_unit(http, uuid),
            "observed_at": measurement.get("timestamp"),
            "water": (station.get("water") or {}).get("longname"),
        }

    # Alle Kandidaten lieferten 404: ehrliches no_data, kein Upstream-Fehler.
    return {"slug": slug, "station": None}


async def _fetch_unit(http: httpx.AsyncClient, uuid: str) -> str:
    """Liest die echte Mess-Einheit aus den W-Zeitreihen-Metadaten (Audit-155).

    ``GET {_BASE}/stations/{uuid}/W.json`` trägt das Feld ``unit`` (für Wasserstand
    quellenseitig durchgängig "cm", aber quellenecht statt hartkodiert). Der
    ``currentmeasurement.json``-Endpunkt liefert die Einheit NICHT, daher dieser
    kleine Zusatz-Request.

    Bewusst DEFENSIV (kein ``raise_for_status``-Durchschlag): schlägt der
    Zusatz-Request fehl oder fehlt das Feld, fällt die Einheit auf "cm" zurück.
    Ein fehlendes Einheits-Label darf nicht den ganzen Pegel-Wert über den
    STALE-ON-ERROR-Pfad verwerfen (der eigentliche Messwert kam bereits sauber).
    """
    try:
        resp = await http.get(f"{_BASE}/stations/{uuid}/W.json")
        resp.raise_for_status()
        unit = resp.json().get("unit")
    except (httpx.HTTPError, ValueError):
        return "cm"
    return unit if isinstance(unit, str) and unit else "cm"
