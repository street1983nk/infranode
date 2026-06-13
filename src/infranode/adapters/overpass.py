"""Keyloser Overpass-Adapter fetch_pois (DATA-04).

Laedt POIs einer Stadt ueber die oeffentliche Overpass-Instanz per POST. Der
Adapter baut die Overpass-QL deterministisch auf:

- die Suchflaeche ist ``area(3600000000 + osm_relation)`` (Overpass leitet eine
  Area-ID aus der OSM-Relation ab, indem es ``3600000000`` addiert),
- der POI-Typ wird ueber eine Whitelist (``_ALLOWED_TYPES``) auf ein festes
  ``amenity``-Tag gemappt.

Sicherheit (T-05-09 Injection / T-05-12 SSRF): Der Host ist in ``_BASE``
hartkodiert. Der User-kontrollierte ``poi_type`` gelangt NIE roh in die QL: ein
unbekannter Typ loest beim Whitelist-Lookup ein ``KeyError`` aus, das die Route
auf 422 mappt (BEVOR ein Request laeuft). Nur die aus dem validierten Register
stammende ``osm_relation`` (int > 0) und das Whitelist-amenity-Tag werden in den
Body interpoliert.

DoS-Schutz (T-05-11, Pitfall 2): ``[out:json][timeout:25]`` begrenzt die
Server-Laufzeit, ``out body 200`` cappt die Antwortgroesse gegen Riesen-Antworten.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.
"""

from __future__ import annotations

import httpx

# Host hartkodiert (T-05-12 SSRF): nur diese eine oeffentliche Overpass-Instanz.
_BASE = "https://overpass-api.de/api/interpreter"

# Offset, mit dem Overpass aus einer OSM-Relation eine Area-ID bildet.
_AREA_OFFSET = 3600000000

# Typ-Whitelist (T-05-09 Injection): jeder erlaubte ``poi_type`` wird auf ein
# festes, gueltiges ``amenity``-Tag gemappt. Ein unbekannter Typ loest beim
# Lookup ein KeyError aus (kein roher User-Input in die Overpass-QL).
_ALLOWED_TYPES: dict[str, str] = {
    "hospital": "hospital",
    "school": "school",
    "pharmacy": "pharmacy",
    "restaurant": "restaurant",
    "police": "police",
    "kindergarten": "kindergarten",
}


async def fetch_pois(
    http: httpx.AsyncClient,
    *,
    slug: str,
    osm_relation: int,
    poi_type: str,
) -> dict:
    """Holt OSM-POIs eines Typs in einer Stadt und liefert das flache raw-dict.

    Die Suchflaeche ist ``area(3600000000 + osm_relation)``; ``poi_type`` wird
    ueber ``_ALLOWED_TYPES`` auf ein ``amenity``-Tag gemappt. Ein unbekannter
    ``poi_type`` loest ein ``KeyError`` aus (Injection-Schutz, T-05-09): roher
    User-Input gelangt NIE in die QL, die Route mappt das KeyError auf 422.

    Rueckgabe-Keys (exakt das, was ``map_overpass_pois`` erwartet): ``slug``,
    ``poi_type`` und ``elements`` (die rohe Overpass-Elementliste).
    """
    # Whitelist-Lookup VOR jeglichem QL-Aufbau: unbekannter Typ -> KeyError.
    amenity = _ALLOWED_TYPES[poi_type]
    area_id = _AREA_OFFSET + osm_relation

    # out center 200 cappt (nwr+center: auch way/relation-POIs) die Antwort (DoS-Schutz, Pitfall 2); timeout begrenzt
    # die Server-Laufzeit. Nur die validierte area_id und das Whitelist-amenity
    # werden interpoliert.
    ql = (
        f"[out:json][timeout:25];"
        f"area({area_id})->.a;"
        f'nwr["amenity"="{amenity}"](area.a);'
        f"out center 200;"
    )

    resp = await http.post(_BASE, data={"data": ql})
    resp.raise_for_status()
    return {
        "slug": slug,
        "poi_type": poi_type,
        "elements": resp.json().get("elements", []),
    }
