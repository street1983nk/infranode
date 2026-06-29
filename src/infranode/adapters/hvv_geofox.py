"""HVV-Geofox-GTI-Adapter: Live-ÖPNV-Abfahrten für Hamburg (DATA-24, Live, Tier C).

Echtzeit-Abfahrten je Halt aus der HVV-Geofox-GTI-API (Geofox Thin Interface).
Im Unterschied zur statischen ``/cities/{slug}/transit`` (DELFI/HVV-GTFS-Stops,
Batch) ist dies ein LIVE-Request-Pfad: minutenfrische Abfahrten inkl. Verspätung
und Linien-Störungshinweisen, nur für Hamburg (Geofox deckt ausschließlich den
HVV-Raum ab).

Auth (verifiziert gegen die bestehende Geofox-Integration, school-kiosk):
- Base ``https://gti.geofox.de/gti/public`` (Host hartkodiert: SSRF-Schutz).
- HMAC-SHA1 über den EXAKTEN JSON-Request-Body, Secret ist der Geofox-Key (NICHT
  der User). Signatur base64. Header: ``geofox-auth-type: HmacSHA1``,
  ``geofox-auth-user: <user>``, ``geofox-auth-signature: <sig>``.
- Credentials gelangen nur in Header/Body, NIE in Cache-Key/Response/Log.

Zwei Calls: ``checkName`` (Stationsname -> Geofox-Station-ID ``Master:...``), dann
``departureList`` (Abfahrtstafel ab jetzt). Findet ``checkName`` keine Station
oder liefert ``departureList`` keine Abfahrten, gibt der Adapter ein ehrliches
leeres Ergebnis (die Route mappt das auf ``no_data``); er wirft NICHT für leere
Resultate. HTTP-/Netzfehler werden durchgereicht (die Resilienz-Fassade behandelt
Breaker/STALE-ON-ERROR). Reine Funktion: KEIN CanonicalRecord (das macht der
Mapper), KEIN Cache/Breaker (Fassade), KEIN Archiv (Tier C, Live-only).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx

_BASE = "https://gti.geofox.de/gti/public"
# GTI-API-Version (bewährt gegen die produktive Geofox-Integration).
_GTI_VERSION = 36
_SERVICE_TYPES = ("BUS", "U", "S", "UBAHN", "SBAHN", "AKN", "FERRY")


def _last_sunday(year: int, month: int) -> int:
    """Tag (1..31) des letzten Sonntags im Monat. Reine Arithmetik."""
    day = 31
    while True:
        try:
            wd = datetime(year, month, day).weekday()  # Mo=0 .. So=6
            break
        except ValueError:
            day -= 1
    return day - ((wd + 1) % 7)


def _berlin_local(now: datetime) -> datetime:
    """Konvertiert aware-UTC nach Europe/Berlin (MEZ/MESZ) ohne tzdata-Dependency.

    Geofox erwartet lokale HVV-Zeit. Decision 1 verbietet neue Dependencies und ein
    Modul-Level ``ZoneInfo`` würde ohne tzdata den App-Import reißen; daher die
    DE-DST-Regel arithmetisch: MESZ (UTC+2) vom letzten Sonntag März 01:00 UTC bis
    zum letzten Sonntag Oktober 01:00 UTC, sonst MEZ (UTC+1). Der Rückgabewert
    dient nur der ``date``/``time``-Formatierung (lokale Wanduhrzeit).
    """
    u = now.astimezone(UTC)
    start = datetime(u.year, 3, _last_sunday(u.year, 3), 1, tzinfo=UTC)
    end = datetime(u.year, 10, _last_sunday(u.year, 10), 1, tzinfo=UTC)
    offset = 2 if start <= u < end else 1
    return u + timedelta(hours=offset)


def _sign(payload: str, key: str) -> str:
    """HMAC-SHA1 des Body-Strings mit dem Geofox-Key, base64.

    SHA1 ist von der Geofox-GTI-API vorgeschrieben (kein eigener Sicherheits-
    Hash): HMAC-SHA1 ist hier korrekt und kein schwacher-Hash-Befund.
    """
    digest = hmac.new(
        key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha1,  # noqa: S324
    ).digest()
    return base64.b64encode(digest).decode("ascii")


async def _geofox(
    http: httpx.AsyncClient, endpoint: str, body: dict, *, user: str, key: str
) -> dict:
    """Signierter POST gegen einen GTI-Endpunkt; gibt die JSON-Antwort zurück."""
    payload = json.dumps(body, separators=(",", ":"))
    resp = await http.post(
        f"{_BASE}/{endpoint}",
        content=payload.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "geofox-auth-type": "HmacSHA1",
            "geofox-auth-user": user,
            "geofox-auth-signature": _sign(payload, key),
        },
    )
    resp.raise_for_status()
    return resp.json()


def _norm_departures(raw: dict) -> list[dict]:
    """Formt die Geofox-``departures`` in schlanke, stabile dicts um.

    Je Abfahrt: ``line`` (z.B. "S1"), ``direction`` (Ziel), ``in_minutes`` (Soll-
    Offset ab jetzt), ``delay_s`` (Verspätung in Sekunden, None falls unbekannt),
    ``alerts`` (deduplizierte Störungstexte der Abfahrt). Defensiv gegen fehlende
    Felder (Live-Realität).
    """
    out: list[dict] = []
    for dep in raw.get("departures", []) or []:
        if not isinstance(dep, dict):
            continue
        line = dep.get("line") or {}
        alerts: list[str] = []
        for attr in dep.get("attributes", []) or []:
            text = str((attr or {}).get("value", "")).strip()
            if text and text != "Unbekannte Ursache" and text not in alerts:
                alerts.append(text[:500])
        delay = dep.get("delay")
        delay_s = int(delay) if isinstance(delay, int | float) else None
        time_offset = dep.get("timeOffset")
        # Audit-Rerun (2026-06-29): in_minutes aus IST = Soll-Offset + Verspätung
        # (analog VGN-Fix). Geofox' timeOffset ist der SOLL-Abstand in Minuten;
        # ohne Einrechnung der Verspätung zeigt eine verspätete Abfahrt einen
        # falschen negativen Countdown (z.B. -58 statt +12 min).
        if isinstance(time_offset, int | float):
            in_minutes: int | None = int(time_offset) + (
                round(delay_s / 60) if delay_s else 0
            )
        else:
            in_minutes = time_offset
        out.append(
            {
                "line": line.get("name"),
                "direction": line.get("direction"),
                "in_minutes": in_minutes,
                "delay_s": delay_s,
                "alerts": alerts,
            }
        )
    return out


async def fetch_hvv_departures(
    http: httpx.AsyncClient,
    *,
    slug: str,
    station: str,
    user: str,
    key: str,
    now: datetime,
) -> dict:
    """Holt Live-Abfahrten der HVV-Station ``station`` als raw-dict.

    Schritt 1 ``checkName``: löst den Stationsnamen auf die erste passende
    Geofox-STATION (``Master:...``) auf. Keine Station gefunden ->
    ``{"slug", "station": None, "departures": []}`` (kein Wurf, Route -> no_data).
    Schritt 2 ``departureList``: Abfahrtstafel ab ``now`` (nach Europe/Berlin
    konvertiert), Echtzeit aktiviert. Rückgabe-Keys (genau das, was
    ``map_hvv_departures`` erwartet): ``slug``, ``stop_id``, ``stop_name``,
    ``departures`` (Liste schlanker dicts), ``timestamp`` (None; observed_at folgt
    aus der Live-Abfrage selbst).
    """
    found = await _geofox(
        http,
        "checkName",
        {
            "theName": {"name": station, "type": "STATION"},
            "maxList": 1,
            "language": "de",
            "version": 1,
        },
        user=user,
        key=key,
    )
    results = [
        r
        for r in (found.get("results") or [])
        if isinstance(r, dict) and r.get("type") == "STATION" and r.get("id")
    ]
    if not results:
        return {"slug": slug, "stop_id": None, "stop_name": None, "departures": []}

    st = results[0]
    local = _berlin_local(now)
    raw = await _geofox(
        http,
        "departureList",
        {
            "station": {"id": st["id"], "name": st.get("name"), "type": "STATION"},
            "time": {
                "date": local.strftime("%d.%m.%Y"),
                "time": local.strftime("%H:%M"),
            },
            "maxList": 20,
            "maxTimeOffset": 120,
            "useRealtime": True,
            "language": "de",
            "version": _GTI_VERSION,
            "serviceTypeList": list(_SERVICE_TYPES),
        },
        user=user,
        key=key,
    )
    return {
        "slug": slug,
        "stop_id": st["id"],
        "stop_name": st.get("name"),
        "departures": _norm_departures(raw),
        "timestamp": None,
    }
