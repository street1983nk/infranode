"""Oeffentliche Per-City-Coverage-Karte der teilabgedeckten Endpunkte.

Ehrlichkeit statt leerer Versprechen (Owner-Entscheidung 2026-06-13): einige
Endpunkte decken nur kuratierte Städte ab. Früher lieferten sie für eine
nicht-abgedeckte Stadt ein leeres ``source_status="ok"`` (sieht aus wie "kein
Ereignis"), was die fehlende Abdeckung verschleiert. Stattdessen weisen die
Routen jetzt ``source_status="not_covered"`` aus (200, ``data: null``) und
nennen im meta-Block die abgedeckten Städte (``covered_cities``). ``not_covered``
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
sichert die Gleichheit beider Listen ab und fängt Drift beim Import hart ab.

NICHT teilabgedeckt (bewusst NICHT in dieser Karte):
- ``water-level``: Geo-Proximity ohne kuratierte Stadt-Map; liefert bei fehlender
  naher Station bereits ehrlich ``no_data`` (dynamisch, deutschlandweit an
  Bundeswasserstraßen).
- ``live/transit/*``: bundesweiter GTFS-RT-Feed ohne strukturelle Stadt-Grenze;
  ``no_data`` bei leerem Redis bleibt das ehrliche Verdict.
Alle übrigen city-/live-Endpunkte sind flächendeckend (84/84).
"""

from __future__ import annotations

from infranode.adapters.autobahn import _CITY_ROADS
from infranode.adapters.baumkataster import BAUM_WFS
from infranode.adapters.boris import BORIS_SHAPEFILE, BORIS_WFS
from infranode.adapters.denkmal import DENKMAL_WFS
from infranode.adapters.lhp import _CITY_PEGEL
from infranode.adapters.parkendd import PARKENDD_CITIES
from infranode.registry.cities import CITY_REGISTRY

# road-events: gespiegelt aus ``api.v1.cities.CONNECTOR_MAP`` (siehe Modul-Docstring).
# Die Assertion in cities.py hält diese Liste mit der CONNECTOR_MAP synchron.
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
# (api.v1.cities._resolve_city_station_evas) -> volle Abdeckung über alle 84
# Städte. Daher kein PARTIAL_COVERAGE-Eintrag (kein not_covered) mehr.

# land-values (DATA-35): BORIS ist pro Bundesland föderiert -> abgedeckt sind
# genau die Register-Städte, deren Bundesland (``state``) entweder einen offenen
# WFS (``BORIS_WFS``) ODER einen offenen Shapefile-Download (``BORIS_SHAPEFILE``,
# NW/ST) hat. Direkt aus beiden Maps + Register ABGELEITET (kein Duplizieren): ein
# neues Land erweitert die Abdeckung automatisch.
_BORIS_STATES = set(BORIS_WFS) | set(BORIS_SHAPEFILE)
_LAND_VALUES_CITIES: frozenset[str] = frozenset(
    c.slug for c in CITY_REGISTRY if c.state in _BORIS_STATES
)

# solar-roofs (DATA-39): Dach-Solarkataster ist pro Bundesland föderiert (wie
# BORIS). NRW-Pilot aus dem amtlichen Gemeinde-Aggregat (Seed) -> abgedeckt sind
# die Register-Städte in NRW. Ein weiteres Land erweitert die Abdeckung, sobald
# sein Seed vorliegt (dann hier um das Kürzel ergänzen).
_SOLAR_CADASTRE_STATES = {"NW", "BY", "BE", "HH"}
_SOLAR_ROOFS_CITIES: frozenset[str] = frozenset(
    c.slug for c in CITY_REGISTRY if c.state in _SOLAR_CADASTRE_STATES
)

# parking (DATA-40): EIN Parking-Endpunkt mit Quellen-Fallback (Dedup-Prinzip).
# Bevorzugt ParkenDD-Live-Belegung (aus ``adapters.parkendd.PARKENDD_CITIES``
# abgeleitet, 22 Städte), zusätzlich München über den statischen CKAN-
# Standortkatalog (Fallback ohne Live-Belegung). Eine neue ParkenDD-Stadt
# erweitert die Abdeckung automatisch.
_PARKING_CITIES: frozenset[str] = frozenset(PARKENDD_CITIES) | {"muenchen"}

# bike-counts (DATA-40): kommunale Radzählstellen-Open-Data je Stadt (KEIN
# Eco-Counter: Lizenz ungeklärt, Owner-Entscheidung 2026-06-23). Jede Stadt eine
# eigene, am Ursprung lizenz-verifizierte Quelle. Wächst additiv je integrierter
# Stadt (muss synchron zu ``_resolve_bike_counts_connector`` in api/v1/cities.py
# bleiben).
_BIKE_COUNTS_CITIES: frozenset[str] = frozenset(
    {"muenchen", "leipzig", "hamburg", "berlin", "stuttgart"}
)

# heritage (DATA-OSM-Tier-2): Denkmallisten sind LANDESsache -> föderiert per WFS
# (wie BORIS/solar-roofs). Abgedeckt sind die Register-Städte, deren Bundesland
# (``state``) einen verifizierten, offen lizenzierten Denkmal-WFS hat
# (``DENKMAL_WFS``). Ein neues Land erweitert die Abdeckung automatisch.
_HERITAGE_STATES = set(DENKMAL_WFS)
_HERITAGE_CITIES: frozenset[str] = frozenset(
    c.slug for c in CITY_REGISTRY if c.state in _HERITAGE_STATES
)

# tree-cadastre (DATA-OSM-Tier-2): Baumkataster sind kommunales Open Data -> per
# Stadt konfiguriert (``BAUM_WFS``). Abgedeckt sind genau die konfigurierten,
# verifiziert offen lizenzierten Städte. Eine neue Stadt erweitert automatisch.
_TREE_CADASTRE_CITIES: frozenset[str] = frozenset(BAUM_WFS)

# district-heating (DATA-41): Fernwärme-/Wärmenetz-Versorgung aus der kommunalen
# Wärmeplanung, föderiert je Stadt-WFS. Die WFS-Registry (``DISTRICT_HEATING_WFS``)
# lebt im PRIVATEN Ingest-Modul (``ingest.district_heating``, kein Public-Export);
# daher wird die Slug-Menge hier gespiegelt (wie road-events/sharing) statt
# importiert, damit der öffentliche Live-Proxy-Code ohne das private Modul lädt. Eine
# Modul-Assertion in ``ingest.district_heating`` hält beide Mengen drift-synchron.
_DISTRICT_HEATING_CITIES: frozenset[str] = frozenset({"berlin", "hamburg"})

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
    "heritage": _HERITAGE_CITIES,
    "tree-cadastre": _TREE_CADASTRE_CITIES,
    "district-heating": _DISTRICT_HEATING_CITIES,
}


def is_covered(endpoint: str, slug: str) -> bool:
    """True, wenn ``slug`` für ``endpoint`` abgedeckt ist.

    Ein unbekannter ``endpoint`` (nicht teilabgedeckt -> flächendeckend) gilt
    immer als abgedeckt (fail-open für die fully-covered-Endpunkte, die diese
    Karte nie befragen).
    """
    covered = PARTIAL_COVERAGE.get(endpoint)
    if covered is None:
        return True
    return slug in covered


def covered_cities(endpoint: str) -> list[str]:
    """Sortierte Liste der für ``endpoint`` abgedeckten Stadt-Slugs.

    Für die meta.covered_cities-Ausweisung der ``not_covered``-Antwort. Leer für
    einen unbekannten (= flächendeckenden) Endpunkt.
    """
    return sorted(PARTIAL_COVERAGE.get(endpoint, frozenset()))
