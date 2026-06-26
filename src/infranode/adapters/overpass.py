"""Keyloser Overpass-Adapter fetch_pois (DATA-04).

Laedt POIs einer Stadt ueber die oeffentliche Overpass-Instanz per POST. Der
Adapter baut die Overpass-QL deterministisch auf:

- die Suchflaeche ist ``area(3600000000 + osm_relation)`` (Overpass leitet eine
  Area-ID aus der OSM-Relation ab, indem es ``3600000000`` addiert),
- der POI-Typ wird ueber eine Whitelist (``_ALLOWED_TYPES``) auf ein festes
  ``amenity``-Tag gemappt.

Sicherheit (T-05-09 Injection / T-05-12 SSRF): Der Host stammt aus ``_BASE`` bzw.
dem operator-gesetzten ``base_url`` (Env ``INFRANODE_OVERPASS_BASE_URL``, KEIN
User-Input) -> SSRF-Invariante bleibt gewahrt. Hintergrund: Die oeffentliche
Overpass-Instanz untersagt Drittnutzer-Backends im Dauerbetrieb (Fair-Use); fuer
Produktion auf eine eigene Instanz (Planet-Dump) oder Geofabrik umstellen. Der
User-kontrollierte ``poi_type`` gelangt NIE roh in die QL: ein
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

from typing import NamedTuple

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
    base_url: str = _BASE,
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

    # out center 200 cappt (nwr+center: auch way/relation-POIs) die Antwort
    # (DoS-Schutz, Pitfall 2); timeout begrenzt die Server-Laufzeit. Nur die
    # validierte area_id und das Whitelist-amenity werden interpoliert.
    ql = (
        f"[out:json][timeout:25];"
        f"area({area_id})->.a;"
        f'nwr["amenity"="{amenity}"](area.a);'
        f"out center 200;"
    )

    resp = await http.post(base_url, data={"data": ql})
    resp.raise_for_status()
    return {
        "slug": slug,
        "poi_type": poi_type,
        "elements": resp.json().get("elements", []),
    }


class _Feature(NamedTuple):
    """Definition einer OSM-Feature-Datenart (DATA-OSM, Tier B copyleft).

    ``groups`` ist eine Liste von Selektor-Gruppen; jede Gruppe ist eine Liste von
    ``(key, value)``-Tags, die innerhalb EINER ``nwr``-Zeile UND-verknuepft werden
    (z.B. ``amenity=recycling`` + ``recycling_type=centre``). Mehrere Gruppen
    bilden eine Vereinigung (mehrere ``nwr``-Zeilen in einer Union). ``extra_tags``
    nennt OSM-Tag-Schluessel, die ueber name/lat/lon hinaus je Element ausgeliefert
    werden (z.B. ``collection_times`` am Briefkasten, ``opening_hours``).
    """

    groups: tuple[tuple[tuple[str, str], ...], ...]
    extra_tags: tuple[str, ...]


# Feature-Whitelist (T-05-09 Injection): jeder Feature-Schluessel mappt auf feste,
# hartkodierte Tag-Selektoren. Ein unbekannter Schluessel loest beim Lookup ein
# KeyError aus (kein roher User-Input in die Overpass-QL). Die Schluessel sind
# zugleich die letzten Pfadsegmente der dedizierten Endpunkte.
_OSM_FEATURES: dict[str, _Feature] = {
    "playgrounds": _Feature(((("leisure", "playground"),),), ()),
    "drinking-water": _Feature(((("amenity", "drinking_water"),),), ()),
    "markets": _Feature(((("amenity", "marketplace"),),), ("opening_hours",)),
    "parcel-lockers": _Feature(
        ((("amenity", "parcel_locker"),),), ("operator", "brand")
    ),
    "post-offices": _Feature(
        ((("amenity", "post_office"),),), ("opening_hours", "operator")
    ),
    "post-boxes": _Feature(((("amenity", "post_box"),),), ("collection_times",)),
    "public-wifi": _Feature(((("internet_access", "wlan"),),), ("operator",)),
    "recycling-centres": _Feature(
        ((("amenity", "recycling"), ("recycling_type", "centre")),),
        ("opening_hours",),
    ),
    "government-offices": _Feature(
        ((("office", "government"),), (("amenity", "townhall"),)),
        ("government", "operator"),
    ),
    "education": _Feature(
        (
            (("amenity", "school"),),
            (("amenity", "college"),),
            (("amenity", "university"),),
            (("amenity", "kindergarten"),),
        ),
        ("operator",),
    ),
}


def _build_feature_ql(area_id: int, feature: _Feature) -> str:
    """Baut die Overpass-QL fuer ein Feature deterministisch (Union der Gruppen).

    Nur die validierte ``area_id`` (int) und die hartkodierten Tag-Schluessel/
    -Werte aus ``_OSM_FEATURES`` werden interpoliert (kein User-Input, T-05-09).
    ``out center 200`` cappt die Antwort (DoS-Schutz, Pitfall 2), ``timeout:25``
    begrenzt die Server-Laufzeit.
    """
    lines = []
    for group in feature.groups:
        filt = "".join(f'["{key}"="{value}"]' for key, value in group)
        lines.append(f"nwr{filt}(area.a);")
    union = "(" + "".join(lines) + ");"
    return f"[out:json][timeout:25];area({area_id})->.a;{union}out center 200;"


async def fetch_osm_feature(
    http: httpx.AsyncClient,
    *,
    slug: str,
    osm_relation: int,
    feature: str,
    base_url: str = _BASE,
) -> dict:
    """Holt eine OSM-Feature-Datenart in einer Stadt und liefert das raw-dict.

    ``feature`` wird ueber ``_OSM_FEATURES`` auf feste Tag-Selektoren gemappt; ein
    unbekannter ``feature`` loest ein ``KeyError`` aus (Injection-Schutz T-05-09,
    die Route mappt das auf 422). Die Suchflaeche ist ``area(3600000000 +
    osm_relation)``.

    Rueckgabe-Keys (exakt das, was ``map_osm_feature`` erwartet): ``slug``,
    ``poi_type`` (= ``feature``), ``extra_tags`` und ``elements`` (rohe
    Overpass-Elementliste).
    """
    feature_def = _OSM_FEATURES[feature]
    area_id = _AREA_OFFSET + osm_relation
    ql = _build_feature_ql(area_id, feature_def)

    resp = await http.post(base_url, data={"data": ql})
    resp.raise_for_status()
    return {
        "slug": slug,
        "poi_type": feature,
        "extra_tags": list(feature_def.extra_tags),
        "elements": resp.json().get("elements", []),
    }
