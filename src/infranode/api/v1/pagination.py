"""Paginierungs-Verträge (API-04): PageParams + page_params + paginate.

Opt-in Listen-Paginierung (D-07): page/limit/offset + Whitelist für sort/order.
``limit`` wird auf ``MAX_LIMIT`` gedeckelt (200 mit gedeckelter Seite statt 5xx,
Best-Practice #8): der zentrale RequestValidationError-Handler mappt auf 400, ein
überhöhtes limit soll aber NICHT als invalid_request gelten, daher wird in
``page_params`` über ``min(limit, MAX_LIMIT)`` gedeckelt statt über ``le=``
abgewiesen. Whitelist-Verstoß bei sort/order -> ``ValidationFailedError`` (400),
BEVOR roher User-String interpretiert wird (T-11-FILTER-INJ). Offset-Overflow ->
Python-Slice ergibt ``[]`` (200, nie 500, Best-Practice #8).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

from infranode.api.errors import ValidationFailedError

# Defaults + harte Obergrenze für das Seiten-Limit (Cap via Query(le=MAX_LIMIT)).
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass
class PageParams:
    """Validierte Paginierungs-Parameter eines Listen-GETs."""

    page: int
    limit: int
    offset: int
    sort: str | None
    order: str


def page_params(
    page: int = Query(1, ge=1),
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
    sort: str | None = Query(None),
    order: str = Query("asc"),
) -> PageParams:
    """FastAPI-Dependency: parst + validiert page/limit/offset/sort/order.

    ``limit`` wird über ``min(limit, MAX_LIMIT)`` gedeckelt (gedeckelte 200-Seite
    statt 5xx/4xx, Best-Practice #8), nicht über ``le=`` hart abgewiesen.
    """
    if order not in ("asc", "desc"):
        raise ValidationFailedError(
            "order muss 'asc' oder 'desc' sein.",
            hint="Erlaubt: asc, desc.",
        )
    limit = min(limit, MAX_LIMIT)
    return PageParams(page=page, limit=limit, offset=offset, sort=sort, order=order)


def paginate(items: list, p: PageParams, *, sort_whitelist: set[str]) -> list:
    """Schneidet eine Seite aus ``items`` (Whitelist-gesichert).

    sort nicht in der Whitelist -> ValidationFailedError(400). Offset-Overflow
    ergibt durch den Python-Slice eine leere Liste (200, nie 500).
    """
    if p.sort and p.sort not in sort_whitelist:
        raise ValidationFailedError(
            f"Unbekanntes sort-Feld '{p.sort}'.",
            hint=f"Erlaubt: {', '.join(sorted(sort_whitelist))}.",
        )
    start = p.offset if p.offset else (p.page - 1) * p.limit
    return items[start : start + p.limit]
