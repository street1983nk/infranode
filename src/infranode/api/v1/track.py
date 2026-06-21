"""Tracking-Beacon: cache-freier Endpunkt, der den Erstkontakt-Push ausloest.

Die Daten-Endpunkte (/api/v1/cities/...) sind Cloudflare-edge-gecacht
(``respect_origin`` + ``max-age``); ein gecachter Treffer (cf-cache-status HIT)
erreicht das Origin NICHT, daher feuert die ``note_first_seen``-Middleware fuer
einen gecachten Daten-Abruf nicht -> ein neuer Dev, der nur gecachte Endpunkte
zieht, bliebe ungemeldet.

Dieser Beacon ist bewusst ``no-store`` (Cloudflare cacht ihn nie): jeder Aufruf
erreicht das Origin, die Telemetrie-Middleware sieht den Client und schickt beim
ERSTEN Mal je IP genau einen ntfy-Erstkontakt-Push (idempotent ueber das
Redis-seen-Set). Die Doku-Seite ruft ihn beim "Try it" zusaetzlich (fire-and-forget)
auf. Antwortet absichtlich leer (204), traegt also keine Last/keine Daten.

Sicherheit: rein lesend, kein Query-/Body-Input, Host fix; laeuft hinter denselben
Rate-Limits/AbuseGuard wie der Rest (kein neuer Angriffsvektor).
"""

from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter()


@router.get("/track", include_in_schema=False)
async def track() -> Response:
    """Cache-freier Erstkontakt-Beacon (204). note_first_seen feuert in der Middleware.

    ``Cache-Control: no-store`` haelt Cloudflare/Browser davon ab, den Beacon zu
    cachen, damit jeder Aufruf das Origin erreicht und der Erstkontakt-Push (pro IP
    einmalig) zuverlaessig ausgeloest wird. ``include_in_schema=False``: interner
    Telemetrie-Pfad, kein Teil des oeffentlichen Datenvertrags.
    """
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
