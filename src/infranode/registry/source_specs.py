"""Deklarative Quellen-Registry: EINE Stelle pro Upstream-Quelle.

Single source of truth fuer die rein-datenhaften Quellen-Attribute, die
frueher auf vier Strukturen verteilt waren:
  * KNOWN_SOURCES        (vorher api/v1/sources.py:_KNOWN_SOURCES)
  * SOURCE_LICENSE       (vorher api/v1/sources.py:SOURCE_LICENSE)
  * SOURCE_TTL           (vorher resilience/client.py:_SOURCE_TTL)
  * FRAGILE_SOURCE_COOLDOWN (vorher resilience/breaker_redis.py)

Eine neue Quelle hinzufuegen = EIN SourceSpec-Eintrag hier (plus weiterhin:
der enable_<name>-Toggle in config.py, der SourceId-Wert in enums.py, der
Adapter/Mapper-Code und die wortgenaue Zeile in DATA-LICENSES.md). Die
Lizenz-Wortlaute bleiben fail-closed gegen DATA-LICENSES.md geprueft
(tests/unit/test_source_license_map.py); die Reihenfolge hier IST die
oeffentliche Reihenfolge der /sources-Route.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    """Eine Upstream-Quelle, deklarativ.

    Args:
        name: Quellen-Schluessel; MUSS exakt zum enable_<name>-Toggle
            (config.py) und zum SourceId-Wert (enums.py) passen.
        license_id: Lizenz-Kuerzel (siehe LicenseId/DATA-LICENSES.md).
        attribution: wortgenaue Attribution VERBATIM aus DATA-LICENSES.md.
        ttl: (fresh_s, stale_s) Cache-Fenster; None = Default (60s/120s).
        cooldown: HALF_OPEN-Probe-Intervall (s) fuer fragile Upstreams;
            None = 30s-Default des Breakers.
    """

    name: str
    license_id: str
    attribution: str
    ttl: tuple[float, float] | None = None
    cooldown: float | None = None


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(name="wikidata", license_id="cc0", attribution="Wikidata"),
    SourceSpec(
        name="openaq",
        license_id="unknown",
        attribution="OpenAQ",
        ttl=(900.0, 21600.0),
        cooldown=900.0,
    ),
    SourceSpec(
        name="dwd",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
        ttl=(600.0, 7200.0),
    ),
    SourceSpec(
        name="overpass",
        license_id="odbl",
        attribution="© OpenStreetMap contributors",
        ttl=(86400.0, 604800.0),
    ),
    SourceSpec(
        name="autobahn",
        license_id="dl_de_by_2_0",
        attribution="Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
    ),
    SourceSpec(
        name="hvv",
        license_id="dl_de_by_2_0",
        attribution="Hamburger Verkehrsverbund GmbH (HVV)",
    ),
    SourceSpec(
        name="delfi",
        license_id="cc_by_4_0",
        attribution="Datenquelle: DELFI e.V. / Mobilitätsdaten Deutschland, CC-BY 4.0",
    ),
    SourceSpec(
        name="bnetza", license_id="cc_by_4_0", attribution="Bundesnetzagentur.de"
    ),
    SourceSpec(
        name="uba",
        license_id="dl_de_by_2_0",
        attribution="Umweltbundesamt (UBA)",
        cooldown=900.0,
    ),
    SourceSpec(
        name="pegelonline",
        license_id="dl_de_zero_2_0",
        attribution=(
            "PEGELONLINE, Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV)"
        ),
        ttl=(300.0, 7200.0),
        cooldown=600.0,
    ),
    SourceSpec(
        name="lhp",
        license_id="cc_by_4_0",
        attribution="Datenquelle: www.hochwasserzentralen.de, Stand: <Zeitstempel>",
    ),
    SourceSpec(
        name="dwd_pollen",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
    ),
    SourceSpec(
        name="genesis",
        license_id="dl_de_by_2_0",
        attribution="Statistisches Bundesamt (Destatis) / Regionalstatistik",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="zensus",
        license_id="dl_de_by_2_0",
        attribution="Statistisches Bundesamt (Destatis) / Regionalstatistik",
    ),
    SourceSpec(
        name="mastr",
        license_id="dl_de_by_2_0",
        attribution="Bundesnetzagentur - Marktstammdatenregister",
    ),
    SourceSpec(
        name="smard", license_id="cc_by_4_0", attribution="Bundesnetzagentur | SMARD.de"
    ),
    SourceSpec(
        name="dwd_warnings",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst",
    ),
    SourceSpec(
        name="kba", license_id="dl_de_by_2_0", attribution="Kraftfahrt-Bundesamt (KBA)"
    ),
    SourceSpec(
        name="unfallatlas",
        license_id="dl_de_by_2_0",
        attribution="Statistische Ämter des Bundes und der Länder, Unfallatlas",
    ),
    SourceSpec(
        name="inkar",
        license_id="dl_de_by_2_0",
        attribution="Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR), INKAR",
    ),
    SourceSpec(
        name="tankerkoenig",
        license_id="cc_by_4_0",
        attribution="Tankerkoenig (creativecommons.tankerkoenig.de), MTS-K",
    ),
    SourceSpec(name="gbfs", license_id="cc0", attribution="nextbike GmbH / GBFS (CC0)"),
    SourceSpec(
        name="db_timetables", license_id="cc_by_4_0", attribution="Deutsche Bahn AG"
    ),
    SourceSpec(
        name="boris",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Bodenrichtwerte",
    ),
    SourceSpec(
        name="stada",
        license_id="cc_by_4_0",
        attribution="Deutsche Bahn AG",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="regionalstatistik",
        license_id="dl_de_by_2_0",
        attribution="Statistische Ämter des Bundes und der Länder",
    ),
    SourceSpec(
        name="bkg",
        license_id="dl_de_by_2_0",
        attribution="(c) GeoBasis-DE / BKG (Jahr)",
    ),
    SourceSpec(
        name="bundeswahl",
        license_id="dl_de_by_2_0",
        attribution="Die Bundeswahlleiterin",
    ),
    SourceSpec(
        name="divi",
        license_id="cc_by_4_0",
        attribution="Robert Koch-Institut (RKI), DIVI-Intensivregister, Stand: <datum>",
    ),
    SourceSpec(
        name="feiertage",
        license_id="gemeinfrei",
        attribution="Feiertage und Schulferien je Bundesland, gemeinfrei",
    ),
    SourceSpec(
        name="berlin_viz",
        license_id="dl_de_by_2_0",
        attribution="Verkehrsinformationszentrale Berlin (VIZ)",
    ),
    SourceSpec(
        name="hamburg_baustellen",
        license_id="dl_de_by_2_0",
        attribution="Freie und Hansestadt Hamburg",
        cooldown=1800.0,
    ),
    SourceSpec(
        name="koeln_verkehr", license_id="dl_de_zero_2_0", attribution="Stadt Köln"
    ),
    SourceSpec(
        name="muenchen_baustellen",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
    ),
    SourceSpec(
        name="mobidata_bw",
        license_id="dl_de_by_2_0",
        attribution="Verkehrsministerium Baden-Württemberg / MobiData BW",
    ),
    SourceSpec(
        name="autobahn_webcam",
        license_id="dl_de_by_2_0",
        attribution="Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
    ),
    SourceSpec(
        name="destination_one", license_id="mixed", attribution="destination.one"
    ),
    SourceSpec(
        name="koeln_events", license_id="dl_de_zero_2_0", attribution="Stadt Köln"
    ),
    SourceSpec(
        name="koeln_traffic_flow", license_id="dl_de_zero_2_0", attribution="Stadt Köln"
    ),
    SourceSpec(
        name="koeln_baustellen_live",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
    ),
    SourceSpec(
        name="koeln_ereignisse_live",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
    ),
    SourceSpec(
        name="koeln_lez_live", license_id="dl_de_zero_2_0", attribution="Stadt Köln"
    ),
    SourceSpec(
        name="berlin_verkehrsmeldungen",
        license_id="dl_de_by_2_0",
        attribution=(
            "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt (SenMVKU)"
        ),
    ),
    SourceSpec(
        name="dortmund_parking",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Dortmund",
    ),
    SourceSpec(
        name="kiel_zaehlstellen",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt Kiel",
    ),
    SourceSpec(
        name="eround_charging",
        license_id="cc0",
        attribution="Hamburger Energienetze GmbH / eRound",
    ),
    SourceSpec(
        name="frankfurt_parking",
        license_id="dl_de_by_2_0",
        attribution="Stadt Frankfurt am Main",
    ),
    SourceSpec(
        name="wuppertal_parking",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Wuppertal",
    ),
    SourceSpec(
        name="bremen_baustellen",
        license_id="dl_de_by_2_0",
        attribution="Freie Hansestadt Bremen",
    ),
    SourceSpec(
        name="hannover_verkehrsmeldungen",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt Hannover",
    ),
    SourceSpec(name="gtfs_rt", license_id="cc_by_sa_4_0", attribution="gtfs.de"),
    SourceSpec(
        name="hvv_geofox",
        license_id="unknown",
        attribution="Hamburger Verkehrsverbund GmbH (HVV) / Geofox",
    ),
    SourceSpec(
        name="vgn",
        license_id="cc_by_4_0",
        attribution="Verkehrs-Aktiengesellschaft Nürnberg (VAG) / VGN",
    ),
    SourceSpec(
        name="hamburg_verkehrslage",
        license_id="dl_de_by_2_0",
        attribution="Freie und Hansestadt Hamburg",
        cooldown=1800.0,
    ),
    SourceSpec(
        name="solar",
        license_id="ec_reuse",
        attribution="PVGIS © European Communities, 2001-2026",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="solar_cadastre",
        license_id="dl_de_zero_2_0",
        attribution="Land NRW / GeoBasis NRW / LANUK (MaStR), Solarkataster NRW",
    ),
    SourceSpec(
        name="muenchen_parkhaeuser",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="muenchen_radzaehl",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="leipzig_radzaehl",
        license_id="dl_de_by_2_0",
        attribution="Stadt Leipzig",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="hamburg_radzaehl",
        license_id="dl_de_by_2_0",
        attribution=(
            "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende"
        ),
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="berlin_radzaehl",
        license_id="dl_de_zero_2_0",
        attribution=(
            "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt Berlin"
        ),
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="stuttgart_radzaehl",
        license_id="cc_by_4_0",
        attribution="Landeshauptstadt Stuttgart",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="parkendd",
        license_id="unknown",
        attribution="ParkenDD",
        ttl=(300.0, 3600.0),
    ),
)

# --- Abgeleitete Sichten (Rueckwaerts-kompatibel zu den alten Strukturen) ---
KNOWN_SOURCES: tuple[str, ...] = tuple(s.name for s in SOURCE_SPECS)

SOURCE_LICENSE: dict[str, dict[str, str]] = {
    s.name: {"license_id": s.license_id, "attribution": s.attribution}
    for s in SOURCE_SPECS
}

SOURCE_TTL: dict[str, tuple[float, float]] = {
    s.name: s.ttl for s in SOURCE_SPECS if s.ttl is not None
}

FRAGILE_SOURCE_COOLDOWN: dict[str, float] = {
    s.name: s.cooldown for s in SOURCE_SPECS if s.cooldown is not None
}
