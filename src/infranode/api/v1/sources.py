"""Source-Status-Route /sources (API-03).

Listet je bekannter Upstream-Quelle ihren ``enabled``-Zustand (aus den
``enable_*``-Settings) und den Circuit-Breaker-State (CLOSED/OPEN/HALF_OPEN aus
der prozessweiten ``app.state.breakers``-Registry). So sehen Clients und Agenten
auf einen Blick, welche Quelle aktiv ist und ob ihr Breaker getrippt hat
(Graceful-Degradation-Transparenz).

Der Breaker wird über die bestehende ``BreakerRegistry`` lazy angelegt; ein noch
nie aufgerufener Breaker meldet seinen Default-State CLOSED. KEINE eigene
HTTPException/try-except mit Detail-Leak: der zentrale Handler bleibt zuständig.
"""

from __future__ import annotations

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Depends, Request, Response

from infranode.api.v1.pagination import PageParams, page_params, paginate
from infranode.api.v1.ratelimit import ANON_LIMIT, limiter
from infranode.registry.source_specs import KNOWN_SOURCES as _KNOWN_SOURCES
from infranode.registry.source_specs import SOURCE_LICENSE

router = APIRouter()

# Whitelist der sortier-/filterbaren Felder für /sources (T-11-FILTER-INJ): nur
# diese Feldnamen sind als sort erlaubt, ein unbekanntes Feld -> 400, BEVOR roher
# User-String interpretiert wird (nie in eine Query/einen Cache-Key interpoliert).
_SOURCES_SORT_WHITELIST = {"source", "enabled", "license"}

# _KNOWN_SOURCES (Reihenfolge = öffentliche /sources-Reihenfolge) und
# SOURCE_LICENSE (Lizenz + wortgenaue Attribution, VERBATIM aus
# DATA-LICENSES.md, fail-closed via tests/unit/test_source_license_map.py)
# kommen jetzt aus der deklarativen Quellen-Registry (registry/source_specs.py),
# damit eine neue Quelle nur EINEN Eintrag dort braucht statt vieler verstreuter
# Stellen. Beide Namen sind oben importiert (Rückwärts-Kompatibilität).


@router.get("/sources")
@limiter.limit(ANON_LIMIT)
async def sources(
    request: Request,
    response: Response,
    page: PageParams = Depends(page_params),  # noqa: B008 - FastAPI-Dependency-Idiom
) -> dict:
    """Listet je Quelle enabled (aus den Settings) + Breaker-State (API-03).

    Rate-limitiert (API-06): @limiter.limit unter @router.get, ``request`` ist
    Pflicht-Param (Pitfall 4). ``response`` ist Pflicht, damit slowapi die
    Standard-RateLimit-Header auf die Erfolgsantwort injizieren kann; bei
    Überschreitung greift der 429-Envelope-Handler.

    Keylos/offen: kein API-Key nötig, das IP-Limit (ANON_LIMIT) gilt für alle.

    Paginiert (API-04, REST-Best-Practice #3/#8): ``Depends(page_params)`` liest
    page/limit/offset/sort/order; ``paginate`` schneidet die Seite Whitelist-
    gesichert (unbekanntes sort -> 400, T-11-FILTER-INJ) und liefert bei Offset-
    Overflow eine leere Liste mit 200 (nie 500). ``limit > MAX_LIMIT`` wird über
    ``Query(le=MAX_LIMIT)`` als 422 abgewiesen.
    """
    settings = request.app.state.settings
    breakers = request.app.state.breakers

    data = [
        {
            "source": name,
            "enabled": bool(getattr(settings, f"enable_{name}", False)),
            "breaker_state": breakers.get(name).state.value,
            "license": SOURCE_LICENSE.get(name, {}).get("license_id"),
            "attribution": SOURCE_LICENSE.get(name, {}).get("attribution"),
        }
        for name in _KNOWN_SOURCES
    ]

    # Whitelist-gesicherte Sortierung VOR dem Slice (sort nur aus der Whitelist,
    # sonst 400 in paginate). order steuert die Richtung, beides ist validiert.
    if page.sort:
        data.sort(
            key=lambda row: (row.get(page.sort) is None, row.get(page.sort)),
            reverse=(page.order == "desc"),
        )

    page_items = paginate(data, page, sort_whitelist=_SOURCES_SORT_WHITELIST)
    return {
        "data": page_items,
        "meta": {
            "correlation_id": correlation_id.get(),
            "page": page.page,
            "limit": page.limit,
            "offset": page.offset,
            "total": len(data),
        },
    }
