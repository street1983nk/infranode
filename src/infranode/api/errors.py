"""Zentrales Fehler-Mapping mit einheitlicher Envelope (FND-04, REST-Regel 7).

Eine ``AppError``-Hierarchie trägt status_code + maschinenlesbaren code. Ein
einziges ``register_exception_handlers(app)`` mappt AppError,
RequestValidationError und die Catch-All-Exception auf eine ``ErrorEnvelope``.
Der Catch-All leakt NIE Stacktrace/Secrets an den Client (Pitfall 2 / T-01-01).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from asgi_correlation_id import correlation_id
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from infranode.api.responses import OrjsonResponse

log = structlog.get_logger()


class ErrorDetail(BaseModel):
    """Maschinen- und menschenlesbares Fehlerdetail."""

    code: str
    message: str
    hint: str | None = None


class ErrorEnvelope(BaseModel):
    """Einheitliche Fehler-Antwort: error-Detail + meta (correlation_id, ts)."""

    error: ErrorDetail
    meta: dict


class AppError(Exception):
    """Basis aller anwendungsspezifischen Fehler."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)


class NotFoundError(AppError):
    status_code, code = 404, "not_found"


class UnauthorizedError(AppError):
    status_code, code = 401, "unauthorized"


class ForbiddenError(AppError):
    status_code, code = 403, "forbidden"


class RateLimitError(AppError):
    status_code, code = 429, "rate_limited"


class UpstreamError(AppError):
    status_code, code = 503, "upstream_unavailable"


class ValidationFailedError(AppError):
    status_code, code = 400, "invalid_request"


class UnprocessableError(AppError):
    """Syntaktisch gültige, aber semantisch unzulässige Eingabe (HTTP 422).

    Genutzt für den ``?type=``-Whitelist-Verstoß der POI-Route: ein
    unbekannter POI-Typ wird abgewiesen, BEVOR roher User-Input in die
    Overpass-QL gelangt (T-05-09 Injection-Schutz).
    """

    status_code, code = 422, "unprocessable"


def _envelope(
    status: int,
    code: str,
    message: str,
    hint: str | None = None,
) -> OrjsonResponse:
    """Baut eine einheitliche ErrorEnvelope-Response."""
    body = ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, hint=hint),
        meta={
            "correlation_id": correlation_id.get(),
            "generated_at": datetime.now(UTC).isoformat(),
        },
    )
    return OrjsonResponse(status_code=status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Registriert die zentralen Exception-Handler auf der App."""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> OrjsonResponse:
        return _envelope(exc.status_code, exc.code, exc.message, exc.hint)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded) -> OrjsonResponse:
        # 429 über den zentralen Envelope (kein slowapi-Default-JSON, kein
        # Stacktrace/Detail-Leak, T-11-RL-LEAK). Code "rate_limited" == RateLimitError.
        response = _envelope(
            429,
            "rate_limited",
            "Rate limit exceeded.",
            hint=(
                "Bitte etwas warten und später erneut versuchen "
                "(RateLimit-Header beachten)."
            ),
        )
        # Standard-RateLimit-Header (D-02) auf die 429-Antwort setzen. slowapi
        # injiziert sie über das normalisierte _header_mapping des Limiters
        # (RateLimit-Limit/Remaining/Reset + Retry-After).
        limiter = getattr(request.app.state, "limiter", None)
        view_limit = getattr(request.state, "view_rate_limit", None)
        if limiter is not None and view_limit is not None:
            limiter._inject_headers(response, view_limit)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> OrjsonResponse:
        # Nur Feldpfad + Fehlertyp an den Client (Audit MEDIUM-2, 2026-06-10):
        # str(exc.errors()) würde Pydantic-Interna UND den Roh-Input (input=...)
        # reflektieren (Information Disclosure). Volle Details nur serverseitig.
        log.info("request_validation_failed", errors=exc.errors()[:5])
        fields = "; ".join(
            ".".join(str(part) for part in e.get("loc", ())) + f": {e.get('type', '')}"
            for e in exc.errors()[:3]
        )
        return _envelope(
            400,
            "invalid_request",
            "Request validation failed",
            hint=fields or None,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> OrjsonResponse:
        # FastAPI/Starlette wirft StarletteHTTPException für Routing-Fälle, die
        # NICHT über unsere AppError-Hierarchie laufen: unbekannter Pfad (404) und
        # falsche Methode (405). Ohne diesen Handler liefert Starlette dort den
        # Default ``{"detail": "..."}`` statt des projektweiten Error-Envelopes
        # (Live-Report M4). Fachliche Fehler (unbekannte Stadt, POI-Typ, Validierung,
        # 503) sind AppError/RequestValidationError und werden vom spezifischeren
        # Handler oben bedient, NICHT hier.
        code_map = {
            404: ("not_found", "Die angeforderte Ressource wurde nicht gefunden."),
            405: (
                "method_not_allowed",
                "Die HTTP-Methode ist für diese Ressource nicht erlaubt.",
            ),
        }
        code, message = code_map.get(
            exc.status_code,
            ("http_error", "Die Anfrage konnte nicht bearbeitet werden."),
        )
        hint = None
        if exc.status_code == 404:
            hint = "Pfad prüfen oder GET /api/v1/openapi.yaml für die Routenliste."
        elif exc.status_code == 405:
            # Erlaubte Methoden aus dem Allow-Header durchreichen, falls gesetzt.
            allowed = exc.headers.get("Allow") if exc.headers else None
            hint = f"Erlaubte Methoden: {allowed}." if allowed else None
        return _envelope(exc.status_code, code, message, hint)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> OrjsonResponse:
        # Stacktrace nur serverseitig loggen, NIE str(exc) an den Client.
        log.error("unhandled_exception", exc_info=exc)
        return _envelope(500, "internal_error", "An unexpected error occurred")
