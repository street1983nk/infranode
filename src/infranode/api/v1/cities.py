"""Stadt-Routen ueber das Register + Wikidata-Stammdaten-Slice.

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

from datetime import UTC, datetime

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Request, Response

from infranode.adapters.autobahn import fetch_traffic, fetch_webcams
from infranode.adapters.berlin_viz import fetch_berlin_road_events
from infranode.adapters.destination_one import fetch_events
from infranode.adapters.divi_live import fetch_icu_live
from infranode.adapters.dwd import fetch_weather
from infranode.adapters.dwd_pollen import fetch_pollen_uv
from infranode.adapters.genesis import fetch_demographics
from infranode.adapters.hamburg_transparenz import fetch_hamburg_road_events
from infranode.adapters.koeln_arcgis import fetch_koeln_road_events
from infranode.adapters.koeln_events import fetch_events as fetch_koeln_events
from infranode.adapters.lhp import fetch_flood
from infranode.adapters.mobidata_bw import fetch_mobidata_road_events
from infranode.adapters.muenchen_opendata import fetch_muenchen_road_events
from infranode.adapters.openaq import fetch_air
from infranode.adapters.overpass import _ALLOWED_TYPES, fetch_pois
from infranode.adapters.pegelonline import fetch_water_level
from infranode.adapters.uba import fetch_air_uba
from infranode.adapters.wikidata import fetch_city_base
from infranode.api.errors import UnprocessableError, UpstreamError
from infranode.archive.mastr_db import read_energy
from infranode.archive.store import append_record, read_records
from infranode.archive.transit_store import read_stops
from infranode.config import Settings
from infranode.infra.cache import build_cache_key
from infranode.normalization.mappers.autobahn import (
    map_autobahn_traffic,
    map_autobahn_webcams,
)
from infranode.normalization.mappers.berlin_viz import map_berlin_road_events
from infranode.normalization.mappers.destination_one import (
    map_destination_one_events,
)
from infranode.normalization.mappers.dwd import map_weather
from infranode.normalization.mappers.dwd_pollen import map_pollen_uv
from infranode.normalization.mappers.genesis import (
    map_demographics,
    map_population_demographics,
)
from infranode.normalization.mappers.hamburg_transparenz import map_hamburg_road_events
from infranode.normalization.mappers.holidays import load_holidays, map_holidays
from infranode.normalization.mappers.hospital import map_hospital
from infranode.normalization.mappers.icu_live import map_icu_live
from infranode.normalization.mappers.koeln_arcgis import map_koeln_road_events
from infranode.normalization.mappers.koeln_events import map_koeln_events
from infranode.normalization.mappers.lhp import map_flood
from infranode.normalization.mappers.mastr import map_mastr_assets
from infranode.normalization.mappers.mobidata_bw import map_mobidata_road_events
from infranode.normalization.mappers.muenchen_opendata import map_muenchen_road_events
from infranode.normalization.mappers.openaq import map_openaq_air
from infranode.normalization.mappers.overpass import map_overpass_pois
from infranode.normalization.mappers.pegelonline import map_water_level
from infranode.normalization.mappers.uba import map_air_uba
from infranode.normalization.mappers.wikidata import map_wikidata_city
from infranode.registry import get_city, list_cities
from infranode.registry.coverage import PARTIAL_COVERAGE, covered_cities, is_covered

router = APIRouter()


def _not_covered(endpoint: str) -> dict:
    """Baut die ehrliche ``not_covered``-Antwort eines teilabgedeckten Endpunkts.

    Owner-Entscheidung 2026-06-13: eine nicht-abgedeckte Stadt liefert KEIN leeres
    ``ok`` (verschleiert die fehlende Abdeckung) und KEIN 404 (das ist "Stadt
    unbekannt"), sondern 200 mit ``source_status="not_covered"``, ``data: null``
    und der Liste der abgedeckten Staedte (``meta.covered_cities``), klar
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
    UNVERAENDERT (kein Breaking Change), es kommen nur die beiden Hinweis-Header
    hinzu. Wird ausschliesslich von den Bestands-Live-Handlern aufgerufen; die
    /live-Alias-Wrapper uebergeben eine Wegwerf-Response, sodass der Header dort
    NICHT landet (der /live-Pfad ist der Nachfolger, nicht der deprecated Altpfad).
    """
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = f'<{successor}>; rel="successor-version"'


# Connector-Registry der /road-events-Route (DATA-15): Stadt-Slug -> (source,
# fetch_fn, mapper). Modul-Konstante, damit 09-06 nur ADDITIV weitere Eintraege
# ergaenzt, ohne die Route-Logik zu aendern (Erweiterungsmechanismus, verbindlich).
# Kein Eintrag fuer einen Slug -> ehrliches 200 source_status="no_data" (keine
# Quelle fuer diese Stadt). Der Toggle wird generisch via
# getattr(Settings(), f"enable_{source}") geprueft (Toggle-Name == source).
#
# Decision B-1 (verbindlich): MobiData BW ist der landesweite Baden-Wuerttemberg-
# DATEX-II-Feed und wird auf die registrierte BW-Landeshauptstadt slug="stuttgart"
# verdrahtet (BBox-gefiltert auf Stuttgart), NICHT auf Karlsruhe (Karlsruhe ist
# keine der 28 Register-Staedte; "z.B. Karlsruhe" im Success-Criterion ist nur das
# Quell-Beispiel, der DATEX-II-Parser-Pfad ist quell-, nicht stadt-gebunden).
# Genau diese 5 Slugs sind registriert und get_city-gueltig.
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
}

# Drift-Schutz (verbindlich): die road-events-Abdeckung in der oeffentlichen
# Coverage-Karte MUSS exakt den CONNECTOR_MAP-Staedten entsprechen. Wird hier ein
# Connector ergaenzt/entfernt, ohne registry/coverage.py nachzuziehen, bricht der
# Import (und damit jeder Test/Boot) sofort - kein stiller Coverage-Drift. Bewusst
# ein echtes raise (kein assert): greift auch unter `python -O`.
if set(CONNECTOR_MAP) != set(PARTIAL_COVERAGE["road-events"]):
    raise RuntimeError(
        "CONNECTOR_MAP und PARTIAL_COVERAGE['road-events'] sind divergiert: "
        f"{set(CONNECTOR_MAP) ^ set(PARTIAL_COVERAGE['road-events'])}"
    )

# [ASSUMED] EVAS-23111-Tabellen-Code des Krankenhausverzeichnisses (RESEARCH
# A4). None-faehig: der Live-Abgleich ist Manual-Only nach Deploy (Owner). Der
# genesis-Adapter liest die Antwort defensiv (None-Fallback je Feld).
#
# Host (base_url): Der RED-Test-Vertrag aus Plan 08-01 mockt
# regionalstatistik.de (das Krankenhausverzeichnis EVAS 23111 liegt auf der
# Regionalstatistik-GENESIS-Instanz, gleiche wie die Demografie). Der Plan-
# Hinweis auf www-genesis.destatis.de (Pitfall 2) traf fuer 23111 NICHT zu; die
# Route nutzt daher den genesis-Adapter-Default-Host (Finding B-3 aufgeloest auf
# den Test-Vertrag, beide Hosts liegen ohnehin in der SSRF-Allowlist).
_HOSPITAL_TABLE = "23111-01-01-4" # [ASSUMED], Live-Abgleich Manual-Only.


@router.get("/cities")
async def cities() -> dict:
    """Listet alle 28 registrierten Staedte (kanonische Register-Eintraege)."""
    return {
        "data": [city.model_dump() for city in list_cities()],
        "meta": {"correlation_id": correlation_id.get()},
    }


@router.get("/cities/{slug}")
async def city(slug: str) -> dict:
    """Liefert eine Stadt; unbekannter Slug loest den 404-Envelope aus."""
    entry = get_city(slug)
    return {
        "data": entry.model_dump(),
        "meta": {"correlation_id": correlation_id.get()},
    }


@router.get("/cities/{slug}/base")
async def city_base(slug: str, request: Request) -> dict:
    """Liefert normalisierte Wikidata-Stammdaten im kanonischen Envelope.

    Ablauf (DATA-01/06, API-01, GOV-01): Register-Lookup (unbekannter
    Slug -> 404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    ueber die Fassade, Register-Geo-Fallback bei fehlendem P625, Mapping,
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
    # geprueft werden, sonst 500. Owner-Entscheidung 2: 503 mit Hint.
    if raw is None:
        raise UpstreamError(
            "Quelle 'wikidata' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # Register-Geo-Fallback (verhindert GeoPoint-ValidationError -> 500): das
    # Register traegt fuer alle Staedte gepruefte Koordinaten; fehlt P625 in
    # Wikidata, uebernimmt der Register-Geo.
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
    Slug -> 404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    ueber die Fassade gegen die keylose Bright-Sky-API (lat/lon aus dem
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
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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


@router.get("/cities/{slug}/charging")
async def city_charging(slug: str) -> dict:
    """Liefert E-Ladesaeulen-Standorte im kanonischen Envelope (DATA-09).

    Ablauf (DATA-09/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), dann ein read-only
    Read ueber ``read_records`` aus dem vorverarbeiteten Datensatz;
    zurueckgegeben wird der juengste Snapshot (max ``retrieved_at``).

    KRITISCH (kein Bulk-Upstream im Request-Pfad): Die BNetzA liefert das
    Ladesaeulenregister seit dem Aus des ArcGIS-FeatureServers (HTTP 499) nur
    noch als ~47-MB-CSV-Bulk-Download. Diese Route liest AUSSCHLIESSLICH aus dem
    vorverarbeiteten Datensatz, NIE die CSV, und ruft KEINEN
    ``resilient_client`` auf. Der Datensatz wird offline aktualisiert.

    Nur Stammdaten, KEINE Belegung (Locked Decision). Drei ``source_status``-
    Werte (analog /energy):
    - ``disabled``: ``enable_bnetza`` per Env-Toggle aus -> data None
    - ``not_ingested``: Quelle aktiv, aber kein Snapshot ->
      ``read_records`` liefert [] -> data None, KEIN 5xx
    - ``ok``: juengster Snapshot -> CanonicalRecord mit Attribution + license_id
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

    # Juengster Snapshot: daher hier max(retrieved_at).
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
    """Liefert normalisierte OpenAQ-Luftdaten im kanonischen Envelope (DATA-02).

    Ablauf (DATA-02/06, API-01, GOV-02): Register-Lookup (unbekannter Slug -> 404
    mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung (deaktiviert ->
    200 ``source_status=disabled``, nie 5xx), Key-Guard (Quelle aktiv aber kein Key
    -> 200 disabled, Graceful Degradation), resilienter Fetch ueber die Fassade
    gegen die keyabhaengige OpenAQ-v3-API (lat/lon aus dem Register-Geo), Mapping,
    dann der Daten-Envelope mit Attribution.

    KRITISCH (GOV-02, Pattern 4/Pitfall 1): OpenAQ ist Tier C live-only. Diese
    Route leitet die Daten ausschliesslich live durch (bewusste Tier-C-
    Entscheidung, kein Versehen).
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/air")

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> 200 disabled.
    settings = Settings()
    settings_key = settings.openaq_api_key
    # Key-Guard (DATA-06): Quelle aktiviert, aber kein Key -> 200 disabled, kein 5xx.
    if not settings.enable_openaq or settings_key is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "disabled",
            },
        }

    client = request.app.state.resilient_client
    key = build_cache_key("openaq", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_air(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            api_key=settings_key.get_secret_value(),
        )

    raw, status = await client.fetch("openaq", key, fetch_fn)

    # OpenAQ (Tier C) liefert keine nutzbaren Daten? Entweder toter Upstream ohne
    # Cache (raw is None) ODER keine Messstation im Umkreis (Sentinel
    # location_id=None). Beide Faelle: UBA-Fallback (Tier A, offene Lizenz, 84/84
    # flaechendeckend). KEINE Tier-Vermischung (GOV-02): der zurueckgegebene Record
    # ist sortenrein UBA (eigene DL-DE/BY-2.0-Attribution + license_tier A);
    # meta.fallback="uba" macht die genutzte Quelle transparent.
    openaq_usable = raw is not None and raw.get("location_id") is not None
    if not openaq_usable and Settings().enable_uba:
        uba_key = build_cache_key("uba", city_slug=entry.slug)

        async def uba_fetch_fn():
            return await fetch_air_uba(
                request.app.state.http,
                slug=entry.slug,
                lat=entry.geo.lat,
                lon=entry.geo.lon,
            )

        uba_raw, uba_status = await client.fetch("uba", uba_key, uba_fetch_fn)
        if uba_raw is not None:
            uba_record = map_air_uba(
                uba_raw,
                retrieved_at=datetime.now(UTC),
                ags=entry.ags,
                wikidata_qid=entry.qid,
            )
            return {
                "data": uba_record.model_dump(mode="json"),
                "meta": {
                    "correlation_id": correlation_id.get(),
                    "source_status": "ok",
                    "cache_status": uba_status,
                    "fallback": "uba",
                },
            }

    # Kein OpenAQ UND kein UBA-Fallback verfuegbar.
    if raw is None:
        raise UpstreamError(
            "Quelle 'openaq' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )
    if raw.get("location_id") is None:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
                "cache_status": status,
            },
        }

    record = map_openaq_air(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    # KRITISCH (GOV-02, Pattern 4/Pitfall 1): Tier C live-only. Der Envelope wird
    # direkt zurueckgegeben.

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
    """Liefert UBA-Luftqualitaet im kanonischen Envelope (DATA-10).

    Ablauf (DATA-10/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    ueber die Fassade gegen die keylose UBA-Air-Data-API (2-Step Station-Geo-
    Naehe + Messwerte, lat/lon aus dem Register-Geo), Mapping mit DL-DE/BY-2.0-
    Attribution, dann der Daten-Envelope mit Attribution.

    KRITISCH (Pitfall 2 / Lizenz-Klassifikation GOV-02): UBA ist der Tier-A-
    Luftpfad (offene Lizenz). Die bestehende Tier-C-OpenAQ-Route ``/air`` (oben)
    bleibt unveraendert -> die beiden Pfade duerfen nie vermischt werden.
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
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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
    """Liefert PEGELONLINE-Pegelstaende im kanonischen Envelope (DATA-11).

    Ablauf (DATA-11/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    ueber die Fassade gegen die keylose PEGELONLINE-API (2-Step Station-Geo-Naehe
    + Wasserstand, lat/lon aus dem Register-Geo), Mapping mit DL-DE/Zero-2.0-
    Attribution, dann der Daten-Envelope mit Attribution.

    KRITISCH (DATA-11, Pitfall 3 / Teilabdeckung): PEGELONLINE deckt nur Staedte
    an Bundeswasserstrassen ab. Findet der Adapter keine nahe Station
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
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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
    Slug -> 404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    ueber die Fassade gegen die keylose LHP-API (``POST get_infospegel.php`` je
    kuratiertem Pegel der Stadt), Mapping mit der PFLICHT-Stand-Attribution
    (CC-BY 4.0), dann der Daten-Envelope mit Attribution.

    KRITISCH (Pitfall 6, GOV-03): Die ``data.attribution.text`` traegt PFLICHT den
    Wortlaut ``"Datenquelle: www.hochwasserzentralen.de, Stand: <stand>"``.

    KRITISCH (DATA-12, Event-Layer): Keine aktive Warnung (leere ``warnings``) ist
    KEIN Fehler -> Happy-Path 200 mit leerem Event. Graceful Degradation: toter
    Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/flood")

    # Coverage-Guard (Owner 2026-06-13): LHP-Hochwasser deckt nur kuratierte Staedte
    # mit Pegel ab (_CITY_PEGEL). Eine nicht-abgedeckte Stadt liefert ehrlich
    # not_covered (200) + covered_cities, statt eines leeren "ok" (das wie "keine
    # Warnung" aussaehe). Vor dem Toggle: die fehlende Abdeckung ist strukturell.
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
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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
    Slug -> 404 mit Hint ueber den zentralen Handler), account-gated Toggle-/Key-
    Guard (Quelle aus ODER kein Credential -> 200 ``source_status=disabled``, nie
    5xx, analog city_air Key-Guard), resilienter Fetch ueber die Fassade gegen die
    keyabhaengige GENESIS-POST-API (Regionalstatistik, AGS aus dem Register-Geo),
    Mapping mit DL-DE/BY-2.0-Attribution, dann der Daten-Envelope mit Attribution.

    KRITISCH (T-08-CRED): Die Credentials gelangen nur in den POST-Body des
    Adapters, NIE in den Cache-Key (der traegt nur den Slug) oder die Response.
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
    # Cache-Key traegt NUR den Slug (T-08-CRED): nie Credentials.
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
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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
    """Liefert DWD-Pollenflug + UV-Index je Grossregion (DATA-14).

    Ablauf (DATA-14/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    ueber die Fassade gegen die keylosen DWD-Open-Data-Dienste (zwei GET,
    s31fg.json Pollen + uvi.json UV, KEIN lat/lon: Region-Map im Adapter),
    Mapping mit der GeoNutzV-Attribution (``modified=True``, Pitfall 5), dann der
    Daten-Envelope.

    KRITISCH (Pitfall 4, Ehrlichkeit): Die Daten sind GROSSREGION-genau, NICHT
    stadtgenau. ``data.payload.region_name``/``region_id`` weisen die Grossregion
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
        # KEIN lat/lon: die Stadt-zu-Grossregion-Map liegt im Adapter (Pitfall 4).
        return await fetch_pollen_uv(request.app.state.http, slug=entry.slug)

    raw, status = await client.fetch("dwd_pollen", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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


@router.get("/cities/{slug}/pois")
async def city_pois(slug: str, request: Request, type: str) -> dict:
    """Liefert nach Typ gefilterte OSM-POIs im kanonischen Envelope (DATA-04).

    Ablauf (DATA-04/06, API-01, GOV-02): Register-Lookup (unbekannter
    Slug -> 404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), Typ-Whitelist-
    Pruefung VOR dem Fetch (unbekannter Typ -> 422, kein roher Input in die
    Overpass-QL, T-05-09), resilienter Fetch ueber die Fassade (der ``type``
    fliesst per ``params`` als sha256-Hash in den Cache-Key -> Cache-Poisoning-
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

    # T-05-09 Injection: unbekannter Typ -> 422, BEVOR ein Fetch laeuft. Roher
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
        )

    raw, status = await client.fetch("overpass", key, fetch_fn)

    # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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


@router.get("/cities/{slug}/traffic", deprecated=True)
async def city_traffic(slug: str, request: Request, response: Response) -> dict:
    """Liefert Baustellen + Verkehrsmeldungen im kanonischen Envelope (DATA-07/08).

    Ablauf (DATA-07/08/06, API-01, GOV-02): Register-Lookup (unbekannter
    Slug -> 404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), resilienter Fetch
    ueber die Fassade gegen die keylose Autobahn-API (Multi-Road + BBox um den
    Register-Geo), Mapping mit DL-DE/BY-Attribution, dann der Daten-Envelope mit
    Attribution.
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/traffic")

    # Coverage-Guard (Owner 2026-06-13): die Autobahn-Verkehrslage deckt nur Staedte
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
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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


@router.get("/cities/{slug}/road-events")
async def city_road_events(slug: str, request: Request) -> dict:
    """Liefert innerstaedtische Baustellen/Sperrungen im kanonischen Envelope (DATA-15).

    Ablauf (DATA-15/06, API-01, GOV-02, DX-06): Register-Lookup
    (unbekannter Slug -> 404 mit Hint ueber den zentralen Handler), Connector-
    Lookup in ``CONNECTOR_MAP`` (kein Eintrag -> ehrliches 200
    ``source_status="no_data"``, keine Quelle fuer diese Stadt), Quellen-Toggle-
    Pruefung (deaktiviert -> 200 ``source_status="disabled"``, nie 5xx),
    resilienter Fetch ueber die Fassade gegen die keylose Quelle, Mapping mit
    DL-DE/BY-Attribution, dann der Daten-Envelope mit Attribution.

    Generischer Erweiterungsmechanismus (verbindlich): die Connector-Auswahl
    ((source, fetch_fn, mapper)) stammt aus ``CONNECTOR_MAP``; 09-06 ergaenzt nur
    weitere Eintraege, ohne diese Route-Logik zu aendern. Der Toggle wird generisch
    via ``getattr(Settings(), f"enable_{source}")`` geprueft.

    Leere ``events`` (Quelle erreichbar, aber keine Ereignisse) -> ehrliches
    200 ``source_status="no_data"`` OHNE Mapper und OHNE ``append_record`` (keine
    Datei, kein 5xx; analog zum Teilabdeckungs-Muster von ``city_water_level``).
    Toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)

    # Connector-Lookup: kein Eintrag fuer diese Stadt -> ehrliches not_covered (200)
    # + covered_cities (Owner 2026-06-13). Frueher no_data; not_covered macht die
    # strukturell fehlende Abdeckung klar unterscheidbar von "Quelle erreichbar, aber
    # gerade keine Ereignisse" (das bleibt no_data, siehe unten). CONNECTOR_MAP und
    # die Coverage-Karte sind per Modul-Assertion (oben) synchron.
    connector = CONNECTOR_MAP.get(entry.slug)
    if connector is None:
        return _not_covered("road-events")

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
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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


@router.get("/cities/{slug}/events")
async def city_events(slug: str, request: Request) -> dict:
    """Liefert destination.one-Stadt-Events im kanonischen Envelope (DATA-16, GOV-04).

    Ablauf (DATA-16/06, API-01, GOV-02/04, DX-06) nach dem
    ``city_road_events``-Muster:
    Register-Lookup (unbekannter Slug -> 404 mit Hint ueber den zentralen Handler),
    Toggle-Guard (Quelle aus -> 200 ``source_status="disabled"``, nie 5xx),
    resilienter Fetch ueber die Fassade gegen die KEYLOSE eT4.META-Such-
    API (Experience ``open-data``, frei zugaenglich, verifiziert 2026-06-10),
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
    # ebenfalls keylose Koeln-Direkt-Feed ist ergaenzend NUR fuer slug="koeln"
    # (D-02/D-06).
    destination_enabled = settings.enable_destination_one
    koeln_enabled = settings.enable_koeln_events and entry.slug == "koeln"

    # D-08: KEINE der relevanten Quellen aktiv -> 200 disabled, nie 5xx, keine
    # Datei. (Fuer Nicht-Koeln-Slugs zaehlt nur destination.one.)
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
        # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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

    # --- Block 2: Koeln-Events (keyloser Direkt-Feed, nur slug="koeln") -----
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

        # Pitfall 4: toter Koeln-Upstream ohne Cache. Der Koeln-Feed ist ein
        # ADDITIVER Block: lieferte destination.one bereits Records, degradiert
        # ein toter Koeln-Feed graceful (Block uebersprungen, kein 503). Nur wenn
        # Koeln die EINZIGE relevante Quelle ist (kein destination.one-Record),
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
        # Record; das no_data-Verdict faellt unten gemeinsam mit Block 1).
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

    # Keine ueberlebenden Events aus irgendeiner Quelle (leer / nur
    # Vergangenheit) -> ehrliches no_data (200). KEIN 5xx.
    if not records:
        return {
            "data": None,
            "meta": {
                "correlation_id": correlation_id.get(),
                "source_status": "no_data",
            },
        }

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
    no_data-Muster: Register-Lookup (unbekannter Slug -> 404 mit Hint ueber den
    zentralen Handler), Quellen-Toggle-Pruefung (``enable_autobahn_webcam`` aus ->
    200 ``source_status="disabled"``, nie 5xx), resilienter Fetch ueber die Fassade
    gegen die keylose Autobahn-Webcam-API (BBox um den Register-Geo), Mapping ueber
    ``map_autobahn_webcams``, dann der Daten-Envelope mit Attribution.

    KRITISCH (Decision 3, Pitfall 1): Webcams sind ein Live-Bild-Feature. Diese
    Route gibt das Live-Bild direkt aus (Feature-Entscheidung, KEIN Tier-Downgrade;
    license_tier bleibt A). Ein leeres ``webcams``-Array ist NORMAL
    (Live-Realitaet) -> ehrliches 200 ``source_status="no_data"`` OHNE Mapper.
    Toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).
    """
    entry = get_city(slug)
    # LIVE-03: Altpfad ist deprecated -> /live-Nachfolger (kein Breaking Change).
    _mark_deprecated(response, "/api/v1/live/{slug}/webcams")

    # Coverage-Guard (Owner 2026-06-13): Autobahn-Webcams decken nur Staedte mit
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
    # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Quelle 'autobahn_webcam' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    # KRITISCH (Decision 3, Pitfall 1): leeres webcams-Array (Live-Realitaet) ->
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
    # zurueckgegeben (Feature-Entscheidung, kein Tier-Downgrade; license_tier bleibt A).

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
    mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung (deaktiviert ->
    200 ``source_status=disabled``, nie 5xx), dann ein memory-armer read-only
    Snapshot-Read ueber ``read_stops(slug, source="bkg")``.

    KRITISCH (kein Bulk-Upstream im Request-Pfad): Diese Route liest AUSSCHLIESSLICH
    aus dem vorverarbeiteten BKG-Datensatz, NIE aus der VG250-GeoJSON, und ruft
    KEINEN ``resilient_client`` auf. Der Datensatz wird offline aktualisiert.

    KRITISCH (Scope): NUR Grenzen + Namen + Flaeche (AGS/GEN-Name/area_km2).
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
    404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), dann ein
    memory-armer read-only Snapshot-Read ueber
    ``read_stops(slug, source="bundeswahl")``.

    KRITISCH (kein Bulk-Upstream im Request-Pfad): Diese Route liest
    AUSSCHLIESSLICH aus dem vorverarbeiteten Bundeswahl-Datensatz, NIE aus der
    kerg-CSV, und ruft KEINEN ``resilient_client`` auf. Der Datensatz wird offline
    aktualisiert.

    KRITISCH (Pitfall 7, GOV-03): Die Granularitaet ist ehrlich "teilweise"
    (Wahlkreis/Kreis-Ebene, nur kreisfreie Staedte stadtscharf, kommunale Ebene
    Out of Scope). Eine nicht-kreisfreie Stadt ohne Snapshot -> ``not_ingested``
    (ehrlich, kein 5xx). Granularitaet + Attribution stehen je Record-Payload.

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
    404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), dann ein
    Seed-Read ueber ``load_holidays(entry.state, jahr)`` aus den eingebetteten
    Seeds ``data/seeds/feiertage_<jahr>.json`` + ``schulferien_<jahr>.json``.

    KRITISCH (kein Upstream im Request-Pfad, T-08-DEP): Diese Route liest
    AUSSCHLIESSLICH aus den committeten statischen Seeds via stdlib ``json``,
    ruft KEINE Laufzeit-Fremd-API auf, KEIN ``resilient_client``.

    KRITISCH (Gray-Area, GOV-02): Feiertage/Schulferien sind GEMEINFREIE Fakten
    (Tier C, nur Live-Anzeige), so in der Attribution markiert. Die Seeds sind
    statisch im Repo (kein DB-Schutzrecht).

    Drei ``source_status``-Werte:
    - ``disabled``: ``enable_feiertage`` per Env-Toggle aus -> data None
    - ``no_data``: Quelle aktiv, aber keine Seed-Eintraege fuer Bundesland/Jahr
      (z. B. fehlende Datei) -> data None, KEIN 5xx (ehrlich)
    - ``ok``: Seed-Eintraege vorhanden -> holiday-Payload je entry.state mit
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
    # fuer Bundesland/Jahr -> leere Listen -> no_data (ehrlich, kein 5xx, kein
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
    404 mit Hint ueber den zentralen Handler), Quellen-Toggle-Pruefung
    (deaktiviert -> 200 ``source_status=disabled``, nie 5xx), dann ein
    parametrisierter Read ueber ``read_energy`` aus dem datierten vorverarbeiteten
    Datensatz (juengster Snapshot via MAX(ingest_date)), optional gefiltert
    nach ``type`` (pv/wind/speicher/biogas).

    KRITISCH (kein Bulk-Upstream im Request-Pfad): Diese Route liest
    AUSSCHLIESSLICH aus dem vorverarbeiteten Datensatz, NIE aus der >1-GB-XML-ZIP,
    und ruft KEINEN ``resilient_client`` auf. Der Datensatz wird offline aktualisiert.

    Der gemappte Record ist die Live-Sicht auf den juengsten Snapshot.

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
    # Der Wert fliesst parametrisiert in die SQLite-Query (?-Binding, T-08-SQLI),
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


@router.get("/cities/{slug}/health")
async def city_health(slug: str, request: Request) -> dict:
    """Liefert Gesundheitsinfrastruktur im kanonischen Envelope (DATA-25a/b).

    Kombiniert zwei Tier-A-Sichten:
    - Krankenhaus-Stammdaten (Destatis-Krankenhausverzeichnis, GENESIS EVAS 23111):
      account-gated Live-POST ueber den GENESIS-Adapter aus Plan 08-02
      (``fetch_demographics`` mit ``table=_HOSPITAL_TABLE``, Default-Host
      regionalstatistik.de wie der RED-Test-Vertrag, Finding B-3), gemappt durch
      den NEUEN ``map_hospital`` (NICHT ``map_demographics``, exakter Destatis-
      Wortlaut, Finding W-1: gleiche Quelle wie Demografie).
    - ICU-Kapazitaet je Kreis (RKI-DIVI-GitHub-CSV, CC-BY 4.0): read-only aus dem
      vorverarbeiteten divi-Datensatz. Folgt dem ``city_transit``-Read.

    Ablauf (DATA-25/06, API-01, GOV-02/03): Register-Lookup (unbekannter
    Slug -> 404 mit Hint), account-gated Toggle-/Key-Guard fuer das
    Krankenhausverzeichnis (Quelle aus ODER kein Credential -> kein Live-Call),
    Read der ICU-Kapazitaet. ``source_status`` weist die Abdeckung ehrlich
    aus (``disabled``/``not_ingested``/``ok``).

    KRITISCH (T-08-CRED): Die GENESIS-Credentials gelangen nur in den POST-Body des
    Adapters, NIE in den Cache-Key oder die Response. KRITISCH (T-08-DBR): Diese
    Route liefert NUR die Tier-A-Aggregate (Krankenhaus, Kreis-ICU-CSV); die
    klinikscharfe DIVI-Live-Lage laeuft getrennt ueber ``/icu-live`` (Tier C,
    nur Live-Anzeige).
    """
    entry = get_city(slug)

    # ICU-Kapazitaet (Kreisebene, CC-BY 4.0) read-only aus dem divi-Datensatz
    # (NIE die CSV im Request-Pfad). Fehlend -> [] (not_ingested).
    icu_records = read_records(source="divi", tier="A", city_slug=entry.slug)

    # Account-gated Toggle-/Key-Guard fuer das Krankenhausverzeichnis frisch lesen
    # (Settings() statt app.state.settings, damit der per-Test gesetzte Env-Override
    # greift). DATA-06: Quelle aus ODER kein Credential -> kein Live-Call.
    settings = Settings()
    hospital_enabled = (
        settings.enable_genesis
        and settings.genesis_username is not None
        and settings.genesis_password is not None
    )

    hospital_data: dict | None = None
    if not hospital_enabled:
        # Kein Krankenhaus-Live-Call. Ist auch keine ICU-Kapazitaet vorhanden,
        # ist die ganze Slice disabled; sonst nur die ICU-Sicht (not_ingested/ok).
        if not icu_records:
            return {
                "data": None,
                "meta": {
                    "correlation_id": correlation_id.get(),
                    "source_status": "disabled",
                },
            }
    else:
        client = request.app.state.resilient_client
        # Cache-Key traegt NUR den Slug (T-08-CRED): nie Credentials.
        key = build_cache_key("genesis_hospital", city_slug=entry.slug)
        genesis_user = settings.genesis_username
        genesis_password = settings.genesis_password

        async def fetch_fn():
            return await fetch_demographics(
                request.app.state.http,
                slug=entry.slug,
                ags=entry.ags,
                username=genesis_user,
                password=genesis_password,
                table=_HOSPITAL_TABLE,
            )

        raw, _status = await client.fetch("genesis_hospital", key, fetch_fn)

        # Pitfall 4: raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper
        # geprueft werden, sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
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

    icu_data = [r.model_dump(mode="json") for r in icu_records]
    # source_status: ok sobald irgendeine Sicht Daten traegt, sonst not_ingested
    # (Quelle aktiv/lesbar, aber noch kein Snapshot/Datensatz).
    status = "ok" if (hospital_data is not None or icu_data) else "not_ingested"

    return {
        "data": {
            "hospital": hospital_data,
            "icu_capacity": icu_data,
        },
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": status,
        },
    }


@router.get("/cities/{slug}/icu-live")
async def city_icu_live(slug: str, request: Request) -> dict:
    """Liefert klinikscharfe DIVI-Live-ICU-Daten (DATA-25b, Tier C, T-08-DBR).

    Ablauf (DATA-25b/06, API-01, GOV-02) nach dem ``city_air``-Tier-C-Muster:
    Register-Lookup (unbekannter Slug -> 404 mit Hint), Quellen-Toggle-Pruefung
    (``enable_divi`` aus -> 200 ``source_status=disabled``, nie 5xx), resilienter
    Fetch ueber die Fassade gegen die keylose DIVI-Live-API, Mapping ueber
    ``map_icu_live`` (Tier C). Fehlt eine kuratierte Kreis-Kennung oder ist der
    Upstream tot ohne Cache, liefert die Route ehrlich
    ``source_status="no_data"`` (200, kein 5xx; Tier-C-Live-Degradation).

    KRITISCH (Datenbank-Schutzrecht, RESEARCH Pitfall 4, T-08-DBR): Die
    klinikscharfe DIVI-Live-Lage ist Tier C live-only. Diese Route leitet die
    Daten ausschliesslich live durch (bewusste Tier-C-Entscheidung, kein Versehen,
    analog city_air). NUR die Kreis-Aggregat-CSV (CC-BY 4.0, Tier A) laeuft
    getrennt ueber ``/health``.
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

    async def fetch_fn():
        return await fetch_icu_live(request.app.state.http, slug=entry.slug)

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
    # zurueckgegeben.

    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": correlation_id.get(),
            "source_status": "ok",
            "cache_status": status,
        },
    }
