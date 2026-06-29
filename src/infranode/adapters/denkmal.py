"""Keyloser Denkmal-WFS-Adapter fetch_heritage (DATA-OSM-Tier-2, Denkmallisten).

Denkmalschutz ist in Deutschland LANDESsache: jedes Bundesland führt eine eigene
Denkmalliste, oft als WFS. Es gibt KEINEN bundesweiten Endpunkt. Daher ist der
Adapter foederiert: ``DENKMAL_WFS`` mappt das Bundesland-Kürzel
(``CityRegistryEntry.state``) auf eine WFS-Konfiguration. Ein neues Land erweitert
die Abdeckung automatisch (``registry.coverage`` leitet die Städte daraus ab).

Stand: Berlin (verifiziert, GeoJSON-WFS, DL-DE/Zero 2.0). Weitere Länder folgen,
sobald ihr WFS verifiziert ist (Hamburg liefert nur GML, NRW eigenes Schema ->
eigene Parser-Logik nötig; Bayern CC-BY-ND = NICHT nutzbar, fail-closed).

Sicherheit (T-SSRF): Host + typeName stammen ausschließlich aus der hartkodierten
``DENKMAL_WFS``-Registry (KEIN User-Input; ``state`` kommt aus dem validierten
Register). DoS-Schutz: ``count`` cappt die Feature-Zahl (analog Overpass
``out center``). Der Adapter ist rein (kein Cache/Breaker; das liefert die
Fassade); ``resp.raise_for_status()`` ist Pflicht (STALE-ON-ERROR-Pfad).
"""

from __future__ import annotations

from typing import NamedTuple

import httpx

# Obergrenze der je Anfrage geladenen Denkmal-Features (DoS-/Groessenschutz). Die
# Antwort liefert Repräsentativpunkte, nicht die rohen (großen) Polygone.
_COUNT_CAP = 500


class DenkmalSource(NamedTuple):
    """WFS-Konfiguration eines Bundeslandes (Denkmalliste).

    ``fields`` nennt die Property-Schlüssel, die je Objekt über lat/lon hinaus
    ausgeliefert werden. ``license_id``/``license_tier``/``attribution`` sind je
    Land verschieden (Berlin DL-DE/Zero) und wandern in den CanonicalRecord.
    """

    url: str
    typename: str
    fields: tuple[str, ...]
    license_id: str
    license_tier: str
    attribution: str


# Bundesland-Kürzel -> WFS-Konfiguration. Nur verifizierte, offen lizenzierte
# Länder (fail-closed). Berlin: GetCapabilities-verifiziert 2026-06-26.
DENKMAL_WFS: dict[str, DenkmalSource] = {
    "BE": DenkmalSource(
        url="https://gdi.berlin.de/services/wfs/denkmale",
        typename="denkmale:denkmale",
        fields=("typ", "link"),
        license_id="dl_de_zero_2_0",
        license_tier="A",
        attribution="Geoportal Berlin / Landesdenkmalamt Berlin, Denkmaldatenbank",
    ),
}


def _representative_point(geometry: dict | None) -> tuple[float | None, float | None]:
    """Mittelt alle Koordinaten einer GeoJSON-Geometrie zu einem Punkt (lat, lon).

    Denkmale sind oft (Multi-)Polygone; statt der großen Polygonringe liefern wir
    einen Repräsentativpunkt (Schwerpunkt der Stützpunkte). GeoJSON-Koordinaten
    sind ``[lon, lat]``. Robuste, defensive Rekursion über verschachtelte Listen.
    """
    if not isinstance(geometry, dict):
        return (None, None)
    lons: list[float] = []
    lats: list[float] = []

    def _collect(coords) -> None:
        if (
            isinstance(coords, (list, tuple))
            and len(coords) >= 2
            and isinstance(coords[0], (int, float))
            and isinstance(coords[1], (int, float))
        ):
            lons.append(float(coords[0]))
            lats.append(float(coords[1]))
            return
        if isinstance(coords, (list, tuple)):
            for part in coords:
                _collect(part)

    _collect(geometry.get("coordinates"))
    if not lons:
        return (None, None)
    return (round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6))


async def fetch_heritage(
    http: httpx.AsyncClient,
    *,
    slug: str,
    state: str,
) -> dict:
    """Holt Denkmale eines Bundeslandes per WFS GetFeature (GeoJSON, WGS84).

    ``state`` (Bundesland-Kürzel aus dem Register) wählt die WFS-Konfiguration;
    ein nicht abgedecktes Land löst ein ``KeyError`` aus (die Route prüft jedoch
    vorher ``is_covered`` und liefert dann ``not_covered``, sodass dieser Pfad nur
    für abgedeckte Länder erreicht wird).

    Rückgabe-Keys (das, was ``map_heritage`` erwartet): ``slug``, ``state``,
    ``fields``, ``license_id``/``license_tier``/``attribution`` und ``features``
    (rohe GeoJSON-FeatureCollection-Einträge).
    """
    src = DENKMAL_WFS[state]
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": src.typename,
        "count": str(_COUNT_CAP),
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
    }
    resp = await http.get(src.url, params=params)
    resp.raise_for_status()
    return {
        "slug": slug,
        "state": state,
        "fields": list(src.fields),
        "license_id": src.license_id,
        "license_tier": src.license_tier,
        "attribution": src.attribution,
        "features": resp.json().get("features", []),
    }
