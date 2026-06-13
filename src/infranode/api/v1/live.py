"""Getrennte Live-Kategorie /api/v1/live (LIVE-01/02/03, Phase 20).

Owner-Entscheid (LOCKED): alle Live-/Quasi-Live-Endpunkte erhalten einen eigenen
Namespace ``/api/v1/live/...`` mit eigenem OpenAPI-Tag "Live" und einem additiv
erweiterten Envelope-Kontrakt: der meta-Block traegt zusaetzlich ``as_of``
(Datenstand, DATEX-II publicationTime) und ``refresh_seconds`` (Kadenz der
Quelle), ohne den Bestands-Envelope zu brechen.

Re-Exposition Bestand (LIVE-03, REST-Regel 6 = eine Quelle der Wahrheit): die
bestehenden Live-/Quasi-Live-Handler aus ``cities.py`` (air, air-uba, water-level,
traffic, webcams, flood) werden hier als DUENNE Alias-Wrapper unter ``/live``
re-exponiert. Es wird KEIN Handler-Body dupliziert: die Wrapper rufen exakt den
jeweiligen ``cities.py``-Handler auf. Die Altpfade in ``cities.py`` bleiben
funktionsfaehig (kein Breaking Change, Envelope-Kontrakt stabil) und tragen
zusaetzlich einen ``Deprecation``-Header sowie ``deprecated=True`` im OpenAPI.

Der Prefix ``/live`` und der Tag "Live" werden beim ``include_router`` in
``__init__.py`` gesetzt (analog cities.py), NICHT hier im Router.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Request, Response

from infranode.adapters.hvv_geofox import fetch_hvv_departures
from infranode.adapters.mobilithek_afir import fetch_afir
from infranode.adapters.mobilithek_datex2 import fetch_datex2
from infranode.api.errors import UpstreamError, ValidationFailedError
from infranode.api.v1 import cities
from infranode.config import Settings
from infranode.infra.cache import build_cache_key
from infranode.normalization.enums import SourceId
from infranode.normalization.mappers.gtfs_rt import (
    map_transit_departures,
    map_transit_route_status,
    map_transit_trip,
)
from infranode.normalization.mappers.hvv_geofox import map_hvv_departures
from infranode.normalization.mappers.mobilithek_afir import map_eround_charging
from infranode.normalization.mappers.mobilithek_koeln import (
    map_koeln_road_events,
    map_koeln_traffic_flow,
)
from infranode.normalization.mappers.mobilithek_parken import (
    map_dortmund_parking,
    map_kiel_counts,
)
from infranode.normalization.mappers.mobilithek_stadt import (
    map_berlin_traffic_messages,
    map_koeln_lez,
)
from infranode.registry import get_city
from infranode.transit.interpolation import estimate_position
from infranode.transit.resolver import stops_with_geo_for_trip
from infranode.transit.store import (
    get_trip_update,
    trips_for_route,
    trips_for_stop,
)

router = APIRouter()


def _live_meta(
    *,
    source_status: str,
    cache_status: str | None = None,
    as_of: str | None = None,
    refresh_seconds: int | None = None,
) -> dict:
    """Baut den Live-Envelope-meta-Block (RESEARCH Pattern 5).

    Spiegelt den Bestands-meta-Block jedes ``cities.py``-Handlers
    (``correlation_id`` + ``source_status`` [+ ``cache_status``]) und ergaenzt ihn
    ADDITIV um die beiden Live-Kennzeichen ``as_of`` (Datenstand) und
    ``refresh_seconds`` (Kadenz der Quelle). Beide Live-Keys sind IMMER praesent
    (auch bei ``disabled``/``no_data``), damit der Live-Kategorie-Kontrakt stabil
    ist; ein noch unbekannter Datenstand ist ``None`` (ehrlich), kein Weglassen.
    """
    meta: dict = {
        "correlation_id": correlation_id.get(),
        "source_status": source_status,
    }
    if cache_status is not None:
        meta["cache_status"] = cache_status
    # Live-Erweiterung: as_of/refresh_seconds IMMER ausweisen (Kontrakt-Stabilitaet).
    meta["as_of"] = as_of
    meta["refresh_seconds"] = refresh_seconds
    return meta


# Kadenz der Mobilithek-Live-Quellen (CONTEXT: live_5min, minutenfrisch).
_LIVE_REFRESH_SECONDS = 300

# Default-Abo-IDs der verifizierten Koeln-Quellen (CONTEXT 2026-06-12, HTTP 200).
# Greifen nur, wenn die Settings-Allowlist (``*_abo_id``) keinen Wert traegt
# (Owner setzt die Werte produktiv aus dem Portal; SSRF-Allowlist bleibt gewahrt:
# der Wert stammt NIE aus User-Input, nur aus Settings ODER diesen Konstanten).
_KOELN_TRAFFIC_FLOW_ABO_ID = "1000923418744061952"
_KOELN_BAUSTELLEN_ABO_ID = "1000922381824032768"


async def _live_mobilithek(
    *,
    city: str,
    request: Request,
    source: str,
    abo_id: str | None,
    publication: str,
    mapper,
    map_kwargs: dict | None = None,
) -> dict:
    """Gemeinsame Köln-Live-Route gegen den Mobilithek-mTLS-Pull (LIVE-06/07).

    Folgt 1:1 dem ``cities.py``-Handler-Skelett (Graceful Degradation), ABER fuer
    reine Live-Daten:
    - Register-Lookup zuerst (T-20-PATH): unbekannter Slug -> 404 (zentraler Handler).
    - Toggle-Check: ``enable_{source}`` False ODER ``app.state.mobilithek_http`` None
      (kein Cert) ODER ``abo_id`` fehlt -> 200 ``source_status="disabled"`` (nie 5xx).
    - resilienter Fetch ueber die Fassade (``resilient_client.fetch``) mit
      ``fetch_datex2`` als ``fetch_fn`` gegen den mTLS-Client.
    - toter Upstream ohne Cache (``raw is None``) -> 503 mit selbst-korrigierendem Hint.
    - leerer Feed (422/keine Daten) -> 200 ``source_status="no_data"`` OHNE Mapper.
    - sonst Mapper + Live-Envelope (``as_of`` aus DATEX-II publicationTime,
      ``refresh_seconds`` = Kadenz).

    KRITISCH (T-20-ARCHIVE): die Live-Routen schreiben KEIN Archiv - reine
    Live-Daten landen nur im Redis-Cache (CONTEXT "Live NICHT archivieren"). Das
    ist der bewusste Unterschied zu den ``cities.py``-Handlern (Code-Review-Gate).
    """
    entry = get_city(city)

    settings = Settings()
    mobilithek_http = getattr(request.app.state, "mobilithek_http", None)
    # disabled: Toggle aus ODER kein Cert (mTLS-Client None) ODER keine Abo-ID.
    if (
        not getattr(settings, f"enable_{source}", False)
        or mobilithek_http is None
        or not abo_id
    ):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_datex2(
            mobilithek_http,
            abo_id=abo_id,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            publication=publication,
        )

    raw, status = await client.fetch(source, key, fetch_fn)

    # raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper geprueft werden,
    # sonst 500. 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            f"Live-Quelle '{source}' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    # Leerer Feed (422/keine Daten) -> ehrliches no_data (200) OHNE Mapper.
    # Payload-Schluessel je Publication (additiv um parking erweitert).
    if publication == "situation":
        payload_key = "events"
    elif publication == "parking":
        payload_key = "facilities"
    else:  # "measured"
        payload_key = "measurements"
    if not raw.get(payload_key):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                as_of=raw.get("as_of"),
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    record = mapper(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        **(map_kwargs or {}),
    )
    # KEIN Archiv-Write fuer reine Live-Daten (T-20-ARCHIVE)! Nur Redis-Cache
    # (ueber die Fassade). Das ist der bewusste Unterschied zu cities.py.
    observed = (
        record.observed_at.isoformat() if record.observed_at else raw.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=observed,
            refresh_seconds=_LIVE_REFRESH_SECONDS,
        ),
    }


@router.get("/{city}/traffic-flow")
async def live_traffic_flow(city: str, request: Request) -> dict:
    """Live-Verkehrslage je Stadt (Koeln MeasuredDataPublication, LIVE-06).

    Vertikaler Live-Endpunkt der getrennten Kategorie. Köln ist die verifizierte
    Quelle (MeasuredDataPublication, minutenfrisch); andere Staedte tragen keinen
    Abo-Eintrag -> ``disabled``. Graceful Degradation + Live-Envelope (``as_of`` +
    ``refresh_seconds``) ueber den gemeinsamen ``_live_mobilithek``-Helfer. KEIN
    Archiv (reine Live-Daten, T-20-ARCHIVE).
    """
    settings = Settings()
    abo_id = settings.koeln_traffic_flow_abo_id or _KOELN_TRAFFIC_FLOW_ABO_ID
    return await _live_mobilithek(
        city=city,
        request=request,
        source=SourceId.KOELN_TRAFFIC_FLOW.value,
        abo_id=abo_id,
        publication="measured",
        mapper=map_koeln_traffic_flow,
    )


@router.get("/{city}/baustellen")
async def live_baustellen(city: str, request: Request) -> dict:
    """Live-Baustellen je Stadt (Koeln SituationPublication, LIVE-07).

    Köln Baustellen (verifiziertes Abo, HTTP 200). SituationPublication ->
    RoadEventPayload. Graceful Degradation + Live-Envelope ueber
    ``_live_mobilithek``. KEIN Archiv (reine Live-Daten, T-20-ARCHIVE).
    """
    settings = Settings()
    abo_id = settings.koeln_baustellen_live_abo_id or _KOELN_BAUSTELLEN_ABO_ID
    return await _live_mobilithek(
        city=city,
        request=request,
        source=SourceId.KOELN_BAUSTELLEN_LIVE.value,
        abo_id=abo_id,
        publication="situation",
        mapper=map_koeln_road_events,
        map_kwargs={"source": SourceId.KOELN_BAUSTELLEN_LIVE},
    )


@router.get("/{city}/ereignisse")
async def live_ereignisse(city: str, request: Request) -> dict:
    """Live-Verkehrsereignisse je Stadt (Koeln SituationPublication, LIVE-07).

    Köln Verkehrsinformationen/Ereignisse. Die Abo-ID wird vom Owner aus dem
    Portal nachgetragen (Settings-Allowlist ``koeln_ereignisse_live_abo_id``);
    bis dahin liefert die Route ehrlich ``disabled`` (kein Default-Abo, CONTEXT
    "noch testen"). SituationPublication -> RoadEventPayload. KEIN Archiv
    (reine Live-Daten, T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city=city,
        request=request,
        source=SourceId.KOELN_EREIGNISSE_LIVE.value,
        abo_id=settings.koeln_ereignisse_live_abo_id,
        publication="situation",
        mapper=map_koeln_road_events,
        map_kwargs={"source": SourceId.KOELN_EREIGNISSE_LIVE},
    )


@router.get("/berlin/verkehrsmeldungen")
async def live_berlin_verkehrsmeldungen(request: Request) -> dict:
    """Live-Verkehrsmeldungen Berlin (SenMVKU SituationPublication, LIVE-08).

    Reine V2-SituationPublication-Quelle ueber denselben Plan-04-Parser
    (``fetch_datex2`` publication="situation") + den gemeinsamen
    ``_live_mobilithek``-Helfer; nur der Mapper (``map_berlin_traffic_messages``)
    ist Berlin-spezifisch. Stadt-Slug fix ``berlin`` (Quelle deckt nur Berlin ab).
    Abo-ID aus der Settings-Allowlist (SSRF, T-20-SSRF). KEIN Archiv (reine
    Live-Daten, T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city="berlin",
        request=request,
        source=SourceId.BERLIN_VERKEHRSMELDUNGEN.value,
        abo_id=settings.berlin_verkehrsmeldungen_abo_id,
        publication="situation",
        mapper=map_berlin_traffic_messages,
    )


@router.get("/koeln/umweltzone")
async def live_koeln_umweltzone(request: Request) -> dict:
    """Live-LowEmissionZone Köln (MoCKiii SituationPublication, LIVE-12).

    Schliesst die Köln-Quellengruppe ab. Reine V2-SituationPublication ueber den
    Plan-04-Parser + ``_live_mobilithek``; nur der Mapper (``map_koeln_lez``) ist
    LEZ-spezifisch. Stadt-Slug fix ``koeln``. Abo-ID aus der Settings-Allowlist
    (SSRF, T-20-SSRF). KEIN Archiv (reine Live-Daten, T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city="koeln",
        request=request,
        source=SourceId.KOELN_LEZ_LIVE.value,
        abo_id=settings.koeln_lez_live_abo_id,
        publication="situation",
        mapper=map_koeln_lez,
    )


@router.get("/dortmund/parking")
async def live_dortmund_parking(request: Request) -> dict:
    """Live-Parkbelegung Dortmund (ParkingStatusPublication, LIVE-09).

    Dortmund Parkleitsystem dynamisch ueber den additiven Parking-Parse-Zweig
    (``fetch_datex2`` publication="parking") + den gemeinsamen
    ``_live_mobilithek``-Helfer; nur der Mapper (``map_dortmund_parking``) ist
    Dortmund-spezifisch. Stadt-Slug fix ``dortmund``. Schliesst die in DATA-09
    dokumentierte Echtzeit-Parkbelegungsluecke (Parken). Abo-ID aus der
    Settings-Allowlist (SSRF, T-20-SSRF). KEIN Archiv (reine Live-Daten,
    T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city="dortmund",
        request=request,
        source=SourceId.DORTMUND_PARKING.value,
        abo_id=settings.dortmund_parking_abo_id,
        publication="parking",
        mapper=map_dortmund_parking,
    )


@router.get("/kiel/zaehlstellen")
async def live_kiel_zaehlstellen(request: Request) -> dict:
    """Live-Zaehldaten Kiel (MIV-/Radzaehlstellen, MeasuredDataPublication, LIVE-10).

    Kiel Dauerzaehlstellen ueber den MeasuredData-Zweig aus Plan 04
    (``fetch_datex2`` publication="measured") + den gemeinsamen
    ``_live_mobilithek``-Helfer; der Mapper (``map_kiel_counts``) interpretiert
    die ``measurements`` als ``counts``. Stadt-Slug fix ``kiel``. Abo-ID aus der
    Settings-Allowlist (SSRF, T-20-SSRF). KEIN Archiv (reine Live-Daten,
    T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city="kiel",
        request=request,
        source=SourceId.KIEL_ZAEHLSTELLEN.value,
        abo_id=settings.kiel_zaehlstellen_abo_id,
        publication="measured",
        mapper=map_kiel_counts,
    )


@router.get("/eround/charging")
async def live_eround_charging(request: Request) -> dict:
    """Live-Ladesaeulen-Belegung eRound (AFIR DATEX-II V3, LIVE-11).

    Die EINZIGE DATEX-II-V3-Quelle der Phase (EnergyInfrastructureStatus-
    Publication, eigener Parser ``fetch_afir`` getrennt vom V2-Pfad). Schliesst
    die zweite Haelfte der DATA-09-Belegungsluecke (Laden). REALITAET (Mobilithek-
    Portal 2026-06-12): Syntax JSON (nicht XML), Zugriffspunkt mit Query-URL-
    Variante (``build_pull_url`` style="query", im Adapter gesetzt). Lizenz CC0 ->
    Tier A (Owner-Verifikation, Checkpoint cc0-tier-a). Stadt-Slug fix ``koeln``
    als Aufhaenger (eRound liefert HH-/bundesweite Standorte; der Slug dient nur
    dem Register-Lookup/Geo-Kontext). Abo-ID aus der Settings-Allowlist (SSRF,
    T-20-SSRF). KEIN Archiv (reine Live-Daten, T-20-ARCHIVE), auch bei Tier A
    (RESEARCH "Live NICHT archivieren").
    """
    settings = Settings()
    city = "koeln"
    abo_id = settings.eround_charging_abo_id
    source = SourceId.EROUND_CHARGING.value

    entry = get_city(city)
    mobilithek_http = getattr(request.app.state, "mobilithek_http", None)
    # disabled: Toggle aus ODER kein Cert (mTLS-Client None) ODER keine Abo-ID.
    if (
        not getattr(settings, f"enable_{source}", False)
        or mobilithek_http is None
        or not abo_id
    ):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_afir(mobilithek_http, abo_id=abo_id, slug=entry.slug)

    raw, status = await client.fetch(source, key, fetch_fn)

    # raw is None (toter Upstream ohne Cache) MUSS vor dem Mapper geprueft werden.
    if raw is None:
        raise UpstreamError(
            f"Live-Quelle '{source}' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    # Leerer Feed (422/keine Daten) -> ehrliches no_data (200) OHNE Mapper.
    if not raw.get("points"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                as_of=raw.get("as_of"),
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    record = map_eround_charging(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # KEIN Archiv-Write fuer reine Live-Daten (T-20-ARCHIVE)! Auch bei Tier A:
    # reine Live-Belegung wird nicht archiviert (RESEARCH "Live NICHT archivieren").
    observed = (
        record.observed_at.isoformat() if record.observed_at else raw.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=observed,
            refresh_seconds=_LIVE_REFRESH_SECONDS,
        ),
    }


# Kadenz der HVV-Geofox-Live-Abfahrten (minutenfrisch).
_HVV_REFRESH_SECONDS = 60


@router.get("/hamburg/departures")
async def live_hamburg_departures(
    request: Request, station: str = "Hamburg Hauptbahnhof"
) -> dict:
    """Live-ÖPNV-Abfahrten Hamburg je Station (HVV-Geofox-GTI, DATA-24, Tier C).

    Echtzeit-Abfahrtstafel inkl. Verspätung und Linien-Störungshinweisen aus der
    HVV-Geofox-GTI-API. Stadt fix ``hamburg`` (Geofox deckt nur den HVV-Raum ab).
    Der Query-Parameter ``station`` ist ein Stationsname (Default Hauptbahnhof),
    den der Adapter via ``checkName`` auf die Geofox-Station-ID auflöst.

    Graceful Degradation: Toggle aus ODER fehlende Credentials (user/key) -> 200
    ``source_status="disabled"`` (nie 5xx). Unbekannte Station / keine Abfahrten
    -> 200 ``source_status="no_data"``. Toter Upstream ohne Cache -> 503 mit
    selbst-korrigierendem Hint. KEIN Archiv (Tier C live-only, T-20-ARCHIVE):
    die Credentials gelangen NIE in Cache-Key (nur der Stationsname) / Response.
    """
    entry = get_city("hamburg")
    settings = Settings()
    key = settings.hvv_api_key
    # disabled: Toggle aus ODER kein Credential-Paar (analog city_demographics).
    if not settings.enable_hvv_geofox or not settings.hvv_user or key is None:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_HVV_REFRESH_SECONDS,
            ),
        }

    name = (station or "").strip()[:100]
    if not name:
        raise ValidationFailedError(
            "Parameter 'station' erforderlich.",
            hint="Einen HVV-Stationsnamen angeben, z. B. station=Hauptbahnhof.",
        )

    client = request.app.state.resilient_client
    # Cache-Key traegt NUR den Stationsnamen (T-08-CRED): nie Credentials.
    cache_key = build_cache_key(
        "hvv_geofox", city_slug=entry.slug, params={"station": name}
    )
    hvv_user = settings.hvv_user
    hvv_secret = key.get_secret_value()

    async def fetch_fn():
        return await fetch_hvv_departures(
            request.app.state.http,
            slug=entry.slug,
            station=name,
            user=hvv_user,
            key=hvv_secret,
            now=datetime.now(UTC),
        )

    raw, status = await client.fetch("hvv_geofox", cache_key, fetch_fn)

    # Toter Upstream ohne Cache -> 503 mit selbst-korrigierendem Hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Live-Quelle 'hvv_geofox' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    # Unbekannte Station oder keine Abfahrten -> ehrliches no_data (200) OHNE Mapper.
    if not raw.get("departures"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                refresh_seconds=_HVV_REFRESH_SECONDS,
            ),
        }

    record = map_hvv_departures(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    # KEIN Archiv-Write (Tier C live-only, T-20-ARCHIVE)! Nur Redis-Cache.
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=record.observed_at.isoformat() if record.observed_at else None,
            refresh_seconds=_HVV_REFRESH_SECONDS,
        ),
    }


# --- Transit-Live-Routen (GTFS-RT, Phase 19, Tier B) -------------------------
#
# Der Request-Pfad liest NUR aus Redis (transit.store): der Hintergrund-Poller
# (transit/poller.py) hat den 68-MB-Feed EINMAL je Kadenz geparst und indiziert
# abgelegt. KEIN 68-MB-Parse pro Request (T-19-REQPARSE). Kadenz 45s (Poller),
# NICHT _LIVE_REFRESH_SECONDS=300 der DATEX-Quellen.

# Poller-Kadenz (CONTEXT: 30-60s; Feed ~68 MB). Die Live-Routen weisen sie als
# refresh_seconds aus, damit Clients ihren Polling-Takt daran ausrichten.
_TRANSIT_REFRESH_SECONDS = 45

# stop_id/route_id-Allowlist (T-19-CACHEPOISON): DELFI-IDs haben das Muster
# de:<AGS-Ziffern>:<rest>; der gtfs.de-Free-Feed nutzt Rein-NUMERISCHE stop_ids
# (live verifiziert 2026-06-12: 150k+ Index-Keys wie transit_rt:idx:stop:27796).
# Beide Formate sind zulaessig; NUR validierte Werte gelangen in Redis-Keys
# (kein roher User-String).
_STOP_ID_RE = re.compile(r"^(de:\d+:[\w:.\-]+|\d+)$")
_ID_RE = re.compile(r"^[\w:.\-]+$")


def _transit_disabled(settings) -> bool:
    """True, wenn der GTFS-RT-Toggle aus ist (-> source_status='disabled')."""
    return not getattr(settings, "enable_gtfs_rt", False)


def _service_day_epoch(now_epoch: int) -> int:
    """Mitternacht (UTC) des Betriebstags von ``now_epoch`` als Unix-Epoch.

    Reine Arithmetik (kein Systemuhr-Aufruf): ``now_epoch`` wird vom Handler
    injiziert. Dient als Bezug fuer GTFS-Soll-Zeiten ("HH:MM:SS", >24h moeglich).
    """
    return now_epoch - (now_epoch % 86_400)


@router.get("/{city}/transit/departures")
async def live_transit_departures(
    city: str, request: Request, stop_id: str | None = None
) -> dict:
    """Live-Abfahrten je Halt mit Verspätung (GTFS-RT, TRANSIT-RT-03, Tier B).

    Liest NUR aus Redis (Poller hat geparst): ``trips_for_stop`` + je Trip
    ``get_trip_update``. Leere Liste -> ``no_data``. ``stop_id`` muss dem
    DELFI-Muster ``de:<digits>:...`` entsprechen (Allowlist, T-19-CACHEPOISON),
    sonst 400. KEIN Archiv (Tier B, T-19-ARCHIVE), KEIN Request-Parse.
    """
    entry = get_city(city)
    settings = Settings()
    if _transit_disabled(settings):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }
    if not stop_id or not _STOP_ID_RE.match(stop_id):
        raise ValidationFailedError(
            "Ungueltige oder fehlende stop_id.",
            hint=(
                "Erwartet wird eine Halt-ID im DELFI-Muster 'de:<AGS>:<id>' "
                "oder eine numerische gtfs.de-Halt-ID."
            ),
        )

    redis = request.app.state.redis
    trip_ids = await trips_for_stop(redis, stop_id)
    departures: list[dict] = []
    for tid in trip_ids:
        update = await get_trip_update(redis, tid)
        if update is None:
            continue
        departures.append(
            {
                "trip_id": tid,
                "route_id": update.get("route_id"),
                "delay_s": update.get("delay"),
            }
        )

    if not departures:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }

    record = map_transit_departures(
        {"stop_id": stop_id, "departures": departures},
        retrieved_at=datetime.now(UTC),
        city_slug=entry.slug,
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # KEIN Archiv-Write fuer reine Live-Daten (T-19-ARCHIVE, Tier B)! Nur Redis.
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            as_of=record.observed_at.isoformat() if record.observed_at else None,
            refresh_seconds=_TRANSIT_REFRESH_SECONDS,
        ),
    }


@router.get("/{city}/transit/trips/{trip_id}")
async def live_transit_trip(city: str, trip_id: str, request: Request) -> dict:
    """Live-Fahrt-Detail inkl. geschätzter Position (GTFS-RT, TRANSIT-RT-04, Tier B).

    Liest das Update aus Redis (``get_trip_update``); fehlt es -> ``no_data``. Die
    Statik-Aufloesung (``stops_with_geo_for_trip`` gegen ``delfi_gtfs_path``) +
    ``estimate_position`` liefern die geschätzte Position. now_epoch ist VERBINDLICH
    die Request-Zeit (``datetime.now(UTC).timestamp()`` im Handler ermittelt und
    injiziert, NICHT der evtl. veraltete update.timestamp). Ist die Statik nicht
    aufloesbar -> ``unresolved=True`` (kein 500, RESEARCH Pitfall 4). KEIN Archiv.
    """
    entry = get_city(city)
    settings = Settings()
    if _transit_disabled(settings):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }
    if not _ID_RE.match(trip_id):
        raise ValidationFailedError(
            "Ungueltige trip_id.",
            hint="Die trip_id darf nur Wort-/Trennzeichen enthalten.",
        )

    redis = request.app.state.redis
    update = await get_trip_update(redis, trip_id)
    if update is None:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }

    # now_epoch VERBINDLICH die Request-Zeit (Plan-Vorgabe), im Handler ermittelt
    # und in den reinen Kern injiziert (estimate_position ist ohne Systemuhr).
    now_epoch = int(datetime.now(UTC).timestamp())
    estimated_position: dict | None = None
    unresolved = True
    # RT-Aufloesung gegen die FEED-EIGENE Statik (gtfs.de, numerische IDs);
    # Fallback delfi_gtfs_path nur fuer Tests/Mobilithek-Quelle mit DELFI-IDs.
    gtfs_path = getattr(settings, "gtfs_rt_static_path", None) or getattr(
        settings, "delfi_gtfs_path", None
    )
    if gtfs_path:
        try:
            stops = stops_with_geo_for_trip(
                gtfs_path, trip_id, service_day_epoch=_service_day_epoch(now_epoch)
            )
            if stops:
                unresolved = False
                estimated_position = estimate_position(
                    stops, delay_s=update.get("delay") or 0, now_epoch=now_epoch
                )
        except (OSError, KeyError, ValueError):
            # Statik nicht lesbar/unvollstaendig -> ehrlich unresolved (kein 500).
            unresolved = True

    record = map_transit_trip(
        {
            "trip_id": trip_id,
            "route_id": update.get("route_id"),
            "delay": update.get("delay"),
            "timestamp": update.get("timestamp"),
            "stop_time_updates": update.get("stop_time_updates", []),
            "estimated_position": estimated_position,
            "unresolved": unresolved,
        },
        retrieved_at=datetime.now(UTC),
        city_slug=entry.slug,
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # KEIN Archiv-Write fuer reine Live-Daten (T-19-ARCHIVE, Tier B)! Nur Redis.
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            as_of=record.observed_at.isoformat() if record.observed_at else None,
            refresh_seconds=_TRANSIT_REFRESH_SECONDS,
        ),
    }


@router.get("/{city}/transit/routes/{route_id}/status")
async def live_transit_route_status(city: str, route_id: str, request: Request) -> dict:
    """Live-Verspätungslage einer Linie (GTFS-RT, TRANSIT-RT-05, Tier B).

    Aggregiert die aktiven Fahrten einer Linie aus Redis (``trips_for_route`` +
    ``get_trip_update``): ``active_trips`` Anzahl, ``avg_delay_s``/``max_delay_s``
    ueber die Verspaetungen. Leer -> ``no_data``. KEIN Request-Parse, KEIN Archiv.
    """
    entry = get_city(city)
    settings = Settings()
    if _transit_disabled(settings):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }
    if not _ID_RE.match(route_id):
        raise ValidationFailedError(
            "Ungueltige route_id.",
            hint="Die route_id darf nur Wort-/Trennzeichen enthalten.",
        )

    redis = request.app.state.redis
    trip_ids = await trips_for_route(redis, route_id)
    delays: list[int] = []
    trips: list[dict] = []
    for tid in trip_ids:
        update = await get_trip_update(redis, tid)
        if update is None:
            continue
        delay = update.get("delay")
        if delay is not None:
            delays.append(delay)
        trips.append({"trip_id": tid, "delay_s": delay})

    if not trips:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }

    avg_delay = round(sum(delays) / len(delays), 1) if delays else None
    max_delay = max(delays) if delays else None
    record = map_transit_route_status(
        {
            "route_id": route_id,
            "active_trips": len(trips),
            "avg_delay_s": avg_delay,
            "max_delay_s": max_delay,
            "trips": trips,
        },
        retrieved_at=datetime.now(UTC),
        city_slug=entry.slug,
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # KEIN Archiv-Write fuer reine Live-Daten (T-19-ARCHIVE, Tier B)! Nur Redis.
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            as_of=record.observed_at.isoformat() if record.observed_at else None,
            refresh_seconds=_TRANSIT_REFRESH_SECONDS,
        ),
    }


# --- Re-Exposition Bestand unter /live (LIVE-03, REST-Regel 6) ---------------
#
# DUENNE Alias-Wrapper: jeder ruft EXAKT den bestehenden cities.py-Handler auf
# (eine Quelle der Wahrheit, KEIN duplizierter Body, RESEARCH Anti-Pattern). Der
# Envelope-Kontrakt ist damit per Konstruktion identisch zum Altpfad. Die Alias-
# Wrapper uebergeben dem cities-Handler eine WEGWERF-Response (``Response()``),
# damit der vom Handler gesetzte Deprecation-Header NICHT auf der /live-Antwort
# landet: der /live-Pfad ist der Nachfolger, nicht der deprecated Altpfad. Die
# Alias-Routen erben Prefix /live + Tag "Live" aus dem include_router.


@router.get("/{slug}/air")
async def live_air(slug: str, request: Request) -> dict:
    """Live-Alias fuer den OpenAQ-Luft-Endpunkt (LIVE-03)."""
    return await cities.city_air(slug, request, Response())


@router.get("/{slug}/air-uba")
async def live_air_uba(slug: str, request: Request) -> dict:
    """Live-Alias fuer den UBA-Luft-Endpunkt (LIVE-03)."""
    return await cities.city_air_uba(slug, request, Response())


@router.get("/{slug}/water-level")
async def live_water_level(slug: str, request: Request) -> dict:
    """Live-Alias fuer den PEGELONLINE-Pegelstand-Endpunkt (LIVE-03)."""
    return await cities.city_water_level(slug, request, Response())


@router.get("/{slug}/traffic")
async def live_traffic(slug: str, request: Request) -> dict:
    """Live-Alias fuer den Autobahn-Verkehrs-Endpunkt (LIVE-03)."""
    return await cities.city_traffic(slug, request, Response())


@router.get("/{slug}/webcams")
async def live_webcams(slug: str, request: Request) -> dict:
    """Live-Alias fuer den Autobahn-Webcam-Endpunkt (LIVE-03)."""
    return await cities.city_webcams(slug, request, Response())


@router.get("/{slug}/flood")
async def live_flood(slug: str, request: Request) -> dict:
    """Live-Alias fuer den LHP-Hochwasser-Endpunkt (LIVE-03)."""
    return await cities.city_flood(slug, request, Response())
