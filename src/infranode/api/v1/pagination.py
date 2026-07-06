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


def _parse_int_param(raw: str | None, *, name: str, minimum: int, default: int) -> int:
    """Parst einen rohen Query-String zu einem int mit Mindestwert (oder Default).

    ``None`` (Parameter nicht gesetzt) -> ``default``. Nicht-numerisch oder unter
    ``minimum`` -> ``ValidationFailedError`` (400 invalid_request), BEVOR der Wert
    in einen Slice-Index gelangt (T-chc-03). Kein roher String erreicht die
    Slice-Semantik.
    """
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationFailedError(
            f"Ungueltiger Wert fuer '{name}': '{raw}'.",
            hint=f"'{name}' muss eine ganze Zahl >= {minimum} sein.",
        ) from None
    if value < minimum:
        raise ValidationFailedError(
            f"Ungueltiger Wert fuer '{name}': {value}.",
            hint=f"'{name}' muss eine ganze Zahl >= {minimum} sein.",
        )
    return value


def parse_page_params(request, *, default_limit: int = DEFAULT_LIMIT) -> PageParams:
    """Parst limit/offset (und page) aus ``request.query_params`` (ohne Depends).

    Gegenstueck zu ``page_params`` fuer Routen/Helper, in denen kein FastAPI-
    ``Depends`` greift (z.B. der geteilte OSM-Helper und die Store-Routen, die die
    Query selbst lesen). Spiegelt die Validierung von ``page_params``:
    ``limit`` >= 1 (Default ``default_limit``, pro Endpunkt konfigurierbar),
    ``offset`` >= 0, ``page`` >= 1; nicht-numerisch/zu klein -> 400 invalid_request;
    ``limit`` wird ueber ``min(limit, MAX_LIMIT)`` gedeckelt (gedeckelte Seite statt
    Fehler, Best-Practice #8).

    ``sort``/``order`` werden fuer diese Datenart-Listen BEWUSST nicht angeboten:
    die zugrunde liegenden Listen tragen keine zugesicherte, stabile serverseitige
    Sortier-Ordnung, daher waere ein ``sort``-Versprechen unehrlich. Sie bleiben
    fix ``None`` / ``"asc"``, sodass ``paginate_envelope`` rein ueber offset/limit
    schneidet.
    """
    qp = request.query_params
    limit = _parse_int_param(
        qp.get("limit"), name="limit", minimum=1, default=default_limit
    )
    offset = _parse_int_param(qp.get("offset"), name="offset", minimum=0, default=0)
    page = _parse_int_param(qp.get("page"), name="page", minimum=1, default=1)
    limit = min(limit, MAX_LIMIT)
    return PageParams(page=page, limit=limit, offset=offset, sort=None, order="asc")


def paginate_envelope(
    data: dict,
    meta: dict,
    p: PageParams,
    *,
    list_key: str,
    delivered_count_field: str | None = None,
) -> None:
    """Begrenzt eine Envelope-Liste EHRLICH und weist den Ausschnitt in meta aus.

    Schneidet ``data["payload"][list_key]`` auf die Seite ``[offset:offset+limit]``
    (Offset-Overflow -> leere Liste, KEIN Fehler, Best-Practice #8) und setzt
    ``meta["pagination"]`` = total/returned/limit/offset/truncated (keine stille
    Kappung, CLAUDE.md "No silent caps"). Item-Werte werden NICHT umgeschrieben, nur
    die Listenlaenge aendert sich (T-chc: nur Ausschnitt/Weglassen).

    ``delivered_count_field`` (nur PoiPayload-Fall): ist es gesetzt, wird
    ``payload[delivered_count_field]`` auf die ausgelieferte Seitenlaenge gesetzt
    (die PoiPayload-Semantik: ``count`` = ausgelieferte Items) und, falls ein
    ``truncated``-Feld existiert, auf ``(total > returned) or bisheriger Wert``
    aktualisiert; ``total_available`` bleibt unangetastet (echter Gesamtbestand).
    Ist ``delivered_count_field`` ``None`` (energy/charging/events), bleiben die
    aggregierten Kennzahlen (count/by_type/total_power_kw) UNBERUEHRT: der Payload
    beschreibt weiter den vollen Snapshot, ``meta.pagination`` die ausgelieferte
    Seite (Auflage 2, ehrliche Trennung Aggregat vs. Seite).

    Defensiv: fehlt ``payload`` oder ``list_key`` oder ist kein ``list`` -> no-op.
    """
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return
    items = payload.get(list_key)
    if not isinstance(items, list):
        return

    total = len(items)
    page = items[p.offset : p.offset + p.limit]
    payload[list_key] = page
    returned = len(page)

    meta["pagination"] = {
        "total": total,
        "returned": returned,
        "limit": p.limit,
        "offset": p.offset,
        "truncated": p.offset + returned < total,
    }

    if delivered_count_field is not None:
        payload[delivered_count_field] = returned
        if "truncated" in payload:
            payload["truncated"] = (total > returned) or bool(payload.get("truncated"))
