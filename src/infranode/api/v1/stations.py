"""Per-Bahnhof-Live-Boards ``/stations/{eva}/departures`` + ``/arrivals`` (DATA-36).

Anders als die stadtweiten ``/cities/{slug}/station-departures`` (kuratierte
Metropolen-Hbf) liefern diese Endpunkte die Live-Tafel JEDES beliebigen DB-
Bahnhofs über seine EVA-Nummer (aus dem Katalog ``/cities/{slug}/stations``),
inklusive Nahverkehr (alle Gattungen ICE/IC/RE/RB/S) und Stoerungen/Meldungen.
Quelle: DB Timetables (DB API Marketplace, CC BY 4.0 = Tier A), derselbe Adapter
wie die stadtweiten Boards, nur mit genau einer EVA.

Sicherheit:
- T-05-08/T-12 (SSRF/Injection): ``eva`` wird strikt als 6-8-stellige Zahl
  validiert, BEVOR sie in die Upstream-URL gelangt (reiner numerischer
  Pfadbestandteil; ein nicht-numerischer/zu langer Wert -> 422).
- T-08-CRED: Client-Id/Api-Key gehen NUR in die Request-Header (Adapter), nie in
  Cache-Key/Response/Log.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Request

from infranode.adapters.db_timetables import (
    fetch_station_arrivals,
    fetch_station_departures,
)
from infranode.api.errors import UnprocessableError, UpstreamError
from infranode.config import Settings
from infranode.infra.cache import build_cache_key
from infranode.normalization.mappers.db_timetables import (
    map_station_arrivals,
    map_station_departures,
)

router = APIRouter()

# Eine EVA-Nummer (Europäische Vehicle-/Bahnhofs-Nummer) ist eine reine Zahl
# (deutsche Bahnhöfe 7-stellig, defensiv 6-8). Strikte Validierung = SSRF-Schutz.
_EVA_RE = re.compile(r"^\d{6,8}$")


def _validate_eva(eva: str) -> str:
    """Validiert die EVA als 6-8-stellige Zahl (SSRF, T-12); 422 bei Verstoß."""
    if not _EVA_RE.match(eva):
        raise UnprocessableError(
            f"Ungueltige EVA-Nummer {eva!r}: erwartet eine 6-8-stellige Zahl.",
            hint="EVA-Nummern stehen im Katalog GET /api/v1/cities/{slug}/stations.",
        )
    return eva


async def _board(
    request: Request,
    *,
    eva: str,
    cache_prefix: str,
    fetch_fn_factory,
    mapper,
    empty_key: str,
) -> dict:
    """Gemeinsamer Kern für Abfahrts-/Ankunfts-Board einer einzelnen EVA.

    Drei ``source_status``: ``disabled`` (Toggle aus/keine Keys), ``no_data``
    (Bahnhof erreichbar, keine Züge im Zeitfenster), ``ok`` (gemappter Payload).
    """
    eva = _validate_eva(eva)
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
    cache_key = build_cache_key(cache_prefix, city_slug=f"eva-{eva}")
    client_id = cid_secret.get_secret_value()
    api_key = key.get_secret_value()

    async def fetch_fn():
        return await fetch_fn_factory(
            request.app.state.http,
            slug=eva,
            evas=(eva,),
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

    if not raw.get(empty_key):
        return {
            "data": None,
            "meta": {
                "correlation_id": cid,
                "source_status": "no_data",
                "cache_status": status,
            },
        }

    record = mapper(raw, retrieved_at=datetime.now(UTC))
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/{eva}/departures")
async def station_departures_by_eva(eva: str, request: Request) -> dict:
    """Live-Abfahrten eines beliebigen DB-Bahnhofs (EVA) inkl. Nahverkehr + Meldungen.

    Nächste Zugabfahrten am Bahnhof mit EVA-Nummer ``eva`` (alle Gattungen
    ICE/IC/RE/RB/S, Echtzeit-Verspätung, Stoerungen/Meldungen). EVA aus dem Katalog
    ``GET /api/v1/cities/{slug}/stations``. Quelle DB Timetables (CC BY 4.0).
    """
    return await _board(
        request,
        eva=eva,
        cache_prefix="db_timetables",
        fetch_fn_factory=fetch_station_departures,
        mapper=map_station_departures,
        empty_key="departures",
    )


@router.get("/{eva}/arrivals")
async def station_arrivals_by_eva(eva: str, request: Request) -> dict:
    """Live-Ankünfte eines beliebigen DB-Bahnhofs (EVA) inkl. Nahverkehr + Meldungen.

    Spiegelbild zu ``station_departures_by_eva`` (``origin`` statt ``destination``).
    Quelle DB Timetables (CC BY 4.0).
    """
    return await _board(
        request,
        eva=eva,
        cache_prefix="db_timetables_arr",
        fetch_fn_factory=fetch_station_arrivals,
        mapper=map_station_arrivals,
        empty_key="arrivals",
    )
