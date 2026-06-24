"""Oeffentliche Per-City-Coverage-Karte der teilabgedeckten Endpunkte.

Ehrlichkeit statt leerer Versprechen (Owner-Entscheidung 2026-06-13): einige
Endpunkte decken nur kuratierte Staedte ab. Frueher lieferten sie fuer eine
nicht-abgedeckte Stadt ein leeres ``source_status="ok"`` (sieht aus wie "kein
Ereignis"), was die fehlende Abdeckung verschleiert. Stattdessen weisen die
Routen jetzt ``source_status="not_covered"`` aus (200, ``data: null``) und
nennen im meta-Block die abgedeckten Staedte (``covered_cities``). ``not_covered``
ist klar unterscheidbar von ``no_data`` (Stadt abgedeckt, aktuell aber keine
Daten) und vom 404 (Stadt unbekannt).

Dieses Modul ist die EINZIGE Quelle der Wahrheit der Abdeckung und wird aus den
kuratierten Adapter-Stadt-Maps ABGELEITET (kein Duplizieren der Slug-Listen):
- ``flood``    -> ``adapters.lhp._CITY_PEGEL`` (kuratierte Pegel je Stadt)
- ``webcams``  -> ``adapters.autobahn._CITY_ROADS`` (kuratierte Autobahnen)
- ``traffic``  -> ``adapters.autobahn._CITY_ROADS`` (dieselbe Map wie webcams)
- ``road-events`` -> ``api.v1.cities.CONNECTOR_MAP`` (kuratierte Stadt-Connectoren)

Da ``CONNECTOR_MAP`` in ``cities.py`` lebt (mit fetch_fn/mapper-Tupeln) und
``cities.py`` dieses Modul importiert, wird die road-events-Liste hier gespiegelt
statt importiert (Zirkelimport-Vermeidung). Eine Modul-Assertion in ``cities.py``
sichert die Gleichheit beider Listen ab und faengt Drift beim Import hart ab.

NICHT teilabgedeckt (bewusst NICHT in dieser Karte):
- ``water-level``: Geo-Proximity ohne kuratierte Stadt-Map; liefert bei fehlender
  naher Station bereits ehrlich ``no_data`` (dynamisch, deutschlandweit an
  Bundeswasserstrassen).
- ``live/transit/*``: bundesweiter GTFS-RT-Feed ohne strukturelle Stadt-Grenze;
  ``no_data`` bei leerem Redis bleibt das ehrliche Verdict.
Alle uebrigen city-/live-Endpunkte sind flaechendeckend (84/84).
"""

from __future__ import annotations

from infranode.adapters.autobahn import _CITY_ROADS
from infranode.adapters.boris import BORIS_SHAPEFILE, BORIS_WFS
from infranode.adapters.lhp import _CITY_PEGEL
from infranode.adapters.parkendd import PARKENDD_CITIES
from infranode.registry.cities import CITY_REGISTRY

# road-events: gespiegelt aus ``api.v1.cities.CONNECTOR_MAP`` (siehe Modul-Docstring).
# Die Assertion in cities.py haelt diese Liste mit der CONNECTOR_MAP synchron.
_ROAD_EVENTS_CITIES: frozenset[str] = frozenset(
    {"berlin", "koeln", "hamburg", "muenchen", "stuttgart", "bremen"}
)

# sharing (DATA-33): gespiegelt aus ``api.v1.cities.GBFS_SYSTEMS`` (kuratierte
# Nextbike-GBFS-Systeme je Stadt). Wie bei road-events lebt die Quell-Map in
# cities.py (das dieses Modul importiert), daher wird die Slug-Menge hier
# gespiegelt und per Modul-Assertion in cities.py drift-synchron gehalten.
_SHARING_CITIES: frozenset[str] = frozenset(
    {
        "berlin",
        "muenchen",
        "koeln",
        "frankfurt-am-main",
        "duesseldorf",
        "dresden",
        "leipzig",
        "hannover",
        "nuernberg",
        "bremen",
        "braunschweig",
        "freiburg-im-breisgau",
        "karlsruhe",
        "aachen",
        "kassel",
        "wiesbaden",
        "oldenburg",
        "potsdam",
        "bielefeld",
        "moenchengladbach",
        "mannheim",
        "heidelberg",
        "ludwigshafen-am-rhein",
        "hanau",
        "leverkusen",
    }
)

# station-departures/-arrivals (DATA-34/36): NICHT mehr teilabgedeckt. Die Haupt-
# Bahnhof-EVAs je Stadt werden aus dem StaDa-Katalog abgeleitet
# (api.v1.cities._resolve_city_station_evas) -> volle Abdeckung ueber alle 84
# Staedte. Daher kein PARTIAL_COVERAGE-Eintrag (kein not_covered) mehr.

# land-values (DATA-35): BORIS ist pro Bundesland foederiert -> abgedeckt sind
# genau die Register-Staedte, deren Bundesland (``state``) entweder einen offenen
# WFS (``BORIS_WFS``) ODER einen offenen Shapefile-Download (``BORIS_SHAPEFILE``,
# NW/ST) hat. Direkt aus beiden Maps + Register ABGELEITET (kein Duplizieren): ein
# neues Land erweitert die Abdeckung automatisch.
_BORIS_STATES = set(BORIS_WFS) | set(BORIS_SHAPEFILE)
_LAND_VALUES_CITIES: frozenset[str] = frozenset(
    c.slug for c in CITY_REGISTRY if c.state in _BORIS_STATES
)

# solar-roofs (DATA-39): Dach-Solarkataster ist pro Bundesland foederiert (wie
# BORIS). NRW-Pilot aus dem amtlichen Gemeinde-Aggregat (Seed) -> abgedeckt sind
# die Register-Staedte in NRW. Ein weiteres Land erweitert die Abdeckung, sobald
# sein Seed vorliegt (dann hier um das Kuerzel ergaenzen).
_SOLAR_CADASTRE_STATES = {"NW", "BY", "BE", "HH"}
_SOLAR_ROOFS_CITIES: frozenset[str] = frozenset(
    c.slug for c in CITY_REGISTRY if c.state in _SOLAR_CADASTRE_STATES
)

# parking (DATA-40): EIN Parking-Endpunkt mit Quellen-Fallback (Dedup-Prinzip).
# Bevorzugt ParkenDD-Live-Belegung (aus ``adapters.parkendd.PARKENDD_CITIES``
# abgeleitet, 22 Staedte), zusaetzlich Muenchen ueber den statischen CKAN-
# Standortkatalog (Fallback ohne Live-Belegung). Eine neue ParkenDD-Stadt
# erweitert die Abdeckung automatisch.
_PARKING_CITIES: frozenset[str] = frozenset(PARKENDD_CITIES) | {"muenchen"}

# bike-counts (DATA-40): kommunale Radzaehlstellen-Open-Data je Stadt (KEIN
# Eco-Counter: Lizenz ungeklaert, Owner-Entscheidung 2026-06-23). Jede Stadt eine
# eigene, am Ursprung lizenz-verifizierte Quelle. Waechst additiv je integrierter
# Stadt (muss synchron zu ``_resolve_bike_counts_connector`` in api/v1/cities.py
# bleiben).
_BIKE_COUNTS_CITIES: frozenset[str] = frozenset(
    {"muenchen", "leipzig", "hamburg", "berlin", "stuttgart"}
)

# Single source of truth: Endpunkt-Kennung -> abgedeckte Stadt-Slugs.
# Die Kennung entspricht dem letzten Pfadsegment der Route (``/cities/{slug}/<key>``).
PARTIAL_COVERAGE: dict[str, frozenset[str]] = {
    "flood": frozenset(_CITY_PEGEL),
    "webcams": frozenset(_CITY_ROADS),
    "traffic": frozenset(_CITY_ROADS),
    "road-events": _ROAD_EVENTS_CITIES,
    "sharing": _SHARING_CITIES,
    "land-values": _LAND_VALUES_CITIES,
    "solar-roofs": _SOLAR_ROOFS_CITIES,
    "parking": _PARKING_CITIES,
    "bike-counts": _BIKE_COUNTS_CITIES,
}


def is_covered(endpoint: str, slug: str) -> bool:
    """True, wenn ``slug`` fuer ``endpoint`` abgedeckt ist.

    Ein unbekannter ``endpoint`` (nicht teilabgedeckt -> flaechendeckend) gilt
    immer als abgedeckt (fail-open fuer die fully-covered-Endpunkte, die diese
    Karte nie befragen).
    """
    covered = PARTIAL_COVERAGE.get(endpoint)
    if covered is None:
        return True
    return slug in covered


def covered_cities(endpoint: str) -> list[str]:
    """Sortierte Liste der fuer ``endpoint`` abgedeckten Stadt-Slugs.

    Fuer die meta.covered_cities-Ausweisung der ``not_covered``-Antwort. Leer fuer
    einen unbekannten (= flaechendeckenden) Endpunkt.
    """
    return sorted(PARTIAL_COVERAGE.get(endpoint, frozenset()))
