"""Keyloser Autobahn-Adapter: fetch_traffic (DATA-07/08) + fetch_webcams (DATA-22).

Die Autobahn-API der Autobahn GmbH (Datenbasis BASt) ist keylos. Der Adapter
löst die 1->N-Zuordnung Stadt -> Autobahnen über eine kuratierte, Adapter-
lokale Liste (``_CITY_ROADS``) und fragt je Autobahn beide Dienste ab:
``roadworks`` (Baustellen, DATA-07) und ``warning`` (Verkehrswarnungen, DATA-08).

Abdeckung: ``_CITY_ROADS`` ist datengetrieben aus der Autobahn-API abgeleitet
(scripts-Scan, 2026-06-29): JEDER der 84 Register-Städte sind die Autobahnen
zugeordnet, die einen roadworks-/warning-Punkt innerhalb ~32 km um die Stadt
haben. Der Laufzeit-BBox-Filter (``radius_km``, Default 30) filtert dann präzise.

Sicherheit (T-05-13 SSRF): Der Host ist in ``_BASE`` hartkodiert. Die ``road``
stammt ausschließlich aus der kuratierten ``_CITY_ROADS``-Map (nie User-Input),
der ``slug`` kommt aus der Register-Allowlist. Ein unbekannter Slug liefert ein
leeres Tuple -> leere Events, kein Request gegen einen fremden Host.

DoS-/Latenz-Schutz (T-05-14): statt aller ~110 Autobahnen wird nur die kuratierte
Liste je Stadt abgefragt; die Requests laufen nebenläufig (``asyncio.gather`` mit
``_MAX_CONCURRENCY``-Semaphore), damit auch Städte mit vielen Autobahnen (Ruhr)
schnell bleiben. Cache/SWR/Single-Flight/Breaker liefert die Resilienz-Fassade.

Fehlertoleranz (Skalierung): eine EINZELNE kranke Autobahn (5xx/Timeout) fällt
tolerant weg (die Stadt liefert die übrigen Events weiter); NUR wenn ALLE Requests
scheitern, schlägt der erste Fehler als ``httpx.HTTPError`` an die Fassade durch
(Breaker/STALE-ON-ERROR greift).

Datenfehler-Schutz (T-05-15 / Pitfall 4): Das Koordinaten-Feld heißt ``long``
(NICHT ``lon``) und sein Wert ist ein STRING. Der Adapter castet defensiv und
überspringt ein fehlerhaftes Event, statt einen 500 auszulösen.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade).
"""

from __future__ import annotations

import asyncio
import math

import httpx

# Host hartkodiert (T-05-13 SSRF): nur diese eine öffentliche Autobahn-Instanz.
_BASE = "https://verkehr.autobahn.de/o/autobahn"

# Beide Dienste je Autobahn: DATA-07 Baustellen + DATA-08 Verkehrslage.
_SERVICES = ("roadworks", "warning")

# Obergrenze gleichzeitiger Upstream-Requests je Fetch (Städte im Ruhrgebiet haben
# >10 Autobahnen; ohne Bound würde EIN Stadt-Fetch den Pool/Upstream fluten).
_MAX_CONCURRENCY = 8

# Kuratierte Stadt -> Autobahnen-Map (T-05-13/14), datengetrieben aus der
# Autobahn-API abgeleitet (alle 84 Register-Städte, Punkt innerhalb ~32 km).
# Nur diese Werte gelangen in die URL (nie User-Input). Unbekannter Slug -> ().
_CITY_ROADS: dict[str, tuple[str, ...]] = {
    "aachen": ("A4",),
    "augsburg": ("A8",),
    "bergisch-gladbach": (
        "A1",
        "A3",
        "A4",
        "A46",
        "A59",
        "A61",
        "A535",
        "A542",
        "A553",
        "A555",
        "A560",
        "A562",
        "A565",
    ),
    "berlin": ("A10", "A11", "A100", "A103", "A111", "A113", "A114", "A115", "A117"),
    "bielefeld": ("A2", "A30", "A33"),
    "bochum": (
        "A1",
        "A2",
        "A3",
        "A40",
        "A42",
        "A43",
        "A44",
        "A45",
        "A46",
        "A52",
        "A59",
        "A448",
        "A516",
        "A535",
    ),
    "bonn": ("A1", "A3", "A4", "A59", "A61", "A553", "A555", "A560", "A562", "A565"),
    "bottrop": (
        "A2",
        "A3",
        "A40",
        "A42",
        "A43",
        "A44",
        "A45",
        "A46",
        "A52",
        "A57",
        "A59",
        "A448",
        "A516",
        "A535",
    ),
    "braunschweig": ("A2", "A7", "A36", "A39", "A391"),
    "bremen": ("A1", "A27", "A28", "A270", "A281"),
    "bremerhaven": ("A27",),
    "chemnitz": ("A4", "A72"),
    "cottbus": ("A13", "A15"),
    "darmstadt": ("A3", "A5", "A45", "A60", "A66", "A67", "A648", "A661"),
    "dortmund": (
        "A1",
        "A2",
        "A40",
        "A42",
        "A43",
        "A44",
        "A45",
        "A46",
        "A52",
        "A445",
        "A448",
    ),
    "dresden": ("A4", "A13", "A17"),
    "duesseldorf": (
        "A1",
        "A3",
        "A40",
        "A42",
        "A44",
        "A46",
        "A52",
        "A57",
        "A59",
        "A61",
        "A516",
        "A535",
        "A542",
    ),
    "duisburg": (
        "A2",
        "A3",
        "A40",
        "A42",
        "A44",
        "A46",
        "A52",
        "A57",
        "A59",
        "A516",
        "A535",
    ),
    "erfurt": ("A4", "A71"),
    "erlangen": ("A3", "A6", "A9", "A73"),
    "essen": (
        "A1",
        "A2",
        "A3",
        "A40",
        "A42",
        "A43",
        "A44",
        "A45",
        "A46",
        "A52",
        "A57",
        "A59",
        "A448",
        "A516",
        "A535",
    ),
    "frankfurt-am-main": ("A3", "A5", "A45", "A60", "A66", "A67", "A648", "A661"),
    "freiburg-im-breisgau": ("A5",),
    "fuerth": ("A3", "A6", "A9", "A73"),
    "gelsenkirchen": (
        "A1",
        "A2",
        "A3",
        "A40",
        "A42",
        "A43",
        "A44",
        "A45",
        "A46",
        "A52",
        "A59",
        "A448",
        "A516",
        "A535",
    ),
    "goettingen": ("A7", "A38"),
    "guetersloh": ("A2", "A33"),
    "hagen": ("A1", "A2", "A40", "A42", "A43", "A44", "A45", "A46", "A448", "A535"),
    "halle-saale": ("A9", "A14", "A38", "A143"),
    "hamburg": ("A1", "A7", "A21", "A23", "A24", "A25", "A39", "A261"),
    "hamm": ("A1", "A2", "A43", "A44", "A46", "A445"),
    "hanau": ("A3", "A5", "A45", "A66", "A648", "A661"),
    "hannover": ("A2", "A7", "A37", "A352"),
    "heidelberg": ("A5", "A6", "A61", "A67", "A656", "A659"),
    "heilbronn": ("A6", "A81"),
    "herne": (
        "A1",
        "A2",
        "A3",
        "A40",
        "A42",
        "A43",
        "A44",
        "A45",
        "A46",
        "A52",
        "A59",
        "A448",
        "A516",
    ),
    "hildesheim": ("A2", "A7", "A37", "A39"),
    "ingolstadt": ("A9", "A93"),
    "jena": ("A4", "A9"),
    "kaiserslautern": ("A6", "A8", "A63"),
    "karlsruhe": ("A5", "A8", "A65"),
    "kassel": ("A7", "A38", "A44", "A49"),
    "kiel": ("A7", "A21", "A215"),
    "koblenz": ("A3", "A61"),
    "koeln": (
        "A1",
        "A3",
        "A4",
        "A46",
        "A59",
        "A61",
        "A542",
        "A553",
        "A555",
        "A560",
        "A562",
        "A565",
    ),
    "krefeld": (
        "A2",
        "A3",
        "A40",
        "A42",
        "A44",
        "A46",
        "A52",
        "A57",
        "A59",
        "A61",
        "A516",
    ),
    "leipzig": ("A9", "A14", "A38", "A72"),
    "leverkusen": (
        "A1",
        "A3",
        "A4",
        "A44",
        "A46",
        "A52",
        "A59",
        "A61",
        "A535",
        "A542",
        "A553",
        "A555",
        "A560",
        "A565",
    ),
    "ludwigshafen-am-rhein": ("A5", "A6", "A61", "A65", "A67", "A656", "A659"),
    "luebeck": ("A1", "A20", "A21", "A226"),
    "magdeburg": ("A2", "A14"),
    "mainz": ("A3", "A5", "A60", "A61", "A66", "A67", "A643", "A648", "A661"),
    "mannheim": ("A5", "A6", "A61", "A65", "A67", "A656", "A659"),
    "moenchengladbach": ("A40", "A44", "A52", "A57", "A59", "A61"),
    "moers": ("A2", "A3", "A40", "A42", "A44", "A52", "A57", "A59", "A61", "A516"),
    "muelheim-an-der-ruhr": (
        "A1",
        "A2",
        "A3",
        "A40",
        "A42",
        "A43",
        "A44",
        "A46",
        "A52",
        "A57",
        "A59",
        "A516",
        "A535",
    ),
    "muenchen": ("A8", "A92", "A94", "A95", "A96", "A99", "A995", "A99a"),
    "muenster": ("A1", "A43"),
    "neuss": (
        "A1",
        "A3",
        "A4",
        "A40",
        "A44",
        "A46",
        "A52",
        "A57",
        "A59",
        "A61",
        "A535",
        "A542",
    ),
    "nuernberg": ("A3", "A6", "A9", "A73"),
    "oberhausen": (
        "A2",
        "A3",
        "A40",
        "A42",
        "A43",
        "A44",
        "A46",
        "A52",
        "A57",
        "A59",
        "A516",
        "A535",
    ),
    "offenbach-am-main": ("A3", "A5", "A45", "A60", "A66", "A67", "A648", "A661"),
    "oldenburg": ("A1", "A28", "A29", "A270", "A293"),
    "osnabrueck": ("A1", "A30", "A33"),
    "paderborn": ("A2", "A44"),
    "pforzheim": ("A5", "A8", "A81"),
    "potsdam": ("A9", "A10", "A100", "A103", "A111", "A113", "A115"),
    "recklinghausen": (
        "A1",
        "A2",
        "A3",
        "A40",
        "A42",
        "A43",
        "A44",
        "A45",
        "A52",
        "A448",
        "A516",
    ),
    "regensburg": ("A3", "A93"),
    "remscheid": (
        "A1",
        "A3",
        "A4",
        "A43",
        "A44",
        "A45",
        "A46",
        "A52",
        "A59",
        "A535",
        "A542",
    ),
    "reutlingen": ("A8", "A81", "A831"),
    "rostock": ("A19", "A20"),
    "saarbruecken": ("A1", "A6", "A8", "A620"),
    "salzgitter": ("A2", "A7", "A36", "A39", "A391"),
    "schwerin": ("A14", "A20", "A24"),
    "siegen": ("A4", "A45"),
    "solingen": (
        "A1",
        "A3",
        "A4",
        "A40",
        "A43",
        "A44",
        "A46",
        "A52",
        "A59",
        "A535",
        "A542",
    ),
    "stuttgart": ("A8", "A81", "A831"),
    "trier": ("A1", "A62", "A64", "A64a"),
    "ulm": ("A7", "A8"),
    "wiesbaden": ("A3", "A5", "A60", "A66", "A67", "A643", "A648", "A661"),
    "wolfsburg": ("A2", "A39", "A391"),
    "wuerzburg": ("A3", "A7", "A81"),
    "wuppertal": (
        "A1",
        "A3",
        "A40",
        "A42",
        "A43",
        "A44",
        "A45",
        "A46",
        "A52",
        "A59",
        "A448",
        "A535",
        "A542",
    ),
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


def _bbox_items(
    items: list[dict], lat: float, lon: float, radius_km: float
) -> list[dict]:
    """Filtert eine Item-Liste auf die Bounding-Box um (lat, lon).

    ``coordinate.long`` (NICHT ``lon``) ist ein STRING (Pitfall 4); ein nicht
    castbares/fehlendes Koordinatenpaar fällt defensiv aus dem Filter heraus.
    """
    out: list[dict] = []
    for item in items:
        coordinate = item.get("coordinate") or {}
        try:
            elat = float(coordinate.get("lat", 0))
            elon = float(coordinate.get("long", 0))
        except (TypeError, ValueError):
            continue
        if _within_bbox(elat, elon, lat, lon, radius_km):
            out.append(item)
    return out


async def _get_service_items(
    http: httpx.AsyncClient, sem: asyncio.Semaphore, road: str, service: str
) -> list[dict]:
    """Holt die Items EINES Dienstes EINER Autobahn (nebenläufig, Semaphore-bound).

    ``raise_for_status`` ist Pflicht, damit ein 5xx als ``httpx.HTTPError`` an den
    Aufrufer (gather) durchschlägt; der entscheidet über Toleranz vs. Fassade.
    """
    async with sem:
        resp = await http.get(f"{_BASE}/{road}/services/{service}")
    resp.raise_for_status()
    return resp.json().get(service, [])


def _raise_if_all_failed(results: list) -> None:
    """Wirft den ersten Fehler, wenn ALLE Requests scheiterten (Totalausfall).

    Einzelne kranke Autobahnen bleiben tolerant (Stadt liefert die übrigen
    Events); nur ein vollständiger Ausfall soll die Resilienz-Fassade (Breaker/
    STALE-ON-ERROR) triggern.
    """
    errors = [r for r in results if isinstance(r, Exception)]
    if results and len(errors) == len(results):
        raise errors[0]


async def fetch_traffic(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt Baustellen + Verkehrswarnungen je kuratierter Autobahn der Stadt.

    Fragt ``_CITY_ROADS.get(slug, ())`` × ``("roadworks", "warning")`` NEBENLÄUFIG
    ab (Semaphore-bound) und filtert per Bounding-Box um (``lat``, ``lon``). Eine
    einzelne kranke Autobahn fällt tolerant weg; nur ein Totalausfall schlägt als
    ``httpx.HTTPError`` an die Fassade durch.

    Rückgabe-Keys (exakt das, was ``map_autobahn_traffic`` erwartet): ``slug``,
    ``roadworks`` (DATA-07) und ``warnings`` (DATA-08).
    """
    roads = _CITY_ROADS.get(slug, ())
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    pairs = [(road, service) for road in roads for service in _SERVICES]
    roadworks: list[dict] = []
    warnings: list[dict] = []
    if pairs:
        results = await asyncio.gather(
            *(_get_service_items(http, sem, road, svc) for road, svc in pairs),
            return_exceptions=True,
        )
        _raise_if_all_failed(results)
        for (_road, service), result in zip(pairs, results, strict=True):
            if isinstance(result, Exception):
                continue
            filtered = _bbox_items(result, lat, lon, radius_km)
            if service == "roadworks":
                roadworks.extend(filtered)
            else:
                warnings.extend(filtered)

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
    in ``fetch_traffic`` (ebenfalls nebenläufig + einzel-fehlertolerant). Je
    ``road`` wird der Dienst ``services/webcam`` abgefragt.

    Webcams sind ein Live-Bild-Feature: die Route gibt das Live-Bild direkt aus.
    Die Lizenz bleibt Tier A DL-DE/BY (siehe ``map_autobahn_webcams``).

    Der webcam-Sub-Service liefert in der Live-Realität oft leere Arrays; ein
    leeres ``webcams`` ist daher KEIN Fehler, sondern speist den ehrlichen
    no_data-Pfad der Route. Rückgabe-Keys exakt für den Mapper: ``slug`` und
    ``webcams``.
    """
    roads = _CITY_ROADS.get(slug, ())
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    cams: list[dict] = []
    if roads:
        results = await asyncio.gather(
            *(_get_service_items(http, sem, road, "webcam") for road in roads),
            return_exceptions=True,
        )
        _raise_if_all_failed(results)
        for result in results:
            if isinstance(result, Exception):
                continue
            cams.extend(_bbox_items(result, lat, lon, radius_km))

    return {"slug": slug, "webcams": cams}
