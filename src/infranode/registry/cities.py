"""Statisches Großstadt-Register als import-zeit-validierte Konstante (CORE-03).

EXPANSION 2026-06: 28 handverifizierte Kern-Städte (``_CORE_REGISTRY``,
``coverage="full"``, unten als Literale) + alle weiteren deutschen Großstädte
über 100.000 EW (``coverage="auto"``, maschinengeneriert aus Wikidata via
scripts/generate_registry.py, geladen aus data/seeds/registry_extended.json).
Die ``auto``-Städte werden NUR von den AGS-/geo-automatischen Tier-A-Quellen
bedient; hand-kuratierte Quellen liefern für sie ehrliches no_data.


Werte (slug/name_de/state/is_state_capital/qid/osm_relation) stammen direkt aus
der SPARQL-verifizierten Tabelle in 02-RESEARCH.md (Wikidata P402/P1082, Stand
2026-06-08). Verletzt ein Eintrag das Schema, schlägt bereits der Import (und
damit jeder Test) fehl. Die 16 Landeshauptstädte tragen
``is_state_capital=True``. Koordinaten sind plausible Stadtzentren.

``ags`` ist der amtliche 8-stellige Gemeindeschlüssel (ARCH-02,
dim_city-Join-Anker). Für kreisfreie Städte gilt: 8-stelliger AGS =
5-stelliger Stadt-Präfix (aus ingest/delfi.py AGS_TO_SLUG) + "000". Alle 28 ags
sind gegen die amtliche GENESIS-Quelle (regionalstatistik.de, Tabelle
12411-01-01-4, Stand 2022) verifiziert; Berlin/Hamburg als Stadtstaaten auf
Länder-Ebene (AGS 11000000/02000000), die übrigen als kreisfreie Städte.
"""

from __future__ import annotations

import json

from infranode.infra.seeds import seeds_dir
from infranode.normalization import GeoPoint
from infranode.registry.models import CityRegistryEntry

_CORE_REGISTRY: tuple[CityRegistryEntry, ...] = (
    CityRegistryEntry(
        slug="berlin",
        name_de="Berlin",
        state="BE",
        ags="11000000",  # verifiziert
        is_state_capital=True,
        qid="Q64",
        osm_relation=62422,
        geo=GeoPoint(lat=52.52, lon=13.405),
        population=3782202,
    ),
    CityRegistryEntry(
        slug="hamburg",
        name_de="Hamburg",
        state="HH",
        ags="02000000",  # verifiziert
        is_state_capital=True,
        qid="Q1055",
        osm_relation=62782,
        geo=GeoPoint(lat=53.5511, lon=9.9937),
        population=1910160,
    ),
    CityRegistryEntry(
        slug="muenchen",
        name_de="München",
        state="BY",
        ags="09162000",  # verifiziert
        is_state_capital=True,
        qid="Q1726",
        osm_relation=62428,
        geo=GeoPoint(lat=48.1374, lon=11.5755),
        population=1510378,
    ),
    CityRegistryEntry(
        slug="koeln",
        name_de="Köln",
        state="NW",
        ags="05315000",  # verifiziert
        is_state_capital=False,
        qid="Q365",
        osm_relation=62578,
        geo=GeoPoint(lat=50.9375, lon=6.9603),
        population=1087353,
    ),
    CityRegistryEntry(
        slug="frankfurt-am-main",
        name_de="Frankfurt am Main",
        state="HE",
        ags="06412000",  # verifiziert
        is_state_capital=False,
        qid="Q1794",
        osm_relation=62400,
        geo=GeoPoint(lat=50.1109, lon=8.6821),
        population=775790,
    ),
    CityRegistryEntry(
        slug="stuttgart",
        name_de="Stuttgart",
        state="BW",
        ags="08111000",  # verifiziert
        is_state_capital=True,
        qid="Q1022",
        osm_relation=2793104,
        geo=GeoPoint(lat=48.7758, lon=9.1829),
        population=633484,
    ),
    CityRegistryEntry(
        slug="duesseldorf",
        name_de="Düsseldorf",
        state="NW",
        ags="05111000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=True,
        qid="Q1718",
        osm_relation=62539,
        geo=GeoPoint(lat=51.2277, lon=6.7735),
        population=631217,
    ),
    CityRegistryEntry(
        slug="leipzig",
        name_de="Leipzig",
        state="SN",
        ags="14713000",  # verifiziert
        is_state_capital=False,
        qid="Q2079",
        osm_relation=62649,
        geo=GeoPoint(lat=51.3397, lon=12.3731),
        population=619879,
    ),
    CityRegistryEntry(
        slug="dortmund",
        name_de="Dortmund",
        state="NW",
        ags="05913000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=False,
        qid="Q1295",
        osm_relation=1829065,
        geo=GeoPoint(lat=51.5136, lon=7.4653),
        population=595471,
    ),
    CityRegistryEntry(
        slug="essen",
        name_de="Essen",
        state="NW",
        ags="05113000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=False,
        qid="Q2066",
        osm_relation=62713,
        geo=GeoPoint(lat=51.4556, lon=7.0116),
        population=586608,
    ),
    CityRegistryEntry(
        slug="bremen",
        name_de="Bremen",
        state="HB",
        ags="04011000",  # verifiziert
        is_state_capital=True,
        qid="Q24879",
        osm_relation=62559,
        geo=GeoPoint(lat=53.0793, lon=8.8017),
        population=577026,
    ),
    CityRegistryEntry(
        slug="dresden",
        name_de="Dresden",
        state="SN",
        ags="14612000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=True,
        qid="Q1731",
        osm_relation=191645,
        geo=GeoPoint(lat=51.0504, lon=13.7373),
        population=566222,
    ),
    CityRegistryEntry(
        slug="hannover",
        name_de="Hannover",
        state="NI",
        # [VERIFIED Wikidata P439, 2026-06-10] Stadt Hannover = 03241001; der
        # frühere Wert 03241000 war Region-Hannover-Kreis + "000" (existiert
        # nicht als Gemeinde) -> /energy und GENESIS liefen für Hannover leer.
        ags="03241001",
        is_state_capital=True,
        qid="Q1715",
        osm_relation=59418,
        geo=GeoPoint(lat=52.3759, lon=9.732),
        population=548186,
    ),
    CityRegistryEntry(
        slug="nuernberg",
        name_de="Nürnberg",
        state="BY",
        ags="09564000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=False,
        qid="Q2090",
        osm_relation=62780,
        geo=GeoPoint(lat=49.4521, lon=11.0767),
        population=526091,
    ),
    CityRegistryEntry(
        slug="duisburg",
        name_de="Duisburg",
        state="NW",
        ags="05112000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=False,
        qid="Q2100",
        osm_relation=62456,
        geo=GeoPoint(lat=51.4344, lon=6.7623),
        population=503707,
    ),
    CityRegistryEntry(
        slug="bochum",
        name_de="Bochum",
        state="NW",
        ags="05911000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=False,
        qid="Q2103",
        osm_relation=62644,
        geo=GeoPoint(lat=51.4818, lon=7.2162),
        population=366385,
    ),
    CityRegistryEntry(
        slug="wuppertal",
        name_de="Wuppertal",
        state="NW",
        ags="05124000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=False,
        qid="Q2107",
        osm_relation=62478,
        geo=GeoPoint(lat=51.2562, lon=7.1508),
        population=358938,
    ),
    CityRegistryEntry(
        slug="bielefeld",
        name_de="Bielefeld",
        state="NW",
        ags="05711000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=False,
        qid="Q2112",
        osm_relation=62646,
        geo=GeoPoint(lat=52.0302, lon=8.5325),
        population=338410,
    ),
    CityRegistryEntry(
        slug="bonn",
        name_de="Bonn",
        state="NW",
        ags="05314000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=False,
        qid="Q586",
        osm_relation=62508,
        geo=GeoPoint(lat=50.7374, lon=7.0982),
        population=335789,
    ),
    CityRegistryEntry(
        slug="muenster",
        name_de="Münster",
        state="NW",
        ags="05515000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=False,
        qid="Q2742",
        osm_relation=62591,
        geo=GeoPoint(lat=51.9607, lon=7.6261),
        population=322904,
    ),
    CityRegistryEntry(
        slug="wiesbaden",
        name_de="Wiesbaden",
        state="HE",
        ags="06414000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=True,
        qid="Q1721",
        osm_relation=62496,
        geo=GeoPoint(lat=50.0826, lon=8.24),
        population=285522,
    ),
    CityRegistryEntry(
        slug="kiel",
        name_de="Kiel",
        state="SH",
        ags="01002000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=True,
        qid="Q1707",
        osm_relation=27021,
        geo=GeoPoint(lat=54.3233, lon=10.1228),
        population=248873,
    ),
    CityRegistryEntry(
        slug="mainz",
        name_de="Mainz",
        state="RP",
        ags="07315000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=True,
        qid="Q1720",
        osm_relation=62630,
        geo=GeoPoint(lat=49.9929, lon=8.2473),
        population=222889,
    ),
    CityRegistryEntry(
        slug="magdeburg",
        name_de="Magdeburg",
        state="ST",
        ags="15003000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=True,
        qid="Q1733",
        osm_relation=62481,
        geo=GeoPoint(lat=52.1205, lon=11.6276),
        population=240114,
    ),
    CityRegistryEntry(
        slug="erfurt",
        name_de="Erfurt",
        state="TH",
        ags="16051000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=True,
        qid="Q1729",
        osm_relation=62745,
        geo=GeoPoint(lat=50.9787, lon=11.0328),
        population=215199,
    ),
    CityRegistryEntry(
        slug="potsdam",
        name_de="Potsdam",
        state="BB",
        ags="12054000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=True,
        qid="Q1711",
        osm_relation=62369,
        geo=GeoPoint(lat=52.3906, lon=13.0645),
        population=187119,
    ),
    CityRegistryEntry(
        slug="saarbruecken",
        name_de="Saarbrücken",
        state="SL",
        # [VERIFIED Wikidata P439, 2026-06-10] Landeshauptstadt Saarbrücken =
        # 10041100; der frühere Wert 10041000 war Regionalverband-Kreis + "000".
        ags="10041100",
        is_state_capital=True,
        qid="Q1724",
        osm_relation=1187159,
        geo=GeoPoint(lat=49.2402, lon=6.9969),
        population=183509,
    ),
    CityRegistryEntry(
        slug="schwerin",
        name_de="Schwerin",
        state="MV",
        ags="13004000",  # verifiziert (GENESIS 12411-01-01-4, 2022)
        is_state_capital=True,
        qid="Q1709",
        osm_relation=62685,
        geo=GeoPoint(lat=53.6355, lon=11.4012),
        population=98733,
    ),
)


def _load_extended() -> tuple[CityRegistryEntry, ...]:
    """Laedt die maschinengenerierten >100k-EW-Städte (coverage="auto").

    Quelle: data/seeds/registry_extended.json (committet, aus Wikidata via
    scripts/generate_registry.py). Beim Import gegen ``CityRegistryEntry``
    validiert (Import schlägt fehl, wenn das JSON das Schema verletzt). QIDs der
    Kern-Städte werden defensiv ausgefiltert (Kern hat Vorrang, keine Dubletten).
    Fehlt die Datei, bleibt es beim Kern-Register (Graceful Degradation).

    Der Seed-Pfad wird über ``seeds_dir()`` aufgelöst (respektiert
    ``INFRANODE_SEEDS_DIR``, Live-Report M1): im Prod-Container liegen die Seeds
    unter ``/app/seeds`` (Named-Volume-Schatten auf ``/app/data``), sonst fehlten
    56 der 84 ``auto``-Städte aus registry_extended.json.
    """
    path = seeds_dir() / "registry_extended.json"
    if not path.exists():
        return ()
    core_qids = {c.qid for c in _CORE_REGISTRY}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        CityRegistryEntry(**entry) for entry in raw if entry.get("qid") not in core_qids
    )


# Vollregister: 28 handverifizierte Kern-Städte (coverage="full") + alle weiteren
# Großstädte >100k EW (coverage="auto", maschinengeneriert). Reihenfolge:
# Kern zuerst (stabil), dann die erweiterten alphabetisch.
CITY_REGISTRY: tuple[CityRegistryEntry, ...] = _CORE_REGISTRY + _load_extended()

# Modul-Index für O(1)-Lookup (statisch, keine Laufzeit-Quelle).
_BY_SLUG: dict[str, CityRegistryEntry] = {c.slug: c for c in CITY_REGISTRY}
