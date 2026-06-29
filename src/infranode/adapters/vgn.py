"""Keyloser VGN/VAG-Nürnberg-Adapter ``fetch_vgn_departures`` (DATA-25, Tier A).

Direkter Zugang zum VAG-Abfahrtsmonitor mit Echtzeitprognose über die offene,
keylose Puls-API (KEIN Key, KEINE Mobilithek; CC-BY 4.0, daher Tier A):

- GET ``/dm/api/abfahrten.json/vgn/{stop_id}`` liefert je Halt
  ``Metadata.Timestamp`` (Server-"jetzt"), ``Haltestellenname`` und ``Abfahrten``
  (je Abfahrt ``Linienname``/``Richtungstext``/``AbfahrtszeitSoll``/
  ``AbfahrtszeitIst``/``Produkt``).

Rückgabe ist das raw-dict für ``map_vgn_departures`` (Form identisch zum HVV-
Geofox-Adapter, damit derselbe ``TransitDeparturePayload`` greift): ``stop_id``,
``as_of`` (Metadata.Timestamp) und ``departures`` (je Abfahrt ``line``/
``direction``/``in_minutes``/``delay_s``/``alerts``/``product``). ``in_minutes``
wird aus der ECHTZEIT-Abfahrt (``AbfahrtszeitIst``, Fallback ``AbfahrtszeitSoll``)
und ``delay_s`` aus der Differenz Ist-Soll berechnet; als "jetzt"-Bezug dient
``Metadata.Timestamp`` (KEINE Systemuhr im Adapter). Der Adapter baut KEINEN
``CanonicalRecord`` und kennt KEIN Cache/Breaker (Resilienz-Fassade).
``resp.raise_for_status()`` ist Pflicht (5xx -> STALE-ON-ERROR).

Sicherheit:
- T-05-08 (SSRF): Host in ``_BASE`` hartkodiert; ``stop_id`` ist vom Handler als
  numerisch validiert (Allowlist) und wird nur als Pfadsegment interpoliert.
"""

from __future__ import annotations

from datetime import datetime

import httpx

# Host hartkodiert (SSRF-Schutz, T-05-08).
_BASE = "https://start.vag.de/dm/api"


def _parse(ts: str | None) -> datetime | None:
    """ISO-8601 (mit tz-Offset) -> aware datetime, sonst None (rein, kein Fehler)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _departure(dep: dict, now: datetime | None) -> dict:
    """Bildet eine VAG-Abfahrt auf das schlanke departure-dict ab (rein)."""
    soll = _parse(dep.get("AbfahrtszeitSoll"))
    ist = _parse(dep.get("AbfahrtszeitIst"))
    # Countdown aus der ECHTZEIT-Prognose (Ist) berechnen, Fallback auf Soll, wenn
    # kein Ist vorliegt (Audit 2026-06-29, Finding 122: vorher immer Soll -> der
    # Countdown ignorierte die Verspätung; delay_s war gesetzt, in_minutes nicht).
    effective = ist or soll
    in_minutes = None
    if effective is not None and now is not None:
        in_minutes = max(0, round((effective - now).total_seconds() / 60))
    delay_s = None
    if soll is not None and ist is not None:
        delay_s = int((ist - soll).total_seconds())
    return {
        "line": dep.get("Linienname"),
        "direction": dep.get("Richtungstext"),
        "in_minutes": in_minutes,
        "delay_s": delay_s,
        "alerts": [],
        "product": dep.get("Produkt"),
    }


async def fetch_vgn_departures(http: httpx.AsyncClient, *, stop_id: str) -> dict:
    """Holt die Live-Abfahrten eines VGN-Halts und liefert das raw-dict.

    Rückgabe-Keys (wie ``map_vgn_departures`` erwartet): ``stop_id``, ``as_of``
    (Metadata.Timestamp, ISO-String oder None) und ``departures`` (Liste schlanker
    dicts). ``raise_for_status`` ist Pflicht (5xx -> Fassade STALE-ON-ERROR).
    """
    url = f"{_BASE}/abfahrten.json/vgn/{stop_id}"
    resp = await http.get(url)
    resp.raise_for_status()
    body = resp.json()

    as_of = (body.get("Metadata") or {}).get("Timestamp")
    now = _parse(as_of)
    departures = [_departure(dep, now) for dep in body.get("Abfahrten", []) or []]
    return {"stop_id": stop_id, "as_of": as_of, "departures": departures}
