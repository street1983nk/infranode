"""App-Factory + Middleware-Wiring + Lifespan (Pattern 1, FND-03/04/05).

``create_app()`` verdrahtet Config, Logging, Correlation-ID-Middleware,
CORS-Whitelist (nie '*'), zentrales Error-Mapping und den versionierten
/api/v1-Router. Der Lifespan oeffnet/schliesst den Redis-Pool (lazy).
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import structlog
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import _find_route_handler
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from infranode.api.responses import OrjsonResponse

from .api.errors import register_exception_handlers
from .api.v1 import api_v1
from .api.v1.ratelimit import limiter, real_client_ip
from .config import get_settings
from .infra.etag import cache_control_for, compute_etag
from .infra.http import close_http_client, create_http_client
from .infra.metrics import incr_request, push_log, record_consumer
from .infra.mobilithek import close_mobilithek_client, create_mobilithek_client
from .infra.redis import close_redis_pool, create_redis_pool
from .logging import configure_logging
from .resilience.breaker_redis import RedisBreakerRegistry
from .resilience.client import ResilientSourceClient
from .transit.poller import maybe_start_gtfs_rt_poller

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Oeffnet Redis-Pool + gepoolten HTTP-Client beim Start, schliesst beim Stop."""
    settings = get_settings()
    app.state.settings = settings
    app.state.redis = create_redis_pool(settings.redis_url)
    # Ein prozessweiter, gepoolter httpx-AsyncClient fuer alle Upstreams (RES-01/05).
    app.state.http = create_http_client(settings)
    # Dedizierter mTLS-Client NUR fuer Mobilithek (LIVE-04, T-20-MTLS): das
    # Client-Cert darf nie an fremde Hosts gehen, daher ein SEPARATER Client,
    # NICHT app.state.http. Graceful Degradation: ohne Cert + Passwort kein Pull
    # (None), die Live-Routen liefern dann source_status="disabled".
    if settings.mobilithek_cert_path and settings.mobilithek_cert_password:
        # Fail-open statt Crash (RES-Kernprinzip): ein fehlendes/defektes Cert
        # (z. B. Volume-Mount vergessen) darf NIE den App-Start verhindern.
        # Live-Routen degradieren dann zu source_status="disabled".
        try:
            app.state.mobilithek_http = create_mobilithek_client(settings)
        except (OSError, ValueError) as exc:
            log.warning(
                "mobilithek_client_init_failed",
                error=str(exc),
                cert_path=str(settings.mobilithek_cert_path),
            )
            app.state.mobilithek_http = None
    else:
        app.state.mobilithek_http = None
    # Prozessweites Task-Set fuer SWR-Background-Refresh (Pitfall 3, Plan 03/04).
    app.state.bg_tasks = set()
    # Prozessweite, Redis-persistente Breaker-Registry: Breaker-State MUSS
    # request-uebergreifend leben (eine in Request A getrippte Quelle bleibt fuer
    # Request B offen, RES-04) UND Deploys/Worker-Grenzen ueberleben (C-2026). Die
    # RedisBreakerRegistry spiegelt den State write-through nach Redis und nutzt
    # Wall-Clock-Zeit (prozessuebergreifend gueltiger opened_at). Faellt Redis aus,
    # degradiert sie still zum reinen in-memory-Verhalten (BreakerRegistry-Basis).
    app.state.breakers = RedisBreakerRegistry(redis=app.state.redis)

    def _schedule(coro):
        """Plant eine SWR-Refresh-Coroutine als langlebigen Task (Pitfall 3).

        Haelt eine Referenz in ``app.state.bg_tasks`` gegen vorzeitige
        Garbage-Collection und entfernt sie nach Abschluss wieder.
        """
        task = asyncio.ensure_future(coro)
        app.state.bg_tasks.add(task)
        task.add_done_callback(app.state.bg_tasks.discard)

    # EINE Fassade fuer alle Quellen-Adapter ab Phase 4 (Integration RES-01..05).
    app.state.resilient_client = ResilientSourceClient(
        http=app.state.http,
        redis=app.state.redis,
        breakers=app.state.breakers,
        schedule=_schedule,
    )
    # GTFS-RT-Hintergrund-Poller (Phase 19): parst den Feed EINMAL je Kadenz nach
    # Redis (NIE im Request-Pfad, T-19-REQPARSE). Wird nur bei enable_gtfs_rt True
    # + aufloesbarer Quelle gestartet (gtfs_de immer; mobilithek_delfi nur mit Cert
    # + Abo-ID); nutzt das bestehende _schedule/bg_tasks-Muster (GC-Schutz). Bei
    # Default (enable_gtfs_rt False) entsteht KEIN Task (kein Verhaltensbruch).
    maybe_start_gtfs_rt_poller(app, settings, _schedule)
    try:
        yield
    finally:
        # Langlebige Hintergrund-Tasks (GTFS-RT-Poller, SWR-Refresh) zuerst canceln,
        # damit kein Task nach dem Pool-Close noch auf http/redis zugreift. Der
        # Poller faengt CancelledError ab und beendet sich sauber (Phase 19).
        for task in list(app.state.bg_tasks):
            task.cancel()
        # Reihenfolge: erst HTTP-Pools schliessen, dann Redis.
        await close_http_client(app.state.http)
        if app.state.mobilithek_http is not None:
            await close_mobilithek_client(app.state.mobilithek_http)
        await close_redis_pool(app.state.redis)


def _etag_payload(body: bytes, request_id: str | None) -> bytes:
    """Neutralisiert die per-Request correlation_id fuer die ETag-Berechnung.

    Der ETag soll den stabilen Ressourcen-Inhalt repraesentieren, nicht die je
    Request frisch erzeugte correlation_id. Ist die aktuelle ID im Body
    enthalten, wird genau ihr Vorkommen durch einen festen Platzhalter ersetzt
    (nur fuer das Hashing); der ausgelieferte Body bleibt unveraendert. Ohne
    bekannte ID (kein Treffer) wird der Body unveraendert gehasht.
    """
    if not request_id:
        return body
    needle = request_id.encode()
    if needle not in body:
        return body
    return body.replace(needle, b"__etag_stable_correlation_id__")


class ETagMiddleware(BaseHTTPMiddleware):
    """ETag/Cache-Control + conditional GET (API-08, Pattern 4).

    Greift NUR auf erfolgreiche GET-Reads (Status 200): liest den finalen
    Response-Body (OrjsonResponse liefert bytes), berechnet daraus einen
    stabilen ETag und setzt Cache-Control je Ressource. Stimmt der
    ``If-None-Match``-Request-Header mit dem berechneten ETag ueberein, wird ein
    304 ohne Body zurueckgegeben (ETag + Cache-Control bleiben erhalten). Fehler-
    Envelopes/503/non-GET/Streaming werden NIE angefasst (Anti-Pattern,
    T-11-ETAG-LEAK). ``If-None-Match`` wird nur verglichen, nie als Cache-
    Schluessel verwendet (T-11-ETAG-POISON).

    Reihenfolge (Pitfall 5): diese Middleware muss den finalen Body sehen, also
    nahe am Response liegen (zuerst hinzugefuegt = zuletzt ausgefuehrt), CORS
    bleibt aussen.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        # Nur erfolgreiche GET-Reads cachen; alles andere unberuehrt lassen.
        if request.method != "GET" or response.status_code != 200:
            return response

        # Finalen Body aus dem Streaming-Iterator zusammenfuehren (BaseHTTPMiddleware
        # liefert eine StreamingResponse), ohne ihn fuer den Client zu verlieren.
        body = b"".join([chunk async for chunk in response.body_iterator])

        # ETag ueber den STABILEN Ressourcen-Inhalt: die per-Request neu erzeugte
        # correlation_id (meta.correlation_id) ist Request-Rauschen und darf den
        # ETag nicht variieren lassen, sonst matcht If-None-Match nie -> kein 304.
        # Wir hashen daher eine Variante mit neutralisierter correlation_id; der
        # AUSGELIEFERTE Body behaelt die echte ID unveraendert.
        etag = compute_etag(_etag_payload(body, correlation_id.get()))
        response.headers["ETag"] = etag
        # Ressource aus dem Pfadsegment nach /api/v1/<resource> ableiten; faellt
        # in cache_control_for auf default zurueck, wenn unbekannt.
        parts = [p for p in request.url.path.split("/") if p]
        resource = parts[2] if len(parts) > 2 else None
        response.headers["Cache-Control"] = cache_control_for(resource)

        # Conditional GET: If-None-Match == ETag -> 304 ohne Body. Header
        # (ETag/Cache-Control + bestehende, z.B. Correlation-ID) bleiben erhalten.
        if request.headers.get("if-none-match") == etag:
            not_modified = Response(status_code=304, headers=dict(response.headers))
            del not_modified.headers["content-length"]
            return not_modified

        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )


class MetricsMiddleware(BaseHTTPMiddleware):
    """Log-Capture fuer das Admin-Dashboard (OPS-01/OPS-02).

    Misst je Request die Bearbeitungsdauer (``time.perf_counter`` VOR/NACH
    ``call_next``) und schreibt nach Abschluss einen KOMPAKTEN Log-Eintrag (Zeit,
    Methode, Pfad, Status, Dauer, request_id) in den gekappten Redis-Ringpuffer
    plus einen Request-Zaehler (gesamt + Status + Endpunkt). Es landen NUR
    Request-Metadaten im Buffer, NIE Header/Body/Cookies (T-13-02-06).

    Reihenfolge (Pitfall 1/5): MetricsMiddleware braucht den finalen Status UND die
    correlation_id. ``CorrelationIdMiddleware`` muss daher VOR der MetricsMiddleware
    laufen (= spaeter added, da Starlette zuletzt-added-zuerst-ausfuehrt), damit
    ``correlation_id.get()`` im dispatch bereits gesetzt ist.

    Jeder Redis-Zugriff ist try/except-gekapselt: ein Metrik-Verlust crasht NIE den
    Request-Pfad (Graceful Degradation, Muster aus metrics.py).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        dauer_ms = round((time.perf_counter() - start) * 1000, 1)

        # Endpunkt-Pfad fuer den Counter-Hash auf das Route-Template normalisieren
        # (keine unbeschraenkte Kardinalitaet durch slugs): bevorzugt das gematchte
        # Route-Template (scope["route"].path), sonst der rohe URL-Pfad.
        route = request.scope.get("route")
        endpoint = getattr(route, "path", None) or request.url.path

        # MCP-Aktionen kennzeichnen: der Remote-MCP-Server markiert seine internen
        # Aufrufe mit X-Infranode-Mcp (Wert = Ressource). So werden MCP-Aktionen im
        # Dashboard sichtbar (eigenes Feld + eigener Counter "mcp:<endpoint>") und
        # nicht mit normalem API-Traffic vermischt (Owner-Wunsch: MCP verfolgen).
        mcp_resource = request.headers.get("x-infranode-mcp")

        try:
            redis = request.app.state.redis
            entry = {
                "zeit": datetime.now(UTC).isoformat(),
                "methode": request.method,
                "pfad": request.url.path,
                "status": response.status_code,
                "dauer_ms": dauer_ms,
                "request_id": correlation_id.get(),
            }
            if mcp_resource:
                entry["via_mcp"] = True
                entry["mcp_ressource"] = mcp_resource
            await push_log(redis, entry)
            await incr_request(
                redis,
                endpoint=f"mcp:{endpoint}" if mcp_resource else endpoint,
                status_code=response.status_code,
            )
            # Aktive-Consumer-Tracking (nur echte Datenabrufe unter /api/v1/, ohne
            # Health/OpenAPI): je Stunde Anzahl + letzte Meta je Client-IP bzw.
            # "mcp" fuer interne MCP-Aufrufe. Speist den stuendlichen ntfy-Digest.
            p = request.url.path
            if p.startswith("/api/v1/") and not p.startswith(
                ("/api/v1/health", "/api/v1/openapi")
            ):
                ident = "mcp" if mcp_resource else real_client_ip(request)
                await record_consumer(
                    redis,
                    ident=ident,
                    user_agent=request.headers.get("user-agent", ""),
                    path=request.url.path,
                    now=datetime.now(UTC),
                )
        except Exception as exc:  # noqa: BLE001 - Metrik-Verlust crasht nie den Request
            # Graceful Degradation: ein Metrik-/Redis-Fehler darf den Request-Pfad
            # nie crashen; nur als Debug protokollieren (vermeidet S110 bare pass).
            log.debug("metrics_middleware_failed", error=str(exc))

        # Erstkontakt-Benachrichtigung: meldet per ntfy, wenn ein neuer Dev (per
        # Client-IP) zum ersten Mal die API nutzt. Selbst gekapselt und best-effort,
        # crasht den Request nie. Nach call_next eingehaengt (Pfad dann bekannt).
        try:
            pass  # Erstkontakt-Telemetrie ist privat (entfernt im Public-Build)
        except Exception as exc:  # noqa: BLE001 - Erstkontakt-Push crasht nie den Request
            log.debug("first_seen_middleware_failed", error=str(exc))

        # MCP-Aktion per ntfy verfolgen (feuert nur bei gesetztem MCP-Header).
        # Eigene Kapselung, best-effort, crasht den Request nie.
        try:
            await note_mcp_action(
                request,
                settings=request.app.state.settings,
            )
        except Exception as exc:  # noqa: BLE001 - MCP-Push crasht nie den Request
            log.debug("mcp_action_middleware_failed", error=str(exc))

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Wendet die Limiter-default_limits auf JEDE Route an (Live-Report M2).

    Hintergrund: slowapi-``@limiter.limit``-Decorator stehen nur auf wenigen Routen
    (/sources, /compare, /admin/login). Die uebrigen City-/Meta-GETs trugen KEINEN
    Decorator, also griff dort weder das IP-Limit (60/min) noch wurden RateLimit-
    Header gesetzt. Diese Middleware ruft den Limiter mit ``in_middleware=True``
    auf: slowapi zieht dann die ``default_limits`` (ANON_LIMIT) fuer alle NICHT per
    Decorator markierten Routen und ueberspringt die bereits dekorierten (kein
    Doppelzaehlen).

    Warum NICHT die mitgelieferte ``SlowAPIMiddleware``: deren synchroner
    429-Pfad faellt auf slowapis eigenen Default-Handler zurueck, sobald der
    registrierte ``RateLimitExceeded``-Handler async ist (unser Envelope-Handler
    ist async) und crasht dort (``exc.detail``). Diese Middleware gibt den 429
    stattdessen direkt ueber den zentralen ErrorEnvelope zurueck (gleiche Form wie
    der async-Handler) und injiziert in beiden Faellen die RateLimit-Header.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        limiter_obj = request.app.state.limiter
        if not getattr(limiter_obj, "enabled", True):
            return await call_next(request)

        handler = _find_route_handler(request.app.routes, request.scope)

        # Routen MIT eigenem @limiter.limit-Decorator NICHT hier pruefen: ihr
        # auto_check-Decorator prueft selbst (sources/compare mit ANON_LIMIT,
        # admin/login mit ADMIN_LOGIN_LIMIT). Sonst zoege slowapi-0.1.9 im
        # Middleware-Pfad das Default ZUSAETZLICH (leere route_limits ->
        # combined_defaults=True), was die Limits verfaelschen wuerde (Doppelzaehlung).
        marked = getattr(limiter_obj, "_Limiter__marked_for_limiting", {})
        if handler is not None:
            handler_name = f"{handler.__module__}.{handler.__name__}"
            if handler_name in marked:
                return await call_next(request)
        try:
            # in_middleware=True: zieht default_limits fuer un-dekorierte Routen,
            # ueberspringt @limiter.limit-markierte (deren Decorator prueft selbst).
            limiter_obj._check_request_limit(request, handler, in_middleware=True)
        except RateLimitExceeded:
            # Zentraler 429-Envelope (identisch zum async-Handler in errors.py),
            # plus RateLimit-Header. Lokaler Import vermeidet Zyklen beim Modul-Load.
            from .api.errors import _envelope

            response = _envelope(
                429,
                "rate_limited",
                "Rate limit exceeded.",
                hint=(
                    "Bitte etwas warten und spaeter erneut versuchen "
                    "(RateLimit-Header beachten)."
                ),
            )
            view_limit = getattr(request.state, "view_rate_limit", None)
            if view_limit is not None:
                limiter_obj._inject_headers(response, view_limit)
            return response

        response = await call_next(request)
        # Bei Erfolg die RateLimit-Header auf die Antwort injizieren (D-02).
        view_limit = getattr(request.state, "view_rate_limit", None)
        if view_limit is not None:
            response = limiter_obj._inject_headers(response, view_limit)
        return response


def create_app() -> FastAPI:
    """Baut und verdrahtet die FastAPI-App (testbare Factory)."""
    settings = get_settings()
    configure_logging(settings.log_level)

    # Fail-fast bei Admin-Teilkonfiguration (Audit LOW-3, 2026-06-10): ist NUR
    # das Passwort gesetzt (ohne Session-Secret), wuerde ein erfolgreicher Login
    # beim Schreiben in request.session mit einem 500er crashen (Session-
    # Middleware nicht montiert). Kein Bypass, aber ein verdeckter Defekt; daher
    # hart beim Start abbrechen statt erst beim ersten Login.
    if bool(settings.admin_password) != bool(settings.admin_session_secret):
        raise RuntimeError(
            "Admin-Teilkonfiguration: INFRANODE_ADMIN_PASSWORD und "
            "INFRANODE_ADMIN_SESSION_SECRET muessen BEIDE gesetzt oder BEIDE "
            "leer sein (fail-closed)."
        )

    app = FastAPI(
        title="InfraNode API",
        version="0.1.0",
        default_response_class=OrjsonResponse,
        lifespan=lifespan,
    )

    # Reihenfolge (Pitfall 1/5): zuletzt hinzugefuegt = beim Request ZUERST
    # ausgefuehrt. Ausfuehrungsreihenfolge eines Requests (aussen -> innen):
    #   CORS -> Session -> CorrelationId -> Metrics -> ETag -> RateLimit -> Route.
    # Begruendung der relativen Ordnung Metrics/CorrelationId/ETag/RateLimit:
    #   - RateLimit ganz innen (zuletzt added): es matcht den finalen Route-Handler
    #     zuverlaessig und injiziert die RateLimit-Header auf die Route-Response;
    #     ETag (weiter aussen) kopiert sie via dict(response.headers) durch (auch auf
    #     die 304-Antwort), CORS bleibt aussen.
    #   - ETag muss den FINALEN Body sehen -> nah an der Route.
    #   - Metrics braucht den finalen Status UND die correlation_id; CorrelationId
    #     muss daher VOR Metrics laufen (= CorrelationId spaeter added als Metrics).
    #   - SessionMiddleware weit aussen (frueh ausgefuehrt), damit request.session
    #     vor dem Inline-Auth-Guard der /admin-Routen bereitsteht.
    #   - CORS bleibt ganz aussen (zuletzt added).
    #
    # RateLimitMiddleware (Live-Report M2): wendet die Limiter-default_limits
    # (ANON_LIMIT, default 60/min pro IP) auf JEDE Route an, auch auf die
    # City-/Meta-GETs ohne eigenen @limiter.limit-Decorator. Ohne diese Middleware
    # griff nur das per-Route-Decorator-Limit (admin-login), die GET-Reads blieben
    # ungedrosselt und ohne RateLimit-Header.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(ETagMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    # SessionMiddleware nur, wenn ein Session-Secret konfiguriert ist (fail-closed,
    # T-13-02-02): ohne Secret gibt es kein Admin-Login. HttpOnly ist Starlette-
    # Default; SameSite=Strict + Secure(Prod) + max_age 8h schuetzen das Cookie.
    if settings.admin_session_secret:
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.admin_session_secret.get_secret_value(),
            session_cookie="cs_admin",
            same_site="strict",
            https_only=settings.admin_cookie_https_only,
            max_age=60 * 60 * 8,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,  # NIE ["*"]
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # StaticFiles-Mount fuer admin.css (B1): check_dir=False verhindert einen
    # RuntimeError, falls das Verzeichnis beim App-Start noch leer/abwesend ist.
    # Pfad paket-relativ absolut via Path(__file__).parent.
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static", check_dir=False),
        name="static",
    )

    # Rate-Limiter (API-06): slowapi liest app.state.limiter pro Request und
    # injiziert die (normalisierten) RateLimit-Header auf Erfolgsantworten der
    # @limiter.limit-annotierten Routen. Der 429-Handler ist in
    # register_exception_handlers verdrahtet (Envelope statt slowapi-Default).
    app.state.limiter = limiter

    register_exception_handlers(app)
    app.include_router(api_v1)
    # Admin-Router (OPS-01): prefix /admin wird im Router gesetzt, NICHT /api/v1.
    return app


app = create_app()
