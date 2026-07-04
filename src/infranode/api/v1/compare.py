"""Multi-City-Compare (API-05): EINE Ressource über mehrere Städte fächern.

D-06: ein Endpunkt liefert eine Ressource über mehrere Städte in EINER Response;
je Stadt ein ``source_status`` (ok/disabled/no_data/error/not_found). Eine fehlende
oder tote Stadt-Quelle erzeugt KEIN Gesamt-5xx (per-Stadt Graceful Degradation):
der Fan-out läuft über ``asyncio.gather`` gegen die resiliente Fassade
(``request.app.state.resilient_client.fetch``), die nie blockiert und keinen
ungemappten Upstream-Fehler raised.

Sicherheit: ``resource`` wird gegen ``RESOURCE_MAP`` validiert (unbekannt -> 400
ValidationFailedError, BEVOR roher User-String in einen Cache-Key/Fetch gelangt,
T-11-FILTER-INJ). Die ``cities``-Liste wird auf ``_MAX_CITIES`` begrenzt
(T-11-CMP-DOS); die Slugs validiert ``get_city`` (build_cache_key nur aus dem
validierten Register-Slug). Die Route ist rate-limitiert (@limiter.limit).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Depends, Request, Response

from infranode.adapters.dwd import fetch_weather
from infranode.adapters.uba import fetch_air_uba
from infranode.api.errors import NotFoundError, ValidationFailedError
from infranode.api.v1.pagination import PageParams, page_params, paginate
from infranode.api.v1.ratelimit import ANON_LIMIT, limiter
from infranode.config import Settings
from infranode.infra.cache import build_cache_key
from infranode.normalization.mappers.dwd import map_weather
from infranode.normalization.mappers.uba import map_air_uba
from infranode.registry import get_city

router = APIRouter()

# Ressource -> (source, fetch_fn, mapper, toggle). Additiv erweiterbar (analog
# CONNECTOR_MAP in cities.py). Die Schlüssel definieren die erlaubten resource-
# Werte (Whitelist, T-11-FILTER-INJ); ein Wert außerhalb -> 400. Genau die hier
# eingetragenen, bestehenden Adapter/Mapper werden wiederverwendet (keine neuen
# Quellen): "weather" -> DWD (keylos), "air" -> UBA (Tier-A-Luftpfad).
RESOURCE_MAP: dict[str, tuple] = {
    "weather": ("dwd", fetch_weather, map_weather, "enable_dwd"),
    "air": ("uba", fetch_air_uba, map_air_uba, "enable_uba"),
}


def _delegated_resources() -> dict:
    """Ressource -> bestehender City-Route-Handler (Compare-Ausbau 2026-07-04).

    Zweiter Zweig neben RESOURCE_MAP: statt eines Adapter-Fetches wird der
    EXISTIERENDE Route-Handler je Stadt aufgerufen (identisches Verhalten
    inkl. Toggles, Fallbacks, no_data/not_ingested und Attribution; keine
    Logik-Duplikate). Nur billige Kandidaten sind gelistet: Store-Reads
    (indicators), gecachte Quellen (GENESIS-Regio, DWD-Warnungen: EIN
    bundesweiter Fetch fuer alle Staedte) und der Redis-Join
    (charging-status). BEWUSST NICHT dabei: fuel-prices (Tankerkoenig-ToS
    verlangt on-demand ohne Cache, ein 28-Staedte-Fan-out je Request waere
    ein ToS-/Limit-Risiko).

    Lazy als Funktion statt Modul-Konstante: cities.py importiert beim Laden
    viel Adapter-Geflecht; der lokale Import vermeidet Import-Zyklen ueber
    api.v1.__init__ und haelt die Modul-Ladezeit von compare.py klein.
    """
    from infranode.api.v1 import cities as city_routes

    return {
        "indicators": city_routes.city_indicators,
        "demographics": city_routes.city_demographics,
        "unemployment": city_routes.city_unemployment,
        "tourism": city_routes.city_tourism,
        "charging-status": city_routes.city_charging_status,
        "weather-warnings": city_routes.city_weather_warnings,
    }


# Obergrenze für die Anzahl verglichener Städte (T-11-CMP-DOS): begrenzt den
# Fan-out unabhängig von der Register-Größe, damit ein langer cities-String
# nicht beliebig viele parallele Upstream-Calls auslöst.
_MAX_CITIES = 28

# Whitelist der sortierbaren Felder der Compare-Liste (T-11-FILTER-INJ).
_COMPARE_SORT_WHITELIST = {"city", "source_status"}


async def _one(slug: str, request: Request, resource: str) -> dict:
    """Holt eine Ressource für EINE Stadt; degradiert per-Stadt graceful (D-06).

    Wirft NIE in den Fan-out hinein: unbekannter Slug -> ``not_found``, Toggle aus
    -> ``disabled``, toter Upstream ohne Cache (raw is None) -> ``error``, leere
    Antwort -> ``no_data``, sonst Mapper -> ``ok``. Jeder Zweig trägt seinen
    eigenen ``source_status``; kein Zweig führt zu einem Gesamt-5xx.
    """
    source, fetch_fn_adapter, mapper, toggle = RESOURCE_MAP[resource]

    # Unbekannter Slug -> per-Stadt not_found als Teilergebnis (D-06: kein 404 für
    # die gesamte Vergleichs-Antwort, eine schlechte Stadt verdirbt nicht die Batch).
    try:
        entry = get_city(slug)
    except NotFoundError:
        return {"city": slug, "data": None, "source_status": "not_found"}

    # Quellen-Toggle frisch lesen (Settings() statt app.state.settings, damit der
    # per-Test gesetzte Env-Override greift). DATA-06: deaktiviert -> disabled.
    if not getattr(Settings(), toggle):
        return {"city": entry.slug, "data": None, "source_status": "disabled"}

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_fn_adapter(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    # D-06: der Fan-out raised NIE. Die Fassade fängt httpx-Fehler/Breaker-Open
    # bereits ab (-> (None, STALE-ON-ERROR)); ein darüber hinaus durchschlagender
    # Fehler (z.B. ein Adapter-/Mapper-Defekt einer einzelnen Stadt) wird hier
    # zusätzlich zu per-Stadt "error" degradiert, damit eine kaputte Stadt nicht
    # die gesamte Vergleichs-Antwort mit 5xx verdirbt.
    try:
        raw, status = await client.fetch(source, key, fetch_fn)
    except Exception:  # noqa: BLE001 - per-Stadt still degradieren (D-06)
        return {"city": entry.slug, "data": None, "source_status": "error"}

    # Toter Upstream ohne Cache -> per-Stadt error (KEIN raise, D-06).
    if raw is None:
        return {"city": entry.slug, "data": None, "source_status": "error"}

    # Quelle erreichbar, aber keine Nutzlast -> ehrliches no_data.
    if not raw:
        return {"city": entry.slug, "data": None, "source_status": "no_data"}

    try:
        record = mapper(
            raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
        )
    except Exception:  # noqa: BLE001 - defekter Datensatz einer Stadt -> error (D-06)
        return {"city": entry.slug, "data": None, "source_status": "error"}

    return {
        "city": entry.slug,
        "data": record.model_dump(mode="json"),
        "source_status": "ok",
        "cache_status": status,
    }


async def _one_delegated(slug: str, request: Request, resource: str) -> dict:
    """Holt eine delegierte Ressource für EINE Stadt über den Route-Handler.

    Gleicher D-06-Vertrag wie ``_one``: unbekannter Slug -> ``not_found``,
    JEDER Handler-Fehler (inkl. UpstreamError-503 des Einzel-Endpunkts) wird
    zu per-Stadt ``error`` degradiert, nie zu einem Gesamt-5xx. Der
    ``source_status`` des Handler-Envelopes (ok/disabled/no_data/
    not_ingested/...) wird unverändert durchgereicht, ``cache_status``/
    ``fallback`` ebenso.

    Sonderfall charging-status: die Einzelpunkt-Liste (bis 500 je Stadt)
    wird im Compare weggelassen (``points_omitted``-Marker statt Liste),
    sonst wüchse eine 28-Städte-Antwort auf Megabyte; für den Vergleich
    zählen die Aggregate (total/reported/status_counts).
    """
    try:
        entry = get_city(slug)
    except NotFoundError:
        return {"city": slug, "data": None, "source_status": "not_found"}

    handler = _delegated_resources()[resource]
    try:
        envelope = await handler(entry.slug, request)
    except Exception:  # noqa: BLE001 - per-Stadt still degradieren (D-06)
        return {"city": entry.slug, "data": None, "source_status": "error"}

    data = envelope.get("data")
    meta = envelope.get("meta") or {}

    if resource == "charging-status" and isinstance(data, dict):
        payload = data.get("payload")
        if isinstance(payload, dict) and "points" in payload:
            payload = {k: v for k, v in payload.items() if k != "points"}
            payload["points_omitted"] = True
            data = {**data, "payload": payload}

    row = {
        "city": entry.slug,
        "data": data,
        "source_status": meta.get("source_status", "ok"),
    }
    if meta.get("cache_status") is not None:
        row["cache_status"] = meta["cache_status"]
    if meta.get("fallback"):
        row["fallback"] = meta["fallback"]
    return row


@router.get("/compare")
@limiter.limit(ANON_LIMIT)
async def compare(
    request: Request,
    response: Response,
    cities: str,
    resource: str,
    page: PageParams = Depends(page_params),  # noqa: B008 - FastAPI-Dependency-Idiom
) -> dict:
    """Faechert ``resource`` über mehrere ``cities`` (API-05, D-06).

    ``cities`` ist eine kommaseparierte Slug-Liste; ``resource`` muss in
    ``RESOURCE_MAP`` liegen (sonst 400). Der Fan-out läuft per ``asyncio.gather``
    über die resiliente Fassade; je Stadt ein ``source_status``, eine
    fehlende/tote Quelle erzeugt KEIN Gesamt-5xx. Das Ergebnis ist paginierbar
    (API-04, Whitelist {city, source_status}).
    """
    # resource gegen die Whitelist (T-11-FILTER-INJ): unbekannt -> 400, BEVOR der
    # rohe Wert in einen Cache-Key/Fetch gelangt. Erlaubt sind die Adapter-
    # Ressourcen (RESOURCE_MAP) plus die delegierten Route-Ressourcen.
    delegated = _delegated_resources()
    if resource not in RESOURCE_MAP and resource not in delegated:
        raise ValidationFailedError(
            f"Unbekannte resource '{resource}'.",
            hint=f"Erlaubt: {', '.join(sorted([*RESOURCE_MAP, *delegated]))}.",
        )

    slugs = [s.strip() for s in cities.split(",") if s.strip()]
    if not slugs:
        raise ValidationFailedError(
            "Parameter 'cities' darf nicht leer sein.",
            hint="Beispiel: cities=berlin,koeln,hamburg.",
        )
    # Fan-out-Größe begrenzen (T-11-CMP-DOS).
    slugs = slugs[:_MAX_CITIES]

    if resource in delegated:
        results = await asyncio.gather(
            *[_one_delegated(s, request, resource) for s in slugs]
        )
    else:
        results = await asyncio.gather(*[_one(s, request, resource) for s in slugs])

    # Optionale Whitelist-gesicherte Sortierung + Paginierung der Compare-Liste
    # (API-04): unbekanntes sort -> 400, Offset-Overflow -> leere 200-Seite.
    results = list(results)
    if page.sort:
        results.sort(
            key=lambda row: (row.get(page.sort) is None, row.get(page.sort)),
            reverse=(page.order == "desc"),
        )
    page_items = paginate(results, page, sort_whitelist=_COMPARE_SORT_WHITELIST)

    return {
        "data": page_items,
        "meta": {
            "resource": resource,
            "correlation_id": correlation_id.get(),
            "total": len(results),
        },
    }
