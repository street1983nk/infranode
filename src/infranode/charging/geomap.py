"""eRound-Geo-Map: refill_point_id -> Stadt-Slug + Koordinaten (DATA-42, Stufe 1).

Der dynamische eRound-Belegungs-Feed trägt NUR ``refill_point_id`` + ``status``
(kein Geo). Die Stadt-Zuordnung liefert der statische Vollbestand
(``aegiEnergyInfrastructureTablePublication``, ~94 MB JSON, Koordinaten je
STATION unter ``locationReference.locAreaLocation.coordinatesForDisplay``,
live verifiziert 2026-07-03: 4921 Sites / 7401 Stationen / 14937 Ladepunkte).

Zwei Rollen:
- ``build_geo_map(doc)``: reine Transformation des geparsten stat-Dokuments in
  die Map ``{slug: {refill_point_id: [lat, lon]}}`` (naechste Registry-Stadt im
  bevölkerungsskalierten Umkreis, Formel-Muster BORIS/denkmal). Rein und ohne
  IO, damit der private Ingest (``ingest.eround_geo``) und der Seed-Generator
  exakt dieselbe Zuordnung rechnen.
- ``load_city_points(path)``: gecachter Datei-Loader für den Request-Pfad.
  Quelle der Wahrheit ist die Datei im persistenten Daten-Volume (vom täglichen
  Ingest geschrieben); fehlt sie, fällt der Loader auf den committeten Seed
  (``data/seeds/eround_geo_map.json``) zurück. BEWUSST eine Datei statt Redis:
  der Redis-Store ist nicht persistent (allkeys-lru, kein RDB/AOF) und könnte
  die Map still evicten; die Datei überlebt Neustarts.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import structlog

from infranode.infra.seeds import seeds_dir

log = structlog.get_logger()

# Fallback-Seed im Repo (Erst-Vollbestand vom 2026-07-03, CC0). Der Ingest
# schreibt die frischere Kopie in das Daten-Volume (settings.eround_geo_map_path).
_SEED_NAME = "eround_geo_map.json"

# Loader-Cache je (aufgeloester Pfad): (mtime, cities-dict). Die Map ändert sich
# höchstens einmal täglich (Ingest); ein mtime-Check pro Request reicht.
_CACHE: dict[str, tuple[float, dict]] = {}


def _city_radius_deg(population: int | None) -> float:
    """Stadt-Umkreis (Grad) aus der Einwohnerzahl (Formel-Muster BORIS/denkmal).

    Größere Städte = größeres Stadtgebiet -> größerer Umkreis, geklammert auf
    [0.06, 0.30] Grad. Bewusst grob (Stadtkern-Umkreis, kein amtlicher
    Grenzschnitt): ein Ladepunkt knapp außerhalb der Gemeindegrenze einer
    Großstadt gehört funktional zum Stadt-Lade-Netz.
    """
    pop = population or 0
    return min(0.30, max(0.06, 0.05 + pop / 16_000_000))


def _coerce_list(value) -> list:
    """DATEX-II-Feld zu Liste normalisieren (dict ODER Liste ODER None)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def nearest_city_slug(lat: float, lon: float, cities) -> str | None:
    """Naechste Stadt, deren Umkreis den Punkt enthält (normierte Grad-Distanz).

    ``cities`` ist eine Sequenz ``(slug, lat, lon, radius_deg)``. Die
    Längen-Differenz wird mit ``cos(lat)`` gestaucht, damit die Distanz am Boden
    näherungsweise isotrop ist (Muster ``denkmal._bbox_param``). Kein Treffer ->
    ``None`` (Punkt liegt außerhalb aller Register-Städte, z.B. ländlich).
    """
    best: str | None = None
    best_d: float | None = None
    for slug, clat, clon, radius in cities:
        dlat = lat - clat
        dlon = (lon - clon) * math.cos(math.radians(clat))
        d = math.hypot(dlat, dlon)
        if d <= radius and (best_d is None or d < best_d):
            best, best_d = slug, d
    return best


def _registry_cities() -> list[tuple[str, float, float, float]]:
    """Alle 84 Register-Städte als (slug, lat, lon, radius_deg)-Tupel."""
    from infranode.registry import CITY_REGISTRY

    return [
        (c.slug, c.geo.lat, c.geo.lon, _city_radius_deg(c.population))
        for c in CITY_REGISTRY
    ]


def build_geo_map(doc: dict) -> dict:
    """Baut die Geo-Map aus dem geparsten stat-Vollbestand (rein, kein IO).

    Navigiert ``payload[].aegiEnergyInfrastructureTablePublication`` ->
    ``energyInfrastructureTable[]`` -> ``energyInfrastructureSite[]`` ->
    ``energyInfrastructureStation[]`` (Koordinaten) -> ``refillPoint[].
    aegiElectricChargingPoint.idG``. Stationen ohne Koordinaten oder außerhalb
    aller Stadt-Umkreise fallen ehrlich raus (der dynamische Status dieser
    Punkte ist keiner Stadt zuordenbar). Rückgabe:
    ``{"publication_time": ..., "cities": {slug: {rp_id: [lat, lon]}}}``.
    """
    container = doc.get("messageContainer")
    if not isinstance(container, dict):
        container = doc if isinstance(doc, dict) else {}

    cities = _registry_cities()
    by_city: dict[str, dict[str, list[float]]] = {}
    publication_time: str | None = None

    for payload in _coerce_list(container.get("payload")):
        if not isinstance(payload, dict):
            continue
        pub = payload.get("aegiEnergyInfrastructureTablePublication")
        if not isinstance(pub, dict):
            continue
        if publication_time is None and pub.get("publicationTime"):
            publication_time = str(pub["publicationTime"])
        for table in _coerce_list(pub.get("energyInfrastructureTable")):
            if not isinstance(table, dict):
                continue
            for site in _coerce_list(table.get("energyInfrastructureSite")):
                if not isinstance(site, dict):
                    continue
                for station in _coerce_list(site.get("energyInfrastructureStation")):
                    if not isinstance(station, dict):
                        continue
                    loc = (
                        (station.get("locationReference") or {})
                        .get("locAreaLocation", {})
                        .get("coordinatesForDisplay", {})
                    )
                    lat, lon = loc.get("latitude"), loc.get("longitude")
                    if lat is None or lon is None:
                        continue
                    slug = nearest_city_slug(float(lat), float(lon), cities)
                    if slug is None:
                        continue
                    for rp in _coerce_list(station.get("refillPoint")):
                        cp = (
                            rp.get("aegiElectricChargingPoint")
                            if isinstance(rp, dict)
                            else None
                        )
                        if isinstance(cp, dict) and cp.get("idG"):
                            by_city.setdefault(slug, {})[str(cp["idG"])] = [
                                round(float(lat), 6),
                                round(float(lon), 6),
                            ]

    return {
        "publication_time": publication_time,
        "cities": {slug: by_city[slug] for slug in sorted(by_city)},
    }


def load_city_points(path: str) -> dict[str, dict[str, list[float]]]:
    """Laedt die Geo-Map fuer den Request-Pfad (Volume-Datei, sonst Seed).

    mtime-gecacht je Pfad (die Map ändert sich höchstens täglich). Eine
    unlesbare/kaputte Datei -> leere Map + Warning (die Route liefert dann
    ehrlich ``no_data``, kein 500). Rückgabe ist NUR das ``cities``-dict.
    """
    candidate = Path(path)
    if not candidate.is_file():
        candidate = seeds_dir() / _SEED_NAME
    resolved = str(candidate)

    try:
        mtime = os.path.getmtime(resolved)
    except OSError:
        return {}

    cached = _CACHE.get(resolved)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        with open(resolved, encoding="utf-8") as fh:
            data = json.load(fh)
        cities = data.get("cities")
        if not isinstance(cities, dict):
            cities = {}
    except (OSError, ValueError) as exc:
        log.warning("eround_geo_map_unreadable", error=type(exc).__name__)
        cities = {}

    _CACHE[resolved] = (mtime, cities)
    return cities
