"""Stadt-Routen über das Register + Wikidata-Stammdaten-Slice.

Macht den 404-Pfad end-to-end sichtbar: ``GET /cities/{slug}`` ruft
``get_city`` auf; ein unbekannter Slug wirft ``NotFoundError``, das der zentrale
Exception-Handler auf den 404-Envelope mit Hint mappt (KEINE eigene
HTTPException/try-except hier).

``GET /cities/{slug}/base`` (DATA-01/06, API-01, GOV-01, DX-06) verdrahtet
die vertikale Wikidata-Slice end-to-end: Register-Lookup -> ResilientSourceClient-
Fassade (Cache/SWR/Single-Flight/Breaker) mit dem keylosen Adapter als ``fetch_fn``
-> Register-Geo-Fallback (verhindert GeoPoint-ValidationError bei fehlendem P625)
-> Mapper -> kanonischer Daten-Envelope mit Attribution.
Graceful Degradation: deaktivierte Quelle liefert 200 mit ``source_status``
``disabled`` (DATA-06, nie 5xx); toter Upstream ohne Cache liefert 503 mit
selbst-korrigierendem Hint, der ``GET /api/v1/health`` nennt (DX-06).
"""

from __future__ import annotations

import asyncio
import math
import os
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, NamedTuple

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Request, Response

from infranode.adapters.aachen_parking import fetch_aachen_parking
from infranode.adapters.autobahn import fetch_traffic, fetch_webcams
from infranode.adapters.baumkataster import fetch_trees
from infranode.adapters.bbk_nina import ars_for_ags, fetch_for_ags
from infranode.adapters.berlin_radzaehl import fetch_berlin_bike_counts
from infranode.adapters.berlin_viz import fetch_berlin_road_events
from infranode.adapters.db_fasta import fetch_station_facilities
from infranode.adapters.db_timetables import (
    fetch_station_arrivals,
    fetch_station_departures,
)
from infranode.adapters.denkmal import fetch_heritage
from infranode.adapters.destination_one import fetch_events
from infranode.adapters.dortmund_baustellen import fetch_dortmund_road_events
from infranode.adapters.dortmund_parking import fetch_dortmund_parking
from infranode.adapters.duesseldorf_radzaehl import fetch_duesseldorf_bike_counts
from infranode.adapters.dwd import fetch_weather
from infranode.adapters.dwd_fire import fetch_fire_danger
from infranode.adapters.dwd_pollen import fetch_pollen_uv
from infranode.adapters.dwd_warnings import fetch_dwd_warnings
from infranode.adapters.eea_bathing import fetch_bathing_water
from infranode.adapters.essen_radzaehl import fetch_essen_bike_counts
from infranode.adapters.gbfs import GbfsSystem, fetch_sharing
from infranode.adapters.genesis import (
    fetch_demographics,
    fetch_genesis_table,
    fetch_hospitals,
)
from infranode.adapters.hamburg_parking import fetch_hamburg_parking
from infranode.adapters.hamburg_radzaehl import fetch_hamburg_bike_counts
from infranode.adapters.hamburg_transparenz import fetch_hamburg_road_events
from infranode.adapters.kaiserslautern_parking import fetch_kaiserslautern_parking
from infranode.adapters.karlsruhe_parking import fetch_karlsruhe_parking
from infranode.adapters.klinik_atlas import fetch_hospital_atlas
from infranode.adapters.koeln_arcgis import fetch_koeln_road_events
from infranode.adapters.koeln_events import fetch_events as fetch_koeln_events
from infranode.adapters.koeln_radzaehl import fetch_koeln_bike_counts
from infranode.adapters.koeln_wartezeiten import fetch_koeln_wait_times
from infranode.adapters.leipzig_radzaehl import fetch_leipzig_bike_counts
from infranode.adapters.lhp import fetch_flood
from infranode.adapters.mobidata_bw import fetch_mobidata_road_events
from infranode.adapters.mobidata_parkapi import fetch_mobidata_parking
from infranode.adapters.mobilithek_datex2 import (
    fetch_datex2,
    fetch_koeln_parking,
    fetch_magdeburg_parking,
    fetch_wuppertal_parking,
)
from infranode.adapters.mobilithek_datex3 import fetch_frankfurt_parking
from infranode.adapters.muenchen_opendata import (
    fetch_muenchen_parking,
    fetch_muenchen_road_events,
)
from infranode.adapters.muenchen_radzaehl import fetch_muenchen_bike_counts
from infranode.adapters.muenchen_ruhver import (
    fetch_muenchen_bike_parking,
    fetch_muenchen_mobility_points,
    fetch_muenchen_park_and_ride,
    fetch_muenchen_parking_onstreet,
)
from infranode.adapters.muenster_parking import fetch_muenster_parking
from infranode.adapters.oldenburg_parking import fetch_oldenburg_parking
from infranode.adapters.overpass import (
    _ALLOWED_TYPES,
    _OSM_FEATURES,
)
from infranode.adapters.parkendd import fetch_parkendd
from infranode.adapters.pegelonline import fetch_water_level
from infranode.adapters.rostock_baustellen import fetch_rostock_road_events
from infranode.adapters.smard import fetch_smard
from infranode.adapters.solar import fetch_solar
from infranode.adapters.sperrinfosys import fetch_sperrinfosys_road_events
from infranode.adapters.stada import fetch_all_stations
from infranode.adapters.stuttgart_radzaehl import fetch_stuttgart_bike_counts
from infranode.adapters.tankerkoenig import fetch_fuel_prices
from infranode.adapters.uba import fetch_air_uba
from infranode.adapters.wikidata import fetch_city_base, fetch_hospitals_wikidata
from infranode.adapters.zensus_grid import fetch_population_density
from infranode.api.errors import (
    NotFoundError,
    UnprocessableError,
    UpstreamError,
    ValidationFailedError,
)
from infranode.api.v1.pagination import (
    _parse_int_param,
    paginate,
    paginate_envelope,
    parse_page_params,
)
from infranode.archive.bka_pks_db import read_crime_stats
from infranode.archive.boris_db import read_land_values
from infranode.archive.council_db import count_council_papers, read_council_papers
from infranode.archive.inkar_db import read_indicators
from infranode.archive.kba_db import read_vehicle_registrations
from infranode.archive.mastr_db import read_energy
from infranode.archive.osm_pois_db import count_pois, read_pois
from infranode.archive.regionalstatistik_db import (
    read_business_registrations,
    read_insolvencies,
    read_tax_rates,
)
from infranode.archive.store import append_record, read_records
from infranode.archive.tender_db import read_public_tenders, search_public_tenders
from infranode.archive.transit_store import read_stops
from infranode.archive.unfallatlas_db import read_accidents
from infranode.archive.wegweiser_db import read_series
from infranode.charging.geomap import load_city_points
from infranode.charging.store import get_point_statuses
from infranode.config import Settings
from infranode.infra.cache import build_cache_key
from infranode.infra.demand_queue import enqueue as enqueue_demand
from infranode.normalization.enums import SourceId
from infranode.normalization.mappers.autobahn import (
    map_autobahn_traffic,
    map_autobahn_webcams,
)
from infranode.normalization.mappers.baumkataster import map_trees
from infranode.normalization.mappers.bbk_nina import map_bbk_nina
from infranode.normalization.mappers.berlin_viz import map_berlin_road_events
from infranode.normalization.mappers.bike_counts import (
    map_berlin_bike_counts,
    map_duesseldorf_bike_counts,
    map_essen_bike_counts,
    map_hamburg_bike_counts,
    map_koeln_bike_counts,
    map_leipzig_bike_counts,
    map_stuttgart_bike_counts,
)
from infranode.normalization.mappers.bka_pks import map_crime_stats
from infranode.normalization.mappers.boris import map_land_values
from infranode.normalization.mappers.db_bahnpark import map_db_bahnpark
from infranode.normalization.mappers.db_fasta import map_station_facilities
from infranode.normalization.mappers.db_timetables import (
    map_station_arrivals,
    map_station_departures,
)
from infranode.normalization.mappers.denkmal import map_heritage
from infranode.normalization.mappers.destination_one import (
    map_destination_one_events,
)
from infranode.normalization.mappers.dortmund_baustellen import (
    map_dortmund_road_events,
)
from infranode.normalization.mappers.dwd import map_weather
from infranode.normalization.mappers.dwd_fire import map_fire_danger
from infranode.normalization.mappers.dwd_pollen import map_pollen_uv
from infranode.normalization.mappers.dwd_warnings import map_dwd_warnings
from infranode.normalization.mappers.eea_bathing import map_bathing_water
from infranode.normalization.mappers.gbfs import map_sharing
from infranode.normalization.mappers.genesis import (
    map_demographics,
    map_population_demographics,
    map_regional_stat,
)
from infranode.normalization.mappers.hamburg_transparenz import map_hamburg_road_events
from infranode.normalization.mappers.holidays import load_holidays, map_holidays
from infranode.normalization.mappers.hospital import (
    map_hospital,
    map_hospital_wikidata,
)
from infranode.normalization.mappers.inkar import map_indicators
from infranode.normalization.mappers.kba import map_vehicle_registrations
from infranode.normalization.mappers.klinik_atlas import map_hospital_atlas
from infranode.normalization.mappers.koeln_arcgis import map_koeln_road_events
from infranode.normalization.mappers.koeln_events import map_koeln_events
from infranode.normalization.mappers.koeln_wartezeiten import map_koeln_wait_times
from infranode.normalization.mappers.lhp import map_flood
from infranode.normalization.mappers.mastr import map_mastr_assets
from infranode.normalization.mappers.mobidata_bw import map_mobidata_road_events
from infranode.normalization.mappers.mobidata_parkapi import map_mobidata_parking
from infranode.normalization.mappers.mobilithek_afir import map_city_charging_status
from infranode.normalization.mappers.mobilithek_bremen import map_bremen_road_events
from infranode.normalization.mappers.mobilithek_parken import (
    map_dortmund_parking,
    map_frankfurt_parking,
    map_koeln_parking,
    map_magdeburg_parking,
    map_wuppertal_parking,
)
from infranode.normalization.mappers.muenchen_opendata import (
    map_muenchen_parking,
    map_muenchen_road_events,
)
from infranode.normalization.mappers.muenchen_radzaehl import map_muenchen_bike_counts
from infranode.normalization.mappers.muenchen_ruhver import (
    map_muenchen_bike_parking,
    map_muenchen_mobility_points,
    map_muenchen_park_and_ride,
    map_muenchen_parking_onstreet,
)
from infranode.normalization.mappers.oparl import (
    COUNCIL_CITY_LICENSE,
    COVERED_COUNCIL_CITIES,
)
from infranode.normalization.mappers.overpass import map_osm_feature, map_overpass_pois
from infranode.normalization.mappers.parkendd import map_parkendd
from infranode.normalization.mappers.pegelonline import map_water_level
from infranode.normalization.mappers.regionalstatistik import (
    map_business_registrations,
    map_insolvencies,
    map_tax_rates,
)
from infranode.normalization.mappers.rostock_baustellen import (
    map_rostock_road_events,
)
from infranode.normalization.mappers.smard import map_smard
from infranode.normalization.mappers.solar import map_solar
from infranode.normalization.mappers.solar_cadastre import (
    load_solar_roofs,
    map_solar_roofs,
)
from infranode.normalization.mappers.sperrinfosys import (
    map_sperrinfosys_road_events,
)
from infranode.normalization.mappers.stada import map_station_catalog
from infranode.normalization.mappers.stadt_parking import (
    map_aachen_parking,
    map_hamburg_parking,
    map_muenster_parking,
    map_oldenburg_parking,
)
from infranode.normalization.mappers.stadt_parking_b import (
    map_kaiserslautern_parking,
    map_karlsruhe_parking,
)
from infranode.normalization.mappers.tankerkoenig import map_fuel_prices
from infranode.normalization.mappers.uba import map_air_uba
from infranode.normalization.mappers.unfallatlas import map_accidents
from infranode.normalization.mappers.wegweiser import (
    dataset_indicators,
    map_indicator_series,
)
from infranode.normalization.mappers.wikidata import map_wikidata_city
from infranode.normalization.mappers.zensus_grid import map_population_density
from infranode.parking.db_bahnpark_store import load_db_bahnpark
from infranode.registry import get_city, list_cities
from infranode.registry.catalog import CITY_DATA_CATALOG
from infranode.registry.coverage import PARTIAL_COVERAGE, covered_cities, is_covered
from infranode.registry.source_specs import SOURCE_LICENSE
from infranode.resilience.client import retry_after_s
from infranode.resilience.types import CacheStatus

router = APIRouter()


def _not_covered(endpoint: str) -> dict:
    """Baut die ehrliche ``not_covered``-Antwort eines teilabgedeckten Endpunkts.

    Owner-Entscheidung 2026-06-13: eine nicht-abgedeckte Stadt liefert KEIN leeres
    ``ok`` (verschleiert die fehlende Abdeckung) und KEIN 404 (das ist "Stadt
    unbekannt"), sondern 200 mit ``source_status="not_covered"``, ``data: null``
    und der Liste der abgedeckten Städte (``meta.covered_cities``), klar
    unterscheidbar von ``no_data`` (abgedeckt, aktuell aber keine Daten).
    """
    return {
        "data": None,
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "not_covered",
            "covered_cities": covered_cities(endpoint),
        },
    }


def _mark_deprecated(response: Response, successor: str) -> None:
    """Markiert einen Altpfad als deprecated (LIVE-03, Phase 20).

    Setzt den ``Deprecation``-Header (RFC 8594, Wert ``"true"``) und einen
    ``Link``-Header auf den /live-Nachfolger (``rel="successor-version"``). Eine
    Quelle der Wahrheit (REST-Regel 6): die Logik/der Envelope der Altpfade bleibt
    UNVERÄNDERT (kein Breaking Change), es kommen nur die beiden Hinweis-Header
    hinzu. Wird ausschließlich von den Bestands-Live-Handlern aufgerufen; die
    /live-Alias-Wrapper übergeben eine Wegwerf-Response, sodass der Header dort
    NICHT landet (der /live-Pfad ist der Nachfolger, nicht der deprecated Altpfad).
    """
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = f'<{successor}>; rel="successor-version"'


# Connector-Registry der /road-events-Route (DATA-15): Stadt-Slug -> (source,
# fetch_fn, mapper). Modul-Konstante, damit 09-06 nur ADDITIV weitere Einträge
# ergänzt, ohne die Route-Logik zu ändern (Erweiterungsmechanismus, verbindlich).
# Kein Eintrag für einen Slug -> ehrliches 200 source_status="no_data" (keine
# Quelle für diese Stadt). Der Toggle wird generisch via
# getattr(Settings(), f"enable_{source}") geprüft (Toggle-Name == source).
#
# Decision B-1 (verbindlich): MobiData BW ist der landesweite Baden-Württemberg-
# DATEX-II-Feed und wird auf die registrierte BW-Landeshauptstadt slug="stuttgart"
# verdrahtet (BBox-gefiltert auf Stuttgart), NICHT auf Karlsruhe (Karlsruhe ist
# keine der 28 Register-Städte; "z.B. Karlsruhe" im Success-Criterion ist nur das
# Quell-Beispiel, der DATEX-II-Parser-Pfad ist quell-, nicht stadt-gebunden).
# Genau diese 5 Slugs sind registriert und get_city-gültig.
CONNECTOR_MAP: dict[str, tuple] = {
    "berlin": ("berlin_viz", fetch_berlin_road_events, map_berlin_road_events),
    "koeln": ("koeln_road_events", fetch_koeln_road_events, map_koeln_road_events),
    "hamburg": (
        "hamburg_roadworks",
        fetch_hamburg_road_events,
        map_hamburg_road_events,
    ),
    "muenchen": (
        "muenchen_roadworks",
        fetch_muenchen_road_events,
        map_muenchen_road_events,
    ),
    "stuttgart": (
        "mobidata_bw",
        fetch_mobidata_road_events,
        map_mobidata_road_events,
    ),
    "dortmund": (
        "dortmund_roadworks",
        fetch_dortmund_road_events,
        map_dortmund_road_events,
    ),
    # SPERRINFOSYS Sachsen (LISt GmbH, DL-DE/BY 2.0): EINE sachsenweite Quelle
    # für Dresden UND Leipzig; der VKZ-Filter im Adapter trennt die Städte.
    # Der Cache-Key ist stadt-scharf (build_cache_key mit city_slug), daher
    # existiert je Stadt ein eigener Cache-Eintrag trotz gemeinsamer Quelle.
    "dresden": (
        "sperrinfosys",
        fetch_sperrinfosys_road_events,
        map_sperrinfosys_road_events,
    ),
    "leipzig": (
        "sperrinfosys",
        fetch_sperrinfosys_road_events,
        map_sperrinfosys_road_events,
    ),
    # DATA-31: Bremen kommt NICHT keylos, sondern über den Mobilithek-mTLS-Pull
    # (VMZ Bremen, DATEX II Situation). fetch_fn=None signalisiert dem
    # city_road_events-Handler den mTLS-Sonderpfad (_bremen_road_events); der
    # generische keylose Pfad wird für Bremen NICHT betreten. Eintrag hält die
    # Coverage-Karte (PARTIAL_COVERAGE["road-events"]) drift-synchron.
    "bremen": ("bremen_roadworks", None, map_bremen_road_events),
    # Rostock: keyloser OpenData.HRO-GeoJSON-Feed (CC0), stadtscharf.
    "rostock": (
        "rostock_roadworks",
        fetch_rostock_road_events,
        map_rostock_road_events,
    ),
}

# Drift-Schutz (verbindlich): die road-events-Abdeckung in der öffentlichen
# Coverage-Karte MUSS exakt den CONNECTOR_MAP-Städten entsprechen. Wird hier ein
# Connector ergaenzt/entfernt, ohne registry/coverage.py nachzuziehen, bricht der
# Import (und damit jeder Test/Boot) sofort - kein stiller Coverage-Drift. Bewusst
# ein echtes raise (kein assert): greift auch unter `python -O`.
if set(CONNECTOR_MAP) != set(PARTIAL_COVERAGE["road-events"]):
    raise RuntimeError(
        "CONNECTOR_MAP und PARTIAL_COVERAGE['road-events'] sind divergiert: "
        f"{set(CONNECTOR_MAP) ^ set(PARTIAL_COVERAGE['road-events'])}"
    )

# GBFS-Sharing-Registry (DATA-33): Stadt-Slug -> kuratierte Nextbike-GBFS-System-
# IDs (NIE User-Input -> kein SSRF). Mehrere Städte können sich ein regionales
# System teilen (z.B. VRNnextbike "nextbike_vn" für Mannheim/Heidelberg/Ludwigs-
# hafen); der BBox-Filter im Adapter trennt sie wieder. Pro System prüft der
# Adapter die GBFS-``license_id`` fail-closed gegen die Tier-A-Allowlist
# (GOV-02/04). Kein Eintrag für einen Slug -> ehrliches not_covered.
GBFS_SYSTEMS: dict[str, tuple[str | GbfsSystem, ...]] = {
    "berlin": ("nextbike_bn",),
    "muenchen": ("nextbike_ml",),
    "koeln": ("nextbike_kg",),
    # Nextbike Frankfurt eingestellt (gbfs.json 404), Ersatz DB Call a Bike ueber
    # den MobiData-BW-GBFS-Aggregator (System-ID callabike, GBFS 2.3, Discovery ohne
    # .json-Suffix). MobiData BW liefert kein system_information.license_id -> der
    # kuratierte Tier-A-Override DL-DE/BY-2.0 greift fail-closed. Quelle:
    # mobidata-bw.de/dataset/bikesh. Host api.mobidata-bw.de ist fest kuratiert
    # (SSRF, T-9q0-01), nie aus User-Input gebaut.
    "frankfurt-am-main": (
        GbfsSystem(
            system_id="callabike",
            base_url="https://api.mobidata-bw.de",
            discovery_path="/sharing/gbfs/v2/{system_id}/gbfs",
            license_override="DL-DE/BY-2.0",
            attribution="Deutsche Bahn Connect GmbH / MobiData BW, DL-DE/BY-2.0",
        ),
    ),
    "duesseldorf": ("nextbike_dd",),
    "dresden": ("nextbike_dx",),
    "leipzig": ("nextbike_le",),
    "hannover": ("nextbike_dh",),
    "nuernberg": ("nextbike_dv",),
    "bremen": ("nextbike_bq",),
    "braunschweig": ("nextbike_dn",),
    "freiburg-im-breisgau": ("nextbike_df",),
    "karlsruhe": ("nextbike_fg",),
    "aachen": ("nextbike_an",),
    "kassel": ("nextbike_dk",),
    "wiesbaden": ("nextbike_wn",),
    "oldenburg": ("nextbike_wo",),
    "potsdam": ("nextbike_dc",),
    "bielefeld": ("nextbike_dg",),
    "moenchengladbach": ("nextbike_sn",),
    "mannheim": ("nextbike_vn",),
    "heidelberg": ("nextbike_vn",),
    "ludwigshafen-am-rhein": ("nextbike_vn",),
    "hanau": ("nextbike_hg",),
    "leverkusen": ("nextbike_dw",),
    # Kiel: SprottenFlotte laeuft auf Donkey Republic (GBFS 3.0), nicht Nextbike.
    # Betreiber-Feed fuehrt system_information.license_id = "CC0-1.0" (verifiziert
    # 2026-07-17) -> greift durch die fail-closed Tier-A-Allowlist ohne Override.
    # Regionalsystem donkey_kielsmile (KielRegion + Smile24); die Stadt-BBox
    # filtert auf Kiel. Host stables.donkey.bike fest kuratiert (SSRF, T-9q0-01).
    "kiel": (
        GbfsSystem(
            system_id="donkey_kielsmile",
            base_url="https://stables.donkey.bike",
            discovery_path="/api/public/gbfs/3.0/{system_id}/gbfs.json",
            attribution="Donkey Republic / SprottenFlotte (CC0)",
        ),
    ),
}

# Drift-Schutz (verbindlich, wie CONNECTOR_MAP): die sharing-Abdeckung in der
# öffentlichen Coverage-Karte MUSS exakt den GBFS_SYSTEMS-Städten entsprechen.
# Echtes raise (kein assert): greift auch unter `python -O`.
if set(GBFS_SYSTEMS) != set(PARTIAL_COVERAGE["sharing"]):
    raise RuntimeError(
        "GBFS_SYSTEMS und PARTIAL_COVERAGE['sharing'] sind divergiert: "
        f"{set(GBFS_SYSTEMS) ^ set(PARTIAL_COVERAGE['sharing'])}"
    )

# DB-Timetables-Registry (DATA-34): Stadt-Slug -> kuratierte Bahnhofs-EVA-Nummern
# (NIE User-Input -> kein SSRF). Metropolen führen NICHT nur den Hbf, sondern alle
# großen Fernverkehrs-Bahnhöfe (Owner-Wunsch: Hamburg Dammtor/Harburg/Altona,
# Berlin Suedkreuz/Gesundbrunnen/Spandau/Ostbf, FFM Sued/Flughafen-Fernbf, München
# Ost/Pasing, Köln Messe-Deutz, Dresden Neustadt, ...). Berlin Hbf hat zwei Ebenen
# mit eigenen EVAs. Der Adapter aggregiert + dedupliziert über alle EVAs und führt
# je Abfahrt/Ankunft den Bahnhofsnamen (``station``). Alle EVAs gegen die
# DB-Timetables-API live verifiziert. Diese Map ist eine BEVORZUGTE/verifizierte
# Override-Liste für die großen Knoten; Städte OHNE Eintrag werden zur Laufzeit
# aus dem StaDa-Katalog abgeleitet (_resolve_city_station_evas) -> volle Abdeckung
# über alle 84 Städte, kein not_covered mehr.
STATION_EVAS: dict[str, tuple[str, ...]] = {
    # Berlin: Hbf (Nord-Süd 8098160 + Ost-West 8089021) + Südkreuz + Gesundbrunnen
    # + Spandau + Ostbahnhof.
    "berlin": ("8098160", "8089021", "8011113", "8011102", "8010404", "8010255"),
    # Hamburg: Hbf + Dammtor + Harburg + Altona.
    "hamburg": ("8002549", "8002548", "8000147", "8002553"),
    # Muenchen: Hbf + Ost + Pasing.
    "muenchen": ("8000261", "8000262", "8004158"),
    # Koeln: Hbf + Messe/Deutz.
    "koeln": ("8000207", "8003368"),
    # Frankfurt: Hbf + Süd + Flughafen Fernbahnhof.
    "frankfurt-am-main": ("8000105", "8002041", "8070003"),
    "stuttgart": ("8000096",),
    "duesseldorf": ("8000085",),
    "hannover": ("8000152",),
    "nuernberg": ("8000284",),
    "leipzig": ("8010205",),
    # Dresden: Hbf + Neustadt.
    "dresden": ("8010085", "8010089"),
    "bremen": ("8000050",),
    "dortmund": ("8000080",),
    "essen": ("8000098",),
    "karlsruhe": ("8000191",),
    "mannheim": ("8000244",),
    "muenster": ("8000263",),
    "mainz": ("8000240",),
    "freiburg-im-breisgau": ("8000107",),
    "bonn": ("8000044",),
    "augsburg": ("8000013",),
}

# Obergrenze der je Stadt aggregierten EVAs (gegen zu viele Upstream-Calls): die
# wichtigsten Bahnhöfe reichen für die Stadt-Tafel.
_MAX_CITY_STATION_EVAS = 6


async def _resolve_city_station_evas(
    request: Request, *, slug: str, ags: str | None, client_id: str, api_key: str
) -> tuple[str, ...]:
    """Liefert die Haupt-Bahnhof-EVAs einer Stadt für die Stadt-Tafel.

    Bevorzugt die verifizierte ``STATION_EVAS``-Override-Liste; für alle anderen
    Städte werden die EVAs zur Laufzeit aus dem StaDa-Katalog abgeleitet
    (Stationen der Stadt via ``municipalityCode == ags``, nach Kategorie sortiert,
    die wichtigsten genommen, ALLE Ebenen-EVAs übernommen, da die /plan-Tafel bei
    Großbahnhöfen teils an einer Ebenen-EVA hängt). So sind alle 84 Städte
    abgedeckt. SSRF: nur numerische EVAs aus StaDa, kein roher User-Input.
    """
    override = STATION_EVAS.get(slug)
    if override:
        return override
    if not ags:
        return ()
    client = request.app.state.resilient_client
    cache_key = build_cache_key("stada", city_slug="_all")

    async def fetch_fn():
        return await fetch_all_stations(
            request.app.state.http, client_id=client_id, api_key=api_key
        )

    raw, _ = await client.fetch("stada", cache_key, fetch_fn)
    if raw is None:
        return ()
    stations = [s for s in raw.get("stations", []) if s.get("ags") == ags]
    stations.sort(key=lambda s: (s.get("category") or 99, s.get("name") or ""))
    evas: list[str] = []
    for station in stations:
        for eva in station.get("evas") or []:
            if eva not in evas:
                evas.append(eva)
        if len(evas) >= _MAX_CITY_STATION_EVAS:
            break
    return tuple(evas[:_MAX_CITY_STATION_EVAS])


# [ASSUMED] EVAS-23111-Tabellen-Code des Krankenhausverzeichnisses (RESEARCH
# A4). None-faehig: der Live-Abgleich ist Manual-Only nach Deploy (Owner). Der
# genesis-Adapter liest die Antwort defensiv (None-Fallback je Feld).
#
# Host (base_url): Der RED-Test-Vertrag aus Plan 08-01 mockt
# regionalstatistik.de (das Krankenhausverzeichnis EVAS 23111 liegt auf der
# Regionalstatistik-GENESIS-Instanz, gleiche wie die Demografie). Der Plan-
# Hinweis auf www-genesis.destatis.de (Pitfall 2) traf für 23111 NICHT zu; die
# Route nutzt daher den genesis-Adapter-Default-Host (Finding B-3 aufgelöst auf
# den Test-Vertrag, beide Hosts liegen ohnehin in der SSRF-Allowlist).
_HOSPITAL_TABLE = "23111-01-01-4"  # [ASSUMED], Live-Abgleich Manual-Only.


@router.get("/cities")
async def cities() -> dict:
    """Listet alle 28 registrierten Städte (kanonische Register-Einträge)."""
    return {
        "data": [city.model_dump() for city in list_cities()],
        "meta": {"correlation_id": correlation_id.get()},
    }


@router.get("/cities/{slug}")
async def city(slug: str) -> dict:
    """Liefert eine Stadt; unbekannter Slug löst den 404-Envelope aus."""
    entry = get_city(slug)
    return {
        "data": entry.model_dump(),
        "meta": {"correlation_id": correlation_id.get()},
    }


@router.get("/cities/{slug}/base")
async def city_base(slug: str, request: Request) -> dict:
    """Liefert normalisierte Wikidata-Stammdaten im kanonischen Envelope.

    Ablauf (DATA-01/06, API-01, GOV-01): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    über die Fassade, Register-Geo-Fallback bei fehlendem P625, Mapping,
    dann der Daten-Envelope mit Attribution.
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift; der Lifespan cached das Singleton
    # bereits vor dem Test-Body). DATA-06: deaktiviert -> 200 disabled, nie 5xx.
    if not Settings().enable_wikidata:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("wikidata", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_city_base(
            request.app.state.http, slug=entry.slug, qid=entry.qid
        )

    raw, status = await client.fetch("wikidata", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. Owner-Entscheidung 2: 503 mit Hint.
    if raw is None:
        raise UpstreamError(
            "Quelle 'wikidata' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # Register-Geo-Fallback (verhindert GeoPoint-ValidationError -> 500): das
    # Register trägt für alle Städte geprüfte Koordinaten; fehlt P625 in
    # Wikidata, übernimmt der Register-Geo.
    if raw.get("lat") is None or raw.get("lon") is None:
        raw["lat"] = entry.geo.lat
        raw["lon"] = entry.geo.lon

    record = map_wikidata_city(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="wikidata")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/weather")
async def city_weather(slug: str, request: Request) -> dict:
    """Liefert normalisierte DWD-Wetterdaten im kanonischen Envelope (DATA-03).

    Ablauf (DATA-03/06, API-01, GOV-03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    über die Fassade gegen die keylose Bright-Sky-API (lat/lon aus dem
    Register-Geo), Mapping mit modified-Attribution, dann der Daten-Envelope mit
    Attribution.
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_dwd:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("dwd", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_weather(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch("dwd", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'dwd' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_weather(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="dwd")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


# Schlüssel aller Katalog-Datenarten (= letztes Pfadsegment von
# ``/cities/{slug}/<key>``). Genutzt vom 422-Hinweis der POI-Route: raet ein Client
# ``?type=playgrounds``, nennt der Hinweis den eigenen Endpunkt statt nur die sechs
# ?type=-Werte. Aus CITY_DATA_CATALOG abgeleitet, damit eine neue Datenart hier nie
# nachgezogen werden muss.
_CATALOG_KEYS: frozenset[str] = frozenset(dt.key for dt in CITY_DATA_CATALOG)


# --- City-Overview (Owner 2026-06-24): EIN Aufruf zeigt die ganze Breite ----------
# Stufe 1 = statischer Katalog ALLER Datenarten je Stadt (aus CITY_DATA_CATALOG +
# Coverage, kein Upstream-Call). Stufe 2 = schlanker Live-Highlight-Snapshot
# (Wetter + Luft + Bahn-Abfahrten am Hauptbahnhof), parallel und zeitgedeckelt,
# damit eine langsame/leere Quelle den Overview nie blockiert. Nicht-abgedeckte
# Datenarten werden nicht verschwiegen,
# sondern vorwärts gewandt dargestellt (wo gibt es sie schon + Roadmap), weil
# InfraNode laufend mehr Daten und Städte bekommt (Owner-Botschaft).

# Highlight-Quellen des Snapshots: (source, fetch_fn, mapper, toggle), gleiche Form
# wie compare.RESOURCE_MAP. Bewusst keylos + flächendeckend (alle 84) -> liefern
# fast immer einen Wert. Additiv erweiterbar (weitere Highlights folgen).
_SNAPSHOT_SOURCES: dict[str, tuple] = {
    "weather": ("dwd", fetch_weather, map_weather, "enable_dwd"),
    "air": ("uba", fetch_air_uba, map_air_uba, "enable_uba"),
}

# Zeitdeckel für den GESAMTEN Snapshot-Fan-out. Gecachte Werte kommen sofort; eine
# langsame Quelle darf den Overview nie über diese Schranke hinaus aufhalten.
_SNAPSHOT_BUDGET_SECONDS = 3.0

# Eine Botschaft, überall gleich: InfraNode wächst. Steht im Overview-Envelope
# (und gespiegelt in docs-site/README/Registries).
OVERVIEW_GROWTH_NOTE = (
    "InfraNode wächst laufend: weitere Datenarten und Städte kommen regelmäßig dazu."
)


async def _snapshot_one(entry, request: Request, name: str) -> tuple[str, dict]:
    """Holt EINE Highlight-Quelle für den Overview-Snapshot; degradiert graceful.

    Wirft NIE: Toggle aus -> ``disabled``, toter Upstream ohne Cache -> ``error``,
    leere Antwort -> ``no_data``, Mapper-Defekt -> ``error``, sonst ``ok`` (D-06-
    Muster wie compare._one). So verdirbt eine haengende/leere Quelle den Overview
    nicht.
    """
    source, fetch_adapter, mapper, toggle = _SNAPSHOT_SOURCES[name]
    if not getattr(Settings(), toggle):
        return name, {"data": None, "source_status": "disabled"}

    client = request.app.state.resilient_client
    cache_key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_adapter(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    try:
        raw, status = await client.fetch(source, cache_key, fetch_fn)
    except Exception:
        return name, {"data": None, "source_status": "error"}
    if raw is None:
        return name, {"data": None, "source_status": "error"}
    if not raw:
        return name, {"data": None, "source_status": "no_data"}
    try:
        record = mapper(
            raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
        )
    except Exception:
        return name, {"data": None, "source_status": "error"}
    return name, {
        "data": record.model_dump(mode="json"),
        "source_status": "ok",
        "cache_status": status,
    }


async def _snapshot_departures(entry, request: Request) -> tuple[str, dict]:
    """Holt die Live-Abfahrtstafel des Stadt-Hauptbahnhofs für den Overview-Snapshot.

    Eigener Helfer (andere Signatur als die lat/lon-Quellen): braucht DB-Timetables-
    Credentials + EVA-Auflösung. Degradiert graceful wie ``_snapshot_one``: fehlende
    Credentials/Toggle -> ``disabled``, keine EVAs/leer -> ``no_data``, toter
    Upstream/Defekt -> ``error``, sonst ``ok``. Wirft NIE in den Fan-out (der
    Overview hängt nie); die EVA-Auflösung kann auf kaltem Cache langsam sein,
    der Zeitdeckel der Route fängt das ab.
    """
    name = "departures"
    settings = Settings()
    cid_secret = settings.db_client_id
    key = settings.db_api_key
    if (
        not settings.enable_db_timetables
        or cid_secret is None
        or key is None
        or not cid_secret.get_secret_value()
        or not key.get_secret_value()
    ):
        return name, {"data": None, "source_status": "disabled"}

    client_id = cid_secret.get_secret_value()
    api_key = key.get_secret_value()
    client = request.app.state.resilient_client
    cache_key = build_cache_key("db_timetables", city_slug=entry.slug)

    try:
        evas = await _resolve_city_station_evas(
            request,
            slug=entry.slug,
            ags=entry.ags,
            client_id=client_id,
            api_key=api_key,
        )
        if not evas:
            return name, {"data": None, "source_status": "no_data"}

        async def fetch_fn():
            return await fetch_station_departures(
                request.app.state.http,
                slug=entry.slug,
                evas=evas,
                client_id=client_id,
                api_key=api_key,
                now=datetime.now(UTC),
            )

        raw, status = await client.fetch("db_timetables", cache_key, fetch_fn)
    except Exception:
        return name, {"data": None, "source_status": "error"}
    if raw is None:
        return name, {"data": None, "source_status": "error"}
    if not raw:
        return name, {"data": None, "source_status": "no_data"}
    try:
        record = map_station_departures(
            raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
        )
    except Exception:
        return name, {"data": None, "source_status": "error"}
    return name, {
        "data": record.model_dump(mode="json"),
        "source_status": "ok",
        "cache_status": status,
    }


@router.get("/cities/{slug}/overview")
async def city_overview(slug: str, request: Request) -> dict:
    """Ein-Aufruf-Ueberblick: Basis + Katalog ALLER Datenarten + Live-Highlights.

    Einstiegspunkt für jede Stadt-Frage. Liefert (1) die Basisdaten der Stadt,
    (2) einen Katalog aller verfügbaren Datenarten mit Abdeckungsstatus und dem
    passenden MCP-Tool je Datenart (Discovery: zeigt die ganze Breite, nicht nur
    Wetter) und (3) einen kleinen Live-Highlight-Snapshot (Wetter, Luft,
    Bahn-Abfahrten am Hauptbahnhof), parallel + zeitgedeckelt. Eine
    nicht-abgedeckte Datenart wird ehrlich, aber vorwärts
    gewandt dargestellt (abgedeckte Städte + Roadmap). Unbekannter Slug -> 404
    (zentraler Handler). Read-only; der Snapshot wirft nie 5xx.
    """
    entry = get_city(slug)

    # Stufe 1: Katalog (statisch, kein Upstream). Verfügbarkeit günstig aus der
    # Coverage-Karte; nicht-abgedeckte Datenarten tragen Pivot + Roadmap-Hinweis.
    catalog: list[dict] = []
    available = 0
    for dt in CITY_DATA_CATALOG:
        covered = is_covered(dt.key, entry.slug)
        item = {
            "type": dt.key,
            "label": dt.label,
            "label_en": dt.label_en,
            "tool": dt.tool,
            "path": f"/api/v1/cities/{entry.slug}/{dt.key}",
            "available": covered,
        }
        if covered:
            available += 1
        else:
            cov = covered_cities(dt.key)
            item["covered_cities"] = cov
            item["note"] = (
                f"Für {entry.slug} noch nicht verfügbar (aktuell {len(cov)} Städte). "
                "Wir bauen die Abdeckung laufend aus."
            )
        catalog.append(item)

    # Stufe 2: Live-Highlights parallel + zeitgedeckelt (hängt nie). Bei
    # Budget-Überschreitung liefern noch offene Highlights ehrlich "error".
    # Budget per INFRANODE_OVERVIEW_SNAPSHOT_BUDGET überschreibbar (Default 3s);
    # bei Überschreitung liefern noch offene Highlights ehrlich "error", der
    # Overview antwortet trotzdem sofort (hängt nie).
    budget = float(
        os.environ.get("INFRANODE_OVERVIEW_SNAPSHOT_BUDGET", _SNAPSHOT_BUDGET_SECONDS)
    )

    async def _bounded(name: str, coro) -> tuple[str, dict]:
        # PER-QUELLE gedeckelt (nicht global): eine langsame/haengende Quelle wird
        # NUR selbst zu "error" und reißt die schnellen, gecachten Highlights nicht
        # mit. wait_for cancelt die Coroutine bei Budget-Überschreitung.
        try:
            return await asyncio.wait_for(coro, budget)
        except Exception:
            return name, {"data": None, "source_status": "error"}

    tasks = [
        _bounded(name, _snapshot_one(entry, request, name))
        for name in _SNAPSHOT_SOURCES
    ]
    tasks.append(_bounded("departures", _snapshot_departures(entry, request)))
    highlights: dict[str, dict] = dict(await asyncio.gather(*tasks))

    cities_total = len(list_cities())
    # headline: macht die Breite fuer Nutzer/Agenten sofort greifbar (Owner-Wunsch:
    # "verstehen, dass sie viele Daten bekommen koennen"). Der volle data_types-
    # Katalog oben listet JEDE Datenart mit ihrem Tool; die headline fasst zusammen.
    headline = (
        f"InfraNode covers {len(catalog)} data types for German cities. "
        f"{available} are available for {entry.slug} right now, each with the tool "
        f"to call in the catalog above. Across {cities_total} cities and thousands "
        "of live data streams, all keyless and free."
    )
    return {
        "data": {
            "city": entry.model_dump(mode="json"),
            "data_types": catalog,
            "highlights": highlights,
            "summary": {
                "data_types_total": len(catalog),
                "data_types_available": available,
                "cities_total": cities_total,
                "headline": headline,
                "note": OVERVIEW_GROWTH_NOTE,
            },
        },
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/solar")
async def city_solar(slug: str, request: Request) -> dict:
    """Liefert Solar-Einstrahlung + normierten PV-Ertrag im Envelope (DATA-38).

    Ablauf (DATA-38/06, API-01, GOV-03): Register-Lookup (unbekannter Slug -> 404
    mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung (deaktiviert ->
    200 ``source_status=disabled``, nie 5xx), resilienter Fetch über die Fassade
    gegen die keylose PVGIS-Rechen-API (lat/lon aus dem Register-Geo), Mapping mit
    modified-Attribution, dann der Daten-Envelope.

    PVGIS rechnet jede Koordinate in Europa -> alle Register-Städte sind ohne
    Stadt-Allowlist abgedeckt. Die Werte sind ein klimatologisches Mehrjahresmittel
    (kein Tageswert), normiert auf 1 kWp bei optimalem Neigungswinkel; der
    Bezugszeitraum steht im Payload (``period_start``/``period_end``).
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_solar:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("solar", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_solar(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch("solar", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'solar' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_solar(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="solar")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/solar-roofs")
async def city_solar_roofs(slug: str) -> dict:
    """Liefert das Dach-Solarkataster je Stadt im kanonischen Envelope (DATA-39).

    Dach-PV-Potenzial (installierbar, kWp + Jahresertrag MWh) plus Bestand
    (installiert) je Stadt aus dem amtlichen Gemeinde-Aggregat (NRW-Pilot,
    Solarkataster NRW, MaStR/LANUK/Geobasis NRW, DL-DE/Zero 2.0 = Tier A). Anders
    als /solar (PVGIS-Einstrahlung/Ertrag je kWp) trägt diese Route die Mengen
    je Stadt. Teilabgedeckt (NRW), föderiert je Bundesland wie /land-values.

    KRITISCH (kein Upstream im Request-Pfad, T-08-DEP): liest AUSSCHLIESSLICH aus
    dem committeten Seed ``data/seeds/solar_cadastre_nrw.json`` via stdlib json,
    KEIN ``resilient_client``, KEINE Fremd-API.

    Vier ``source_status``-Werte:
    - ``disabled``: ``enable_solar_cadastre`` per Env-Toggle aus -> data None
    - ``not_covered``: Stadt außerhalb der abgedeckten Bundesländer (mit
      covered_cities) -> data None, KEIN 5xx
    - ``no_data``: abgedeckte Stadt, aber kein Seed-Eintrag -> data None
    - ``ok``: Seed-Eintrag vorhanden -> SolarRoofsPayload mit Attribution
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings). DATA-06.
    if not Settings().enable_solar_cadastre:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Teilabdeckung: Stadt außerhalb NRW -> 200 not_covered mit covered_cities.
    if not is_covered("solar-roofs", entry.slug):
        return _not_covered("solar-roofs")

    raw = load_solar_roofs(entry.ags)
    if raw is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = map_solar_roofs(
        raw,
        slug=entry.slug,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/charging")
async def city_charging(slug: str, request: Request) -> dict:
    """Liefert E-Ladesäulen-Standorte im kanonischen Envelope (DATA-09).

    Ablauf (DATA-09/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), dann ein read-only
    Read über ``read_records`` aus dem vorverarbeiteten Datensatz;
    zurückgegeben wird der jüngste Snapshot (max ``retrieved_at``).

    KRITISCH (kein Bulk-Upstream im Request-Pfad): Die BNetzA liefert das
    Ladesäulenregister seit dem Aus des ArcGIS-FeatureServers (HTTP 499) nur
    noch als ~47-MB-CSV-Bulk-Download. Diese Route liest AUSSCHLIESSLICH aus dem
    vorverarbeiteten Datensatz, NIE die CSV, und ruft KEINEN
    ``resilient_client`` auf. Der Datensatz wird offline aktualisiert.

    Nur Stammdaten, KEINE Belegung (Locked Decision). Drei ``source_status``-
    Werte (analog /energy):
    - ``disabled``: ``enable_bnetza`` per Env-Toggle aus -> data None
    - ``not_ingested``: Quelle aktiv, aber kein Snapshot ->
      ``read_records`` liefert [] -> data None, KEIN 5xx
    - ``ok``: jüngster Snapshot -> CanonicalRecord mit Attribution + license_id

    Die ``stations``-Liste ist über ``limit`` (Default 50, max 200) + ``offset``
    paginierbar; ``meta.pagination`` weist total/returned/truncated ehrlich aus
    (keine stille Kappung); Offset-Overflow -> leere Seite 200. ``payload.count``
    bleibt der volle Snapshot-Gesamtbestand (Aggregat != Seitenlänge).
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_bnetza:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Read-only aus dem vorverarbeiteten bnetza-Datensatz (NIE die CSV im
    # Request-Pfad). Fehlender Datensatz -> [] -> not_ingested, kein 5xx.
    records = read_records(source="bnetza", tier="A", city_slug=entry.slug)
    if not records:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    # Jüngster Snapshot: daher hier max(retrieved_at).
    record = max(records, key=lambda r: r.retrieved_at)

    data = record.model_dump(mode="json")
    meta = {
        "correlation_id": correlation_id.get(),
        "source_status": "ok",
    }
    # Listen-Paginierung (DATA-09): stations-Liste begrenzen; count bleibt das
    # volle Snapshot-Aggregat (delivered_count_field=None).
    p = parse_page_params(request)
    paginate_envelope(data, meta, p, list_key="stations")
    return {"data": data, "meta": meta}


@router.get("/cities/{slug}/district-heating")
async def city_district_heating(slug: str) -> dict:
    """Liefert die Fernwärme-/Wärmenetz-Versorgung je Stadt im Envelope (DATA-41).

    Aggregat aus den amtlichen Wärmenetz-Geodaten der kommunalen Wärmeplanung,
    föderiert je Stadt-WFS (wie /solar-roofs, je Ursprung lizenzverifiziert):
    Berlin (Energienetze, DL-DE/Zero 2.0) + Hamburg (Gebiete mit Wärmenetz,
    DL-DE/BY 2.0), beide Tier A. Trägt je Stadt die Netzbetreiber, die Zahl der
    Versorgungs-/Netzflächen und, je nach Quelle, die versorgte Fläche (Berlin)
    bzw. Hausanschlüsse + Trassenlänge (Hamburg).

    KRITISCH (kein WFS im Request-Pfad, T-08-DEP): liest AUSSCHLIESSLICH read-only
    den jüngsten Snapshot aus ``tier_a/district_heating/`` (Batch-Ingest
    ``python -m infranode.ingest.district_heating``), NIE den WFS, KEIN
    ``resilient_client``.

    Vier ``source_status``-Werte (analog /solar-roofs):
    - ``disabled``: ``enable_district_heating`` per Env-Toggle aus -> data None
    - ``not_covered``: Stadt außerhalb der abgedeckten Städte (mit covered_cities)
    - ``not_ingested``: abgedeckte Stadt, aber kein Snapshot -> data None, KEIN 5xx
    - ``ok``: jüngster Snapshot -> DistrictHeatingPayload mit Attribution
    """
    entry = get_city(slug)

    if not Settings().enable_district_heating:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    if not is_covered("district-heating", entry.slug):
        return _not_covered("district-heating")

    records = read_records(source="district_heating", tier="A", city_slug=entry.slug)
    if not records:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = max(records, key=lambda r: r.retrieved_at)
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/air", deprecated=True)
async def city_air(slug: str, request: Request, response: Response) -> dict:
    """Liefert normalisierte UBA-Luftqualität im kanonischen Envelope (DATA-10).

    Ablauf (DATA-10/06, API-01, GOV-02/03): Register-Lookup (unbekannter Slug ->
    404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    über die Fassade gegen die keylose UBA-Air-Data-API (lat/lon aus dem
    Register-Geo), Mapping mit DL-DE/BY-2.0-Attribution, dann der Daten-Envelope.

    KRITISCH (Pitfall 2 / Lizenz-Klassifikation GOV-02): UBA ist der Tier-A-
    Luftpfad (offene Lizenz, 84/84 flächendeckend). Diese Route liefert direkt
    UBA (keine Quellen-Verzweigung, kein Fallback-Zweig) und persistiert Tier A.
    Der Deprecation-Pointer zeigt auf den Altpfad-Nachfolger
    ``/api/v1/live/{slug}/air`` (NICHT /air-uba).
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/air")

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_uba:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("uba", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_air_uba(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch("uba", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'uba' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_air_uba(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="uba")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/air-uba", deprecated=True)
async def city_air_uba(slug: str, request: Request, response: Response) -> dict:
    """Liefert UBA-Luftqualität im kanonischen Envelope (DATA-10).

    Ablauf (DATA-10/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    über die Fassade gegen die keylose UBA-Air-Data-API (2-Step Station-Geo-
    Nähe + Messwerte, lat/lon aus dem Register-Geo), Mapping mit DL-DE/BY-2.0-
    Attribution, dann der Daten-Envelope mit Attribution.

    KRITISCH (Pitfall 2 / Lizenz-Klassifikation GOV-02): UBA ist der Tier-A-
    Luftpfad (offene Lizenz). Diese Route ``/air-uba`` persistiert Tier A; der
    ältere Pfad ``/air`` (oben) nutzt dieselbe UBA-Quelle und persistiert Tier A
    ebenso.
    Graceful Degradation: toter Upstream ohne Cache -> 503 mit Hint (DX-06).
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/air-uba")

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_uba:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("uba", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_air_uba(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch("uba", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'uba' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_air_uba(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="uba")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/water-level", deprecated=True)
async def city_water_level(slug: str, request: Request, response: Response) -> dict:
    """Liefert PEGELONLINE-Pegelstände im kanonischen Envelope (DATA-11).

    Ablauf (DATA-11/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    über die Fassade gegen die keylose PEGELONLINE-API (2-Step Station-Geo-Nähe
    + Wasserstand, lat/lon aus dem Register-Geo), Mapping mit DL-DE/Zero-2.0-
    Attribution, dann der Daten-Envelope mit Attribution.

    KRITISCH (DATA-11, Pitfall 3 / Teilabdeckung): PEGELONLINE deckt nur Städte
    an Bundeswasserstraßen ab. Findet der Adapter keine nahe Station
    (``raw["station"] is None``, z.B. Binnenstadt), liefert die Route ehrlich
    ``source_status="no_data"`` (200) OHNE Mapper (KEIN 5xx). Graceful
    Degradation: toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint
    (DX-06).
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/water-level")

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_pegelonline:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("pegelonline", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_water_level(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch("pegelonline", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'pegelonline' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # KRITISCH (DATA-11, Pitfall 3): keine nahe Station (Binnenstadt) -> ehrliches
    # no_data (200) OHNE Mapper. KEIN 5xx; die Teilabdeckung wird ehrlich ausgewiesen.
    if raw.get("station") is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = map_water_level(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    # Nur bei vorhandener Station.
    await append_record(record, source="pegelonline")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/flood", deprecated=True)
async def city_flood(slug: str, request: Request, response: Response) -> dict:
    """Liefert LHP-Hochwasser-Warnstufen im kanonischen Envelope (DATA-12).

    Ablauf (DATA-12/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    über die Fassade gegen die keylose LHP-API (``POST get_infospegel.php`` je
    kuratiertem Pegel der Stadt), Mapping mit der PFLICHT-Stand-Attribution
    (CC-BY 4.0), dann der Daten-Envelope mit Attribution.

    KRITISCH (Pitfall 6, GOV-03): Die ``data.attribution.text`` trägt PFLICHT den
    Wortlaut ``"Datenquelle: www.hochwasserzentralen.de, Stand: <stand>"``.

    KRITISCH (DATA-12, Event-Layer): Keine aktive Warnung (leere ``warnings``) ist
    KEIN Fehler -> Happy-Path 200 mit leerem Event. Graceful Degradation: toter
    Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/flood")

    # Coverage-Guard (Owner 2026-06-13): LHP-Hochwasser deckt nur kuratierte Städte
    # mit Pegel ab (_CITY_PEGEL). Eine nicht-abgedeckte Stadt liefert ehrlich
    # not_covered (200) + covered_cities, statt eines leeren "ok" (das wie "keine
    # Warnung" aussähe). Vor dem Toggle: die fehlende Abdeckung ist strukturell.
    if not is_covered("flood", entry.slug):
        return _not_covered("flood")

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_lhp:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("lhp", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_flood(request.app.state.http, slug=entry.slug)

    raw, status = await client.fetch("lhp", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'lhp' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_flood(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    # Leere warnings sind KEIN Fehler.
    await append_record(record, source="lhp")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/demographics")
async def city_demographics(slug: str, request: Request) -> dict:
    """Liefert GENESIS-Demografie im kanonischen Envelope (DATA-17).

    Ablauf (DATA-17/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), account-gated Toggle-/Key-
    Guard (Quelle aus ODER kein Credential -> 200 ``source_status=disabled``, nie
    5xx, analog city_air Key-Guard), resilienter Fetch über die Fassade gegen die
    keyabhängige GENESIS-POST-API (Regionalstatistik, AGS aus dem Register-Geo),
    Mapping mit DL-DE/BY-2.0-Attribution, dann der Daten-Envelope mit Attribution.

    KRITISCH (T-08-CRED): Die Credentials gelangen nur in den POST-Body des
    Adapters, NIE in den Cache-Key (der trägt nur den Slug) oder die Response.
    Graceful Degradation: toter Upstream ohne Cache -> 503 mit selbst-
    korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)

    # Account-gated Toggle-/Key-Guard frisch lesen (Settings() statt
    # app.state.settings, damit der per-Test gesetzte Env-Override greift).
    # DATA-06: Quelle aus ODER kein Credential -> 200 disabled, nie 5xx.
    settings = Settings()
    if (
        not settings.enable_genesis
        or settings.genesis_username is None
        or settings.genesis_password is None
    ):
        # GENESIS aus: Minimal-Fallback auf die Register-Einwohnerzahl (Wikidata,
        # CC0, Tier A) statt leerem disabled, sofern vorhanden. meta.fallback
        # macht die Herkunft transparent; sortenrein (kein GENESIS-Payload).
        if entry.population is not None:
            fb = map_population_demographics(
                slug=entry.slug,
                population=entry.population,
                retrieved_at=datetime.now(UTC),
                ags=entry.ags,
                wikidata_qid=entry.qid,
            )
            return {
                "data": fb.model_dump(mode="json"),
                "meta": {
                    "correlation_id": correlation_id.get(),
                    "source_status": "ok",
                    "fallback": "wikidata",
                },
            }
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    # Cache-Key trägt NUR den Slug (T-08-CRED): nie Credentials.
    key = build_cache_key("genesis", city_slug=entry.slug)

    genesis_user = settings.genesis_username
    genesis_password = settings.genesis_password

    async def fetch_fn():
        return await fetch_demographics(
            request.app.state.http,
            slug=entry.slug,
            ags=entry.ags,
            username=genesis_user,
            password=genesis_password,
        )

    raw, status = await client.fetch("genesis", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'genesis' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_demographics(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="genesis")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/pollen-uv")
async def city_pollen_uv(slug: str, request: Request) -> dict:
    """Liefert DWD-Pollenflug + UV-Index je Großregion (DATA-14).

    Ablauf (DATA-14/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    über die Fassade gegen die keylosen DWD-Open-Data-Dienste (zwei GET,
    s31fg.json Pollen + uvi.json UV, KEIN lat/lon: Region-Map im Adapter),
    Mapping mit der GeoNutzV-Attribution (``modified=True``, Pitfall 5), dann der
    Daten-Envelope.

    KRITISCH (Pitfall 4, Ehrlichkeit): Die Daten sind GROSSREGION-genau, NICHT
    stadtgenau. ``data.payload.region_name``/``region_id`` weisen die Großregion
    ehrlich aus. Graceful Degradation: toter Upstream ohne Cache -> 503 mit
    selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_dwd_pollen:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("dwd_pollen", city_slug=entry.slug)

    async def fetch_fn():
        # KEIN lat/lon: die Stadt-zu-Großregion-Map liegt im Adapter (Pitfall 4).
        return await fetch_pollen_uv(request.app.state.http, slug=entry.slug)

    raw, status = await client.fetch("dwd_pollen", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'dwd_pollen' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_pollen_uv(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="dwd_pollen")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/fire-danger")
async def city_fire_danger(slug: str, request: Request) -> dict:
    """Liefert den DWD-Waldbrand-/Graslandfeuerindex der naechsten Station.

    Ablauf (API-01, GOV-02/03): Register-Lookup (unbekannter Slug -> 404 mit Hint),
    Quellen-Toggle-Pruefung (deaktiviert -> 200 ``source_status=disabled``, nie
    5xx), resilienter Fetch ueber die Fassade gegen den keylosen DWD-Daten-
    FeatureServer (Waldbrandgefahrenindex + best-effort Graslandfeuerindex),
    Mapping mit der GeoNutzV-Attribution (``modified=True``, Pitfall 5), dann der
    Daten-Envelope.

    KRITISCH (Pitfall 4, Ehrlichkeit): Der Index ist STATIONS-genau, NICHT
    stadtgenau. ``data.payload.station_name``/``distance_km`` weisen die naechste
    DWD-Station ehrlich aus. Graceful Degradation: toter Upstream ohne Cache ->
    503 mit selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)

    if not Settings().enable_dwd_fire:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("dwd_fire", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_fire_danger(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            base_url=Settings().dwd_fire_base_url,
        )

    raw, status = await client.fetch("dwd_fire", key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Quelle 'dwd_fire' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_fire_danger(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="dwd_fire")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/bathing-water")
async def city_bathing_water(slug: str, request: Request) -> dict:
    """Liefert die Badegewaesserqualitaet im Umkreis einer Stadt (EEA, Tier A).

    Ablauf (API-01, GOV-02/03): Register-Lookup (unbekannter Slug -> 404 mit Hint),
    Quellen-Toggle-Pruefung (deaktiviert -> 200 ``source_status=disabled``, nie
    5xx), resilienter Fetch ueber die Fassade gegen den keylosen EEA-DiscoMap-Dienst
    (EU-Badegewaesserrichtlinie 2006/7/EG), Mapping mit CC-BY-Attribution, dann der
    Daten-Envelope.

    KRITISCH (Pitfall 4, Ehrlichkeit): Badegewaesser liegen ORTSNAH (Umland), NICHT
    stadtgenau; ``data.payload.sites[].distance_km`` weist das aus. Inland-Staedte
    ohne Badegewaesser im Umkreis liefern ehrlich ``count=0``. Graceful Degradation:
    toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)

    if not Settings().enable_eea_bathing:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("eea_bathing", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_bathing_water(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            season_year=Settings().eea_bathing_year,
            base_url=Settings().eea_bathing_base_url,
        )

    raw, status = await client.fetch("eea_bathing", key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Quelle 'eea_bathing' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_bathing_water(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="eea_bathing")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/hospitals-atlas")
async def city_hospitals_atlas(slug: str, request: Request) -> dict:
    """Liefert Krankenhausstandorte im Umkreis einer Stadt (Bundes-Klinik-Atlas).

    FAIL-CLOSED: Der Bundes-Klinik-Atlas weist KEINE explizite offene Lizenz aus;
    die Quelle ist daher per Default DEAKTIVIERT (``enable_klinik_atlas=False`` ->
    200 ``source_status=disabled``) und als license_id UNKNOWN/Tier C getaggt, bis
    BMG/IQTIG die Lizenz bestaetigt. Standortgenaue Liste (Name/Adresse/Betten/
    Kontakt/Koordinaten), ORTSNAH gefiltert (Pitfall 4, ``distance_km`` je Standort).
    Graceful Degradation: toter Upstream ohne Cache -> 503 mit Hint (DX-06).
    """
    entry = get_city(slug)

    if not Settings().enable_klinik_atlas:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("klinik_atlas", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_hospital_atlas(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            base_url=Settings().klinik_atlas_base_url,
        )

    raw, status = await client.fetch("klinik_atlas", key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Quelle 'klinik_atlas' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_hospital_atlas(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="klinik_atlas")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/station-facilities")
async def city_station_facilities(slug: str, request: Request) -> dict:
    """Liefert Aufzug-/Rolltreppen-Status an Bahnhoefen einer Stadt (DB FaSta).

    KEY-GATED: Die FaSta-API laeuft ueber denselben DB-API-Marketplace wie
    db_timetables/stada und nutzt die gemeinsamen ``db_client_id``/``db_api_key``
    (gleiche "InfraNode"-Anwendung, kein eigener Key). Ohne diese Credentials (oder
    bei ``enable_db_fasta=False``) liefert die Route 200 ``source_status=disabled``
    (nie 5xx). Echtzeit-Barrierefreiheit (ACTIVE/INACTIVE/UNKNOWN je Anlage),
    ORTSNAH gefiltert (Pitfall 4, ``distance_km`` je Anlage). Graceful Degradation:
    toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)

    settings = Settings()
    # Gemeinsame DB-API-Marketplace-Credentials (wie db_timetables/stada).
    client_id = settings.db_client_id
    api_key = settings.db_api_key
    # KEY-GATED: ohne Toggle ODER ohne Credentials -> ehrlich disabled (kein 5xx).
    if not settings.enable_db_fasta or client_id is None or api_key is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("db_fasta", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_station_facilities(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            client_id=client_id.get_secret_value(),
            api_key=api_key.get_secret_value(),
            base_url=settings.db_fasta_base_url,
        )

    raw, status = await client.fetch("db_fasta", key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Quelle 'db_fasta' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_station_facilities(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="db_fasta")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


def _osm_rows_to_elements(rows: list[dict]) -> list[dict]:
    """Rekonstruiert aus Store-Zeilen rohe Overpass-Elemente für die Mapper.

    Der Precompute-Store liefert je POI ein flaches dict ``{name, lat, lon, ...extra}``
    (``osm_pois_db.read_pois``); die unveränderten Mapper (``map_overpass_pois`` /
    ``map_osm_feature``, ODbL/Tier B, Drift-Tests) erwarten dagegen rohe Overpass-
    Elemente der Form ``{tags:{name, ...extra}, lat, lon}``. Diese Brücke hält die
    Lizenz-/Attributions-/Truncation-Ableitung in EINER Quelle (den Mappern),
    obwohl die Daten jetzt aus dem Store statt live von Overpass kommen.
    """
    elements: list[dict] = []
    for r in rows:
        tags = {k: v for k, v in r.items() if k not in ("lat", "lon")}
        elements.append({"tags": tags, "lat": r.get("lat"), "lon": r.get("lon")})
    return elements


@router.get("/cities/{slug}/pois")
# A002 unterdrueckt: der Parametername IST der oeffentliche Query-Parameter
# (?type=), eine Umbenennung braeche den API-Vertrag.
async def city_pois(slug: str, request: Request, type: str) -> dict:  # noqa: A002
    """Liefert nach Typ gefilterte OSM-POIs im kanonischen Envelope (DATA-04).

    Ablauf (DATA-04/06, API-01, GOV-02): Register-Lookup (unbekannter Slug -> 404
    mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung (deaktiviert ->
    200 ``source_status=disabled``, nie 5xx), Typ-Whitelist-Prüfung (unbekannter
    Typ -> 422, T-05-09), read-only-Lesung aus dem Precompute-Store, Mapping, dann
    der Daten-Envelope.

    Read-only (wie council-papers/public-tenders): ein periodischer Batch-Ingest
    (``ingest.osm_pois``, wöchentlich) extrahiert die POIs offline aus dem Geofabrik-
    Deutschland-Extrakt in den ``osm_pois``-Store; die Route liest AUSSCHLIESSLICH
    daraus, NIE live über eine Fremd-Overpass-Instanz (keine Fair-Use-/Rate-Limit-
    Abhängigkeit mehr). ``total_available`` ist der echte Gesamtbestand
    (``count_pois``), ``items`` die auf ``overpass_max_elements`` gedeckelte
    Stichprobe (``read_pois``); der Mapper leitet ``truncated`` daraus ab.
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_overpass:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # T-05-09 Injection: unbekannter Typ -> 422. Die Whitelist bleibt die Quelle der
    # erlaubten POI-Typen (identisch zum Ingest über ``osm_poi_tags``); roher User-
    # Input gelangt nie in eine Store-Query (``read_pois`` bindet ?-parametrisiert).
    if type not in _ALLOWED_TYPES:
        # Befund 2026-07-26: der osm_pois-Store trägt 17 Typen, ``?type=`` erlaubt
        # aber nur die 6 klassischen POI-Typen. Die anderen 11 (playgrounds,
        # post-boxes, public-wifi, ...) sind eigene Datenarten mit eigenem Endpunkt.
        # Wer die hier rät, bekam bisher nur die 6er-Liste und keinen Weg zum Ziel
        # (live: 58 x 422 auf /cities/osnabrueck/pois am 25.07.). Ist der geratene
        # Typ eine Katalog-Datenart, nennt der Hinweis jetzt deren Pfad. Der
        # Katalog bleibt die eine Quelle der Datenart-Schlüssel (kein zweiter
        # Hartkodier-Ort, der beim Hinzufügen einer Datenart veraltet).
        hint = f"Erlaubte Typen: {', '.join(sorted(_ALLOWED_TYPES))}."
        if type in _CATALOG_KEYS:
            hint = (
                f"'{type}' ist eine eigene Datenart: "
                f"GET /api/v1/cities/{entry.slug}/{type}. "
                f"Über ?type= laufen nur {', '.join(sorted(_ALLOWED_TYPES))}."
            )
        raise UnprocessableError(f"Unbekannter POI-Typ '{type}'.", hint=hint)

    # Read-only aus dem Precompute-Store. ``total_available`` = echter Gesamtbestand,
    # ``items`` = gedeckelte Stichprobe; leerer Store -> ehrliches 200 no_data.
    max_elements = Settings().overpass_max_elements
    rows = read_pois(entry.slug, type, limit=max_elements)
    total = count_pois(entry.slug, type)

    if not rows:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    raw = {
        "slug": entry.slug,
        "poi_type": type,
        "elements": _osm_rows_to_elements(rows),
        "total_available": total,
    }
    record = map_overpass_pois(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


async def _osm_feature_response(request: Request, entry, feature: str) -> dict:
    """Geteilte Logik aller OSM-Feature-Endpunkte (OSM, Tier B copyleft).

    Identischer Ablauf wie ``/pois`` (DATA-04/06): Quellen-Toggle (deaktiviert ->
    200 ``source_status=disabled``, nie 5xx), read-only-Lesung aus dem Precompute-
    Store, leerer Store -> 200 ``no_data``, dann Mapping mit ODbL-Attribution und
    Daten-Envelope. ``feature`` ist stets ein festes, intern gesetztes Literal aus
    ``_OSM_FEATURES`` (kein User-Input); die je Feature deklarierten Zusatz-Tags
    (``extra_tags``) reicht der Mapper aus dem Store durch.

    Read-only wie ``/pois``: der Batch-Ingest (``ingest.osm_pois``, wöchentlich)
    füllt den Store offline, die Route liest AUSSCHLIESSLICH daraus (nie live).

    Die ``items``-Liste ist über ``limit`` (Default 50, max 200) + ``offset``
    paginierbar; ``meta.pagination`` weist total/returned/truncated ehrlich aus,
    Offset-Overflow -> leere Seite 200. ``payload.count`` trägt die ausgelieferte
    Seitenlänge (PoiPayload-Semantik), ``total_available`` bleibt der echte
    Gesamtbestand aus dem Store. So erben education/playgrounds/post-boxes/
    parcel-lockers/public-wifi und die übrigen OSM-Features limit/offset."""
    if not Settings().enable_overpass:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Read-only aus dem Precompute-Store (feature ist internes Literal aus
    # _OSM_FEATURES). total_available = echter Gesamtbestand, items = gedeckelte
    # Stichprobe; leerer Store -> ehrliches 200 no_data.
    max_elements = Settings().overpass_max_elements
    rows = read_pois(entry.slug, feature, limit=max_elements)
    total = count_pois(entry.slug, feature)

    if not rows:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    raw = {
        "slug": entry.slug,
        "poi_type": feature,
        "extra_tags": list(_OSM_FEATURES[feature].extra_tags),
        "elements": _osm_rows_to_elements(rows),
        "total_available": total,
    }
    record = map_osm_feature(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )

    data = record.model_dump(mode="json")
    meta = {
        "correlation_id": correlation_id.get(),
        "source_status": "ok",
    }
    # Listen-Paginierung (DATA-04): items-Liste begrenzen. delivered_count_field=
    # "count" -> PoiPayload.count == ausgelieferte Seite; total_available bleibt der
    # echte Gesamtbestand. Der Helper liest limit/offset selbst aus der Query (kein
    # Depends), daher erben alle OSM-Route-Signaturen die Paginierung.
    p = parse_page_params(request)
    paginate_envelope(data, meta, p, list_key="items", delivered_count_field="count")
    return {"data": data, "meta": meta}


@router.get("/cities/{slug}/playgrounds")
async def city_playgrounds(slug: str, request: Request) -> dict:
    """Liefert öffentliche Spielplätze (OSM ``leisure=playground``, Tier B)."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "playgrounds")


@router.get("/cities/{slug}/drinking-water")
async def city_drinking_water(slug: str, request: Request) -> dict:
    """Liefert öffentliche Trinkwasserbrunnen (OSM ``amenity=drinking_water``).

    Hinweis: Die OSM-Abdeckung ist je Stadt unterschiedlich vollständig."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "drinking-water")


@router.get("/cities/{slug}/public-toilets")
async def city_public_toilets(slug: str, request: Request) -> dict:
    """Liefert öffentliche Toiletten (OSM ``amenity=toilets``).

    Je Element werden Barrierefreiheits-Tags ausgewiesen (``wheelchair``,
    ``changing_table``) sowie ``fee``/``access``/``opening_hours``/``unisex``.
    Hinweis: Die OSM-Abdeckung ist je Stadt unterschiedlich vollständig."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "public-toilets")


@router.get("/cities/{slug}/markets")
async def city_markets(slug: str, request: Request) -> dict:
    """Liefert Wochen-/Marktplaetze (OSM ``amenity=marketplace``, Tier B).

    Markttage/Zeiten kommen als optionales ``opening_hours`` je Element (oft leer)."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "markets")


@router.get("/cities/{slug}/parcel-lockers")
async def city_parcel_lockers(slug: str, request: Request) -> dict:
    """Liefert Paketstationen/Locker (OSM ``amenity=parcel_locker``, Tier B).

    ``operator``/``brand`` (DHL/Amazon/DPD/Hermes/GLS) je Element, wenn getaggt."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "parcel-lockers")


@router.get("/cities/{slug}/post-offices")
async def city_post_offices(slug: str, request: Request) -> dict:
    """Liefert Postfilialen (OSM ``amenity=post_office``, Tier B)."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "post-offices")


@router.get("/cities/{slug}/post-boxes")
async def city_post_boxes(slug: str, request: Request) -> dict:
    """Liefert öffentliche Briefkästen (OSM ``amenity=post_box``, Tier B).

    Leerungszeiten kommen als optionales ``collection_times`` je Element (~3/4
    der Briefkästen getaggt; ``null``/fehlend = Datenpunkt-Lücke, kein Fehler)."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "post-boxes")


@router.get("/cities/{slug}/public-wifi")
async def city_public_wifi(slug: str, request: Request) -> dict:
    """Liefert öffentliche WLAN-Standorte (OSM ``internet_access=wlan``, Tier B)."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "public-wifi")


@router.get("/cities/{slug}/recycling-centres")
async def city_recycling_centres(slug: str, request: Request) -> dict:
    """Liefert Recycling-/Wertstoffhoefe (OSM ``amenity=recycling`` +
    ``recycling_type=centre``, Tier B). ``opening_hours`` je Element, wenn getaggt."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "recycling-centres")


@router.get("/cities/{slug}/government-offices")
async def city_government_offices(slug: str, request: Request) -> dict:
    """Liefert Behoerden/Aemter (OSM ``office=government`` + ``amenity=townhall``).

    Konsolidiert Bürgerämter, Verwaltungs- und sonstige Ämter; der Subtyp steht
    je Element als optionales ``government``-Tag."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "government-offices")


@router.get("/cities/{slug}/education")
async def city_education(slug: str, request: Request) -> dict:
    """Liefert Bildungseinrichtungen (OSM ``amenity=school/college/university/
    kindergarten``, Tier B)."""
    entry = get_city(slug)
    return await _osm_feature_response(request, entry, "education")


@router.get("/cities/{slug}/heritage")
async def city_heritage(slug: str, request: Request) -> dict:
    """Liefert Bau-/Denkmal-Objekte je Stadt (Denkmalliste, Land-WFS).

    Ablauf (DATA-OSM-Tier-2): Register-Lookup (unbekannter Slug -> 404), Coverage-
    Guard (Denkmalschutz ist Landessache -> nur Städte in Ländern mit
    verifiziertem offenem WFS, sonst 200 ``not_covered`` + covered_cities),
    Quellen-Toggle (deaktiviert -> 200 ``disabled``), resilienter WFS-Fetch
    (GeoJSON, Repräsentativpunkt je Objekt), Mapping mit landesabhängiger Lizenz
    (Berlin DL-DE/Zero 2.0), dann der Daten-Envelope. Toter Upstream ohne Cache
    -> 503 mit Hint auf GET /api/v1/health."""
    entry = get_city(slug)

    # Coverage-Guard (föderiert je Bundesland): nicht abgedeckte Stadt -> ehrlich
    # not_covered (200) + covered_cities, klar unterscheidbar von no_data.
    if not is_covered("heritage", entry.slug):
        return _not_covered("heritage")

    # Quellen-Toggle frisch lesen (Env-Override-tauglich). DATA-06.
    if not Settings().enable_heritage:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("heritage", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_heritage(
            request.app.state.http,
            slug=entry.slug,
            state=entry.state,
            lat=entry.geo.lat if entry.geo else None,
            lon=entry.geo.lon if entry.geo else None,
            population=entry.population,
        )

    raw, status = await client.fetch("heritage", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'heritage' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_heritage(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="heritage")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/tree-cadastre")
async def city_tree_cadastre(slug: str, request: Request) -> dict:
    """Liefert das städtische Baumkataster (kommunaler WFS, Tier A).

    Ablauf (DATA-OSM-Tier-2): Register-Lookup (unbekannter Slug -> 404), Coverage-
    Guard (Baumkataster ist kommunal -> nur Städte mit verifiziertem offenem WFS,
    sonst 200 ``not_covered`` + covered_cities), Quellen-Toggle (deaktiviert -> 200
    ``disabled``), resilienter WFS-Fetch (GeoJSON-Punkte, gedeckelte Stichprobe),
    Mapping mit stadtabhängiger Lizenz (Berlin DL-DE/Zero 2.0), dann der Daten-
    Envelope. HINWEIS: Kataster sind sehr groß; die Antwort ist eine gedeckelte
    Stichprobe (``count`` = ausgelieferte Bäume; der echte Gesamtbestand steht in
    ``total_available``, ``truncated=true`` zeigt die Deckelung an, Audit-220).
    Toter Upstream ohne Cache -> 503 mit Hint auf GET /api/v1/health."""
    entry = get_city(slug)

    # Coverage-Guard (per Stadt): nicht abgedeckt -> ehrlich not_covered (200).
    if not is_covered("tree-cadastre", entry.slug):
        return _not_covered("tree-cadastre")

    if not Settings().enable_tree_cadastre:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("tree_cadastre", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_trees(request.app.state.http, slug=entry.slug)

    raw, status = await client.fetch("tree_cadastre", key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Quelle 'tree_cadastre' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_trees(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="tree_cadastre")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/population-density")
async def city_population_density(slug: str, request: Request) -> dict:
    """Liefert die Einwohnerdichte je Stadt aus dem Zensus-2022-100m-Gitter.

    Ablauf (DATA-OSM-Tier-2): Register-Lookup (unbekannter Slug -> 404), Quellen-
    Toggle (deaktiviert -> 200 ``disabled``), resilienter Fetch (server-seitige
    Aggregation über die Gitterzellen mit der Stadt-AGS: Summe Einwohner + Zahl
    bewohnter Zellen), Mapping (bewohnte Fläche + Dichte je km2). Flächendeckend
    (jede Stadt hat eine AGS); liefert eine Stadt keine Gitterzellen, ist
    ``source_status="no_data"`` (data=null). Toter Upstream ohne Cache -> 503 mit
    Hint auf GET /api/v1/health."""
    entry = get_city(slug)

    if not Settings().enable_zensus_grid:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("zensus_grid", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_population_density(
            request.app.state.http, slug=entry.slug, ags=entry.ags
        )

    raw, status = await client.fetch("zensus_grid", key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Quelle 'zensus_grid' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # Keine bewohnten Zellen -> ehrlich no_data (data=null), kein leeres "ok".
    if not raw.get("populated_cells"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
                "cache_status": status,
            },
        }

    record = map_population_density(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="zensus_grid")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/traffic", deprecated=True)
async def city_traffic(slug: str, request: Request, response: Response) -> dict:
    """Liefert Baustellen + Verkehrsmeldungen im kanonischen Envelope (DATA-07/08).

    Ablauf (DATA-07/08/06, API-01, GOV-02): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    über die Fassade gegen die keylose Autobahn-API (Multi-Road + BBox um den
    Register-Geo), Mapping mit DL-DE/BY-Attribution, dann der Daten-Envelope mit
    Attribution.
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/traffic")

    # Coverage-Guard (Owner 2026-06-13): die Autobahn-Verkehrslage deckt nur Städte
    # mit kuratierten Autobahnen ab (_CITY_ROADS, dieselbe Map wie webcams). Eine
    # nicht-abgedeckte Stadt liefert ehrlich not_covered (200) + covered_cities,
    # statt eines leeren "ok". Vor dem Toggle: die Abdeckung ist strukturell.
    if not is_covered("traffic", entry.slug):
        return _not_covered("traffic")

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_autobahn:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("autobahn", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_traffic(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch("autobahn", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'autobahn' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # include=geometry-Opt-in (quick-260706-g9q): die Roh-Polyline bleibt nur auf
    # ausdruecklichen Wunsch erhalten (Default schlank). Kanalunabhaengig (kein
    # GPT-/MCP-Raten), gegen feste Werte gematcht (T-g9q-03: kein roher String).
    qp = request.query_params
    include_geometry = qp.get("include") == "geometry" or (
        (qp.get("full") or "").strip().lower() in ("1", "true", "yes")
    )

    record = map_autobahn_traffic(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        include_geometry=include_geometry,
    )
    await append_record(record, source="autobahn")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


async def _bremen_road_events(entry, request: Request) -> dict:
    """Archivierter Bremen-road-events-Pfad über den Mobilithek-mTLS-Pull (DATA-31).

    Anders als die keylosen road-events-Städte kommt Bremen über den
    Mobilithek-mTLS-Pull (VMZ Bremen, DATEX II SituationPublication). Wird aber wie
    die anderen archiviert (``append_record`` -> Analyst-Speisung). Graceful
    Degradation: Toggle aus ODER kein Cert (mTLS-Client) ODER keine Abo-ID -> 200
    ``source_status="disabled"``; keine Ereignisse -> 200 ``no_data`` OHNE
    ``append_record``; toter Upstream ohne Cache -> 503 mit Hint.
    """
    settings = Settings()
    cid = correlation_id.get()
    mobilithek_http = getattr(request.app.state, "mobilithek_http", None)
    abo_id = settings.bremen_roadworks_abo_id
    if not settings.enable_bremen_roadworks or mobilithek_http is None or not abo_id:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }

    client = request.app.state.resilient_client
    key = build_cache_key("bremen_roadworks", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_datex2(
            mobilithek_http,
            abo_id=abo_id,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            publication="situation",
        )

    raw, status = await client.fetch("bremen_roadworks", key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'bremen_roadworks' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )
    if not raw.get("events"):
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "no_data"},
        }
    record = map_bremen_road_events(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="bremen_roadworks")
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/road-events")
async def city_road_events(slug: str, request: Request) -> dict:
    """Liefert innerstädtische Baustellen/Sperrungen im kanonischen Envelope (DATA-15).

    Ablauf (DATA-15/06, API-01, GOV-02, DX-06): Register-Lookup
    (unbekannter Slug -> 404 mit Hint über den zentralen Handler), Connector-
    Lookup in ``CONNECTOR_MAP`` (kein Eintrag -> ehrliches 200
    ``source_status="no_data"``, keine Quelle für diese Stadt), Quellen-Toggle-
    Prüfung (deaktiviert -> 200 ``source_status="disabled"``, nie 5xx),
    resilienter Fetch über die Fassade gegen die keylose Quelle, Mapping mit
    DL-DE/BY-Attribution, dann der Daten-Envelope mit Attribution.

    Generischer Erweiterungsmechanismus (verbindlich): die Connector-Auswahl
    ((source, fetch_fn, mapper)) stammt aus ``CONNECTOR_MAP``; 09-06 ergänzt nur
    weitere Einträge, ohne diese Route-Logik zu ändern. Der Toggle wird generisch
    via ``getattr(Settings(), f"enable_{source}")`` geprüft.

    Leere ``events`` (Quelle erreichbar, aber keine Ereignisse) -> ehrliches
    200 ``source_status="no_data"`` OHNE Mapper und OHNE ``append_record`` (keine
    Datei, kein 5xx; analog zum Teilabdeckungs-Muster von ``city_water_level``).
    Toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)

    # Connector-Lookup: kein Eintrag für diese Stadt -> ehrliches not_covered (200)
    # + covered_cities (Owner 2026-06-13). Früher no_data; not_covered macht die
    # strukturell fehlende Abdeckung klar unterscheidbar von "Quelle erreichbar, aber
    # gerade keine Ereignisse" (das bleibt no_data, siehe unten). CONNECTOR_MAP und
    # die Coverage-Karte sind per Modul-Assertion (oben) synchron.
    connector = CONNECTOR_MAP.get(entry.slug)
    if connector is None:
        return _not_covered("road-events")

    # DATA-31: Bremen über den Mobilithek-mTLS-Pull (eigener Pfad), aber wie die
    # anderen archiviert (append_record -> Analyst). fetch_fn ist None (Marker).
    if entry.slug == "bremen":
        return await _bremen_road_events(entry, request)

    source, fetch_road_events, map_road_events = connector

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not getattr(Settings(), f"enable_{source}"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_road_events(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch(source, key, fetch_fn)

    # Pitfall: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            f"Quelle '{source}' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # Quelle erreichbar, aber keine Ereignisse -> ehrliches no_data (200) OHNE
    # Mapper und OHNE append_record. Es entsteht KEINE Datei und KEIN 5xx.
    if not raw.get("events"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = map_road_events(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source=source)

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


# Parking-Connector-Registry (DATA-40 / PARK-08): EINE deklarative Registry ersetzt
# die früheren drei getrennten Parking-Auflösungspfade (ParkenDD-Städteliste,
# Connector-Resolver, Mobilithek-Map). EIN Endpunkt je Stadt, Quelle je Stadt kuratiert.
# ``kind`` steuert die Fetch-Signatur:
#  - "http_direct": fetch_fn(http) (keylose Stadt-OpenData-Direktquellen)
#  - "mobidata":    fetch_fn(http, slug=, source_uids=, lat=, lon=) (MobiData BW)
#  - "http_geo":    fetch_fn(http, slug=, lat=, lon=) (München + ParkenDD-Übergang)
#  - "mobilithek":  fetch_fn(mtls, abo_id=, static_abo_id=, slug=) (DATEX II mTLS)
#  - "db_store":    Store-Lesung (kein fetch_fn/Upstream im Request-Pfad; DB BahnPark
#                   statischer Katalog aus dem täglichen Ingest-Snapshot)
# ``source`` ist zugleich die enable_<source>-Toggle-Basis UND das Cache-/Fassaden-
# Quellenlabel (build_cache_key stadt-scharf, T-25-25). source_uids/abo_attr/static_attr
# sind kind-spezifisch. Alle Werte stammen ausschließlich aus DIESER Registry (SSRF
# T-25-23, nie User-Input).
#
# ParkenDD-Übergang (Owner-Entscheid 2026-07-19): nur noch dresden (heute live, keine
# belegte Direktquelle) bleibt bis zur ParkenDD-Entfernung (25-08) über den
# ParkenDD-Adapter bedient. koeln ist seit 2026-07-23 (quick-260723-gaq) direkt auf
# Mobilithek DATEX II V2 umgestellt (upstream bei ParkenDD eingefroren 2021-09,
# lieferte no_data). hamburg ist seit 2026-07-19 direkt auf den keylosen
# geodienste.hamburg.de-WFS umgestellt (dl-de/by, Tier A). mannheim
# (NULL-Lizenz, T-25-26) und nicht gelistete Städte haben KEINEN Eintrag -> not_covered.
class ParkingConnector(NamedTuple):
    source: str
    kind: str  # "http_direct" | "mobidata" | "http_geo" | "mobilithek"
    # Heterogene Signaturen je kind -> Callable[..., Any] statt object (die
    # kind-Zweige unten rufen sie mit den passenden Argumenten auf). None nur
    # bei kind=db_store (Store-Lesung ohne Upstream-Call).
    fetch_fn: Callable[..., Any] | None
    mapper: Callable[..., Any]
    source_uids: tuple[str, ...] = ()
    abo_attr: str | None = None
    static_attr: str | None = None


PARKING_CONNECTORS: dict[str, ParkingConnector] = {
    # Stadt-OpenData-Direktquellen (keylos, parameterlose http-Adapter)
    "dortmund": ParkingConnector(
        "dortmund_parking", "http_direct", fetch_dortmund_parking, map_dortmund_parking
    ),
    "aachen": ParkingConnector(
        "aachen_parking", "http_direct", fetch_aachen_parking, map_aachen_parking
    ),
    "muenster": ParkingConnector(
        "muenster_parking", "http_direct", fetch_muenster_parking, map_muenster_parking
    ),
    "oldenburg": ParkingConnector(
        "oldenburg_parking",
        "http_direct",
        fetch_oldenburg_parking,
        map_oldenburg_parking,
    ),
    "kaiserslautern": ParkingConnector(
        "kaiserslautern_parking",
        "http_direct",
        fetch_kaiserslautern_parking,
        map_kaiserslautern_parking,
    ),
    "karlsruhe": ParkingConnector(
        "karlsruhe_parking",
        "http_direct",
        fetch_karlsruhe_parking,
        map_karlsruhe_parking,
    ),
    # Hamburg: keyloser HUP-WFS (dl-de/by, umgeht den api.hamburg.de-Block)
    "hamburg": ParkingConnector(
        "hamburg_parking", "http_direct", fetch_hamburg_parking, map_hamburg_parking
    ),
    # MobiData BW ParkAPI (source_uids je Stadt, 25-02 live-verifiziert)
    "freiburg-im-breisgau": ParkingConnector(
        "mobidata_parkapi",
        "mobidata",
        fetch_mobidata_parking,
        map_mobidata_parking,
        source_uids=("freiburg",),
    ),
    "heidelberg": ParkingConnector(
        "mobidata_parkapi",
        "mobidata",
        fetch_mobidata_parking,
        map_mobidata_parking,
        source_uids=("heidelberg",),
    ),
    "heilbronn": ParkingConnector(
        "mobidata_parkapi",
        "mobidata",
        fetch_mobidata_parking,
        map_mobidata_parking,
        source_uids=("heilbronn_goldbeck",),
    ),
    "ulm": ParkingConnector(
        "mobidata_parkapi",
        "mobidata",
        fetch_mobidata_parking,
        map_mobidata_parking,
        source_uids=("ulm_sensors",),
    ),
    # München: statischer CKAN-Standortkatalog (Fallback ohne Live-Belegung)
    "muenchen": ParkingConnector(
        "muenchen_parking", "http_geo", fetch_muenchen_parking, map_muenchen_parking
    ),
    # Mobilithek mTLS (DATEX II); Abo-gated -> disabled ohne Cert/Abo-ID
    "frankfurt-am-main": ParkingConnector(
        "frankfurt_parking",
        "mobilithek",
        fetch_frankfurt_parking,
        map_frankfurt_parking,
        abo_attr="frankfurt_parking_abo_id",
        static_attr="frankfurt_parking_static_abo_id",
    ),
    "wuppertal": ParkingConnector(
        "wuppertal_parking",
        "mobilithek",
        fetch_wuppertal_parking,
        map_wuppertal_parking,
        abo_attr="wuppertal_parking_abo_id",
        static_attr="wuppertal_parking_static_abo_id",
    ),
    "magdeburg": ParkingConnector(
        "magdeburg_parking",
        "mobilithek",
        fetch_magdeburg_parking,
        map_magdeburg_parking,
        abo_attr="magdeburg_parking_abo_id",
        static_attr="magdeburg_parking_static_abo_id",
    ),
    # koeln: seit 2026-07-23 (quick-260723-gaq) direkt Mobilithek DATEX II V2
    # (ParkenDD-Upstream eingefroren 2021-09, lieferte no_data)
    "koeln": ParkingConnector(
        "koeln_parking",
        "mobilithek",
        fetch_koeln_parking,
        map_koeln_parking,
        abo_attr="koeln_parking_abo_id",
        static_attr="koeln_parking_static_abo_id",
    ),
    # ParkenDD-Übergang bis 25-08 (Owner-Entscheid 2026-07-19; kein Live-Regress):
    # nur noch dresden
    "dresden": ParkingConnector("parkendd", "http_geo", fetch_parkendd, map_parkendd),
    # DB BahnPark statischer Katalog (kind "db_store": Store-Lesung ohne Upstream-Call
    # im Request-Pfad; täglicher Ingest schreibt den Snapshot). free=None (nur
    # statische Kapazität), Tier A dl-de/by. Nur Register-Städte ohne andere Quelle.
    **{
        slug: ParkingConnector("db_bahnpark", "db_store", None, map_db_bahnpark)
        for slug in (
            "berlin",
            "bochum",
            "bonn",
            "bremen",
            "duesseldorf",
            "duisburg",
            "erfurt",
            "essen",
            "hannover",
            "mainz",
            "saarbruecken",
            "schwerin",
            "stuttgart",
            "wiesbaden",
        )
    },
}


# Drift-Schutz (verbindlich, wie CONNECTOR_MAP/GBFS_SYSTEMS): Registry und Coverage-
# Karte MÜSSEN deckungsgleich sein, sonst fällt eine Stadt still auf not_covered oder
# eine Route zeigt ins Leere (T-25-24). Echtes raise (greift auch unter python -O).
if set(PARKING_CONNECTORS) != set(PARTIAL_COVERAGE["parking"]):
    raise RuntimeError(
        "PARKING_CONNECTORS und PARTIAL_COVERAGE['parking'] sind divergiert: "
        f"{set(PARKING_CONNECTORS) ^ set(PARTIAL_COVERAGE['parking'])}"
    )


@router.get("/cities/{slug}/parking")
async def city_parking(slug: str, request: Request) -> dict:
    """Liefert Parkhaus-Daten je Stadt im kanonischen Envelope (DATA-40, Dedup).

    EIN Parking-Endpunkt mit Quellen-Fallback (löst das frühere
    /live/dortmund/parking ab): bevorzugt ParkenDD-Live-Belegung (frei/gesamt je
    Parkhaus, ~22 Städte keylos, Lizenz pro Stadt am Ursprung verifiziert), für
    München den statischen CKAN-Standortkatalog (Fallback ohne Live-Belegung,
    Tier A DL-DE/BY) und für Frankfurt am Main/Wuppertal/Magdeburg/Köln die
    Mobilithek-mTLS-Quellen (DATEX II, statisch+dynamisch gejoint; bislang nur
    als /live-Routen erreichbar, Lücken-Schluss 2026-07-02; Köln seit
    2026-07-23 direkt statt ParkenDD).

    Ablauf wie ``city_road_events``: Register-Lookup (404 bei unbekanntem Slug),
    Coverage-/Connector-Prüfung (nicht abgedeckt -> 200 ``not_covered`` +
    covered_cities), Quellen-Toggle (aus -> 200 ``disabled``; bei den
    Mobilithek-Städten auch ohne Cert/Abo-ID), resilienter Fetch
    über die Fassade, Mapping. Quelle erreichbar aber leer -> ``no_data``; toter
    Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint. KEIN Archiv-Write
    (Live-/Standortdaten).
    """
    entry = get_city(slug)

    conn = PARKING_CONNECTORS.get(entry.slug)
    if conn is None:
        return _not_covered("parking")

    settings = Settings()
    source = conn.source
    map_parking = conn.mapper

    # Quellen-Toggle aus -> ehrliches disabled (200, nie 5xx).
    if not getattr(settings, f"enable_{source}", False):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    if conn.kind == "db_store":
        # Statischer Katalog (DB BahnPark): Store-Lesung, KEIN Upstream-Call im
        # Request-Pfad (T-25-19). Snapshot aus dem Daten-Volume, sonst committeter
        # Seed; leerer Slug -> no_data unten. Kein Cache/Breaker nötig (Datei-Read).
        raw = {
            "slug": entry.slug,
            "as_of": None,
            "facilities": load_db_bahnpark(settings.db_bahnpark_store_path).get(
                entry.slug, []
            ),
        }
        status = "STORE"
    else:
        http = request.app.state.http
        fetch_upstream = conn.fetch_fn
        if fetch_upstream is None:
            # Nie erreichbar: fetch_fn=None gibt es nur bei kind=db_store, und der
            # ist oben bedient. Guard fuer die statische Optional-Kette (pyright).
            raise RuntimeError(f"Connector {source} ohne fetch_fn")
        if conn.kind == "mobilithek":
            # mTLS + Abo-Paar; ohne Cert/Abo-ID ehrlich disabled (Graceful Degrade).
            mobilithek_http = getattr(request.app.state, "mobilithek_http", None)
            # abo_attr/static_attr sind bei kind=mobilithek in der Registry immer
            # gesetzt; der None-Zweig existiert fuer die Optional-Kette.
            abo_id = getattr(settings, conn.abo_attr) if conn.abo_attr else None
            if mobilithek_http is None or not abo_id:
                return {
                    "data": None,
                    "meta": {
                        "correlation_id": correlation_id.get(),
                        "source_status": "disabled",
                    },
                }

            async def fetch_fn():
                return await fetch_upstream(
                    mobilithek_http,
                    abo_id=abo_id,
                    static_abo_id=(
                        getattr(settings, conn.static_attr)
                        if conn.static_attr
                        else None
                    ),
                    slug=entry.slug,
                )
        elif conn.kind == "mobidata":

            async def fetch_fn():
                return await fetch_upstream(
                    http,
                    slug=entry.slug,
                    source_uids=list(conn.source_uids),
                    lat=entry.geo.lat,
                    lon=entry.geo.lon,
                )
        elif conn.kind == "http_geo":

            async def fetch_fn():
                return await fetch_upstream(
                    http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
                )
        else:  # http_direct: keyloser parameterloser Adapter

            async def fetch_fn():
                return await fetch_upstream(http)

        client = request.app.state.resilient_client
        key = build_cache_key(source, city_slug=entry.slug)

        raw, status = await client.fetch(source, key, fetch_fn)

        if raw is None:
            raise UpstreamError(
                f"Quelle '{source}' voruebergehend nicht erreichbar, kein gecachter "
                "Wert vorhanden.",
                hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
            )

    # Quelle erreichbar, aber kein Parkhaus -> ehrliches no_data (200).
    if not raw.get("facilities"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = map_parking(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


# eRound-Ladebelegung (DATA-42): Cap der Einzelpunkt-Liste (Muster heritage
# _COUNT_CAP). Hamburg hat ~2700 Ladepunkte; ``status_counts`` zählt IMMER alle
# gemeldeten Punkte, nur die points-Liste wird gekappt (``truncated`` ehrlich).
_CHARGING_STATUS_POINTS_CAP = 500


@router.get("/cities/{slug}/charging-status")
async def city_charging_status(slug: str, request: Request) -> dict:
    """Live-Ladesäulen-Belegung je Stadt (DATA-42, eRound AFIR, CC0/Tier A).

    Join aus zwei Zuständen, KEIN Upstream-Call im Request-Pfad:
    - Geo-Map (``charging/geomap``): refill_point_id -> Stadt + Koordinaten aus
      dem statischen eRound-Vollbestand (täglicher Ingest ins Daten-Volume,
      Fallback committeter Seed; alle 84 Städte abgedeckt).
    - Belegungs-State (``charging/store``): vom Hintergrund-Poller akkumulierte
      Deltas des dynamischen Abos (Drain-Queue), TTL 24 h = Staleness-Fenster.

    Toggle aus -> ``disabled``. Stadt ohne bekannte Ladepunkte ODER (noch) ohne
    akkumulierten Live-Status -> ehrliches ``no_data`` (200). Unbekannter Slug
    -> 404 (Register-Lookup). KEIN Archiv-Write (reine Live-Daten, T-20-ARCHIVE).
    """
    entry = get_city(slug)
    settings = Settings()
    source = SourceId.EROUND_CHARGING.value

    if not getattr(settings, f"enable_{source}", False):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    rp_map = load_city_points(settings.eround_geo_map_path).get(entry.slug) or {}
    statuses = (
        await get_point_statuses(request.app.state.redis, rp_map.keys())
        if rp_map
        else {}
    )

    # Keine bekannten Ladepunkte im Stadtumkreis ODER noch kein akkumulierter
    # Live-Status (Poller frisch gestartet/TTL abgelaufen) -> ehrliches no_data.
    if not statuses:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    status_counts: dict[str, int] = {}
    points: list[dict] = []
    for rp_id in sorted(statuses):
        value = statuses[rp_id]
        state = str(value.get("status"))
        status_counts[state] = status_counts.get(state, 0) + 1
        coords = rp_map.get(rp_id) or [None, None]
        points.append(
            {
                "refill_point_id": rp_id,
                "lat": coords[0],
                "lon": coords[1],
                "status": state,
                "observed_at": value.get("observed_at"),
            }
        )

    truncated = len(points) > _CHARGING_STATUS_POINTS_CAP
    raw = {
        "slug": entry.slug,
        "total_points": len(rp_map),
        "reported_points": len(statuses),
        "status_counts": status_counts,
        "points": points[:_CHARGING_STATUS_POINTS_CAP],
        "truncated": truncated,
    }
    record = map_city_charging_status(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        geo=entry.geo,
    )

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


# Bike-Counts-Connector-Auflösung (DATA-40): EIN /cities/{slug}/bike-counts-
# Endpunkt mit Per-Stadt-Quelle (kommunale Radzähl-Open-Data, KEIN Eco-Counter:
# dessen Lizenz ist ungeklärt -> Owner-Entscheidung 2026-06-23 "ausschliessen").
# Jede Quelle ist am Ursprung lizenz-verifiziert (Tier im Mapper). Eintrag:
# slug -> (source, fetch_factory(http, entry) -> raw, mapper). Die fetch_factory
# kapselt die je Quelle leicht abweichende Adapter-Signatur (z.B. München braucht
# das Jahr für das CKAN-Paket). Nicht aufgelöster Slug -> not_covered.
async def _fetch_muenchen_bike_counts(http, entry) -> dict:
    """Adapter-Wrapper Muenchen: injiziert das aktuelle Jahr (CKAN-Jahres-Paket)."""
    return await fetch_muenchen_bike_counts(
        http,
        slug=entry.slug,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
        year=datetime.now(UTC).year,
    )


async def _fetch_leipzig_bike_counts(http, entry) -> dict:
    """Adapter-Wrapper Leipzig (Standard-Signatur)."""
    return await fetch_leipzig_bike_counts(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


async def _fetch_hamburg_bike_counts(http, entry) -> dict:
    """Adapter-Wrapper Hamburg (Standard-Signatur)."""
    return await fetch_hamburg_bike_counts(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


async def _fetch_berlin_bike_counts(http, entry) -> dict:
    """Adapter-Wrapper Berlin (Standard-Signatur)."""
    return await fetch_berlin_bike_counts(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


async def _fetch_stuttgart_bike_counts(http, entry) -> dict:
    """Adapter-Wrapper Stuttgart (Standard-Signatur)."""
    return await fetch_stuttgart_bike_counts(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


async def _fetch_koeln_bike_counts(http, entry) -> dict:
    """Adapter-Wrapper Köln (Standard-Signatur)."""
    return await fetch_koeln_bike_counts(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


async def _fetch_essen_bike_counts(http, entry) -> dict:
    """Adapter-Wrapper Essen (Standard-Signatur)."""
    return await fetch_essen_bike_counts(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


async def _fetch_duesseldorf_bike_counts(http, entry) -> dict:
    """Adapter-Wrapper Düsseldorf (Standard-Signatur)."""
    return await fetch_duesseldorf_bike_counts(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


def _resolve_bike_counts_connector(slug: str):
    """Liefert ``(source, fetch_factory, map_fn)`` für bike-counts oder None."""
    if slug == "muenchen":
        return (
            "muenchen_bike_counts",
            _fetch_muenchen_bike_counts,
            map_muenchen_bike_counts,
        )
    if slug == "leipzig":
        return (
            "leipzig_bike_counts",
            _fetch_leipzig_bike_counts,
            map_leipzig_bike_counts,
        )
    if slug == "hamburg":
        return (
            "hamburg_bike_counts",
            _fetch_hamburg_bike_counts,
            map_hamburg_bike_counts,
        )
    if slug == "berlin":
        return ("berlin_bike_counts", _fetch_berlin_bike_counts, map_berlin_bike_counts)
    if slug == "stuttgart":
        return (
            "stuttgart_bike_counts",
            _fetch_stuttgart_bike_counts,
            map_stuttgart_bike_counts,
        )
    if slug == "koeln":
        return ("koeln_bike_counts", _fetch_koeln_bike_counts, map_koeln_bike_counts)
    if slug == "essen":
        return ("essen_bike_counts", _fetch_essen_bike_counts, map_essen_bike_counts)
    if slug == "duesseldorf":
        return (
            "duesseldorf_bike_counts",
            _fetch_duesseldorf_bike_counts,
            map_duesseldorf_bike_counts,
        )
    return None


@router.get("/cities/{slug}/bike-counts")
async def city_bike_counts(slug: str, request: Request) -> dict:
    """Liefert Radzählstellen-Daten je Stadt im kanonischen Envelope (DATA-40).

    Per-Stadt-Quelle aus kommunalen Radzähl-Open-Data (Dauerzählstellen), je
    Ursprung lizenz-verifiziert (Tier im Mapper). Eco-Counter/Eco-Visio ist
    bewusst NICHT eingebunden (Lizenz ungeklärt, Owner-Entscheidung). Ablauf wie
    ``city_parking``: Register-Lookup (404 bei unbekanntem Slug), Connector-/
    Coverage-Prüfung (nicht abgedeckt -> 200 ``not_covered`` + covered_cities),
    Toggle-Guard (aus -> 200 ``disabled``), resilienter Fetch über die Fassade,
    Mapping. Quelle erreichbar aber ohne Station -> ``no_data``; toter Upstream
    ohne Cache -> 503 mit selbst-korrigierendem Hint. KEIN Archiv-Write (Live-/
    Zähldaten).
    """
    entry = get_city(slug)

    connector = _resolve_bike_counts_connector(entry.slug)
    if connector is None:
        return _not_covered("bike-counts")
    source, fetch_factory, map_counts = connector

    if not getattr(Settings(), f"enable_{source}"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_factory(request.app.state.http, entry)

    raw, status = await client.fetch(source, key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            f"Quelle '{source}' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # Quelle erreichbar, aber keine Zählstelle -> ehrliches no_data (200).
    if not raw.get("stations"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = map_counts(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/office-wait-times")
async def city_office_wait_times(slug: str, request: Request) -> dict:
    """Liefert Behoerden-Wartezeiten je Stadt im kanonischen Envelope (Quick-jgt).

    Live-Wartezeiten der Kundenzentren + Kfz-Zulassungsstelle. Aktuell NUR Koeln
    abgedeckt (keyloser Direkt-Feed waiting-od.php, DL-DE/Zero 2.0, Tier A). Ablauf
    wie ``city_bike_counts``: Register-Lookup (404 bei unbekanntem Slug), Coverage-
    Pruefung (nicht abgedeckt -> 200 ``not_covered`` + covered_cities), Toggle-Guard
    (aus -> 200 ``disabled``), resilienter Fetch ueber die Fassade, Mapping. Quelle
    erreichbar aber ohne Standort -> ``no_data``; toter Upstream ohne Cache -> 503
    mit selbst-korrigierendem Hint. KEIN Archiv-Write (reine Live-Daten).
    """
    entry = get_city(slug)

    if not is_covered("office-wait-times", entry.slug):
        return _not_covered("office-wait-times")

    source = SourceId.KOELN_WAIT_TIMES.value
    if not getattr(Settings(), f"enable_{source}"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_koeln_wait_times(request.app.state.http)

    raw, status = await client.fetch(source, key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            f"Quelle '{source}' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # Quelle erreichbar, aber kein Standort -> ehrliches no_data (200).
    if not raw.get("items"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = map_koeln_wait_times(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


# --------------------------------------------------------------------------- #
# Quick-260729-muc: ruhender Verkehr Muenchen (drei Datenarten)                #
# --------------------------------------------------------------------------- #
# Alle drei folgen demselben Ablauf wie ``city_office_wait_times`` (Register-
# Lookup, Coverage-Pruefung, Toggle-Guard, resilienter Fetch, Mapping) und teilen
# ihn deshalb ueber diesen Helfer, statt ihn dreimal zu wiederholen. Reine
# Stammdaten der Landeshauptstadt Muenchen: KEIN Archiv-Write, keine
# Live-Belegung (die veroeffentlicht Muenchen nicht offen, Stand 2026-07-29).
async def _muenchen_ruhver_resource(
    slug: str,
    request: Request,
    *,
    resource: str,
    source_id: SourceId,
    fetch,
    mapper,
    data_keys: tuple[str, ...],
) -> dict:
    """Liefert eine Muenchner Ruhender-Verkehr-Datenart im kanonischen Envelope.

    ``resource`` ist der Katalog-Key (Coverage + not_covered-Hinweis),
    ``source_id`` traegt Toggle-Name und Cache-Key, ``data_keys`` nennt die
    Roh-Listen, die ueber "Daten vorhanden" entscheiden: sind alle leer, ist die
    Antwort ein ehrliches ``no_data`` (200) statt eines leeren Payloads.

    Unbekannter Slug -> 404 (zentraler Handler), Stadt ohne Abdeckung -> 200
    ``not_covered`` samt ``covered_cities``, Quelle abgeschaltet -> 200
    ``disabled``, toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint.
    """
    entry = get_city(slug)

    if not is_covered(resource, entry.slug):
        return _not_covered(resource)

    source = source_id.value
    if not getattr(Settings(), f"enable_{source}"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch(source, key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            f"Quelle '{source}' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # Quelle erreichbar, aber alle Listen leer -> ehrliches no_data (200).
    if not any(raw.get(k) for k in data_keys):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = mapper(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/parking-onstreet")
async def city_parking_onstreet(slug: str, request: Request) -> dict:
    """Liefert den bewirtschafteten Strassenparkraum je Stadt (Quick-muc).

    Parkseiten (Strassenabschnitte mit Stellplatzanzahl und Parkregelung),
    Parkraummanagementgebiete, Behindertenparkplaetze und Halteflaechen zum
    Laden, Liefern, Leisten. Aktuell NUR Muenchen abgedeckt (vier keylose
    WFS-Layer des Mobilitaetsreferats, DL-DE/BY 2.0, Tier A). Ausgeliefert werden
    Gesamtsummen plus drei Aggregate (je Parkregelung, je Strasse, je Gebiet),
    nicht die fuenfstellige Rohsegment-Liste.
    """
    return await _muenchen_ruhver_resource(
        slug,
        request,
        resource="parking-onstreet",
        source_id=SourceId.MUENCHEN_PARKING_ONSTREET,
        fetch=fetch_muenchen_parking_onstreet,
        mapper=map_muenchen_parking_onstreet,
        data_keys=("segments", "zones", "accessible", "loading"),
    )


@router.get("/cities/{slug}/park-and-ride")
async def city_park_and_ride(slug: str, request: Request) -> dict:
    """Liefert P+R- und B+R-Anlagen je Stadt (Quick-muc).

    Stellplatzzahlen, Bauform, Einfahrtshoehe, Preise, OePNV-Anbindung und die
    Belegungsprognose je Tagesart und Zeitscheibe. Aktuell NUR Muenchen abgedeckt
    (drei keylose CKAN-Pakete der P+R Park & Ride GmbH Muenchen, DL-DE/BY 2.0,
    Tier A). Die Prognose stammt aus historischen Erfahrungswerten und ist KEINE
    Echtzeit-Belegung.
    """
    return await _muenchen_ruhver_resource(
        slug,
        request,
        resource="park-and-ride",
        source_id=SourceId.MUENCHEN_PARK_AND_RIDE,
        fetch=fetch_muenchen_park_and_ride,
        mapper=map_muenchen_park_and_ride,
        data_keys=("car_rows", "bike_rows"),
    )


@router.get("/cities/{slug}/mobility-points")
async def city_mobility_points(slug: str, request: Request) -> dict:
    """Liefert Mobilitaetspunkte und Carsharing-Parkflaechen je Stadt (Quick-muc).

    Je Mobilitaetspunkt die gebuendelten Angebote (Carsharing-Stellplaetze,
    Ladepunkte, Abstellflaechen fuer geteilte Mikromobilitaet, Radservice,
    OePNV-Anbindung) plus die allgemeinen und stationsbasierten
    Carsharing-Parkflaechen. Aktuell NUR Muenchen abgedeckt (drei keylose
    WFS-Layer des Mobilitaetsreferats, DL-DE/BY 2.0, Tier A).
    """
    return await _muenchen_ruhver_resource(
        slug,
        request,
        resource="mobility-points",
        source_id=SourceId.MUENCHEN_MOBILITY_POINTS,
        fetch=fetch_muenchen_mobility_points,
        mapper=map_muenchen_mobility_points,
        data_keys=("points", "carsharing_general", "carsharing_station"),
    )


@router.get("/cities/{slug}/bike-parking")
async def city_bike_parking(slug: str, request: Request) -> dict:
    """Liefert Radabstellanlagen je Stadt (Quick-mrp).

    Bestand an Fahrrad- und Lastenradabstellanlagen mit Stellplatzsumme, Bauform,
    Ueberdachung, Doppelstock, Beleuchtung, zeitlicher Begrenzung und
    Bike-and-Ride-Kennzeichnung, dazu die zwanzig groessten Standorte. Aktuell NUR
    Muenchen abgedeckt (zwei keylose WFS-Layer des Mobilitaetsreferats,
    DL-DE/BY 2.0, Tier A).

    Gezaehlt wird ausschliesslich der BESTAND. Geplante, abgebaute und ausser
    Betrieb genommene Anlagen fuehrt die Quelle im selben Layer; sie stehen als
    eigene Zahlen in der Antwort, gehen aber nicht in die Stellplatzsumme ein.
    """
    return await _muenchen_ruhver_resource(
        slug,
        request,
        resource="bike-parking",
        source_id=SourceId.MUENCHEN_BIKE_PARKING,
        fetch=fetch_muenchen_bike_parking,
        mapper=map_muenchen_bike_parking,
        data_keys=("bike", "cargo"),
    )


@router.get("/cities/{slug}/events")
async def city_events(slug: str, request: Request) -> dict:
    """Liefert destination.one-Stadt-Events im kanonischen Envelope (DATA-16, GOV-04).

    Ablauf (DATA-16/06, API-01, GOV-02/04, DX-06) nach dem
    ``city_road_events``-Muster:
    Register-Lookup (unbekannter Slug -> 404 mit Hint über den zentralen Handler),
    Toggle-Guard (Quelle aus -> 200 ``source_status="disabled"``, nie 5xx),
    resilienter Fetch über die Fassade gegen die KEYLOSE eT4.META-Such-
    API (Experience ``open-data``, frei zugänglich, verifiziert 2026-06-10),
    Mapping mit Pro-Record-Tier aus ``map_license``, dann der Daten-Envelope mit
    Attribution.

    KRITISCH (GOV-04, T-10-CONTAM): Das Tier kommt aus ``record.license_tier``
    (GOV-04-Backstop), sodass ein CC-BY-SA-Event korrekt als Tier B gekennzeichnet
    wird. Bei gemischten Lizenzen entsteht je Tier ein eigener Record.

    Graceful Degradation: leere/nur-Vergangenheit -> 200 ``source_status="no_data"``;
    toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).

    Die ``events``-Liste ist über ``limit`` (Default 50, max 200) + ``offset``
    paginierbar; ``meta.pagination`` weist total/returned/truncated ehrlich aus,
    Offset-Overflow -> leere Seite 200. Der Ausschnitt wird konsistent auf jeden
    ``meta.records``-Eintrag angewandt, damit der Envelope begrenzt bleibt.
    """
    entry = get_city(slug)

    # Account-gated Toggle-/Key-Guard frisch lesen (Settings() statt
    # app.state.settings, damit der per-Test gesetzte Env-Override greift).
    settings = Settings()
    client = request.app.state.resilient_client

    # destination.one ist keylos (Experience "open-data", nur Toggle); der
    # ebenfalls keylose Köln-Direkt-Feed ist ergänzend NUR für slug="koeln"
    # (D-02/D-06).
    destination_enabled = settings.enable_destination_one
    koeln_enabled = settings.enable_koeln_events and entry.slug == "koeln"

    # D-08: KEINE der relevanten Quellen aktiv -> 200 disabled, nie 5xx, keine
    # Datei. (Für Nicht-Köln-Slugs zählt nur destination.one.)
    if not destination_enabled and not koeln_enabled:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    records = []
    cache_status = None

    # --- Block 1: destination.one (bundesweit, account-gated) ---------------
    if destination_enabled:
        key = build_cache_key("destination_one", city_slug=entry.slug)
        # Serverseitiger Zukunftsfilter (D-07): heutiges Datum als Untergrenze;
        # der Mapper-Datums-Guard bleibt der zweite Backstop.
        events_date_from = datetime.now(UTC).date().isoformat()

        async def fetch_dest_fn():
            return await fetch_events(
                request.app.state.http,
                slug=entry.slug,
                lat=entry.geo.lat,
                lon=entry.geo.lon,
                date_from=events_date_from,
            )

        raw, status = await client.fetch("destination_one", key, fetch_dest_fn)

        # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
        # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
        if raw is None:
            raise UpstreamError(
                "Quelle 'destination_one' voruebergehend nicht erreichbar, kein "
                "gecachter Wert vorhanden.",
                hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
            )

        # Mapper liefert eine LISTE von Records (je Tier einen, D-05/GOV-04). Der
        # Zukunftsfilter (D-07) verwirft Vergangenheits-/Statistik-Events hier.
        dest_records = map_destination_one_events(
            raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
        )
        records.extend(dest_records)
        cache_status = status

    # --- Block 2: Köln-Events (keyloser Direkt-Feed, nur slug="koeln") -----
    if koeln_enabled:
        koeln_key = build_cache_key("koeln_events", city_slug=entry.slug)

        async def fetch_koeln_fn():
            return await fetch_koeln_events(
                request.app.state.http,
                slug=entry.slug,
                lat=entry.geo.lat,
                lon=entry.geo.lon,
            )

        koeln_raw, koeln_status = await client.fetch(
            "koeln_events", koeln_key, fetch_koeln_fn
        )

        # Pitfall 4: toter Köln-Upstream ohne Cache. Der Köln-Feed ist ein
        # ADDITIVER Block: lieferte destination.one bereits Records, degradiert
        # ein toter Köln-Feed graceful (Block übersprungen, kein 503). Nur wenn
        # Köln die EINZIGE relevante Quelle ist (kein destination.one-Record),
        # ist der tote Upstream ein 503 mit Hint (DX-06).
        if koeln_raw is None:
            if not records:
                raise UpstreamError(
                    "Quelle 'koeln_events' voruebergehend nicht erreichbar, kein "
                    "gecachter Wert vorhanden.",
                    hint=(
                        "Erneut versuchen oder GET /api/v1/health fuer Quellen-Status."
                    ),
                )
        # Nur bei vorhandenen Events einen Record bauen (leerer Feed -> kein
        # Record; das no_data-Verdict fällt unten gemeinsam mit Block 1).
        elif koeln_raw.get("events"):
            koeln_record = map_koeln_events(
                koeln_raw,
                retrieved_at=datetime.now(UTC),
                ags=entry.ags,
                wikidata_qid=entry.qid,
            )
            records.append(koeln_record)
            if cache_status is None:
                cache_status = koeln_status

    # Keine überlebenden Events aus irgendeiner Quelle (leer / nur
    # Vergangenheit) -> ehrliches no_data (200). KEIN 5xx.
    if not records:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    # H4 (GOV-04): data soll den freiest nutzbaren Record tragen. Die
    # Mapper-Tier-Gruppen entstehen in der Auftreten-Reihenfolge der Lizenzen im
    # Feed (nicht deterministisch), und Köln wird additiv angehängt -> records[0]
    # war zufällig (live z.B. Tier B). Stabil nach Tier (A<B<C) sortieren, damit
    # data den permissivsten Record trägt; meta.records bleibt vollständig.
    records.sort(key=lambda r: r.license_tier.value)

    # Die Quelle leitet sich aus der SourceId des Records ab
    # (destination_one bzw. koeln_events).
    for record in records:
        await append_record(record, source=record.source.value)

    data = records[0].model_dump(mode="json")
    meta = {
        "correlation_id": correlation_id.get(),
        "source_status": "ok",
        "cache_status": cache_status,
        "records": [r.model_dump(mode="json") for r in records],
    }
    # Listen-Paginierung (DATA-16): events-Liste begrenzen (meta.pagination bezieht
    # sich auf data == records[0]). Zusätzlich JEDEN meta.records-Eintrag auf
    # dieselbe Seite schneiden, sonst bleibt der Envelope über meta.records groß.
    p = parse_page_params(request)
    paginate_envelope(data, meta, p, list_key="events")
    for r in meta["records"]:
        events = r.get("payload", {}).get("events")
        if isinstance(events, list):
            # Vollausgabe (p.limit None: REST-Default / limit=all) -> nur ab offset
            # schneiden, kein oberes Limit (``offset + None`` waere ein Typfehler).
            if p.limit is None:
                r["payload"]["events"] = events[p.offset :]
            else:
                r["payload"]["events"] = events[p.offset : p.offset + p.limit]
    return {"data": data, "meta": meta}


@router.get("/cities/{slug}/webcams", deprecated=True)
async def city_webcams(slug: str, request: Request, response: Response) -> dict:
    """Liefert Autobahn-Live-Webcams im kanonischen Envelope (DATA-22).

    Ablauf (DATA-22/06, API-01, GOV-02, DX-06) nach dem ``city_water_level``-
    no_data-Muster: Register-Lookup (unbekannter Slug -> 404 mit Hint über den
    zentralen Handler), Quellen-Toggle-Prüfung (``enable_autobahn_webcam`` aus ->
    200 ``source_status="disabled"``, nie 5xx), resilienter Fetch über die Fassade
    gegen die keylose Autobahn-Webcam-API (BBox um den Register-Geo), Mapping über
    ``map_autobahn_webcams``, dann der Daten-Envelope mit Attribution.

    KRITISCH (Decision 3, Pitfall 1): Webcams sind ein Live-Bild-Feature. Diese
    Route gibt das Live-Bild direkt aus (Feature-Entscheidung, KEIN Tier-Downgrade;
    license_tier bleibt A). Ein leeres ``webcams``-Array ist NORMAL
    (Live-Realität) -> ehrliches 200 ``source_status="no_data"`` OHNE Mapper.
    Toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/webcams")

    # Coverage-Guard (Owner 2026-06-13): Autobahn-Webcams decken nur Städte mit
    # kuratierten Autobahnen ab (_CITY_ROADS, dieselbe Map wie traffic). Eine
    # nicht-abgedeckte Stadt liefert ehrlich not_covered (200) + covered_cities,
    # statt eines leeren "ok". Vor dem Toggle: die Abdeckung ist strukturell.
    if not is_covered("webcams", entry.slug):
        return _not_covered("webcams")

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_autobahn_webcam:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("autobahn_webcam", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_webcams(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch("autobahn_webcam", key, fetch_fn)

    # Pitfall: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'autobahn_webcam' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # KRITISCH (Decision 3, Pitfall 1): leeres webcams-Array (Live-Realität) ->
    # ehrliches no_data (200) OHNE Mapper. KEIN 5xx.
    if not raw.get("webcams"):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = map_autobahn_webcams(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    # KRITISCH (Decision 3): Webcams = Live-Bild-Feature. Der Envelope wird direkt
    # zurückgegeben (Feature-Entscheidung, kein Tier-Downgrade; license_tier bleibt A).

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


def _transit_haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Grosskreis-Distanz in km zwischen zwei WGS84-Punkten (rein, deterministisch).

    Lokaler Nachbau des Vorbilds ``_haversine_km`` aus adapters/destination_one.py
    (die private Funktion wird bewusst NICHT importiert, um keine Modul-Kopplung
    quer durch die Codebasis zu ziehen).
    """
    earth_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * earth_km * math.asin(math.sqrt(a))


def _parse_near_param(raw: str) -> tuple[float, float]:
    """Parst ``near="lat,lon"`` zu (lat, lon) mit WGS84-Bounds-Pruefung.

    Fehlerhaftes Format ODER Werte ausserhalb lat[-90,90]/lon[-180,180] ->
    ``ValidationFailedError`` (400 invalid_request), BEVOR gerechnet wird
    (T-eqr-VAL). Kein roher User-String erreicht die Distanz-Rechnung.
    """
    hint = "Erwartet: near=lat,lon (z.B. near=52.52,13.405)."
    parts = raw.split(",", 1)
    if len(parts) != 2:
        raise ValidationFailedError(
            f"Ungueltiger Wert fuer 'near': '{raw}'.", hint=hint
        )
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except (TypeError, ValueError):
        raise ValidationFailedError(
            f"Ungueltiger Wert fuer 'near': '{raw}'.", hint=hint
        ) from None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise ValidationFailedError(
            f"Koordinaten ausserhalb des gueltigen Bereichs: '{raw}'.",
            hint="lat in [-90,90], lon in [-180,180].",
        )
    return lat, lon


@router.get("/cities/{slug}/transit")
async def city_transit(slug: str, request: Request) -> dict:
    """Liefert vorverarbeitete ÖPNV-Haltestellen im kanonischen Envelope (DATA-05).

    Ablauf (DATA-05/06, API-01, GOV-02): Register-Lookup (unbekannter Slug -> 404
    mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung (beide Quellen
    aus -> 200 ``source_status=disabled``, nie 5xx), dann ein memory-armer
    Read über ``read_stops`` je aktivierter Quelle (DELFI und/oder HVV).

    KRITISCH: Diese Route liest AUSSCHLIESSLICH aus dem vorverarbeiteten
    Datensatz, NIE aus der GTFS-ZIP, und ruft KEINEN resilient_client auf (kein
    Live-Upstream). Der Datensatz wird offline aktualisiert.

    Drei ``source_status``-Werte:
    - ``disabled``: beide Quellen per Env-Toggle aus -> data None
    - ``not_ingested``: Quelle aktiv, aber noch kein Snapshot (Datei fehlt ->
      ``read_stops`` liefert []) -> data leer, KEIN 5xx
    - ``ok``: vorverarbeitete Stops vorhanden -> data nicht leer, je Element
      Attribution + license_id

    Suche/Filter/Paginierung (Paket 260706-eqr), damit man eine Haltestelle
    gezielt findet statt die Vollliste (Berlin ~6,7 MB) zu ziehen:
    - ``?q=alsterdorf``: case-insensitive Substring-Filter auf ``stop_name``
      (reiner Python-``in``, KEIN Regex/eval aus User-String, T-eqr-INJ).
    - ``?near=lat,lon`` (+ optional ``?radius_m``, Default 1000): nur Stops im
      Umkreis, aufsteigend nach Distanz; Muell/Out-of-Bounds -> 400 (T-eqr-VAL).
    - Default (ohne q/near): erste Seite ueber ``parse_page_params`` (Default 50,
      Cap 200); ``meta.pagination`` weist total/returned/limit/offset/truncated
      ehrlich aus (No silent caps). ``source_status`` haengt am Vorhandensein
      eines Snapshots (VOR dem Filter), nicht am Filter-Ergebnis.
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: beide aus -> 200 disabled.
    s = Settings()
    if not (s.enable_delfi or s.enable_hvv):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Je aktivierter Quelle den vorverarbeiteten Snapshot lesen (NIE die ZIP).
    # Fehlende Datei -> [] (Batch nicht gelaufen) -> not_ingested, kein 5xx.
    records: list = []
    for source, enabled in (("delfi", s.enable_delfi), ("hvv", s.enable_hvv)):
        if enabled:
            records.extend(read_stops(entry.slug, source=source))

    # Snapshot-Status VOR dem Filtern ermitteln: "ok", sobald ueberhaupt ein
    # Snapshot existierte (auch wenn q/near danach 0 Treffer liefert), sonst
    # "not_ingested". So bleibt eine leere Trefferliste ehrlich "ok".
    status = "ok" if records else "not_ingested"

    # 1. q-Filter: case-insensitive Substring auf stop_name (reiner Python-`in`,
    #    KEIN eval/Regex-aus-User-String, T-eqr-INJ).
    q = request.query_params.get("q")
    if q and q.strip():
        needle = q.strip().lower()
        records = [r for r in records if needle in r.payload.stop_name.lower()]

    # 2. near-Filter: nur Stops im Umkreis, aufsteigend nach Distanz. Parsing +
    #    Bounds-Pruefung (T-eqr-VAL) BEVOR gerechnet wird; radius_m ueber denselben
    #    Validierungsstil wie parse_page_params (nicht-numerisch/<1 -> 400).
    near = request.query_params.get("near")
    if near is not None:
        near_lat, near_lon = _parse_near_param(near)
        radius_m = _parse_int_param(
            request.query_params.get("radius_m"),
            name="radius_m",
            minimum=1,
            default=1000,
        )
        radius_km = radius_m / 1000
        with_dist: list[tuple[float, object]] = []
        for r in records:
            if r.geo is None:
                continue  # Stops ohne Koordinate koennen nicht verortet werden.
            dist = _transit_haversine_km(near_lat, near_lon, r.geo.lat, r.geo.lon)
            if dist <= radius_km:
                with_dist.append((dist, r))
        with_dist.sort(key=lambda t: t[0])
        records = [r for _, r in with_dist]

    # 3. Paginierung auf der CanonicalRecord-Liste. paginate_envelope passt NICHT
    #    (data ist hier eine flache Record-Liste, kein payload-Envelope), daher
    #    paginate() + meta.pagination MANUELL in identischer Form setzen.
    p = parse_page_params(request)
    total = len(records)
    page = paginate(records, p, sort_whitelist=set())

    return {
        "data": [r.model_dump(mode="json") for r in page],
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": status,
            "pagination": {
                "total": total,
                "returned": len(page),
                "limit": p.limit,
                "offset": p.offset,
                "truncated": p.offset + len(page) < total,
            },
        },
    }


@router.get("/cities/{slug}/geo")
async def city_geo(slug: str) -> dict:
    """Liefert BKG-Verwaltungsgrenzen im kanonischen Envelope (DATA-19).

    Ablauf (DATA-19/06, API-01, GOV-02/03): Register-Lookup (unbekannter Slug -> 404
    mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung (deaktiviert ->
    200 ``source_status=disabled``, nie 5xx), dann ein memory-armer read-only
    Snapshot-Read über ``read_stops(slug, source="bkg")``.

    KRITISCH (kein Bulk-Upstream im Request-Pfad): Diese Route liest AUSSCHLIESSLICH
    aus dem vorverarbeiteten BKG-Datensatz, NIE aus der VG250-GeoJSON, und ruft
    KEINEN ``resilient_client`` auf. Der Datensatz wird offline aktualisiert.

    KRITISCH (Scope): NUR Grenzen + Namen + Fläche (AGS/GEN-Name/area_km2).
    Geocoding/PLZ ist BEWUSST NICHT enthalten (Tier-B/C-Geocoder Out of Scope).

    Drei ``source_status``-Werte:
    - ``disabled``: ``enable_bkg`` per Env-Toggle aus -> data None
    - ``not_ingested``: Quelle aktiv, aber noch kein Snapshot (Datei fehlt ->
      ``read_stops`` liefert []) -> data None, KEIN 5xx (Batch noch nicht gelaufen)
    - ``ok``: vorverarbeitete Verwaltungsgrenze vorhanden -> admin_boundary-Payload
      mit Attribution + license_id
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: aus -> 200 disabled, nie 5xx.
    s = Settings()
    if not s.enable_bkg:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Read-only-Snapshot aus dem bkg-Datensatz (NIE die GeoJSON).
    # Fehlende Datei -> [] -> not_ingested, kein 5xx.
    # record_id/content_hash werden im Reader gestrippt (extra=forbid).
    records = read_stops(entry.slug, source="bkg")
    status = "ok" if records else "not_ingested"

    return {
        "data": [r.model_dump(mode="json") for r in records] if records else None,
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": status,
        },
    }


@router.get("/cities/{slug}/election")
async def city_election(slug: str) -> dict:
    """Liefert Bundeswahl-Ergebnisse im kanonischen Envelope (DATA-20).

    Ablauf (DATA-20/06, API-01, GOV-02/03): Register-Lookup (unbekannter Slug ->
    404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), dann ein
    memory-armer read-only Snapshot-Read über
    ``read_stops(slug, source="bundeswahl")``.

    KRITISCH (kein Bulk-Upstream im Request-Pfad): Diese Route liest
    AUSSCHLIESSLICH aus dem vorverarbeiteten Bundeswahl-Datensatz, NIE aus der
    kerg-CSV, und ruft KEINEN ``resilient_client`` auf. Der Datensatz wird offline
    aktualisiert.

    KRITISCH (Pitfall 7, GOV-03): Die Granularität ist ehrlich "teilweise"
    (Wahlkreis/Kreis-Ebene, nur kreisfreie Städte stadtscharf, kommunale Ebene
    Out of Scope). Eine nicht-kreisfreie Stadt ohne Snapshot -> ``not_ingested``
    (ehrlich, kein 5xx). Granularität + Attribution stehen je Record-Payload.

    Drei ``source_status``-Werte:
    - ``disabled``: ``enable_bundeswahl`` per Env-Toggle aus -> data None
    - ``not_ingested``: Quelle aktiv, aber kein Snapshot (Datei fehlt ->
      ``read_stops`` liefert []) -> data None, KEIN 5xx (Batch nicht gelaufen)
    - ``ok``: vorverarbeitetes Wahlergebnis vorhanden -> election_result-Payload
      mit Attribution + license_id
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: aus -> 200 disabled, nie 5xx.
    s = Settings()
    if not s.enable_bundeswahl:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Read-only-Snapshot aus dem bundeswahl-Datensatz (NIE die kerg-CSV).
    # Fehlende Datei -> [] -> not_ingested, kein 5xx.
    # record_id/content_hash werden im Reader gestrippt (extra=forbid).
    records = read_stops(entry.slug, source="bundeswahl")
    status = "ok" if records else "not_ingested"

    return {
        "data": [r.model_dump(mode="json") for r in records] if records else None,
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": status,
        },
    }


@router.get("/cities/{slug}/holidays")
async def city_holidays(slug: str) -> dict:
    """Liefert gemeinfreie Feiertage + Schulferien im kanonischen Envelope (DATA-21).

    Ablauf (DATA-21/06, API-01, GOV-02/03): Register-Lookup (unbekannter Slug ->
    404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), dann ein
    Seed-Read über ``load_holidays(entry.state, jahr)`` aus den eingebetteten
    Seeds ``data/seeds/holidays_<jahr>.json`` + ``schulferien_<jahr>.json``.

    KRITISCH (kein Upstream im Request-Pfad, T-08-DEP): Diese Route liest
    AUSSCHLIESSLICH aus den committeten statischen Seeds via stdlib ``json``,
    ruft KEINE Laufzeit-Fremd-API auf, KEIN ``resilient_client``.

    KRITISCH (Gray-Area, GOV-02): Feiertage/Schulferien sind GEMEINFREIE Fakten
    (Tier C, nur Live-Anzeige), so in der Attribution markiert. Die Seeds sind
    statisch im Repo (kein DB-Schutzrecht).

    Drei ``source_status``-Werte:
    - ``disabled``: ``enable_holidays`` per Env-Toggle aus -> data None
    - ``no_data``: Quelle aktiv, aber keine Seed-Einträge für Bundesland/Jahr
      (z. B. fehlende Datei) -> data None, KEIN 5xx (ehrlich)
    - ``ok``: Seed-Einträge vorhanden -> holiday-Payload je entry.state mit
      Attribution + license_id (gemeinfrei, nicht permissiv lizenziert)
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: aus -> 200 disabled, nie 5xx.
    s = Settings()
    if not s.enable_holidays:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Jahr aus dem aktuellen Datum (statische Jahres-Seeds). Fehlende Seed-Daten
    # für Bundesland/Jahr -> leere Listen -> no_data (ehrlich, kein 5xx, kein
    # Fremd-API). Gemeinfreie statische Seeds.
    jahr = datetime.now(UTC).year
    data = load_holidays(entry.state, jahr)
    if not (data["holidays"] or data["school_holidays"]):
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = map_holidays(
        entry.state,
        jahr,
        data["holidays"],
        data["school_holidays"],
        slug=entry.slug,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/energy")
async def city_energy(slug: str, request: Request) -> dict:
    """Liefert MaStR-Energieanlagen im kanonischen Envelope (DATA-18).

    Ablauf (DATA-18/06, API-01, GOV-02/03): Register-Lookup (unbekannter Slug ->
    404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), dann ein
    parametrisierter Read über ``read_energy`` aus dem datierten vorverarbeiteten
    Datensatz (jüngster Snapshot via MAX(ingest_date)), optional gefiltert
    nach ``type`` (pv/wind/speicher/biogas).

    KRITISCH (kein Bulk-Upstream im Request-Pfad): Diese Route liest
    AUSSCHLIESSLICH aus dem vorverarbeiteten Datensatz, NIE aus der >1-GB-XML-ZIP,
    und ruft KEINEN ``resilient_client`` auf. Der Datensatz wird offline aktualisiert.

    Der gemappte Record ist die Live-Sicht auf den jüngsten Snapshot.

    Drei ``source_status``-Werte:
    - ``disabled``: ``enable_mastr`` per Env-Toggle aus -> data None
    - ``not_ingested``: Quelle aktiv, aber kein Snapshot (DB/Tabelle fehlt ->
      ``read_energy`` liefert []) -> data None, KEIN 5xx
    - ``ok``: vorverarbeitete Anlagen vorhanden -> gemappter energy_asset-Payload
      mit Attribution + license_id

    Die ``assets``-Liste ist über ``limit`` (Default 50, max 200) + ``offset``
    paginierbar; ``meta.pagination`` weist total/returned/truncated ehrlich aus,
    Offset-Overflow -> leere Seite 200. count/by_type/total_power_kw/power_by_type
    bleiben die vollen Snapshot-Aggregate (Aggregat != Seitenlänge).
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: aus -> 200 disabled.
    s = Settings()
    if not s.enable_mastr:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Optionaler Anlagen-Typ-Filter aus der Query (pv/wind/speicher/biogas).
    # Der Wert fließt parametrisiert in die SQLite-Query (?-Binding, T-08-SQLI),
    # nie roh in einen f-string.
    plant_type = request.query_params.get("type")

    # Parametrisierter Read aus dem vorverarbeiteten Datensatz (NIE die ZIP).
    # Fehlende DB/Tabelle -> [] -> not_ingested, kein 5xx.
    rows = read_energy(entry.slug, ags=entry.ags, plant_type=plant_type)

    if not rows:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_mastr_assets(
        entry.slug,
        rows,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )

    data = record.model_dump(mode="json")
    meta = {
        "correlation_id": correlation_id.get(),
        "source_status": "ok",
    }
    # Listen-Paginierung (DATA-18): assets-Liste begrenzen. delivered_count_field=
    # None -> count/by_type/total_power_kw/power_by_type bleiben die vollen
    # Snapshot-Aggregate (Auflage 2: Aggregat != Seitenlänge).
    p = parse_page_params(request)
    paginate_envelope(data, meta, p, list_key="assets")
    return {"data": data, "meta": meta}


@router.get("/cities/{slug}/vehicle-registrations")
async def city_vehicle_registrations(slug: str, request: Request) -> dict:
    """Liefert den KBA-Pkw-Bestand + Elektro-Anteil im kanonischen Envelope (DATA-27).

    Ablauf (analog ``city_energy``, API-01, GOV-02/03): Register-Lookup
    (unbekannter Slug -> 404 über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), dann ein
    parametrisierter Read über ``read_vehicle_registrations`` aus dem datierten
    Bulk-Datensatz (jüngster Snapshot via MAX(ingest_date)).

    KRITISCH (kein Bulk-Upstream im Request-Pfad): Diese Route liest
    AUSSCHLIESSLICH aus dem vorverarbeiteten Datensatz und ruft KEINEN
    ``resilient_client`` auf. Der Datensatz wird offline aktualisiert.

    Regionale Auflösung ist der Zulassungsbezirk (= Kreis/kreisfreie Stadt); der
    Payload weist ihn über ``district``/``district_key`` ehrlich aus. Drei
    ``source_status``-Werte:
    - ``disabled``: ``enable_kba`` per Env-Toggle aus -> data None
    - ``not_ingested``: Quelle aktiv, aber kein Snapshot für den Kreis der Stadt
      (DB/Tabelle/Zeile fehlt) -> data None, KEIN 5xx
    - ``ok``: Daten vorhanden -> gemappter vehicle_registration-Payload
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: aus -> 200 disabled.
    s = Settings()
    if not s.enable_kba:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Parametrisierter Read aus dem vorverarbeiteten Datensatz (NIE der Bulk-Pull).
    # Fehlende DB/Tabelle/Zeile -> None -> not_ingested, kein 5xx.
    row = read_vehicle_registrations(entry.slug, ags=entry.ags)

    if row is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_vehicle_registrations(
        entry.slug,
        row,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # Anders als die MaStR-Route schreibt KBA den gemappten Record zusätzlich in
    # die Tier-A-Tagespartition (wie SMARD): so wächst eine Tageszeitreihe, aus
    # der der nachgelagerte Analyst den Pkw-Bestand/Elektro-Anteil je Stufe lesen
    # kann. Die Per-Tag-Aggregation entdoppelt mehrfache Abrufe desselben Tages.
    await append_record(record, source="kba")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/accidents")
async def city_accidents(slug: str, request: Request) -> dict:
    """Liefert das Unfallatlas-Jahres-Aggregat je Stadt im Envelope (DATA-29).

    Ablauf wie ``city_vehicle_registrations`` (Store-read, KEIN resilient_client):
    Register-Lookup (unbekannt -> 404), Toggle-Prüfung (aus -> 200 disabled),
    parametrisierter Read über ``read_accidents`` aus dem Bulk-Datensatz (je
    5-stelligem Kreisschlüssel). Regionale Auflösung Kreis/kreisfreie Stadt
    (district_key). Drei ``source_status``: disabled / not_ingested (kein Snapshot
    für den Kreis) / ok. Der ok-Record wird zusätzlich ins Tier-A-Archiv
    geschrieben (Analyst-Speisung, wie KBA).
    """
    entry = get_city(slug)

    if not Settings().enable_unfallatlas:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    row = read_accidents(entry.slug, ags=entry.ags)
    if row is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_accidents(
        entry.slug,
        row,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    await append_record(record, source="unfallatlas")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/crime-stats")
async def city_crime_stats(slug: str, request: Request) -> dict:
    """Liefert die BKA-PKS-Kriminalstatistik je Stadt im Envelope (PKS-01).

    Ablauf wie ``city_accidents`` (Store-read, KEIN resilient_client): Register-
    Lookup (unbekannt -> 404), Toggle-Prüfung (aus -> 200 disabled),
    parametrisierter Read über ``read_crime_stats`` aus der offline befüllten
    SQLite-Kreis-Falltabelle (je 5-stelligem Kreisschlüssel). Geliefert werden je
    Hauptstraftatengruppe Fälle, Häufigkeitszahl (HZ, Fälle je 100.000
    Einwohner) und Aufklärungsquote (AQ in Prozent). Drei ``source_status``:
    disabled / not_ingested (kein Snapshot für den Kreis) / ok. Der ok-Record
    wird zusätzlich ins Tier-A-Archiv geschrieben (Analyst-Speisung, wie
    ``accidents``).
    """
    entry = get_city(slug)

    if not Settings().enable_bka_pks:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    row = read_crime_stats(entry.slug, ags=entry.ags)
    if row is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_crime_stats(
        entry.slug,
        row["groups"],
        reference_year=row["jahr"],
        version=row["version"],
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    await append_record(record, source="bka_pks")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/indicators")
async def city_indicators(slug: str, request: Request) -> dict:
    """Liefert die kuratierten INKAR/BBSR-Indikatoren je Stadt im Envelope (DATA-32).

    Ablauf wie ``city_vehicle_registrations``/``city_accidents`` (Store-read, KEIN
    resilient_client): Register-Lookup (unbekannt -> 404), Toggle-Prüfung (aus ->
    200 disabled), parametrisierter Read über ``read_indicators`` aus dem Bulk-
    Datensatz (je 5-stelligem Kreisschlüssel). Regionale Auflösung Kreis/
    kreisfreie Stadt. Drei ``source_status``:
    - ``disabled``: ``enable_inkar`` per Env-Toggle aus -> data None
    - ``not_ingested``: kein Snapshot für den Kreis der Stadt -> data None, kein 5xx
    - ``ok``: gemappter indicators-Payload (Liste der Kennzahlen je Kategorie)

    KRITISCH (kein Bulk-Upstream im Request-Pfad): liest AUSSCHLIESSLICH aus dem
    vorverarbeiteten Datensatz; der INKAR-Wizard-Pull läuft offline als Batch.
    """
    entry = get_city(slug)

    if not Settings().enable_inkar:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    rows = read_indicators(entry.slug, ags=entry.ags)
    if not rows:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_indicators(
        entry.slug,
        rows,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    await append_record(record, source="inkar")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


# Jahresspanne, die der Wegweiser-Bestand ueberhaupt kennt: Ist-Daten ab 2006,
# Bevoelkerungsprognosen bis 2040. Grenzen fuer die ?from=/?to=-Validierung.
_WEGWEISER_MIN_YEAR = 2006
_WEGWEISER_MAX_YEAR = 2040


def _wegweiser_year(request: Request, name: str) -> int | None:
    """Liest ``from``/``to`` aus der Query und validiert streng (Zero-Trust, #5).

    Erlaubt sind vier Ziffern in einem Bereich, den die Quelle überhaupt kennt
    (2006 bis 2040). Alles andere ist ein Eingabefehler und wird zu 400
    gemappt, statt still ein leeres Ergebnis zu liefern: ``?from=zwanzig`` als
    "keine Daten" auszugeben wäre irreführend.
    """
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return None
    try:
        year = int(raw)
    except ValueError:
        raise ValidationFailedError(
            f"Parameter '{name}' muss eine Jahreszahl sein (z.B. 2020)."
        ) from None
    if not (_WEGWEISER_MIN_YEAR <= year <= _WEGWEISER_MAX_YEAR):
        raise ValidationFailedError(
            f"Parameter '{name}' liegt ausserhalb des Bestands "
            f"({_WEGWEISER_MIN_YEAR} bis {_WEGWEISER_MAX_YEAR})."
        )
    return year


async def _wegweiser_dataset(slug: str, dataset: str, request: Request) -> dict:
    """Gemeinsamer Handler für alle Datenarten aus dem Wegweiser-Bulk (CC0).

    Bewusst EIN Handler statt einer Kopie je Datenart: die Datenarten
    unterscheiden sich ausschließlich in der Themen-Auswahl aus
    ``mappers.wegweiser.TOPIC_TO_DATASET``. Eine weitere Datenart ist damit ein
    Registry-Eintrag plus eine dreizeilige Route, kein neuer Handler.

    Optional grenzen ``?from=`` und ``?to=`` die Zeitreihe ein (beide inklusive).
    Ohne sie kommt die volle Reihe, damit bestehende Clients unverändert
    weiterlaufen. Für die großen Datenarten ist der Filter praktisch nötig:
    ``population-structure`` wiegt ungefiltert rund 90 KB, mit ``?from=2023``
    einen Bruchteil davon.

    Ablauf wie ``city_indicators`` (Store-read, KEIN resilient_client):
    Register-Lookup (unbekannt -> 404), Toggle-Prüfung (aus -> 200 disabled),
    parametrisierter Read über ``read_series`` aus dem Bulk. Drei
    ``source_status``:
    - ``disabled``: ``enable_wegweiser`` per Env-Toggle aus -> data None
    - ``not_ingested``: kein Snapshot für diese Stadt/Datenart -> data None,
      kein 5xx (gilt auch für die kreisangehörigen Städte, denen die Quelle
      einen Teil der Indikatoren nicht gemeindescharf liefert, und für ein
      Jahresfenster, in dem diese Stadt keine Werte hat)
    - ``ok``: gemappter indicator_series-Payload mit Zeitreihe je Indikator

    KRITISCH (kein Bulk-Upstream im Request-Pfad): liest AUSSCHLIESSLICH aus dem
    vorverarbeiteten Datensatz; der Wegweiser-Zug läuft offline als Jahresbatch.
    """
    entry = get_city(slug)
    year_from = _wegweiser_year(request, "from")
    year_to = _wegweiser_year(request, "to")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValidationFailedError(
            "Parameter 'from' darf nicht groesser als 'to' sein."
        )

    if not Settings().enable_wegweiser:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    rows = read_series(
        entry.slug,
        ags=entry.ags,
        indicators=dataset_indicators(dataset),
        year_from=year_from,
        year_to=year_to,
    )
    if not rows:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_indicator_series(
        entry.slug,
        rows,
        dataset=dataset,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    await append_record(record, source="wegweiser")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/sustainability")
async def city_sustainability(slug: str, request: Request) -> dict:
    """Liefert die Nachhaltigkeits-/SDG-Indikatoren je Stadt als Zeitreihe.

    53 Indikatoren aus dem Wegweiser Kommune (Bertelsmann Stiftung, CC0) zu den
    UN-Nachhaltigkeitszielen auf kommunaler Ebene: Flächeninanspruchnahme,
    Naherholungsflächen, erneuerbare Energie im Wohnungsneubau,
    Breitbandversorgung, Beschäftigung, Bildung, soziale Teilhabe und weitere.
    Jahresdaten, in der Regel 2006 bis 2023, je Indikator mit voller Reihe.
    Optional per ``?from=``/``?to=`` auf ein Jahresfenster eingrenzbar.
    """
    return await _wegweiser_dataset(slug, "sustainability", request)


@router.get("/cities/{slug}/population-structure")
async def city_population_structure(slug: str, request: Request) -> dict:
    """Altersaufbau der Stadt als Zeitreihe (Wegweiser Kommune, CC0).

    110 Indikatoren zum Ist-Zustand der Bevölkerung: Zahl und Anteil je
    Altersgruppe (von 0-2 bis ab 80), getrennt nach Geschlecht, nach
    Generationen, dazu Altenquotient und Jugendquotient. Ist-Daten ab 2006,
    Prognosewerte bis 2040.

    HINWEIS zur Größe: ungefiltert wiegt die Antwort rund 90 KB. Für einen
    einzelnen Stand lohnt ``?from=2023&to=2023``, für einen Verlauf reicht meist
    ein Ausschnitt wie ``?from=2015``.
    """
    return await _wegweiser_dataset(slug, "population-structure", request)


@router.get("/cities/{slug}/population-trend")
async def city_population_trend(slug: str, request: Request) -> dict:
    """Veränderung des Altersaufbaus als Zeitreihe (Wegweiser Kommune, CC0).

    70 Indikatoren zur Bewegung statt zum Bestand: Entwicklung der Altersgruppen
    (absolut und seit 2011, auch nach Geschlecht), Geburten- und Sterberate,
    Wanderungssaldo, Gesamtbevölkerungsentwicklung. Ergänzt
    ``population-structure`` um die Frage, wohin sich die Stadt bewegt.
    """
    return await _wegweiser_dataset(slug, "population-trend", request)


@router.get("/cities/{slug}/municipal-finance")
async def city_municipal_finance(slug: str, request: Request) -> dict:
    """Kommunale Finanzkennzahlen als Zeitreihe (Wegweiser Kommune, CC0).

    30 Indikatoren: Hebesätze für Gewerbe- und Grundsteuer, Steuereinnahmekraft,
    kommunale Schulden, Investitionen, Personal- und Sozialausgaben je
    Einwohner. Jahreswerte ab 2006.

    ABGRENZUNG: ``tax-rates`` (Regionalstatistik) bleibt die aktuellere Quelle
    für die reinen Hebesätze (Stichtag 2024-12-31 gegen 2023 hier). Diese
    Datenart liefert dafür die HISTORIE und den finanziellen Gesamtzusammenhang.
    """
    return await _wegweiser_dataset(slug, "municipal-finance", request)


@router.get("/cities/{slug}/labour-market")
async def city_labour_market(slug: str, request: Request) -> dict:
    """Arbeitsmarkt und Pendlerverflechtung als Zeitreihe (Wegweiser, CC0).

    40 Indikatoren: Arbeitslosenquoten (gesamt, Jugendliche, Langzeit,
    Ausländer), Beschäftigungsquoten nach Alter und Geschlecht, geringfügige
    Beschäftigung, Hochqualifizierte, Ein- und Auspendler.

    ABGRENZUNG: ``unemployment`` (GENESIS, Berichtsjahr 2025) bleibt die
    aktuellere Quelle für die reine Arbeitslosenzahl, ``indicators``
    (INKAR/BBSR) führt eigene Kennzahlen mit anderer Methodik. Hier steht der
    Verlauf ab 2006.
    """
    return await _wegweiser_dataset(slug, "labour-market", request)


@router.get("/cities/{slug}/integration")
async def city_integration(slug: str, request: Request) -> dict:
    """Integrationskennzahlen als Zeitreihe (Wegweiser Kommune, CC0).

    26 Indikatoren zur Lage von Menschen mit ausländischer Staatsangehörigkeit
    und Migrationshintergrund: Bevölkerungsanteile, Beschäftigung,
    Arbeitslosigkeit, Kinderbetreuung, Schulabschlüsse, Einbürgerungen.
    Jahreswerte ab 2006.
    """
    return await _wegweiser_dataset(slug, "integration", request)


@router.get("/cities/{slug}/childcare")
async def city_childcare(slug: str, request: Request) -> dict:
    """Kinderbetreuung als Zeitreihe (Wegweiser Kommune, CC0).

    20 Indikatoren: Betreuungsquoten für unter Dreijährige, 3- bis 5-Jährige und
    Schulkinder, getrennt nach Tageseinrichtung und Tagespflege sowie nach
    Betreuungsumfang (bis 25 h, 25 bis 35 h, mehr als 35 h), dazu Kinder mit
    Migrationshintergrund in Tageseinrichtungen. Jahreswerte ab 2006.

    Teilabdeckung: 83 der 84 Städte (Reutlingen fehlt in der Quelle).
    """
    return await _wegweiser_dataset(slug, "childcare", request)


@router.get("/cities/{slug}/education-stats")
async def city_education_stats(slug: str, request: Request) -> dict:
    """Bildungsstatistik als Zeitreihe (Wegweiser Kommune, CC0).

    33 Indikatoren: Schulabgänger nach Abschlussart (ohne Abschluss bis
    Hochschulreife), Übergangsquoten, Auszubildende, Ausbildungsplätze,
    Weiterbildungsbeteiligung. Jahreswerte ab 2006.

    NICHT zu verwechseln mit ``education``: dort liegen OSM-Schulstandorte als
    POIs mit Koordinaten, hier die amtliche Statistik.

    Teilabdeckung: 70 Städte. Die 14 kreisangehörigen Städte (Hannover, Aachen,
    Göttingen, ...) fehlen, weil die Quelle Bildungsdaten erst ab Kreisebene
    führt.
    """
    return await _wegweiser_dataset(slug, "education-stats", request)


@router.get("/cities/{slug}/social-situation")
async def city_social_situation(slug: str, request: Request) -> dict:
    """Soziale Lage als Zeitreihe (Wegweiser Kommune, CC0).

    17 Indikatoren: SGB-II-Quoten (gesamt, Kinder, Ältere), Altersarmut,
    Grundsicherung, Wohngeld, Schuldnerquote, Einkommensverteilung.
    Jahreswerte ab 2006.
    """
    return await _wegweiser_dataset(slug, "social-situation", request)


@router.get("/cities/{slug}/care")
async def city_care(slug: str, request: Request) -> dict:
    """Pflegekennzahlen als Zeitreihe (Wegweiser Kommune, CC0).

    11 Indikatoren: Pflegebedürftige je Altersgruppe, Pflegequote, Verteilung
    auf ambulante und stationäre Pflege sowie Pflegegeld, dazu die
    Pflegevorausberechnung bis 2030. Jahreswerte ab 2006.

    Teilabdeckung: 73 Städte, die übrigen führt die Quelle erst ab Kreisebene.
    """
    return await _wegweiser_dataset(slug, "care", request)


@router.get("/cities/{slug}/land-values")
async def city_land_values(slug: str, request: Request) -> dict:
    """Liefert die aggregierten amtlichen Bodenrichtwerte je Stadt (DATA-35).

    Ablauf wie ``city_indicators`` (Store-read, KEIN resilient_client): Register-
    Lookup (unbekannt -> 404), Toggle-Prüfung (aus -> 200 disabled), Coverage-
    Prüfung (BORIS ist pro Bundesland föderiert -> Stadt ohne Landes-WFS liefert
    ehrlich ``not_covered`` statt leerem ``ok``), parametrisierter Read über
    ``read_land_values`` aus dem Bulk-Datensatz. Vier ``source_status``:
    - ``disabled``: ``enable_boris`` per Env-Toggle aus -> data None
    - ``not_covered``: Bundesland der Stadt hat (noch) keinen BORIS-WFS -> data None
    - ``not_ingested``: abgedeckt, aber kein Snapshot -> data None, kein 5xx
    - ``ok``: gemappte Bodenrichtwert-Kennzahl (Median/Min/Max + Zonen + Stichtag)

    KRITISCH (kein Bulk-Upstream im Request-Pfad): liest AUSSCHLIESSLICH aus dem
    vorverarbeiteten Datensatz; die Landes-WFS-Aggregation läuft offline als Batch.
    """
    entry = get_city(slug)

    if not Settings().enable_boris:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Teilabdeckung (GOV-honesty): nicht-abgedecktes Bundesland -> ehrliches
    # not_covered (200, data null) statt verschleierndem leerem ok.
    if not is_covered("land-values", entry.slug):
        return _not_covered("land-values")

    row = read_land_values(entry.slug)
    if row is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_land_values(
        entry.slug,
        row,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    await append_record(record, source="boris")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


def _regio_configured() -> bool:
    """True, wenn Toggle an UND beide GENESIS-Credentials gesetzt sind (DATA-37).

    Anders als die keylosen Bulk-Quellen (INKAR/BORIS) verlangt der GENESIS-
    Webservice eine Registrierung; ohne ``regio_user``/``regio_pass`` könnte der
    Bulk-Datensatz nie ingestet werden -> die Routen melden ehrlich ``disabled``.
    """
    s = Settings()
    # SecretStr-Objekte sind immer truthy -> den eigentlichen Wert prüfen, damit
    # ein leer gesetzter Key (INFRANODE_REGIO_USER="") als "fehlt" gilt.
    user = s.regio_user.get_secret_value() if s.regio_user else None
    pw = s.regio_pass.get_secret_value() if s.regio_pass else None
    return bool(s.enable_regionalstatistik and user and pw)


@router.get("/cities/{slug}/tax-rates")
async def city_tax_rates(slug: str, request: Request) -> dict:
    """Liefert die Realsteuer-Hebesätze einer Stadt im Envelope (DATA-37, 71231).

    Ablauf wie ``city_indicators`` (Store-read, KEIN resilient_client): Register-
    Lookup (unbekannt -> 404), Konfig-Prüfung (Toggle aus ODER keine GENESIS-
    Credentials -> 200 disabled), parametrisierter Read über ``read_tax_rates``
    (je 8-stelligem Gemeindeschlüssel). Drei ``source_status``:
    - ``disabled``: ``enable_regionalstatistik`` aus ODER regio_user/pass fehlt
    - ``not_ingested``: kein Snapshot für die Gemeinde -> data None, kein 5xx
    - ``ok``: gemappte Hebesatz-Kennzahl (Gewerbe-/Grundsteuer A/B/C + Stichtag)

    KRITISCH (kein Bulk-Upstream im Request-Pfad): liest AUSSCHLIESSLICH aus dem
    vorverarbeiteten Datensatz; der GENESIS-Pull läuft offline als Batch.
    """
    entry = get_city(slug)

    if not _regio_configured():
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    row = read_tax_rates(entry.slug)
    if row is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_tax_rates(
        entry.slug,
        row,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # Eigener Archiv-Quellenname je Teilmetrik (analog genesis_unemployment/
    # -tourism/-construction): tax-rates und business-registrations teilten sich
    # sonst das tier_a/regionalstatistik-Verzeichnis, wo die Tages-Aggregation des
    # Analysten (letzter Record je Tag gewinnt) eine der beiden Metriken
    # systematisch verlieren würde. Getrennt -> beide sauber auswertbar.
    await append_record(record, source="regionalstatistik_tax")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/business-registrations")
async def city_business_registrations(slug: str, request: Request) -> dict:
    """Liefert die Gewerbean-/-abmeldungen einer Stadt im Envelope (DATA-37, 52311).

    Ablauf wie ``city_tax_rates`` (Store-read, KEIN resilient_client): Register-
    Lookup (unbekannt -> 404), Konfig-Prüfung (Toggle aus ODER keine GENESIS-
    Credentials -> 200 disabled), parametrisierter Read über
    ``read_business_registrations`` (je 5-stelligem Kreisschlüssel). Drei
    ``source_status``:
    - ``disabled``: ``enable_regionalstatistik`` aus ODER regio_user/pass fehlt
    - ``not_ingested``: kein Snapshot für den Kreis -> data None, kein 5xx
    - ``ok``: gemappte Gründungsdynamik (Anmeldungen/Abmeldungen/Saldo + Jahr)

    KRITISCH (kein Bulk-Upstream im Request-Pfad): liest AUSSCHLIESSLICH aus dem
    vorverarbeiteten Datensatz; der GENESIS-Pull läuft offline als Batch.
    """
    entry = get_city(slug)

    if not _regio_configured():
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    row = read_business_registrations(entry.slug)
    if row is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_business_registrations(
        entry.slug,
        row,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # Eigener Archiv-Quellenname (siehe city_tax_rates): getrennt von tax-rates,
    # damit die Tages-Aggregation des Analysten beide Metriken behält.
    await append_record(record, source="regionalstatistik_business")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/cities/{slug}/insolvencies")
async def city_insolvencies(slug: str, request: Request) -> dict:
    """Liefert die beantragten Insolvenzen einer Stadt im Envelope (DATA-37, 52411).

    Ablauf wie ``city_business_registrations`` (Store-read, KEIN resilient_client):
    Register-Lookup (unbekannt -> 404), Konfig-Prüfung (Toggle aus ODER keine
    GENESIS-Credentials -> 200 disabled), parametrisierter Read über
    ``read_insolvencies`` (je 5-stelligem Kreisschlüssel; Tabelle 52411-02 ISV006
    Unternehmen + 52411-03 ISV007 übrige Schuldner, in einen Record gemergt).
    Drei ``source_status``:
    - ``disabled``: ``enable_regionalstatistik`` aus ODER regio_user/pass fehlt
    - ``not_ingested``: kein Snapshot für den Kreis -> data None, kein 5xx
    - ``ok``: gemappte Insolvenzlage (Unternehmens- + übrige-Schuldner-
      Insolvenzen, letztere inkl. Verbraucher/ehem. Selbstständige, + Jahr)

    KRITISCH (kein Bulk-Upstream im Request-Pfad): liest AUSSCHLIESSLICH aus dem
    vorverarbeiteten Datensatz; der GENESIS-Pull läuft offline als Batch.
    """
    entry = get_city(slug)

    if not _regio_configured():
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    row = read_insolvencies(entry.slug)
    if row is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "not_ingested",
            },
        }

    record = map_insolvencies(
        entry.slug,
        row,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # Eigener Archiv-Quellenname (siehe city_tax_rates / city_business_registrations):
    # getrennt von tax-rates und business, sonst verliert die Tages-Aggregation des
    # Analysten (letzter Record je Tag gewinnt) eine der Regionalstatistik-Metriken.
    await append_record(record, source="regionalstatistik_insolvency")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


# GENESIS-Regionalstatistik-Trio (DATA-28): je Datensatz der verifizierte
# Tabellen-Code + die Spaltenindizes der datencsv-Datenzeile (0=Jahr, 1=AGS,
# 2=Name, ab 3 die Werte). Live gegen regionalstatistik.de verifiziert
# (2026-06-15). Alle Kreis-Ebene (regionalvariable=KREISE), Jahreswerte.
_GENESIS_DATASETS: dict[str, dict] = {
    "unemployment": {
        # 13211-02-05-4 Arbeitslose + Arbeitslosenquoten, Jahresdurchschnitt.
        "table": "13211-02-05-4",
        # idx3 = Arbeitslose (Anzahl), idx11 = Arbeitslosenquote bez. alle zivilen
        # Erwerbspersonen (Prozent, die gängig zitierte Gesamtquote).
        "cols": {"arbeitslose": 3, "arbeitslosenquote": 11},
        "archive_source": "genesis_unemployment",
    },
    "tourism": {
        # 45412-01-02-4 Beherbergung, Jahressumme.
        "table": "45412-01-02-4",
        # idx5 = Gästeübernachtungen, idx6 = Gästeankünfte.
        "cols": {"uebernachtungen": 5, "ankuenfte": 6},
        "archive_source": "genesis_tourism",
    },
    "construction": {
        # 31111-01-02-4 Baugenehmigungen Wohngebaeude/Wohnungen, Jahressumme.
        "table": "31111-01-02-4",
        # idx3 = genehmigte Wohngebäude (insg.), idx7 = genehmigte Wohnungen (insg.).
        "cols": {"wohngebaeude": 3, "wohnungen": 7},
        "archive_source": "genesis_construction",
    },
}


async def _genesis_regio_envelope(slug: str, request: Request, *, dataset: str) -> dict:
    """Gemeinsamer Pfad für das GENESIS-Trio (Toggle/Key-Guard, Fetch, Map, Archiv).

    Account-gated wie city_demographics: Quelle aus ODER kein Credential -> 200
    ``disabled`` (nie 5xx). Resilienter Fetch über die "genesis"-Fassade gegen die
    keyabhängige Regionalstatistik-API (Header-Auth, je Kreis), Mapping mit
    DL-DE/BY-2.0-Attribution. Kein Treffer (leere values) -> ``no_data``; toter
    Upstream ohne Cache -> 503 (DX-06). Der ok-Record wird je Datensatz in eine
    eigene Tier-A-Partition geschrieben (Analyst-Speisung). Credentials gehen NUR
    in die Header (T-08-CRED), nie in den Cache-Key (nur dataset+slug) oder die
    Response.
    """
    entry = get_city(slug)
    cid = correlation_id.get()

    settings = Settings()
    if (
        not settings.enable_genesis_regio
        or settings.genesis_username is None
        or settings.genesis_password is None
    ):
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }

    spec = _GENESIS_DATASETS[dataset]
    client = request.app.state.resilient_client
    key = build_cache_key("genesis", city_slug=f"{dataset}-{entry.slug}")
    ags5 = entry.ags[:5]
    genesis_user = settings.genesis_username
    genesis_password = settings.genesis_password
    col_specs = spec["cols"]
    table = spec["table"]

    async def fetch_fn():
        return await fetch_genesis_table(
            request.app.state.http,
            table=table,
            ags5=ags5,
            username=genesis_user,
            password=genesis_password,
            col_specs=col_specs,
        )

    raw, status = await client.fetch("genesis", key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'genesis' voruebergehend nicht erreichbar, kein gecachter Wert.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )
    values = raw.get("values") or {}
    if not any(v is not None for v in values.values()):
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "no_data"},
        }

    record = map_regional_stat(
        entry.slug,
        raw,
        dataset=dataset,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    await append_record(record, source=spec["archive_source"])
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/unemployment")
async def city_unemployment(slug: str, request: Request) -> dict:
    """Arbeitslose + Arbeitslosenquote je Kreis, Jahreswert (GENESIS, Tier A).

    Quelle: Statistische Ämter des Bundes und der Länder / Regionalstatistik
    (Arbeitsmarktstatistik der Bundesagentur für Arbeit). Regionale Auflösung
    Kreis/kreisfreie Stadt (region_name weist sie aus). values: arbeitslose
    (Anzahl), arbeitslosenquote (Prozent, bez. alle zivilen Erwerbspersonen).
    """
    return await _genesis_regio_envelope(slug, request, dataset="unemployment")


@router.get("/cities/{slug}/tourism")
async def city_tourism(slug: str, request: Request) -> dict:
    """Gaesteuebernachtungen + Ankünfte je Kreis, Jahreswert (GENESIS, Tier A).

    Quelle: Statistische Ämter des Bundes und der Länder / Regionalstatistik
    (Monatserhebung im Tourismus, Jahressumme). values: übernachtungen,
    ankünfte (jeweils Anzahl). Regionale Auflösung Kreis/kreisfreie Stadt.
    """
    return await _genesis_regio_envelope(slug, request, dataset="tourism")


@router.get("/cities/{slug}/construction")
async def city_construction(slug: str, request: Request) -> dict:
    """Baugenehmigungen (Wohngebaeude/Wohnungen) je Kreis, Jahreswert (GENESIS, Tier A).

    Quelle: Statistische Ämter des Bundes und der Länder / Regionalstatistik
    (Statistik der Baugenehmigungen, Jahressumme). values: wohngebäude,
    wohnungen (genehmigt, Anzahl). Regionale Auflösung Kreis/kreisfreie Stadt.
    """
    return await _genesis_regio_envelope(slug, request, dataset="construction")


# Bundesland -> Stromnetz-Regelzone (SMARD-Verbrauch liegt je Regelzone vor).
# Näherung nach Bundesland; Zonen folgen nicht exakt den Landesgrenzen, für eine
# regionale Verbrauchs-Kennzahl je Stadt aber die etablierte Zuordnung.
_SMARD_STATE_TO_ZONE = {
    "BW": "TransnetBW",
    "BY": "TenneT",
    "HB": "TenneT",
    "HE": "TenneT",
    "NI": "TenneT",
    "SH": "TenneT",
    "BE": "50Hertz",
    "BB": "50Hertz",
    "HH": "50Hertz",
    "MV": "50Hertz",
    "SN": "50Hertz",
    "ST": "50Hertz",
    "TH": "50Hertz",
    "NW": "Amprion",
    "RP": "Amprion",
    "SL": "Amprion",
}


async def _smard_envelope(
    slug: str,
    request: Request,
    *,
    filter_id: str,
    region: str,
    measure: Literal["load", "price"],
    unit: str,
) -> dict:
    """Gemeinsamer SMARD-Pfad für power-load/power-price (Toggle/Fetch/Map/Archiv)."""
    entry = get_city(slug)
    cid = correlation_id.get()
    if not Settings().enable_smard:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }
    client = request.app.state.resilient_client
    key = build_cache_key("smard", city_slug=f"{measure}-{region}")

    async def fetch_fn():
        return await fetch_smard(
            request.app.state.http, filter_id=filter_id, region=region
        )

    raw, status = await client.fetch("smard", key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'smard' voruebergehend nicht erreichbar, kein gecachter Wert.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )
    if raw.get("value") is None:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "no_data"},
        }
    record = map_smard(
        entry.slug,
        raw,
        measure=measure,
        unit=unit,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
    )
    # Verbrauch und Preis in getrennte Archiv-Partitionen (smard_load/smard_price),
    # damit die Per-Tag-Aggregation des Analysten beide Reihen sauber trennt.
    await append_record(record, source=f"smard_{measure}")
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/power-load")
async def city_power_load(slug: str, request: Request) -> dict:
    """Stromverbrauch (Netzlast) der Regelzone der Stadt, Tageswert (SMARD, Tier A).

    SMARD liefert den realisierten Stromverbrauch je Regelzone (50Hertz/Amprion/
    TenneT/TransnetBW); die Stadt wird über ihr Bundesland einer Zone zugeordnet
    (regionale Kennzahl, nicht stadtgenau). Quelle: Bundesnetzagentur | SMARD.de.
    """
    region = _SMARD_STATE_TO_ZONE.get(get_city(slug).state, "DE")
    return await _smard_envelope(
        slug, request, filter_id="410", region=region, measure="load", unit="MWh"
    )


@router.get("/cities/{slug}/power-price")
async def city_power_price(slug: str, request: Request) -> dict:
    """Day-ahead-Börsenstrompreis (bundesweit DE/LU), Tageswert (SMARD, Tier A).

    Der Großhandelspreis gilt bundesweit (eine Gebotszone), ist also für alle
    Städte identisch. Quelle: Bundesnetzagentur | SMARD.de.
    """
    return await _smard_envelope(
        slug, request, filter_id="4169", region="DE", measure="price", unit="EUR/MWh"
    )


@router.get("/cities/{slug}/weather-warnings")
async def city_weather_warnings(slug: str, request: Request) -> dict:
    """Amtliche DWD-Wetterwarnungen je Stadt (max_level 0-4, Tier A).

    Holt die Warnungen je Stadt über die keylose Brightsky-Alerts-API (lat/lon
    aus dem Register-Geo, exakt das city_weather-Muster); die zuständige
    Warncell liefert Brightsky in der Antwort mit. max_level 0 = keine reguläre
    Warnung, 1-4 = Warnstufe aus der CAP-severity; Hitze-/UV-Gesundheits-
    warnungen (category "health") zählen NICHT in max_level, sondern stehen
    separat in special_warnings (Audit K5). Quelle: Deutscher Wetterdienst
    (GeoNutzV). Deaktiviert -> 200 source_status="disabled".
    """
    entry = get_city(slug)
    cid = correlation_id.get()
    if not Settings().enable_dwd_warnings:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }
    client = request.app.state.resilient_client
    key = build_cache_key("dwd_warnings", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_dwd_warnings(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    raw, status = await client.fetch("dwd_warnings", key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'dwd_warnings' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )
    record = map_dwd_warnings(
        entry.slug,
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
    )
    await append_record(record, source="dwd_warnings")
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/civil-protection-warnings")
async def city_civil_protection_warnings(slug: str, request: Request) -> dict:
    """Amtliche BBK-NINA-Bevoelkerungsschutz-Warnungen je Stadt (Tier A, keylos).

    Fuellt die echte Zivilschutz-Luecke (Gefahrstoff, Grossbrand, Bomben-
    entschaerfung) neben weather-warnings (DWD) und flood (Hochwasser). Der
    Regionsbezug wird ueber den 12-stelligen Kreis-ARS (aus dem Register-AGS)
    hergestellt; ``coverage_granularity`` weist ehrlich aus, ob der ARS die Stadt
    (kreisfrei) oder ihren ganzen Kreis (kreisangehoerig) abdeckt.

    LIZENZ-AUFLAGE (§ 5 Abs. 2 UrhG): Der amtliche Warntext wird UNVERAENDERT,
    verbatim durchgereicht (modified=False, keine KI-Umformulierung). Provider
    DWD/LHP sind je Warnung via ``duplicate_of`` auf weather-warnings bzw. flood
    markiert. Deaktiviert -> 200 source_status="disabled"; keine aktive Warnung ->
    200 source_status="ok" (count 0); toter Upstream ohne Cache -> 503 mit Hint.
    KEIN Archiv-Write (reine Live-Warnungen).
    """
    entry = get_city(slug)
    cid = correlation_id.get()
    if not Settings().enable_bbk_nina:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }
    client = request.app.state.resilient_client
    # Cache-Key ueber den ARS: Staedte im selben Kreis teilen sich das Dashboard.
    ars = ars_for_ags(entry.ags)
    key = build_cache_key("bbk_nina", city_slug=ars)

    async def fetch_fn():
        return await fetch_for_ags(request.app.state.http, ags=entry.ags)

    raw, status = await client.fetch("bbk_nina", key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'bbk_nina' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )
    record = map_bbk_nina(
        entry.slug,
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


def _fuel_fetched_at(raw: dict) -> datetime:
    """Zeitpunkt des Upstream-Abrufs aus dem zwischengespeicherten raw-dict.

    Die Route stempelt ``fetched_at`` in dem Moment, in dem der Upstream-Call
    zurueckkommt (siehe ``city_fuel_prices``); der Stempel liegt damit MIT der
    Nutzlast im Cache und ueberlebt jeden HIT/STALE. Fehlt oder faellt er aus
    dem Format (Eintrag aus einer aelteren Version), ist die Antwortzeit der
    Rueckfall: nie ein Fehler, nur eine unschaerfere Angabe.
    """
    try:
        return datetime.fromisoformat(raw["fetched_at"])
    except (KeyError, TypeError, ValueError):
        return datetime.now(UTC)


@router.get("/cities/{slug}/fuel-prices")
async def city_fuel_prices(slug: str, request: Request) -> dict:
    """Aktuelle Spritpreise je Stadt, aggregiert (Tankerkoenig/MTS-K, Tier A).

    Aggregiert die Tankstellen im Umkreis der Stadtkoordinate zu Durchschnitts- und
    Minimal-Preisen je Sorte (e5/e10/diesel). Quelle: Markttransparenzstelle für
    Kraftstoffe (MTS-K) via Tankerkönig (CC BY 4.0). Toggle aus ODER kein API-Key
    -> 200 source_status="disabled" (nie 5xx); keine Tankstelle im Radius -> 200
    source_status="no_data". Der Key gelangt NIE in Cache-Key/Response/Log.
    """
    entry = get_city(slug)
    cid = correlation_id.get()
    settings = Settings()
    key = settings.tankerkoenig_key
    # disabled: Toggle aus ODER kein (leerer) Key (analog hvv_geofox). Ein leerer
    # Env-String INFRANODE_TANKERKOENIG_KEY="" ist KEIN None -> ``get_secret_value``
    # zusätzlich prüfen, damit der Guard deterministisch greift.
    if not settings.enable_tankerkoenig or key is None or not key.get_secret_value():
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }

    client = request.app.state.resilient_client
    # Cache-Key trägt NUR den Slug (T-08-CRED): nie den Key.
    cache_key = build_cache_key("tankerkoenig", city_slug=entry.slug)
    apikey = key.get_secret_value()

    async def fetch_fn():
        raw = await fetch_fuel_prices(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            apikey=apikey,
        )
        # Zeitanker fuer die Ehrlichkeit des Envelopes: der Stempel entsteht
        # HIER (nach dem Upstream-Call) und wird mit der Nutzlast
        # zwischengespeichert, damit ``retrieved_at`` in der Antwort den echten
        # Abruf nennt und nicht die Uhrzeit der Antwort. Bei 24 h Stale-Fenster
        # ist das der Unterschied zwischen einer Angabe und einer Behauptung.
        raw["fetched_at"] = datetime.now(UTC).isoformat()
        return raw

    # Redis-Cache (Owner-Entscheid 2026-07-08) entlastet den geteilten API-Key
    # und hält uns unter dem Tankerkönig-Limit von 1 Request/Minute (quellenweit,
    # alle Städte zusammen; Aggregat-Bremse in resilience/client.py). Das
    # Frische-Fenster folgt seit 2026-09-07 dem Tagesprofil des
    # Kraftstoffpreisanpassungsgesetzes (registry/ttl_profiles.py: 4 h nachts,
    # 60 min vormittags, 5 min im Erhöhungsfenster 11:50 bis 12:20, 20 min
    # nachmittags, 45 min abends, immer gekappt auf die nächste 11:50-Grenze),
    # das Stale-Fenster liegt bei 24 h. KEINE dauerhafte Speicherung: kein
    # append_record, kein Abruf im Hintergrund; Redis läuft ohne Persistence
    # (allkeys-lru).
    raw, status = await client.fetch("tankerkoenig", cache_key, fetch_fn)
    if raw is None:
        # Zwei verschiedene 503: die Bremse hat abgewiesen (Quota-Signal, Retry-
        # After sagt wann es wieder geht) oder die Quelle ist wirklich weg.
        # slowapi (headers_enabled) legt auf jede Antwort das Maximum aus diesem
        # Wert und dem Reset des Rate-Limit-Fensters; der Header wird also nie
        # kleiner als die Bremse, hoechstens das Fenster.
        retry_after = retry_after_s("tankerkoenig")
        if retry_after is not None:
            # VERLUSTPFAD 1 (RCA 2026-09-15): Diese Useraktion hat den Slot der
            # Minute verloren und bekommt keine Daten. Die Stadt wandert in die
            # Nachfrage-Warteschlange, damit der Collector die Anfrage
            # zeitversetzt nachholt (infra/demand_queue.py, dort auch die
            # ToS-Begruendung). Fail-open: ein Redis-Fehler aendert die Antwort
            # nicht, er kostet nur den Nachhol-Versuch.
            await enqueue_demand(
                request.app.state.redis, source="tankerkoenig", slug=entry.slug
            )
            raise UpstreamError(
                "Tankerkoenig erlaubt eine Anfrage je Minute fuer alle Staedte "
                "zusammen; fuer diese Stadt liegt noch kein Zwischenstand vor.",
                hint=(
                    "Nach Retry-After Sekunden erneut versuchen. Eine bereits "
                    "abgefragte Stadt bleibt bis zu 24 Stunden aus dem Cache "
                    "beantwortbar; cache_status STALE weist den Zwischenstand "
                    "aus, retrieved_at nennt den Zeitpunkt des Abrufs."
                ),
                headers={"Retry-After": str(retry_after)},
            )
        raise UpstreamError(
            "Quelle 'tankerkoenig' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # VERLUSTPFAD 2 (RCA 2026-09-15): Die Antwort ist 200, aber aus der
    # Notreserve. STALE-ON-ERROR heisst, dass es KEINEN Upstream-Call gab
    # (Bremse, Cooldown oder offener Breaker) und der Cache-Key damit NICHT
    # erneuert wurde: diese Useraktion hat den Slot der Minute ebenso verloren
    # wie im 503-Fall, sie bekam nur noch einen alten Stand zu sehen. Also
    # ebenfalls einreihen. Bei HIT/MISS/STALE wird NICHT eingereiht: dort lief
    # ein Fetch oder es liegt ein frischer Stand vor, es gibt nichts nachzuholen.
    if status == CacheStatus.STALE_ON_ERROR:
        await enqueue_demand(
            request.app.state.redis, source="tankerkoenig", slug=entry.slug
        )

    # Keine Tankstelle im Radius -> ehrliches no_data (200) OHNE Mapper/Archiv.
    if not raw.get("station_count"):
        return {
            "data": None,
            "meta": {
                "correlation_id": cid,
                "source_status": "no_data",
                "cache_status": status,
            },
        }

    record = map_fuel_prices(
        raw,
        retrieved_at=_fuel_fetched_at(raw),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
    )
    # KEIN append_record: Die Tankerkönig-Nutzungsbedingungen kennen kein
    # ausdrückliches Cache-/Speicherverbot (Wortlaut geprüft 2026-07-25), verlangen
    # aber "Requests on Demand - auf Useraktion" und "Regelmäßige, nicht explizit
    # vom User initiierte Requests sind zu vermeiden"; Spiegeln/Massenabfragen nur
    # nach Absprache mit Tankerkönig. Deshalb: kein Archiv, kein Timer-Job, nur
    # Live-Auslieferung bei Useraktion. NACHZUG 2026-09-15 (RCA, Owner-Entscheid):
    # Verliert eine Useraktion den Slot der Minute, wird die Stadt eingereiht und
    # der Abruf ZEITVERSETZT nachgeholt (siehe Verlustpfade oben und
    # infra/demand_queue.py). Der Auslöser bleibt damit die Nutzeraktion; eine
    # Stadt, die niemand abfragt, wird auch nie abgerufen. Der kurze Redis-Cache
    # oben senkt die Upstream-Last und arbeitet damit FÜR die Vorgabe "unnötige
    # Belastungen des Tankerkönig-Servers sind zu vermeiden".
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/sharing")
async def city_sharing(slug: str, request: Request) -> dict:
    """Bike-/Scooter-Sharing je Stadt, aggregiert (GBFS, Tier A, DATA-33).

    Aggregiert die offenen GBFS-Feeds der kuratierten Tier-A-Anbieter (Primär
    Nextbike, CC0) im Stadtgebiet zu einer Live-Kennzahl (verfügbare Fahrzeuge +
    Stationen). Quelle: General Bikeshare Feed Specification; die Lizenz wird PRO
    System aus ``system_information.license_id`` fail-closed gegen die Tier-A-
    Allowlist geprüft (GOV-02/04). Vier ``source_status``-Werte:
    - ``disabled``: ``enable_gbfs`` per Env-Toggle aus -> data None
    - ``not_covered``: kein kuratiertes GBFS-System für diese Stadt (mit der Liste
      der abgedeckten Städte), klar unterscheidbar von no_data
    - ``no_data``: System(e) erreichbar, aber kein akzeptierter Tier-A-Anbieter
      bzw. keine Fahrzeuge -> data None
    - ``ok``: gemappter sharing-Payload
    Toggle aus -> 200 disabled (nie 5xx).
    """
    entry = get_city(slug)
    cid = correlation_id.get()
    settings = Settings()
    if not settings.enable_gbfs:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }

    systems = GBFS_SYSTEMS.get(entry.slug)
    if systems is None:
        return _not_covered("sharing")

    client = request.app.state.resilient_client
    cache_key = build_cache_key("gbfs", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_sharing(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            systems=systems,
        )

    raw, status = await client.fetch("gbfs", cache_key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'gbfs' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # Kein akzeptierter Tier-A-Anbieter (fail-closed verworfen) -> ehrliches no_data.
    if not raw.get("providers"):
        return {
            "data": None,
            "meta": {
                "correlation_id": cid,
                "source_status": "no_data",
                "cache_status": status,
            },
        }

    record = map_sharing(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
    )
    await append_record(record, source="gbfs")
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


# Lokale Umlaut-Normalisierung für den q-Namensfilter des Bahnhofs-Katalogs
# (Vorbild: Doppel-Index im Slug-Resolver, bewusst NICHT aus registry importiert).
# Zwei Formen decken beide Eingabe-Gewohnheiten ab: Expansion (muenchen) und
# Bare-Vowel (munchen); ß -> ss kommt aus casefold.
_STATION_EXPAND_UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})
_STATION_BARE_UMLAUT = str.maketrans({"ä": "a", "ö": "o", "ü": "u"})


def _station_name_prep(raw: str) -> str:
    """Vorstufe der Namens-Normalisierung: NFC + strip + casefold."""
    return unicodedata.normalize("NFC", raw).strip().casefold()


def _station_name_matches(query: str, name: str) -> bool:
    """Umlaut-toleranter Teilstring-Match von ``query`` auf einem Bahnhofsnamen.

    Matcht, wenn die Expansion-Form von q Teilstring der Expansion-Form des
    Namens ist ODER die Bare-Vowel-Form von q Teilstring der Bare-Vowel-Form
    des Namens ist. So matchen sowohl ``munchen`` als auch ``muenchen`` den
    Namen "München Hbf".
    """
    q = _station_name_prep(query)
    n = _station_name_prep(name)
    if q.translate(_STATION_EXPAND_UMLAUT) in n.translate(_STATION_EXPAND_UMLAUT):
        return True
    return q.translate(_STATION_BARE_UMLAUT) in n.translate(_STATION_BARE_UMLAUT)


@router.get("/cities/{slug}/stations")
async def city_stations(slug: str, request: Request) -> dict:
    """Bahnhofs-Katalog einer Stadt: ALLE DB-Bahnhöfe (StaDa, DATA-36, CC BY 4.0).

    Listet jeden DB-Bahnhof im Stadtgebiet (Zuordnung über den amtlichen
    Gemeindeschluessel: StaDa ``municipalityCode`` == Stadt-``ags``) mit EVA, Name,
    Kategorie, Geo und PLZ. Die EVA füttert die Per-Bahnhof-Boards
    ``GET /stations/{eva}/departures``. Drei ``source_status``-Werte:
    - ``disabled``: Toggle aus ODER kein DB-Client-Id/Api-Key -> data None
    - ``no_data``: kein DB-Bahnhof im Stadtgebiet gefunden
    - ``ok``: gemappter station_catalog-Payload
    StaDa wird EINMAL bundesweit geholt + lange gecacht und je Stadt gefiltert; die
    Keys gelangen NIE in Cache-Key/Response/Log. Volle Abdeckung (alle Städte).

    Optionale Query-Parameter (Filter NACH dem Cache-Read, Cache-Key bleibt
    q-/limit-frei -> kein Poisoning):
    - ``q``: umlaut-toleranter Teilstring-Match auf dem Bahnhofsnamen
      (``munchen`` UND ``muenchen`` matchen "München Hbf"); kein Treffer ->
      ``no_data``.
    - ``limit``: kappt die sortierte Liste (minimum 1, Cap 100, Default alle);
      Unsinn -> 422.
    """
    entry = get_city(slug)
    cid = correlation_id.get()
    settings = Settings()
    cid_secret = settings.db_client_id
    key = settings.db_api_key
    if (
        not settings.enable_stada
        or cid_secret is None
        or key is None
        or not cid_secret.get_secret_value()
        or not key.get_secret_value()
    ):
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }

    client = request.app.state.resilient_client
    # Geteilter Cache-Key (keine Stadt): ein bundesweiter Abruf bedient alle Städte.
    cache_key = build_cache_key("stada", city_slug="_all")
    client_id = cid_secret.get_secret_value()
    api_key = key.get_secret_value()

    async def fetch_fn():
        return await fetch_all_stations(
            request.app.state.http, client_id=client_id, api_key=api_key
        )

    raw, status = await client.fetch("stada", cache_key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'stada' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # Bahnhof -> Stadt über den amtlichen Gemeindeschlüssel (municipalityCode==ags),
    # dann nach Kategorie (Wichtigkeit, 1=gross) und Name sortiert.
    stations = [s for s in raw.get("stations", []) if s.get("ags") == entry.ags]
    stations.sort(key=lambda s: (s.get("category") or 99, s.get("name") or ""))
    # Optionaler Namensfilter (umlaut-tolerant) NACH ags-Filter + Sortierung,
    # aber VOR dem no_data-Zweig: kein Treffer landet konsistent in no_data.
    q = request.query_params.get("q")
    if q is not None and q.strip():
        stations = [
            s for s in stations if _station_name_matches(q, s.get("name") or "")
        ]
    # Optionales limit NACH dem q-Filter (Default alle, minimum 1, Cap 100).
    raw_limit = request.query_params.get("limit")
    if raw_limit is not None:
        limit = _tender_int_param(
            raw_limit, name="limit", default=100, minimum=1, maximum=100
        )
        stations = stations[:limit]
    if not stations:
        return {
            "data": None,
            "meta": {
                "correlation_id": cid,
                "source_status": "no_data",
                "cache_status": status,
            },
        }

    record = map_station_catalog(
        {"slug": entry.slug, "stations": stations},
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/station-departures")
async def city_station_departures(slug: str, request: Request) -> dict:
    """Live-Abfahrtstafel der Haupt-Bahnhöfe einer Stadt (DB Timetables, DATA-34).

    Nächste Zugabfahrten an den wichtigsten Bahnhöfen der Stadt mit Echtzeit-
    Verspätung (Soll- + Änderungsdaten gemerged). Die EVAs der Haupt-Bahnhöfe
    werden aus dem StaDa-Katalog abgeleitet (bzw. einer verifizierten Override-
    Liste) -> ALLE 84 Städte abgedeckt. Für einen bestimmten Bahnhof:
    ``GET /stations/{eva}/departures``. Quelle: DB Timetables (CC BY 4.0). Drei
    ``source_status``-Werte:
    - ``disabled``: Toggle aus ODER kein DB-Client-Id/Api-Key -> data None
    - ``no_data``: kein Bahnhof/keine Abfahrt im Zeitfenster
    - ``ok``: gemappter station_departures-Payload
    Die Keys gelangen NIE in Cache-Key/Response/Log.
    """
    entry = get_city(slug)
    cid = correlation_id.get()
    settings = Settings()
    cid_secret = settings.db_client_id
    key = settings.db_api_key
    # disabled: Toggle aus ODER fehlende/leere Credentials (analog tankerkoenig).
    if (
        not settings.enable_db_timetables
        or cid_secret is None
        or key is None
        or not cid_secret.get_secret_value()
        or not key.get_secret_value()
    ):
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }

    client = request.app.state.resilient_client
    cache_key = build_cache_key("db_timetables", city_slug=entry.slug)
    client_id = cid_secret.get_secret_value()
    api_key = key.get_secret_value()

    evas = await _resolve_city_station_evas(
        request, slug=entry.slug, ags=entry.ags, client_id=client_id, api_key=api_key
    )
    if not evas:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "no_data"},
        }

    async def fetch_fn():
        return await fetch_station_departures(
            request.app.state.http,
            slug=entry.slug,
            evas=evas,
            client_id=client_id,
            api_key=api_key,
            now=datetime.now(UTC),
        )

    raw, status = await client.fetch("db_timetables", cache_key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'db_timetables' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    if not raw.get("departures"):
        return {
            "data": None,
            "meta": {
                "correlation_id": cid,
                "source_status": "no_data",
                "cache_status": status,
            },
        }

    record = map_station_departures(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
    )
    # Archiv-Write ist hier BEABSICHTIGT (nicht der Tier-B-Live-Verzicht aus
    # T-19-ARCHIVE): DB Timetables ist Tier A (CC BY 4.0, Archiv-/Weitergaberecht),
    # historische Abfahrts-/Ankunftstafeln tragen Verspätungs-/Zeitreihenwert. Die
    # "Live-NIE-archivieren"-Regel gilt nur für Tier B (z.B. GTFS-RT-Transit, das
    # in live.py bewusst NICHT archiviert). Der Store leitet das Tier-Verzeichnis
    # zwingend aus record.license_tier (=A) ab (GOV-02), nicht aus diesem Aufruf.
    # Audit 2026-06-29 (Finding 120): geprüft, konsistent.
    await append_record(record, source="db_timetables")
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/station-arrivals")
async def city_station_arrivals(slug: str, request: Request) -> dict:
    """Live-Ankunftstafel des Haupt-Bahnhofs einer Stadt (DB Timetables, DATA-34).

    Spiegelbild zu ``city_station_departures``: ankommende Züge mit Echtzeit-
    Verspätung (``origin`` = Startbahnhof). Gleiche Quelle/Lizenz/Abdeckung wie die
    Abfahrtstafel (alle 84 Städte, EVAs aus StaDa abgeleitet). Drei
    ``source_status``: disabled / no_data / ok.
    Die Keys gelangen NIE in Cache-Key/Response/Log.
    """
    entry = get_city(slug)
    cid = correlation_id.get()
    settings = Settings()
    cid_secret = settings.db_client_id
    key = settings.db_api_key
    if (
        not settings.enable_db_timetables
        or cid_secret is None
        or key is None
        or not cid_secret.get_secret_value()
        or not key.get_secret_value()
    ):
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }

    client = request.app.state.resilient_client
    cache_key = build_cache_key("db_timetables_arr", city_slug=entry.slug)
    client_id = cid_secret.get_secret_value()
    api_key = key.get_secret_value()

    evas = await _resolve_city_station_evas(
        request, slug=entry.slug, ags=entry.ags, client_id=client_id, api_key=api_key
    )
    if not evas:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "no_data"},
        }

    async def fetch_fn():
        return await fetch_station_arrivals(
            request.app.state.http,
            slug=entry.slug,
            evas=evas,
            client_id=client_id,
            api_key=api_key,
            now=datetime.now(UTC),
        )

    raw, status = await client.fetch("db_timetables", cache_key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'db_timetables' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    if not raw.get("arrivals"):
        return {
            "data": None,
            "meta": {
                "correlation_id": cid,
                "source_status": "no_data",
                "cache_status": status,
            },
        }

    record = map_station_arrivals(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
    )
    # Archiv-Write ist hier BEABSICHTIGT (nicht der Tier-B-Live-Verzicht aus
    # T-19-ARCHIVE): DB Timetables ist Tier A (CC BY 4.0, Archiv-/Weitergaberecht),
    # historische Abfahrts-/Ankunftstafeln tragen Verspätungs-/Zeitreihenwert. Die
    # "Live-NIE-archivieren"-Regel gilt nur für Tier B (z.B. GTFS-RT-Transit, das
    # in live.py bewusst NICHT archiviert). Der Store leitet das Tier-Verzeichnis
    # zwingend aus record.license_tier (=A) ab (GOV-02), nicht aus diesem Aufruf.
    # Audit 2026-06-29 (Finding 120): geprüft, konsistent.
    await append_record(record, source="db_timetables")
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/cities/{slug}/health")
async def city_health(slug: str, request: Request) -> dict:
    """Liefert Gesundheitsinfrastruktur im kanonischen Envelope (DATA-25a/b).

    Kombiniert zwei Tier-A-Sichten:
    - Krankenhaus-Stammdaten (Destatis-Krankenhausverzeichnis, GENESIS EVAS 23111):
      account-gated Live-POST über ``fetch_hospitals`` (K2-Fix Audit 2026-06-29:
      echtes 23111-Schema count/hospitals/reference_date, NICHT mehr
      ``fetch_demographics`` mit Demografie-Schema), gemappt durch ``map_hospital``
      (exakter Destatis-Wortlaut). Ist GENESIS aus/credential-los (Prod-Realität),
      greift der keylose Wikidata-Fallback (H3-Fix: SPARQL Q16917 + P131 je
      Stadt-QID, sortenrein CC0, ``meta.fallback=wikidata``).
    Ablauf (DATA-25/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint), account-gated Toggle-/Key-Guard für das
    Krankenhausverzeichnis (Quelle aus ODER kein Credential -> kein Live-Call),
    ``source_status`` weist die Abdeckung ehrlich aus
    (``disabled``/``not_ingested``/``ok``).

    KRITISCH (T-08-CRED): Die GENESIS-Credentials gelangen nur in den POST-Body des
    Adapters, NIE in den Cache-Key oder die Response.
    """
    entry = get_city(slug)

    # Account-gated Toggle-/Key-Guard für das Krankenhausverzeichnis frisch lesen
    # (Settings() statt app.state.settings, damit der per-Test gesetzte Env-Override
    # greift). DATA-06: Quelle aus ODER kein Credential -> kein Live-Call.
    settings = Settings()
    hospital_enabled = (
        settings.enable_genesis
        and settings.genesis_username is not None
        and settings.genesis_password is not None
    )

    hospital_data: dict | None = None
    fallback: str | None = None
    if not hospital_enabled:
        # H3-Fix (Audit 2026-06-29): GENESIS aus/credential-los (Prod-Realität).
        # Statt still hospital:null den keylosen Wikidata-Fallback versuchen
        # (SPARQL: Krankenhäuser je Stadt-QID, Q16917 + P131), sofern wikidata
        # aktiv ist und die Stadt eine QID trägt. Sortenrein Tier A (CC0), ehrlich
        # via meta.fallback=wikidata gekennzeichnet (KEINE GENESIS-Attribution).
        if Settings().enable_wikidata and entry.qid:
            client = request.app.state.resilient_client
            wiki_key = build_cache_key(
                "genesis_hospital_wikidata", city_slug=entry.slug
            )

            async def wiki_fetch_fn():
                return await fetch_hospitals_wikidata(
                    request.app.state.http, slug=entry.slug, qid=entry.qid
                )

            wiki_raw, _wiki_status = await client.fetch(
                "wikidata", wiki_key, wiki_fetch_fn
            )
            if wiki_raw is not None:
                wiki_record = map_hospital_wikidata(
                    wiki_raw,
                    retrieved_at=datetime.now(UTC),
                    ags=entry.ags,
                    wikidata_qid=entry.qid,
                )
                await append_record(wiki_record, source="wikidata")
                hospital_data = wiki_record.model_dump(mode="json")
                fallback = "wikidata"

        # Kein Krankenhaus (auch kein Wikidata-Treffer) -> Slice ist disabled.
        if hospital_data is None:
            return {
                "data": None,
                "meta": {
                    "correlation_id": correlation_id.get(),
                    "source_status": "disabled",
                },
            }
    else:
        client = request.app.state.resilient_client
        # Cache-Key trägt NUR den Slug (T-08-CRED): nie Credentials.
        key = build_cache_key("genesis_hospital", city_slug=entry.slug)
        genesis_user = settings.genesis_username
        genesis_password = settings.genesis_password
        if genesis_user is None or genesis_password is None:
            # Nie erreichbar: hospital_enabled hat beide Credentials geprueft.
            # Der Guard existiert fuer die statische Optional-Kette (pyright).
            raise RuntimeError("GENESIS-Credentials fehlen trotz hospital_enabled")

        async def fetch_fn():
            # K2-Fix (Audit 2026-06-29): fetch_hospitals (echtes 23111-Schema:
            # count/hospitals/reference_date), NICHT fetch_demographics (das nur
            # population/households/... liefert -> count blieb 0, hospitals leer).
            return await fetch_hospitals(
                request.app.state.http,
                slug=entry.slug,
                ags=entry.ags,
                username=genesis_user,
                password=genesis_password,
                table=_HOSPITAL_TABLE,
            )

        raw, _status = await client.fetch("genesis_hospital", key, fetch_fn)

        # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
        # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
        if raw is None:
            raise UpstreamError(
                "Quelle 'genesis' (Krankenhausverzeichnis) voruebergehend nicht "
                "erreichbar, kein gecachter Wert vorhanden.",
                hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
            )

        # Der GENESIS-raw geht durch den NEUEN map_hospital (NICHT map_demographics):
        # exakter Destatis-Custom-Wortlaut (Pitfall 6, Finding B-3).
        record = map_hospital(
            raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
        )
        # Finding W-1: gleiche Quelle wie Demografie (genesis).
        await append_record(record, source="genesis")
        hospital_data = record.model_dump(mode="json")

    # source_status: ok sobald das Krankenhausverzeichnis Daten trägt, sonst
    # not_ingested (Quelle aktiv/lesbar, aber noch kein Snapshot).
    status = "ok" if hospital_data is not None else "not_ingested"

    meta: dict = {
        "correlation_id": correlation_id.get(),
        "source_status": status,
    }
    if fallback is not None:
        meta["fallback"] = fallback

    return {
        "data": {"hospital": hospital_data},
        "meta": meta,
    }


# OCDS-Status-Allowlist (T-21-INPUT): nur diese Werte gelangen überhaupt in den
# parametrisierten Reader. "active" = laufendes Vergabeverfahren (aus der
# Auftragsbekanntmachung, notice_type=tender), "complete" = entschiedenes Verfahren
# inkl. aufgehobener Vergaben (notice_type=award). Der DE-OCDS-Export trägt NIE ein
# tender.status; der status wird semantisch aus dem notice_type abgeleitet, der rohe
# Zuschlag-Status steht im Feld award_status. Ein unbekannter Wert -> 422, BEVOR
# roher Input in die Query geht (kein f-string/%-SQL am Aufrufort, alle ?-gebunden).
_TENDER_STATUS_ALLOWED = frozenset({"active", "complete"})

# match-Allowlist (T-21-INPUT): Bezug der Stadt-Zuordnung. "buyer_city" = Sitz des
# auftraggebenden Amts, "place_of_performance" = Erfüllungsort der Leistung.
_TENDER_MATCH_ALLOWED = frozenset({"buyer_city", "place_of_performance"})

# Pagination-Cap: schützt vor unbeschränkten Seiten (Best-Practice #8).
_TENDER_LIMIT_DEFAULT = 50
_TENDER_LIMIT_MAX = 200

# Lizenz des Tender-Datensatzes (oeffentlichevergabe.de, CC0 = Tier A). Die Route
# baut eine eigene Response (kein CanonicalRecord-Envelope), daher Lizenz +
# Attribution explizit aus SOURCE_LICENSE durchreichen, damit der Datensatz NICHT
# ohne Lizenzangabe ausgeliefert wird (Audit-Rerun-Followup 2026-06-30).
_TENDER_LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def _tender_int_param(
    raw: str | None, *, name: str, default: int, minimum: int, maximum: int
) -> int:
    """Parst einen int-Query-Parameter mit Default + Cap (422 bei Unsinn).

    Nicht-numerisch -> 422 (UnprocessableError, T-21-INPUT). Negativ -> 422.
    Über dem Cap -> auf den Cap geklemmt (kein Fehler, Best-Practice #8).
    """
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise UnprocessableError(
            f"Query-Parameter '{name}' muss eine ganze Zahl sein.",
            hint=f"Beispiel: ?{name}={default}",
        ) from exc
    if value < minimum:
        raise UnprocessableError(
            f"Query-Parameter '{name}' darf nicht kleiner als {minimum} sein.",
        )
    return min(value, maximum)


def _tender_since_param(raw: str | None) -> str | None:
    """Validiert den ``since``-Query-Parameter als ISO-Datum YYYY-MM-DD.

    ``None`` -> ``None`` (kein Filter). Sonst strikt via ``strptime`` prüfen und
    bei Formatfehler 422 (``UnprocessableError``, T-21-INPUT). Bei Erfolg den
    unveränderten String zurückgeben (der Reader vergleicht String gegen die
    ``publication_date``-Spalte).
    """
    if raw is None:
        return None
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise UnprocessableError(
            "Query-Parameter 'since' muss ein ISO-Datum YYYY-MM-DD sein.",
            hint="Beispiel: ?since=2026-01-01",
        ) from exc
    return raw


@router.get("/cities/{slug}/public-tenders")
async def city_public_tenders(slug: str, request: Request) -> dict:
    """Liefert öffentliche Auftragsvergaben EINER Stadt (TENDER-01/05, CC0/Tier A).

    Ablauf (analog ``city_energy``, API-01, GOV-02/03): Register-Lookup
    (unbekannter Slug -> 404 über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), Query-Validierung
    (status/match gegen Allowlist, sonst 422; limit/offset int + Cap), dann ein
    parametrisierter, read-only Read über ``read_public_tenders`` aus dem
    deduplizierten SQLite-Store (Plan 21-04).

    KRITISCH (T-21-REQINGEST, kein Live-ZIP im Request-Pfad): Diese Route liest
    AUSSCHLIESSLICH aus dem vorverarbeiteten Store, ruft NIE ``fetch_notice_export``
    /``resilient_client`` und schreibt NIE ``append_record``. Die OCDS-ZIPs werden
    offline vom Batch-Ingest (``ingest.oeffentlichevergabe``) gezogen.

    status-Semantik (Quick 260708-f5c): Der DE-OCDS-Export trägt NIE ein
    ``tender.status``; der ``status`` wird semantisch aus dem notice_type
    (OCDS-Release-tag) abgeleitet. ``active`` = laufendes Vergabeverfahren aus der
    Auftragsbekanntmachung (notice_type=tender), ``complete`` = entschiedenes
    Verfahren inkl. aufgehobener/eingestellter Vergaben (notice_type=award). Der
    rohe Zuschlag-Status steht je Notice im Feld ``award_status`` (active =
    Zuschlag erteilt, pending, unsuccessful = aufgehoben, None wenn keine awards).
    Ehrlich: die Angebotsfrist (``deadline``) fehlt im Quell-Export fast immer und
    steht dann nur in der Original-Bekanntmachung über ``source_url``.

    Optionale Query-Filter (parametrisiert in den Reader, T-21-INPUT/T-08-SQLI):
    - ``status``: ``active`` (laufendes Verfahren) | ``complete`` (entschieden)
    - ``match``: ``buyer_city`` | ``place_of_performance``
    - ``q``: freies Titel-Stichwort (parametrisierter ``LIKE``-Teilstring)
    - ``since``: ISO-Datum YYYY-MM-DD (nur Bekanntmachungen ab dem Datum;
      ungültiges Datum -> 422)
    - ``limit`` (Default 50, Cap 200) / ``offset`` (>=0) für Pagination

    Drei ``source_status``-Werte:
    - ``disabled``: ``enable_oeffentlichevergabe`` per Env-Toggle aus -> data None
    - ``no_data``: Quelle aktiv, aber keine Bekanntmachungen für die Stadt
      (Store/Tabelle/Zeilen fehlen -> ``read_public_tenders`` liefert []) ->
      data None, KEIN 5xx
    - ``ok``: Bekanntmachungen vorhanden -> aggregierter Envelope
      (``notices``-Liste + ``count``)
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: aus -> 200 disabled.
    s = Settings()
    if not s.enable_oeffentlichevergabe:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Query-Validierung VOR der Store-Lesung (T-21-INPUT): status/match gegen
    # Allowlist (sonst 422, kein roher Input in die Query), limit/offset int+Cap.
    status_filter = request.query_params.get("status")
    if status_filter is not None and status_filter not in _TENDER_STATUS_ALLOWED:
        raise UnprocessableError(
            "Query-Parameter 'status' ist unzulaessig.",
            hint="Erlaubt: active (laufend), complete (entschieden).",
        )

    match_filter = request.query_params.get("match")
    if match_filter is not None and match_filter not in _TENDER_MATCH_ALLOWED:
        raise UnprocessableError(
            "Query-Parameter 'match' ist unzulaessig.",
            hint="Erlaubt: buyer_city, place_of_performance.",
        )

    # q ist freier Text (kein Allowlist-Zwang), wird im Reader parametrisiert
    # gebunden; since strikt als ISO-Datum validiert (sonst 422, T-21-INPUT).
    q_filter = request.query_params.get("q")
    since_filter = _tender_since_param(request.query_params.get("since"))

    limit = _tender_int_param(
        request.query_params.get("limit"),
        name="limit",
        default=_TENDER_LIMIT_DEFAULT,
        minimum=1,
        maximum=_TENDER_LIMIT_MAX,
    )
    offset = _tender_int_param(
        request.query_params.get("offset"),
        name="offset",
        default=0,
        minimum=0,
        maximum=2_000_000_000,
    )

    # Read-only Store-Lesung (NIE Live-ZIP, T-21-REQINGEST). Fehlender Store/Tabelle
    # -> [] -> no_data, kein 5xx. Alle Filterwerte ?-gebunden im Reader (T-08-SQLI).
    rows = read_public_tenders(
        entry.slug,
        status=status_filter,
        match=match_filter,
        q=q_filter,
        since=since_filter,
        limit=limit,
        offset=offset,
    )

    if not rows:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    return {
        "data": {
            "notices": rows,
            "count": len(rows),
            "license_id": SOURCE_LICENSE["oeffentlichevergabe"]["license_id"],
            "license_tier": "A",
            "attribution": {
                "text": SOURCE_LICENSE["oeffentlichevergabe"]["attribution"],
                "license_url": _TENDER_LICENSE_URL,
            },
        },
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


@router.get("/tenders")
async def all_public_tenders(request: Request) -> dict:
    """Sucht öffentliche Auftragsvergaben deutschlandweit (Cross-City, CC0/Tier A).

    Analog ``city_public_tenders``, aber OHNE Stadt-Lookup: der Endpunkt sucht
    über ALLE Städte im deduplizierten SQLite-Store (Reader
    ``search_public_tenders``), damit der Ausschreibungs-GPT bundesweit nach
    Stichwort und Zeitfenster suchen kann, ohne jede Stadt einzeln abzufragen.
    Da ``cities.router`` ohne Prefix gemountet ist, ergibt der Pfad
    ``/api/v1/tenders``. Die Tender-Konstanten und ``_tender_int_param`` werden
    aus einer Quelle der Wahrheit wiederverwendet (Best-Practice #6, keine
    Duplikate).

    KRITISCH (T-21-REQINGEST, kein Live-ZIP im Request-Pfad): reine read-only
    Store-Lesung, NIE ``fetch_notice_export``/``resilient_client``, kein
    ``append_record``.

    status-Semantik (Quick 260708-f5c): Der DE-OCDS-Export trägt NIE ein
    ``tender.status``; der ``status`` wird semantisch aus dem notice_type
    abgeleitet. ``active`` = laufendes Vergabeverfahren (notice_type=tender),
    ``complete`` = entschiedenes Verfahren inkl. aufgehobener Vergaben
    (notice_type=award); der rohe Zuschlag-Status steht im Feld ``award_status``.
    Ehrlich: die Angebotsfrist (``deadline``) fehlt im Quell-Export fast immer.

    Optionale Query-Filter (parametrisiert in den Reader, T-21-INPUT/T-08-SQLI):
    - ``q``: freies Titel-Stichwort (parametrisierter ``LIKE``-Teilstring)
    - ``status``: ``active`` (laufendes Verfahren) | ``complete`` (entschieden)
    - ``since``: ISO-Datum YYYY-MM-DD (ungültiges Datum -> 422)
    - ``limit`` (Default 50, Cap 200) / ``offset`` (>=0) für Pagination

    ``source_status``: ``disabled`` (Toggle aus) | ``no_data`` (leerer Store) |
    ``ok`` (Bekanntmachungen vorhanden).
    """
    # Quellen-Toggle frisch lesen (Env-Override greift pro Test). Aus -> disabled.
    s = Settings()
    if not s.enable_oeffentlichevergabe:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Query-Validierung VOR der Store-Lesung (T-21-INPUT): status gegen Allowlist
    # (sonst 422), q frei (im Reader ?-gebunden), since strikt als ISO-Datum.
    status_filter = request.query_params.get("status")
    if status_filter is not None and status_filter not in _TENDER_STATUS_ALLOWED:
        raise UnprocessableError(
            "Query-Parameter 'status' ist unzulaessig.",
            hint="Erlaubt: active (laufend), complete (entschieden).",
        )

    q_filter = request.query_params.get("q")
    since_filter = _tender_since_param(request.query_params.get("since"))

    limit = _tender_int_param(
        request.query_params.get("limit"),
        name="limit",
        default=_TENDER_LIMIT_DEFAULT,
        minimum=1,
        maximum=_TENDER_LIMIT_MAX,
    )
    offset = _tender_int_param(
        request.query_params.get("offset"),
        name="offset",
        default=0,
        minimum=0,
        maximum=2_000_000_000,
    )

    # Cross-City read-only Store-Lesung (NIE Live-ZIP, T-21-REQINGEST). Leer -> []
    # -> no_data, kein 5xx. Alle Filterwerte ?-gebunden im Reader (T-08-SQLI).
    rows = search_public_tenders(
        q=q_filter,
        status=status_filter,
        since=since_filter,
        limit=limit,
        offset=offset,
    )

    if not rows:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    return {
        "data": {
            "notices": rows,
            "count": len(rows),
            "license_id": SOURCE_LICENSE["oeffentlichevergabe"]["license_id"],
            "license_tier": "A",
            "attribution": {
                "text": SOURCE_LICENSE["oeffentlichevergabe"]["attribution"],
                "license_url": _TENDER_LICENSE_URL,
            },
        },
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


# --- council-papers (Quick 260708-tsv, kommunale Ratsinformationen, OParl) ----

# Pagination-Cap der council-papers-Route (eigene Konstanten, kleiner als tenders,
# weil einzelne Paper-Objekte grösser sind). Best-Practice #8.
_COUNCIL_LIMIT_DEFAULT = 50
_COUNCIL_LIMIT_MAX = 100


@router.get("/cities/{slug}/council-papers")
# Alias-Pfad, absichtlich NICHT im generierten Schema: zwei Routen auf derselben
# Funktion erben dieselbe operationId, und FastAPI warnt dann bei jedem
# Spec-Aufbau ("Duplicate Operation ID"). Die veroeffentlichte Referenz
# (docs/openapi.yaml) fuehrt den Alias ohnehin nur in der Beschreibung, nicht als
# eigenen Pfad; include_in_schema haelt beide Specs deckungsgleich. Die Route
# bleibt voll funktionsfaehig (Test test_council_papers_alias).
@router.get("/cities/{slug}/council/papers", include_in_schema=False)
async def city_council_papers(slug: str, request: Request) -> dict:
    """Liefert kommunale Ratsinformationen EINER Stadt (council-papers, OParl).

    Schwester-Route zu ``city_public_tenders``: was die Stadt ENTSCHEIDET (Vorlagen,
    Anträge, Beschlüsse), analog zu was die Stadt EINKAUFT. Unter ZWEI Pfaden
    registriert (dieselbe Funktion): ``/cities/{slug}/council-papers`` (kanonisch,
    MCP-/Katalog-/Coverage-Key) und ``/cities/{slug}/council/papers`` (Alias für
    menschliche/GPT-Nutzung).

    Ablauf:
    1. ``get_city(slug)`` (unbekannter Slug -> zentraler 404-Handler).
    2. Coverage-Guard: Stadt NICHT in ``COVERED_COUNCIL_CITIES`` -> 404 mit Hint
       (nur die acht lizenzgeklärten Städte sind abgedeckt).
    3. ``enable_council`` aus -> 200 ``source_status="disabled"``, data None.
    4. Query-Validierung: ``q`` frei (im Reader ?-gebunden), ``since`` ISO-Datum,
       ``paper_type`` frei/optional, ``limit`` (Default 50, Cap 100) / ``offset``.
    5. ``read_council_papers`` (read-only Store, NIE Live-OParl im Request-Pfad).
       Leer -> 200 ``source_status="no_data"``.
    6. Treffer -> ``{data:{papers, count, total, attribution}, meta:{...}}`` mit
       per-Stadt-Attribution aus ``COUNCIL_CITY_LICENSE``. ``count`` ist die
       Seitenlänge, ``total`` der Gesamtbestand zu den aktiven Filtern (gleiche
       ?-gebundene Bedingungen, ``count_council_papers``), damit Clients den
       Bestand kennen, ohne bis zur leeren Seite zu blättern.

    Read-only (wie public-tenders): der Batch-Ingest (``ingest.oparl``) zieht die
    OParl-Paper offline; die Route liest ausschliesslich aus dem Store. PDFs sind
    NUR als ``main_file_url``-Link enthalten (nie gespiegelt).
    """
    entry = get_city(slug)

    # Coverage-Guard: nur die acht lizenzgeklärten Städte (fail-closed). Eine nicht
    # abgedeckte Stadt ist hier ein echter 404 (die Datenart existiert für sie
    # nicht), mit agentenfreundlichem Hint.
    if entry.slug not in COVERED_COUNCIL_CITIES:
        raise NotFoundError(
            f"council-papers ist für '{entry.slug}' nicht verfügbar.",
            hint=(
                "council-papers gibt es nur für: "
                + ", ".join(sorted(COVERED_COUNCIL_CITIES))
                + "."
            ),
        )

    # Quellen-Toggle frisch lesen (Settings() statt app.state, damit der per-Test
    # gesetzte Env-Override greift). Default-off: aus -> 200 disabled.
    s = Settings()
    if not s.enable_council:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    # Query-Validierung VOR der Store-Lesung (T-INPUT): q/paper_type frei (im Reader
    # ?-gebunden), since strikt ISO-Datum (sonst 422), limit/offset int + Cap.
    q_filter = request.query_params.get("q")
    paper_type_filter = request.query_params.get("paper_type")
    since_filter = _tender_since_param(request.query_params.get("since"))

    limit = _tender_int_param(
        request.query_params.get("limit"),
        name="limit",
        default=_COUNCIL_LIMIT_DEFAULT,
        minimum=1,
        maximum=_COUNCIL_LIMIT_MAX,
    )
    offset = _tender_int_param(
        request.query_params.get("offset"),
        name="offset",
        default=0,
        minimum=0,
        maximum=2_000_000_000,
    )

    rows = read_council_papers(
        entry.slug,
        q=q_filter,
        since=since_filter,
        paper_type=paper_type_filter,
        limit=limit,
        offset=offset,
    )

    if not rows:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    # Gesamtbestand zu den aktiven Filtern (gleiche ?-gebundene Bedingungen wie
    # die Lese-Query): Clients sollen den Bestand kennen, ohne bis zur leeren
    # Seite zu blättern.
    total = count_council_papers(
        entry.slug,
        q=q_filter,
        since=since_filter,
        paper_type=paper_type_filter,
    )

    lic = COUNCIL_CITY_LICENSE[entry.slug]
    return {
        "data": {
            "papers": rows,
            "count": len(rows),
            "total": total,
            "license_id": lic["license_id"],
            "license_tier": "A",
            "attribution": {
                "text": lic["attribution"],
                "license_url": lic["license_url"],
                "source": lic["source"],
                "modified": lic["modified"],
            },
        },
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }
