"""Keyloser Autobahn-Adapter: fetch_traffic (DATA-07/08) + fetch_webcams (DATA-22).

Die Autobahn-API der Autobahn GmbH (Datenbasis BASt) ist keylos. Der Adapter
löst die 1->N-Zuordnung Stadt -> Autobahnen über eine kuratierte, Adapter-
lokale Liste (``_CITY_ROADS``) und fragt je Autobahn beide Dienste ab:
``roadworks`` (Baustellen, DATA-07) und ``warning`` (Verkehrswarnungen, DATA-08).

Sicherheit (T-05-13 SSRF): Der Host ist in ``_BASE`` hartkodiert. Die ``road``
stammt ausschließlich aus der kuratierten ``_CITY_ROADS``-Map (nie User-Input),
der ``slug`` kommt aus der Register-Allowlist. Ein unbekannter Slug liefert ein
leeres Tuple -> leere Events, kein Request gegen einen fremden Host.

DoS-Schutz (T-05-14): statt aller ~120 Autobahnen wird nur die kuratierte Liste
je Stadt abgefragt; Cache/SWR/Single-Flight/Breaker liefert die Resilienz-Fassade.

Datenfehler-Schutz (T-05-15 / Pitfall 4): Das Koordinaten-Feld heißt ``long``
(NICHT ``lon``) und sein Wert ist ein STRING. Der Adapter castet defensiv per
``float(c.get("long", 0))``; ein fehlerhaftes Event fällt aus dem BBox-Filter
heraus, statt einen 500 auszulösen.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.
"""

from __future__ import annotations

import math

import httpx

# Host hartkodiert (T-05-13 SSRF): nur diese eine öffentliche Autobahn-Instanz.
_BASE = "https://verkehr.autobahn.de/o/autobahn"

# Beide Dienste je Autobahn: DATA-07 Baustellen + DATA-08 Verkehrslage.
_SERVICES = ("roadworks", "warning")

# Kuratierte Stadt -> Autobahnen-Map (T-05-13/14): Adapter-lokal für das MVP,
# kein neues Register-Feld. Nur diese Werte gelangen in die URL (nie User-Input).
# Ein unbekannter Slug -> leeres Tuple -> leere Events.
_CITY_ROADS: dict[str, tuple[str, ...]] = {
    "berlin": ("A10", "A100", "A111", "A113", "A114", "A115"),
    "hamburg": ("A1", "A7", "A23", "A24", "A25", "A255"),
    "muenchen": ("A8", "A9", "A92", "A94", "A95", "A96", "A99"),
    "koeln": ("A1", "A3", "A4", "A57", "A555", "A559"),
}


def _within_bbox(
    elat: float, elon: float, clat: float, clon: float, radius_km: float
) -> bool:
    """Prueft per einfacher Grad-Box, ob (elat, elon) nahe (clat, clon) liegt.

    Bewusst KEIN Haversine (Don't-Hand-Roll): eine simple, robuste Grad-Box mit
    breitengrad-korrigierter Längen-Toleranz reicht für den groben Stadt-Filter.
    1 Grad Breite ~= 111 km; die Längen-Toleranz wird mit ``cos(lat)`` skaliert.
    """
    lat_tol = radius_km / 111.0
    cos_lat = math.cos(math.radians(clat))
    # Division-Schutz nahe der Pole (für dt. Städte unkritisch, aber sauber).
    lon_tol = radius_km / (111.0 * cos_lat) if cos_lat > 1e-6 else 360.0
    return abs(elat - clat) <= lat_tol and abs(elon - clon) <= lon_tol


async def fetch_traffic(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt Baustellen + Verkehrswarnungen je kuratierter Autobahn der Stadt.

    Iteriert über ``_CITY_ROADS.get(slug, ())`` und je Autobahn über
    ``("roadworks", "warning")``. Liest ``coordinate.long`` (STRING, NICHT
    ``lon``) und castet defensiv nach ``float`` (Pitfall 4); nur Events innerhalb
    der Bounding-Box um (``lat``, ``lon``) passieren den Filter.

    Rückgabe-Keys (exakt das, was ``map_autobahn_traffic`` erwartet): ``slug``,
    ``roadworks`` (DATA-07) und ``warnings`` (DATA-08).
    """
    roadworks: list[dict] = []
    warnings: list[dict] = []

    for road in _CITY_ROADS.get(slug, ()):
        for service in _SERVICES:
            resp = await http.get(f"{_BASE}/{road}/services/{service}")
            resp.raise_for_status()
            for item in resp.json().get(service, []):
                coordinate = item.get("coordinate") or {}
                # Pitfall 4: Feld heißt "long" (nicht "lon"), Wert ist String.
                elat = float(coordinate.get("lat", 0))
                elon = float(coordinate.get("long", 0))
                if not _within_bbox(elat, elon, lat, lon, radius_km):
                    continue
                if service == "roadworks":
                    roadworks.append(item)
                else:
                    warnings.append(item)

    return {"slug": slug, "roadworks": roadworks, "warnings": warnings}


async def fetch_webcams(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt die Autobahn-Webcams je kuratierter Autobahn der Stadt (DATA-22).

    Additiver webcam-Sub-Service (Decision 3): KEIN neuer Adapter, sondern eine
    1:1-Wiederverwendung von ``_CITY_ROADS``, ``_BASE`` und ``_within_bbox`` wie
    in ``fetch_traffic``. Je ``road`` wird der Dienst ``services/webcam`` abgefragt.

    Webcams sind ein Live-Bild-Feature: die Route gibt das Live-Bild direkt aus.
    Die Lizenz bleibt Tier A DL-DE/BY (siehe ``map_autobahn_webcams``).

    Datenfehler-Schutz (Pitfall 5, identisch zu ``fetch_traffic``): das Koordinaten-
    Feld heißt ``long`` (NICHT ``lon``) und sein Wert ist ein STRING. Der Adapter
    castet defensiv per ``float(c.get("long", 0))``; ein fehlerhaftes Item fällt
    aus dem BBox-Filter heraus, statt einen 500 auszulösen.

    Der webcam-Sub-Service liefert in der Live-Realität oft leere Arrays; ein
    leeres ``webcams`` ist daher KEIN Fehler, sondern speist den ehrlichen
    no_data-Pfad der Route (Plan 09-06). Rückgabe-Keys exakt für den Mapper:
    ``slug`` und ``webcams``.
    """
    cams: list[dict] = []

    for road in _CITY_ROADS.get(slug, ()):
        resp = await http.get(f"{_BASE}/{road}/services/webcam")
        resp.raise_for_status()
        for item in resp.json().get("webcam", []):
            coordinate = item.get("coordinate") or {}
            # Pitfall 5: Feld heißt "long" (nicht "lon"), Wert ist String.
            elat = float(coordinate.get("lat", 0))
            elon = float(coordinate.get("long", 0))
            if not _within_bbox(elat, elon, lat, lon, radius_km):
                continue
            cams.append(item)

    return {"slug": slug, "webcams": cams}
