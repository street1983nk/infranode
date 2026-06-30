"""Keyloser Overpass-Adapter fetch_pois (DATA-04).

Lädt POIs einer Stadt über die öffentliche Overpass-Instanz per POST. Der
Adapter baut die Overpass-QL deterministisch auf:

- die Suchfläche ist ``area(3600000000 + osm_relation)`` (Overpass leitet eine
  Area-ID aus der OSM-Relation ab, indem es ``3600000000`` addiert),
- der POI-Typ wird über eine Whitelist (``_ALLOWED_TYPES``) auf ein festes
  ``amenity``-Tag gemappt.

Sicherheit (T-05-09 Injection / T-05-12 SSRF): Der Host stammt aus ``_BASE`` bzw.
dem operator-gesetzten ``base_url`` (Env ``INFRANODE_OVERPASS_BASE_URL``, KEIN
User-Input) -> SSRF-Invariante bleibt gewahrt. Hintergrund: Die öffentliche
Overpass-Instanz untersagt Drittnutzer-Backends im Dauerbetrieb (Fair-Use); für
Produktion auf eine eigene Instanz (Planet-Dump) oder Geofabrik umstellen. Der
User-kontrollierte ``poi_type`` gelangt NIE roh in die QL: ein
unbekannter Typ löst beim Whitelist-Lookup ein ``KeyError`` aus, das die Route
auf 422 mappt (BEVOR ein Request läuft). Nur die aus dem validierten Register
stammende ``osm_relation`` (int > 0) und das Whitelist-amenity-Tag werden in den
Body interpoliert.

DoS-Schutz (T-05-11, Pitfall 2): ``[out:json][timeout:25]`` begrenzt die
Server-Laufzeit, ``out center <max_elements>`` cappt die Antwortgröße gegen
Riesen-Antworten. Das Element-Limit ist KONFIGURIERBAR (``max_elements``, Default
``_DEFAULT_MAX_ELEMENTS`` = 2000) statt hart 200 (Audit K9: das alte Cap 200 hat
~67-87% aller Objekte still gekappt, z.B. Köln Spielplätze 200 statt 1540).

Ehrlichkeit bei Truncation (Audit K9): jede QL führt ZUSÄTZLICH ein
``out count;`` auf demselben Ergebnis-Set, BEVOR die (gedeckelte) Element-Ausgabe
folgt. Overpass liefert dann ein Element ``type=="count"`` mit dem ECHTEN
Gesamtbestand (``tags.total``) plus die auf ``max_elements`` gedeckelte
Stichprobe. Der Adapter trennt das count-Element heraus und reicht
``total_available`` (echter Gesamtbestand) ans raw-dict durch; der Mapper leitet
daraus ``count`` (gelieferte Stichprobe), ``total_available`` und ``truncated``
ab. KEIN zweiter Netz-Call nötig (beides in EINER Query).

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.
"""

from __future__ import annotations

from typing import NamedTuple

import httpx

# Host hartkodiert (T-05-12 SSRF): nur diese eine öffentliche Overpass-Instanz.
_BASE = "https://overpass-api.de/api/interpreter"

# Read-Timeout der Overpass-POSTs. Die QL traegt server-seitig ``[out:json]
# [timeout:25]`` (25s Ausfuehrungsbudget); der Client-Read MUSS laenger sein als
# dieses Budget, sonst laeuft jede stadtweite Area-Abfrage zwangslaeufig ins
# ``ReadTimeout`` und der per-Source-Breaker flappt dauerhaft OPEN (alle OSM-
# Endpunkte liefern dann 503/not-covered). Der konservative 5s-Client-Default
# (infra/http.py) ist fuer Overpass also zu kurz; hier explizit pro Request
# ueberschrieben (T-03-03), ohne den Default fuer schnelle Quellen zu lockern.
_OVERPASS_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=2.0)

# Offset, mit dem Overpass aus einer OSM-Relation eine Area-ID bildet.
_AREA_OFFSET = 3600000000

# Default-Element-Limit (Audit K9): die ausgelieferte Stichprobe wird auf diesen
# Wert gedeckelt (statt hart 200). Operator-konfigurierbar über das Setting
# ``overpass_max_elements`` (Env INFRANODE_OVERPASS_MAX_ELEMENTS), das die Routen
# als ``max_elements`` durchreichen. Der ECHTE Gesamtbestand kommt unabhängig
# davon über ``out count;`` (siehe Modul-Docstring) als ``total_available``.
_DEFAULT_MAX_ELEMENTS = 2000

# Typ-Whitelist (T-05-09 Injection): jeder erlaubte ``poi_type`` wird auf ein
# festes, gültiges ``amenity``-Tag gemappt. Ein unbekannter Typ löst beim
# Lookup ein KeyError aus (kein roher User-Input in die Overpass-QL).
_ALLOWED_TYPES: dict[str, str] = {
    "hospital": "hospital",
    "school": "school",
    "pharmacy": "pharmacy",
    "restaurant": "restaurant",
    "police": "police",
    "kindergarten": "kindergarten",
}


def _split_count_element(elements: list[dict]) -> tuple[int | None, list[dict]]:
    """Trennt das Overpass-``out count``-Element von den echten POI-Elementen.

    ``out count;`` hängt der Antwort ein Pseudo-Element ``type=="count"`` mit dem
    echten Gesamtbestand in ``tags.total`` voran (Audit K9, Ehrlichkeit bei
    Truncation). Rueckgabe: ``(total_available, poi_elements)``. ``total_available``
    ist ``None``, wenn keine count-Zeile vorliegt (alte Mocks/Fixtures ohne count
    bleiben damit kompatibel); ``poi_elements`` ist die Liste OHNE das count-Element.
    """
    total: int | None = None
    pois: list[dict] = []
    for element in elements:
        if element.get("type") == "count":
            raw_total = element.get("tags", {}).get("total")
            if raw_total is not None:
                try:
                    total = int(raw_total)
                except (TypeError, ValueError):
                    total = None
            continue
        pois.append(element)
    return total, pois


async def fetch_pois(
    http: httpx.AsyncClient,
    *,
    slug: str,
    osm_relation: int,
    poi_type: str,
    base_url: str = _BASE,
    max_elements: int = _DEFAULT_MAX_ELEMENTS,
) -> dict:
    """Holt OSM-POIs eines Typs in einer Stadt und liefert das flache raw-dict.

    Die Suchfläche ist ``area(3600000000 + osm_relation)``; ``poi_type`` wird
    über ``_ALLOWED_TYPES`` auf ein ``amenity``-Tag gemappt. Ein unbekannter
    ``poi_type`` löst ein ``KeyError`` aus (Injection-Schutz, T-05-09): roher
    User-Input gelangt NIE in die QL, die Route mappt das KeyError auf 422.

    ``max_elements`` deckelt die ausgelieferte Stichprobe (Default
    ``_DEFAULT_MAX_ELEMENTS``); der vorgeschaltete ``out count;`` liefert den
    echten Gesamtbestand (Audit K9).

    Rückgabe-Keys (exakt das, was ``map_overpass_pois`` erwartet): ``slug``,
    ``poi_type``, ``elements`` (die rohe Overpass-Elementliste OHNE count-Zeile)
    und ``total_available`` (echter Gesamtbestand laut Quelle, ggf. ``None``).
    """
    # Whitelist-Lookup VOR jeglichem QL-Aufbau: unbekannter Typ -> KeyError.
    amenity = _ALLOWED_TYPES[poi_type]
    area_id = _AREA_OFFSET + osm_relation

    # Ergebnis-Set zwischenspeichern (->.r), darauf erst out count; (echter
    # Gesamtbestand) und dann out center <max_elements> (gedeckelte Stichprobe,
    # auch way/relation-POIs). DoS-Schutz Pitfall 2 + Audit-K9-Ehrlichkeit. Nur die
    # validierte area_id, das Whitelist-amenity und das int-Limit werden interpoliert.
    ql = (
        f"[out:json][timeout:25];"
        f"area({area_id})->.a;"
        f'nwr["amenity"="{amenity}"](area.a)->.r;'
        f".r out count;"
        f".r out center {max_elements};"
    )

    resp = await http.post(base_url, data={"data": ql}, timeout=_OVERPASS_TIMEOUT)
    resp.raise_for_status()
    total, pois = _split_count_element(resp.json().get("elements", []))
    return {
        "slug": slug,
        "poi_type": poi_type,
        "elements": pois,
        "total_available": total,
    }


class _Feature(NamedTuple):
    """Definition einer OSM-Feature-Datenart (DATA-OSM, Tier B copyleft).

    ``groups`` ist eine Liste von Selektor-Gruppen; jede Gruppe ist eine Liste von
    ``(key, value)``-Tags, die innerhalb EINER ``nwr``-Zeile UND-verknüpft werden
    (z.B. ``amenity=recycling`` + ``recycling_type=centre``). Mehrere Gruppen
    bilden eine Vereinigung (mehrere ``nwr``-Zeilen in einer Union). ``extra_tags``
    nennt OSM-Tag-Schlüssel, die über name/lat/lon hinaus je Element ausgeliefert
    werden (z.B. ``collection_times`` am Briefkasten, ``opening_hours``).
    """

    groups: tuple[tuple[tuple[str, str], ...], ...]
    extra_tags: tuple[str, ...]


# Feature-Whitelist (T-05-09 Injection): jeder Feature-Schlüssel mappt auf feste,
# hartkodierte Tag-Selektoren. Ein unbekannter Schlüssel löst beim Lookup ein
# KeyError aus (kein roher User-Input in die Overpass-QL). Die Schlüssel sind
# zugleich die letzten Pfadsegmente der dedizierten Endpunkte.
_OSM_FEATURES: dict[str, _Feature] = {
    "playgrounds": _Feature(((("leisure", "playground"),),), ()),
    "drinking-water": _Feature(((("amenity", "drinking_water"),),), ()),
    # Oeffentliche Toiletten inkl. Barrierefreiheits-Tags (USP): wheelchair +
    # changing_table je Element, plus fee/access/opening_hours/unisex.
    "public-toilets": _Feature(
        ((("amenity", "toilets"),),),
        ("wheelchair", "changing_table", "fee", "access", "opening_hours", "unisex"),
    ),
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


def _build_feature_ql(
    area_id: int, feature: _Feature, max_elements: int = _DEFAULT_MAX_ELEMENTS
) -> str:
    """Baut die Overpass-QL für ein Feature deterministisch (Union der Gruppen).

    Nur die validierte ``area_id`` (int), die hartkodierten Tag-Schluessel/-Werte
    aus ``_OSM_FEATURES`` und das int-Limit ``max_elements`` werden interpoliert
    (kein User-Input, T-05-09). Die Union wird über ``->.r`` zwischengespeichert;
    darauf laufen ``out count;`` (echter Gesamtbestand, Audit K9) und
    ``out center <max_elements>`` (gedeckelte Stichprobe, DoS-Schutz Pitfall 2).
    ``timeout:25`` begrenzt die Server-Laufzeit.
    """
    lines = []
    for group in feature.groups:
        filt = "".join(f'["{key}"="{value}"]' for key, value in group)
        lines.append(f"nwr{filt}(area.a);")
    union = "(" + "".join(lines) + ")->.r;"
    return (
        f"[out:json][timeout:25];area({area_id})->.a;{union}"
        f".r out count;.r out center {max_elements};"
    )


async def fetch_osm_feature(
    http: httpx.AsyncClient,
    *,
    slug: str,
    osm_relation: int,
    feature: str,
    base_url: str = _BASE,
    max_elements: int = _DEFAULT_MAX_ELEMENTS,
) -> dict:
    """Holt eine OSM-Feature-Datenart in einer Stadt und liefert das raw-dict.

    ``feature`` wird über ``_OSM_FEATURES`` auf feste Tag-Selektoren gemappt; ein
    unbekannter ``feature`` löst ein ``KeyError`` aus (Injection-Schutz T-05-09,
    die Route mappt das auf 422). Die Suchfläche ist ``area(3600000000 +
    osm_relation)``. ``max_elements`` deckelt die Stichprobe (Default
    ``_DEFAULT_MAX_ELEMENTS``); ``out count;`` liefert den echten Gesamtbestand.

    Rückgabe-Keys (exakt das, was ``map_osm_feature`` erwartet): ``slug``,
    ``poi_type`` (= ``feature``), ``extra_tags``, ``elements`` (rohe Overpass-
    Elementliste OHNE count-Zeile) und ``total_available`` (echter Gesamtbestand
    laut Quelle, ggf. ``None``).
    """
    feature_def = _OSM_FEATURES[feature]
    area_id = _AREA_OFFSET + osm_relation
    ql = _build_feature_ql(area_id, feature_def, max_elements)

    resp = await http.post(base_url, data={"data": ql}, timeout=_OVERPASS_TIMEOUT)
    resp.raise_for_status()
    total, pois = _split_count_element(resp.json().get("elements", []))
    return {
        "slug": slug,
        "poi_type": feature,
        "extra_tags": list(feature_def.extra_tags),
        "elements": pois,
        "total_available": total,
    }
