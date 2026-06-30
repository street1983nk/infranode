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
import os
from datetime import UTC, datetime

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Request, Response

from infranode.adapters.autobahn import fetch_traffic, fetch_webcams
from infranode.adapters.baumkataster import fetch_trees
from infranode.adapters.berlin_radzaehl import fetch_berlin_radzaehl
from infranode.adapters.berlin_viz import fetch_berlin_road_events
from infranode.adapters.db_fasta import fetch_station_facilities
from infranode.adapters.db_timetables import (
    fetch_station_arrivals,
    fetch_station_departures,
)
from infranode.adapters.denkmal import fetch_heritage
from infranode.adapters.destination_one import fetch_events
from infranode.adapters.divi_live import fetch_icu_live
from infranode.adapters.dwd import fetch_weather
from infranode.adapters.dwd_fire import fetch_fire_danger
from infranode.adapters.dwd_pollen import fetch_pollen_uv
from infranode.adapters.dwd_warnings import (
    extract_warncell,
    fetch_dwd_warnings_all,
    warncell_for_ags,
)
from infranode.adapters.eea_bathing import fetch_bathing_water
from infranode.adapters.gbfs import fetch_sharing
from infranode.adapters.genesis import (
    fetch_demographics,
    fetch_genesis_table,
    fetch_hospitals,
)
from infranode.adapters.hamburg_radzaehl import fetch_hamburg_radzaehl
from infranode.adapters.hamburg_transparenz import fetch_hamburg_road_events
from infranode.adapters.klinik_atlas import fetch_hospital_atlas
from infranode.adapters.koeln_arcgis import fetch_koeln_road_events
from infranode.adapters.koeln_events import fetch_events as fetch_koeln_events
from infranode.adapters.leipzig_radzaehl import fetch_leipzig_radzaehl
from infranode.adapters.lhp import fetch_flood
from infranode.adapters.mobidata_bw import fetch_mobidata_road_events
from infranode.adapters.mobilithek_datex2 import fetch_datex2
from infranode.adapters.muenchen_opendata import (
    fetch_muenchen_parking,
    fetch_muenchen_road_events,
)
from infranode.adapters.muenchen_radzaehl import fetch_muenchen_radzaehl
from infranode.adapters.overpass import (
    _ALLOWED_TYPES,
    fetch_osm_feature,
    fetch_pois,
)
from infranode.adapters.parkendd import PARKENDD_CITIES, fetch_parkendd
from infranode.adapters.pegelonline import fetch_water_level
from infranode.adapters.smard import fetch_smard
from infranode.adapters.solar import fetch_solar
from infranode.adapters.stada import fetch_all_stations
from infranode.adapters.stuttgart_radzaehl import fetch_stuttgart_radzaehl
from infranode.adapters.tankerkoenig import fetch_fuel_prices
from infranode.adapters.uba import fetch_air_uba
from infranode.adapters.wikidata import fetch_city_base, fetch_hospitals_wikidata
from infranode.adapters.zensus_grid import fetch_population_density
from infranode.api.errors import UnprocessableError, UpstreamError
from infranode.archive.bka_pks_db import read_crime_stats
from infranode.archive.boris_db import read_land_values
from infranode.archive.inkar_db import read_indicators
from infranode.archive.kba_db import read_vehicle_registrations
from infranode.archive.mastr_db import read_energy
from infranode.archive.regionalstatistik_db import (
    read_business_registrations,
    read_insolvencies,
    read_tax_rates,
)
from infranode.archive.store import append_record, read_records
from infranode.archive.tender_db import read_public_tenders
from infranode.archive.transit_store import read_stops
from infranode.archive.unfallatlas_db import read_accidents
from infranode.config import Settings
from infranode.infra.cache import build_cache_key
from infranode.normalization.mappers.autobahn import (
    map_autobahn_traffic,
    map_autobahn_webcams,
)
from infranode.normalization.mappers.baumkataster import map_trees
from infranode.normalization.mappers.berlin_viz import map_berlin_road_events
from infranode.normalization.mappers.bike_counts import (
    map_berlin_radzaehl,
    map_hamburg_radzaehl,
    map_leipzig_radzaehl,
    map_stuttgart_radzaehl,
)
from infranode.normalization.mappers.bka_pks import map_crime_stats
from infranode.normalization.mappers.boris import map_land_values
from infranode.normalization.mappers.db_fasta import map_station_facilities
from infranode.normalization.mappers.db_timetables import (
    map_station_arrivals,
    map_station_departures,
)
from infranode.normalization.mappers.denkmal import map_heritage
from infranode.normalization.mappers.destination_one import (
    map_destination_one_events,
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
from infranode.normalization.mappers.icu_live import map_icu_live
from infranode.normalization.mappers.inkar import map_indicators
from infranode.normalization.mappers.kba import map_vehicle_registrations
from infranode.normalization.mappers.klinik_atlas import map_hospital_atlas
from infranode.normalization.mappers.koeln_arcgis import map_koeln_road_events
from infranode.normalization.mappers.koeln_events import map_koeln_events
from infranode.normalization.mappers.lhp import map_flood
from infranode.normalization.mappers.mastr import map_mastr_assets
from infranode.normalization.mappers.mobidata_bw import map_mobidata_road_events
from infranode.normalization.mappers.mobilithek_bremen import map_bremen_road_events
from infranode.normalization.mappers.muenchen_opendata import (
    map_muenchen_parking,
    map_muenchen_road_events,
)
from infranode.normalization.mappers.muenchen_radzaehl import map_muenchen_radzaehl
from infranode.normalization.mappers.overpass import map_osm_feature, map_overpass_pois
from infranode.normalization.mappers.parkendd import map_parkendd
from infranode.normalization.mappers.pegelonline import map_water_level
from infranode.normalization.mappers.regionalstatistik import (
    map_business_registrations,
    map_insolvencies,
    map_tax_rates,
)
from infranode.normalization.mappers.smard import map_smard
from infranode.normalization.mappers.solar import map_solar
from infranode.normalization.mappers.solar_cadastre import (
    load_solar_roofs,
    map_solar_roofs,
)
from infranode.normalization.mappers.stada import map_station_catalog
from infranode.normalization.mappers.tankerkoenig import map_fuel_prices
from infranode.normalization.mappers.uba import map_air_uba
from infranode.normalization.mappers.unfallatlas import map_accidents
from infranode.normalization.mappers.wikidata import map_wikidata_city
from infranode.normalization.mappers.zensus_grid import map_population_density
from infranode.registry import get_city, list_cities
from infranode.registry.catalog import CITY_DATA_CATALOG
from infranode.registry.coverage import PARTIAL_COVERAGE, covered_cities, is_covered
from infranode.registry.source_specs import SOURCE_LICENSE

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
    "koeln": ("koeln_verkehr", fetch_koeln_road_events, map_koeln_road_events),
    "hamburg": (
        "hamburg_baustellen",
        fetch_hamburg_road_events,
        map_hamburg_road_events,
    ),
    "muenchen": (
        "muenchen_baustellen",
        fetch_muenchen_road_events,
        map_muenchen_road_events,
    ),
    "stuttgart": (
        "mobidata_bw",
        fetch_mobidata_road_events,
        map_mobidata_road_events,
    ),
    # DATA-31: Bremen kommt NICHT keylos, sondern über den Mobilithek-mTLS-Pull
    # (VMZ Bremen, DATEX II Situation). fetch_fn=None signalisiert dem
    # city_road_events-Handler den mTLS-Sonderpfad (_bremen_road_events); der
    # generische keylose Pfad wird für Bremen NICHT betreten. Eintrag hält die
    # Coverage-Karte (PARTIAL_COVERAGE["road-events"]) drift-synchron.
    "bremen": ("bremen_baustellen", None, map_bremen_road_events),
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
GBFS_SYSTEMS: dict[str, tuple[str, ...]] = {
    "berlin": ("nextbike_bn",),
    "muenchen": ("nextbike_ml",),
    "koeln": ("nextbike_kg",),
    "frankfurt-am-main": ("nextbike_ff",),
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
    except Exception:  # noqa: BLE001 - Snapshot degradiert still (Overview hängt nie)
        return name, {"data": None, "source_status": "error"}
    if raw is None:
        return name, {"data": None, "source_status": "error"}
    if not raw:
        return name, {"data": None, "source_status": "no_data"}
    try:
        record = mapper(
            raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
        )
    except Exception:  # noqa: BLE001 - defekter Datensatz einer Quelle -> error
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
    except Exception:  # noqa: BLE001 - Snapshot degradiert still (Overview hängt nie)
        return name, {"data": None, "source_status": "error"}
    if raw is None:
        return name, {"data": None, "source_status": "error"}
    if not raw:
        return name, {"data": None, "source_status": "no_data"}
    try:
        record = map_station_departures(
            raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
        )
    except Exception:  # noqa: BLE001 - defekter Datensatz -> error statt 5xx
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
        except Exception:  # noqa: BLE001 - Timeout/Fehler -> nur diese Quelle "error"
            return name, {"data": None, "source_status": "error"}

    tasks = [
        _bounded(name, _snapshot_one(entry, request, name))
        for name in _SNAPSHOT_SOURCES
    ]
    tasks.append(_bounded("departures", _snapshot_departures(entry, request)))
    highlights: dict[str, dict] = dict(await asyncio.gather(*tasks))

    return {
        "data": {
            "city": entry.model_dump(mode="json"),
            "data_types": catalog,
            "highlights": highlights,
            "summary": {
                "data_types_total": len(catalog),
                "data_types_available": available,
                "cities_total": len(list_cities()),
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
async def city_charging(slug: str) -> dict:
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
    ältere Pfad ``/air`` (oben) liefert dieselbe UBA-Quelle live ohne Persistenz.
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


@router.get("/cities/{slug}/pois")
async def city_pois(slug: str, request: Request, type: str) -> dict:
    """Liefert nach Typ gefilterte OSM-POIs im kanonischen Envelope (DATA-04).

    Ablauf (DATA-04/06, API-01, GOV-02): Register-Lookup (unbekannter
    Slug -> 404 mit Hint über den zentralen Handler), Quellen-Toggle-Prüfung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), Typ-Whitelist-
    Prüfung VOR dem Fetch (unbekannter Typ -> 422, kein roher Input in die
    Overpass-QL, T-05-09), resilienter Fetch über die Fassade (der ``type``
    fließt per ``params`` als sha256-Hash in den Cache-Key -> Cache-Poisoning-
    Schutz T-05-10), Mapping, dann der Daten-Envelope.
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

    # T-05-09 Injection: unbekannter Typ -> 422, BEVOR ein Fetch läuft. Roher
    # User-Input gelangt nie in die Overpass-QL (die Whitelist mappt auf ein
    # festes amenity-Tag). Der Hint nennt die erlaubten Typen.
    if type not in _ALLOWED_TYPES:
        raise UnprocessableError(
            f"Unbekannter POI-Typ '{type}'.",
            hint=f"Erlaubte Typen: {', '.join(sorted(_ALLOWED_TYPES))}.",
        )

    client = request.app.state.resilient_client
    # type als params -> sha256-Hash im Cache-Key (Cache-Poisoning-Schutz, T-05-10).
    key = build_cache_key("overpass", city_slug=entry.slug, params={"type": type})

    async def fetch_fn():
        return await fetch_pois(
            request.app.state.http,
            slug=entry.slug,
            osm_relation=entry.osm_relation,
            poi_type=type,
            base_url=Settings().overpass_base_url,
            max_elements=Settings().overpass_max_elements,
        )

    raw, status = await client.fetch("overpass", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'overpass' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_overpass_pois(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="osm")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


async def _osm_feature_response(request: Request, entry, feature: str) -> dict:
    """Geteilte Logik aller OSM-Feature-Endpunkte (Overpass, Tier B copyleft).

    Identischer Ablauf wie ``/pois`` (DATA-04/06): Quellen-Toggle (deaktiviert ->
    200 ``source_status=disabled``, nie 5xx), resilienter Fetch über die Fassade
    (``feature`` fließt per ``params`` als sha256-Hash in den Cache-Key, Cache-
    Poisoning-Schutz T-05-10), None-Guard (toter Upstream ohne Cache -> 503), dann
    Mapping mit ODbL-Attribution und Daten-Envelope. ``feature`` ist stets ein
    festes, intern gesetztes Literal aus ``_OSM_FEATURES`` (kein User-Input)."""
    if not Settings().enable_overpass:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    # feature als params -> sha256-Hash im Cache-Key (Cache-Poisoning-Schutz).
    key = build_cache_key("overpass", city_slug=entry.slug, params={"feature": feature})

    async def fetch_fn():
        return await fetch_osm_feature(
            request.app.state.http,
            slug=entry.slug,
            osm_relation=entry.osm_relation,
            feature=feature,
            base_url=Settings().overpass_base_url,
            max_elements=Settings().overpass_max_elements,
        )

    raw, status = await client.fetch("overpass", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'overpass' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_osm_feature(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="osm")

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


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
    if not Settings().enable_denkmal:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("denkmal", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_heritage(
            request.app.state.http,
            slug=entry.slug,
            state=entry.state,
        )

    raw, status = await client.fetch("denkmal", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprüft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'denkmal' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_heritage(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="denkmal")

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

    if not Settings().enable_baumkataster:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("baumkataster", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_trees(request.app.state.http, slug=entry.slug)

    raw, status = await client.fetch("baumkataster", key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Quelle 'baumkataster' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    record = map_trees(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    await append_record(record, source="baumkataster")

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

    record = map_autobahn_traffic(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
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
    abo_id = settings.bremen_baustellen_abo_id
    if not settings.enable_bremen_baustellen or mobilithek_http is None or not abo_id:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }

    client = request.app.state.resilient_client
    key = build_cache_key("bremen_baustellen", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_datex2(
            mobilithek_http,
            abo_id=abo_id,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            publication="situation",
        )

    raw, status = await client.fetch("bremen_baustellen", key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'bremen_baustellen' voruebergehend nicht erreichbar, kein Cache.",
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
    await append_record(record, source="bremen_baustellen")
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


# Parking-Connector-Auflösung (DATA-40, Dedup-Prinzip): EIN Parking-Endpunkt mit
# Quellen-Fallback. Bevorzugt ParkenDD (Live-Belegung frei/gesamt, ~22 Städte,
# Lizenz PRO STADT am Ursprung verifiziert, sonst ehrlich UNKNOWN/Tier C); für
# München der statische CKAN-Standortkatalog (Fallback ohne Live-Belegung, Tier A
# DL-DE/BY). Beide Adapter teilen die Signatur
# (http, *, slug, lat, lon) und Mapper-Signatur (raw, *, retrieved_at, ags, qid).
# Die abgedeckten Slugs (PARTIAL_COVERAGE["parking"]) leiten sich aus genau diesen
# Quellen ab (PARKENDD_CITIES | {muenchen}); ein nicht aufgelöster Slug ist daher
# automatisch not_covered.
def _resolve_parking_connector(slug: str):
    """Liefert ``(source, fetch_fn, map_fn)`` für den Parking-Endpunkt oder None."""
    if slug in PARKENDD_CITIES:
        return ("parkendd", fetch_parkendd, map_parkendd)
    if slug == "muenchen":
        return ("muenchen_parkhaeuser", fetch_muenchen_parking, map_muenchen_parking)
    return None


@router.get("/cities/{slug}/parking")
async def city_parking(slug: str, request: Request) -> dict:
    """Liefert Parkhaus-Daten je Stadt im kanonischen Envelope (DATA-40, Dedup).

    EIN Parking-Endpunkt mit Quellen-Fallback (löst das frühere
    /live/dortmund/parking ab): bevorzugt ParkenDD-Live-Belegung (frei/gesamt je
    Parkhaus, ~22 Städte keylos, Lizenz pro Stadt am Ursprung verifiziert), für
    München den statischen CKAN-Standortkatalog (Fallback ohne Live-Belegung,
    Tier A DL-DE/BY).

    Ablauf wie ``city_road_events``: Register-Lookup (404 bei unbekanntem Slug),
    Coverage-/Connector-Prüfung (nicht abgedeckt -> 200 ``not_covered`` +
    covered_cities), Quellen-Toggle (aus -> 200 ``disabled``), resilienter Fetch
    über die Fassade, Mapping. Quelle erreichbar aber leer -> ``no_data``; toter
    Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint. KEIN Archiv-Write
    (Live-/Standortdaten).
    """
    entry = get_city(slug)

    connector = _resolve_parking_connector(entry.slug)
    if connector is None:
        return _not_covered("parking")
    source, fetch_parking, map_parking = connector

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
        return await fetch_parking(
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


# Bike-Counts-Connector-Auflösung (DATA-40): EIN /cities/{slug}/bike-counts-
# Endpunkt mit Per-Stadt-Quelle (kommunale Radzähl-Open-Data, KEIN Eco-Counter:
# dessen Lizenz ist ungeklärt -> Owner-Entscheidung 2026-06-23 "ausschliessen").
# Jede Quelle ist am Ursprung lizenz-verifiziert (Tier im Mapper). Eintrag:
# slug -> (source, fetch_factory(http, entry) -> raw, mapper). Die fetch_factory
# kapselt die je Quelle leicht abweichende Adapter-Signatur (z.B. München braucht
# das Jahr für das CKAN-Paket). Nicht aufgelöster Slug -> not_covered.
async def _fetch_muenchen_radzaehl(http, entry) -> dict:
    """Adapter-Wrapper Muenchen: injiziert das aktuelle Jahr (CKAN-Jahres-Paket)."""
    return await fetch_muenchen_radzaehl(
        http,
        slug=entry.slug,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
        year=datetime.now(UTC).year,
    )


async def _fetch_leipzig_radzaehl(http, entry) -> dict:
    """Adapter-Wrapper Leipzig (Standard-Signatur)."""
    return await fetch_leipzig_radzaehl(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


async def _fetch_hamburg_radzaehl(http, entry) -> dict:
    """Adapter-Wrapper Hamburg (Standard-Signatur)."""
    return await fetch_hamburg_radzaehl(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


async def _fetch_berlin_radzaehl(http, entry) -> dict:
    """Adapter-Wrapper Berlin (Standard-Signatur)."""
    return await fetch_berlin_radzaehl(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


async def _fetch_stuttgart_radzaehl(http, entry) -> dict:
    """Adapter-Wrapper Stuttgart (Standard-Signatur)."""
    return await fetch_stuttgart_radzaehl(
        http, slug=entry.slug, lat=entry.geo.lat, lon=entry.geo.lon
    )


def _resolve_bike_counts_connector(slug: str):
    """Liefert ``(source, fetch_factory, map_fn)`` für bike-counts oder None."""
    if slug == "muenchen":
        return ("muenchen_radzaehl", _fetch_muenchen_radzaehl, map_muenchen_radzaehl)
    if slug == "leipzig":
        return ("leipzig_radzaehl", _fetch_leipzig_radzaehl, map_leipzig_radzaehl)
    if slug == "hamburg":
        return ("hamburg_radzaehl", _fetch_hamburg_radzaehl, map_hamburg_radzaehl)
    if slug == "berlin":
        return ("berlin_radzaehl", _fetch_berlin_radzaehl, map_berlin_radzaehl)
    if slug == "stuttgart":
        return (
            "stuttgart_radzaehl",
            _fetch_stuttgart_radzaehl,
            map_stuttgart_radzaehl,
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

    return {
        "data": records[0].model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": cache_status,
            "records": [r.model_dump(mode="json") for r in records],
        },
    }


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


@router.get("/cities/{slug}/transit")
async def city_transit(slug: str) -> dict:
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

    status = "ok" if records else "not_ingested"

    return {
        "data": [r.model_dump(mode="json") for r in records],
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": status,
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
    Seeds ``data/seeds/feiertage_<jahr>.json`` + ``schulferien_<jahr>.json``.

    KRITISCH (kein Upstream im Request-Pfad, T-08-DEP): Diese Route liest
    AUSSCHLIESSLICH aus den committeten statischen Seeds via stdlib ``json``,
    ruft KEINE Laufzeit-Fremd-API auf, KEIN ``resilient_client``.

    KRITISCH (Gray-Area, GOV-02): Feiertage/Schulferien sind GEMEINFREIE Fakten
    (Tier C, nur Live-Anzeige), so in der Attribution markiert. Die Seeds sind
    statisch im Repo (kein DB-Schutzrecht).

    Drei ``source_status``-Werte:
    - ``disabled``: ``enable_feiertage`` per Env-Toggle aus -> data None
    - ``no_data``: Quelle aktiv, aber keine Seed-Einträge für Bundesland/Jahr
      (z. B. fehlende Datei) -> data None, KEIN 5xx (ehrlich)
    - ``ok``: Seed-Einträge vorhanden -> holiday-Payload je entry.state mit
      Attribution + license_id (gemeinfrei, nicht permissiv lizenziert)
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: aus -> 200 disabled, nie 5xx.
    s = Settings()
    if not s.enable_feiertage:
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

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
        },
    }


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
    measure: str,
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

    Holt die bundesweite DWD-WarnApp-JSON (einmal gecacht) und filtert die Stadt
    über ihre Gemeinde-Warncell (= '1'+AGS). max_level 0 = keine reguläre Warnung,
    1-4 = DWD-Warnstufe; Hitze-/Sonderwarnungen (DWD-Code >= 50) zählen NICHT in
    max_level, sondern stehen separat in special_warnings (Audit K5). Quelle:
    Deutscher Wetterdienst (GeoNutzV). Deaktiviert -> 200 source_status="disabled".
    """
    entry = get_city(slug)
    cid = correlation_id.get()
    if not Settings().enable_dwd_warnings:
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }
    client = request.app.state.resilient_client
    # Ein Fetch des bundesweiten Files reicht für alle Städte -> globaler Cache-Key.
    key = build_cache_key("dwd_warnings", city_slug="all")

    async def fetch_fn():
        return await fetch_dwd_warnings_all(request.app.state.http)

    full, status = await client.fetch("dwd_warnings", key, fetch_fn)
    if full is None:
        raise UpstreamError(
            "Quelle 'dwd_warnings' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )
    raw = extract_warncell(full, warncell_for_ags(entry.ags))
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
        return await fetch_fuel_prices(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            apikey=apikey,
        )

    # ON-DEMAND (store=False): Tankerkoenig/MTS-K-ToS verbieten Spiegeln/Vorhalten
    # ("nur aktuelle Preise auf Useraktion"). Daher KEIN Redis-Cache, kein Stale,
    # kein SWR-Refresh und kein persistenter Schreibpfad (auch kein Hintergrund-Job).
    raw, status = await client.fetch("tankerkoenig", cache_key, fetch_fn, store=False)
    if raw is None:
        raise UpstreamError(
            "Quelle 'tankerkoenig' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
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
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        lat=entry.geo.lat,
        lon=entry.geo.lon,
    )
    # KEIN append_record: Tankerkönig-ToS untersagen das Vorhalten/Archivieren der
    # Preise (on-demand, nur Live-Anzeige). Die Quelle wird daher nirgends
    # persistiert, sondern ausschließlich live bei Useraktion ausgeliefert.
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
    - ICU-Kapazität je Kreis (RKI-DIVI-GitHub-CSV, CC-BY 4.0): read-only aus dem
      vorverarbeiteten divi-Datensatz. H2-Fix: nur der JÜNGSTE Stand
      (nach ``payload.datum`` sortiert), nicht der komplette Verlauf;
      ``meta.icu_latest`` trägt das Stichdatum.

    Ablauf (DATA-25/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint), account-gated Toggle-/Key-Guard für das
    Krankenhausverzeichnis (Quelle aus ODER kein Credential -> kein Live-Call),
    Read der ICU-Kapazität. ``source_status`` weist die Abdeckung ehrlich
    aus (``disabled``/``not_ingested``/``ok``).

    KRITISCH (T-08-CRED): Die GENESIS-Credentials gelangen nur in den POST-Body des
    Adapters, NIE in den Cache-Key oder die Response. KRITISCH (T-08-DBR): Diese
    Route liefert NUR die Tier-A-Aggregate (Krankenhaus, Kreis-ICU-CSV); die
    klinikscharfe DIVI-Live-Lage läuft getrennt über ``/icu-live`` (Tier C,
    nur Live-Anzeige).
    """
    entry = get_city(slug)

    # ICU-Kapazität (Kreisebene, CC-BY 4.0) read-only aus dem divi-Datensatz
    # (NIE die CSV im Request-Pfad). Fehlend -> [] (not_ingested).
    icu_records = read_records(source="divi", tier="A", city_slug=entry.slug)

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

        # Kein Krankenhaus (auch kein Wikidata-Treffer) und keine ICU-Kapazität
        # -> die ganze Slice ist disabled; sonst die vorhandene(n) Sicht(en).
        if hospital_data is None and not icu_records:
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

    # H2-Fix (Audit 2026-06-29): read_records liefert ALLE ICU-Records unsortiert
    # (Live: berlin = 1971 Records ab 2020). Früher wurde der ganze Verlauf
    # ausgeliefert (icu_capacity[0] = ältester Stand). Jetzt: nach Stand-Datum
    # (payload.datum) sortieren und NUR den jüngsten Record ausliefern; ein
    # latest-Stichdatum macht den Stand transparent. Records ohne datum sinken
    # ans Ende (leerer Sortier-Key).
    def _icu_datum(rec) -> str:
        datum = getattr(rec.payload, "datum", None)
        return datum or ""

    icu_sorted = sorted(icu_records, key=_icu_datum)
    latest_icu = icu_sorted[-1] if icu_sorted else None
    icu_data = [latest_icu.model_dump(mode="json")] if latest_icu is not None else []
    icu_latest_date = _icu_datum(latest_icu) or None if latest_icu is not None else None

    # source_status: ok sobald irgendeine Sicht Daten trägt, sonst not_ingested
    # (Quelle aktiv/lesbar, aber noch kein Snapshot/Datensatz).
    status = "ok" if (hospital_data is not None or icu_data) else "not_ingested"

    meta: dict = {
        "correlation_id": correlation_id.get(),
        "source_status": status,
    }
    if fallback is not None:
        meta["fallback"] = fallback
    if icu_latest_date is not None:
        meta["icu_latest"] = icu_latest_date

    return {
        "data": {
            "hospital": hospital_data,
            "icu_capacity": icu_data,
        },
        "meta": meta,
    }


@router.get("/cities/{slug}/icu-live")
async def city_icu_live(slug: str, request: Request) -> dict:
    """Liefert klinikscharfe DIVI-Live-ICU-Daten (DATA-25b, Tier C, T-08-DBR).

    Ablauf (DATA-25b/06, API-01, GOV-02) nach dem ``city_air``-Tier-C-Muster:
    Register-Lookup (unbekannter Slug -> 404 mit Hint), Quellen-Toggle-Prüfung
    (``enable_divi`` aus -> 200 ``source_status=disabled``, nie 5xx), resilienter
    Fetch über die Fassade gegen die keylose DIVI-Live-API, Mapping über
    ``map_icu_live`` (Tier C). Fehlt eine kuratierte Kreis-Kennung oder ist der
    Upstream tot ohne Cache, liefert die Route ehrlich
    ``source_status="no_data"`` (200, kein 5xx; Tier-C-Live-Degradation).

    KRITISCH (Datenbank-Schutzrecht, RESEARCH Pitfall 4, T-08-DBR): Die
    klinikscharfe DIVI-Live-Lage ist Tier C live-only. Diese Route leitet die
    Daten ausschließlich live durch (bewusste Tier-C-Entscheidung, kein Versehen,
    analog city_air). NUR die Kreis-Aggregat-CSV (CC-BY 4.0, Tier A) läuft
    getrennt über ``/health``.
    """
    entry = get_city(slug)

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    if not Settings().enable_divi:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("divi_live", city_slug=entry.slug)

    # Kreis-Präfix aus dem Register ableiten (Finding 218): die ersten 5 AGS-Stellen
    # sind der Kreisschlüssel -> alle 84 Städte abgedeckt, nicht nur die vier
    # kuratierten. Quelle ist das Register (entry.ags), nie User-Input (T-08-SSRF).
    kreis_ags = entry.ags[:5] if entry.ags else None

    async def fetch_fn():
        return await fetch_icu_live(
            request.app.state.http, slug=entry.slug, kreis_ags=kreis_ags
        )

    raw, status = await client.fetch("divi_live", key, fetch_fn)

    # Tier-C-Live-Degradation: toter Upstream ohne Cache (raw None) oder keine
    # kuratierte Kreis-Kennung (kreis_id None) -> ehrliches no_data (200), KEIN
    # 5xx. Die Live-Lage ist optional/teilabdeckend.
    if raw is None or raw.get("kreis_id") is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

    record = map_icu_live(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    # KRITISCH (T-08-DBR, Pitfall 4): Tier C live-only. Der Envelope wird direkt
    # zurückgegeben.

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }


# OCDS-Status-Allowlist (T-21-INPUT): nur diese Werte gelangen überhaupt in den
# parametrisierten Reader. "active" = laufende Ausschreibung, "complete" = bereits
# vergeben (OCDS-tender.status). Ein unbekannter Wert -> 422, BEVOR roher Input in
# die Query geht (kein f-string/%-SQL am Aufrufort, alle Werte ?-gebunden).
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

    Optionale Query-Filter (parametrisiert in den Reader, T-21-INPUT/T-08-SQLI):
    - ``status``: ``active`` (laufend) | ``complete`` (vergeben)
    - ``match``: ``buyer_city`` | ``place_of_performance``
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
            hint="Erlaubt: active (laufend), complete (vergeben).",
        )

    match_filter = request.query_params.get("match")
    if match_filter is not None and match_filter not in _TENDER_MATCH_ALLOWED:
        raise UnprocessableError(
            "Query-Parameter 'match' ist unzulaessig.",
            hint="Erlaubt: buyer_city, place_of_performance.",
        )

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
