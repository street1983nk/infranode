"""DB-Timetables-Adapter ``fetch_station_departures`` (DATA-34, Live, Tier A).

Live-Abfahrtstafel je Metropolen-Hauptbahnhof (inkl. Fernverkehr) aus der offenen
DB-Timetables-API (DB API Marketplace, Produkt "Timetables", CC BY 4.0 = Tier A).
Zwei Bausteine je Bahnhof (EVA-Nummer), gemerged:

- ``/plan/{evaNo}/{YYMMDD}/{HH}``: der Sollfahrplan EINER Stunde (LOKALE Zeit
  Europe/Berlin!) als XML ``<timetable><s id><tl c n f/><dp pt pp ppth l fb/></s>``.
- ``/fchg/{evaNo}``: die aktuellen Abweichungen (Echtzeit) als XML, je ``<s id>``
  ein geaendertes ``<dp ct cp cs/>`` (ct=geaenderte Zeit, cp=geaendertes Gleis,
  cs="c"=Ausfall). Gematcht wird ueber die Stop-``id``.

Aggregiert ueber die kuratierten EVAs einer Stadt (Berlin Hbf hat z.B. zwei
Ebenen mit eigenen EVAs), dedupliziert je Stop-``id``, berechnet die Verspaetung
und liefert die naechsten Abfahrten zeitsortiert.

Sicherheit:
- T-05-08 (SSRF): Host hartkodiert; nur kuratierte EVAs (cities.STATION_EVAS, NIE
  User-Input) fliessen in die URL.
- T-08-CRED: Client-Id/Api-Key gehen NUR in die Request-Header, nie in
  Cache-Key/Response/Log.
- T-9-01 (untrusted Live-XML): Pre-Parse-Guard gegen DOCTYPE/ENTITY + Size-Cap VOR
  dem stdlib-Parse (kein XXE/Billion-Laughs). KEINE neue XML-Dependency.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` und kennt KEIN Cache/Breaker (Resilienz-Fassade).
``raise_for_status`` ist Pflicht (5xx -> STALE-ON-ERROR).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from xml.etree.ElementTree import fromstring  # noqa: S405
from zoneinfo import ZoneInfo

import httpx

# Host hartkodiert (SSRF, T-05-08): der DB-API-Marketplace-Gateway.
_BASE = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
# DB-Timetables /plan ist nach LOKALER Stunde indiziert (Bahnhofszeit).
_TZ = ZoneInfo("Europe/Berlin")
# Size-Cap (T-9-01): ein Stundenfahrplan ist klein; alles ueber dem Cap wird nicht
# geparst (DoS-Schutz beim untrusted Live-XML).
_MAX_BYTES = 8 * 1024 * 1024


def _guarded_parse(xml_bytes: bytes):
    """Parst DB-XML mit Pre-Parse-Guard + Size-Cap (T-9-01); None bei Ablehnung.

    DOCTYPE/ENTITY -> Ablehnung VOR dem Parse (kein XXE/Billion-Laughs, stdlib-only);
    leerer Body -> None (``no_data``).
    """
    if not xml_bytes or len(xml_bytes) > _MAX_BYTES:
        return None
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        return None
    try:
        return fromstring(xml_bytes)  # noqa: S314 - Guard oben, stdlib (Decision 1)
    except Exception:  # noqa: BLE001 - defektes XML -> no_data statt 500
        return None


def _parse_dt(value: str | None) -> datetime | None:
    """Parst die DB-Zeit ``YYMMDDHHmm`` zu einem (naiven) datetime oder None."""
    if not value or len(value) != 10 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%y%m%d%H%M")  # noqa: DTZ007 - relativer Diff
    except ValueError:
        return None


def _line_label(dp, category: str | None, number: str | None) -> str | None:
    """Bildet das Linien-Label (RB22 / "ICE 73" / Kategorie+Nummer) (rein)."""
    return (
        dp.get("l")
        or dp.get("fb")
        or (f"{category} {number}" if category and number else category)
    )


def _parse_board(
    root,
    *,
    changes: dict[str, dict],
    tag: str,
    place_key: str,
    path_index: int,
    station: str | None = None,
) -> list[dict]:
    """Liest ``<s>``-Stops eines /plan-Baums fuer Abfahrt (``dp``)/Ankunft (``ar``).

    ``tag`` waehlt das Ereignis (``dp``/``ar``); ``place_key`` ist der Ortsname im
    Ergebnis (``destination`` bei Abfahrt, ``origin`` bei Ankunft); ``path_index``
    waehlt das Glied im ``ppth`` (-1 = Ziel/letztes Glied, 0 = Ursprung/erstes).
    ``station`` ist der Bahnhofsname (aus dem ``<timetable station=...>``-Wurzel-
    attribut), der je Eintrag mitgefuehrt wird - so unterscheidet eine Metropolen-
    Tafel die mehreren Grossbahnhoefe (z.B. Hamburg Hbf/Dammtor/Harburg/Altona).
    Wendet die /fchg-Aenderungen (ct/cp/cs) je Stop-``id`` an. Stops ohne das
    gewaehlte Ereignis (z.B. Endbahnhof ohne Abfahrt) werden uebersprungen.
    """
    out: list[dict] = []
    for s in root.findall("s"):
        ev = s.find(tag)
        if ev is None:
            continue
        sid = s.get("id")
        tl = s.find("tl")
        category = tl.get("c") if tl is not None else None
        number = tl.get("n") if tl is not None else None
        long_distance = (tl.get("f") == "F") if tl is not None else False
        ppth = ev.get("ppth") or ""
        place = ppth.split("|")[path_index] if ppth else None
        planned = _parse_dt(ev.get("pt"))

        platform = ev.get("pp")
        delay_minutes: int | None = None
        cancelled = False
        change = changes.get(sid) if sid else None
        if change is not None:
            if change.get("cp"):
                platform = change["cp"]
            cancelled = change.get("cs") == "c"
            changed = _parse_dt(change.get("ct"))
            if changed is not None and planned is not None:
                delay_minutes = round((changed - planned).total_seconds() / 60)

        out.append(
            {
                "stop_id": sid,
                "station": station,
                "line": _line_label(ev, category, number),
                "category": category,
                "train_number": number,
                "long_distance": long_distance,
                place_key: place,
                "planned_time": planned.isoformat() if planned else None,
                "platform": platform,
                "delay_minutes": delay_minutes,
                "cancelled": cancelled,
                "_sort": planned or datetime.max,
            }
        )
    return out


def _parse_changes(root, *, tag: str) -> dict[str, dict]:
    """Baut aus /fchg die Stop-``id`` -> Aenderung-Map fuer ``tag`` (rein)."""
    changes: dict[str, dict] = {}
    for s in root.findall("s"):
        sid = s.get("id")
        ev = s.find(tag)
        if sid and ev is not None:
            changes[sid] = {"ct": ev.get("ct"), "cp": ev.get("cp"), "cs": ev.get("cs")}
    return changes


async def _get(http: httpx.AsyncClient, url: str, headers: dict) -> bytes | None:
    """Holt eine DB-Timetables-XML-Ressource; 404 -> None (Stunde ohne Daten)."""
    resp = await http.get(url, headers=headers)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


async def _fetch_board(
    http: httpx.AsyncClient,
    *,
    slug: str,
    evas: tuple[str, ...],
    client_id: str,
    api_key: str,
    now: datetime,
    tag: str,
    place_key: str,
    path_index: int,
    result_key: str,
    horizon_hours: int = 2,
    limit: int = 40,
) -> dict:
    """Holt + merged eine Live-Tafel (Abfahrt ``dp`` oder Ankunft ``ar``) der EVAs.

    Je EVA werden ``horizon_hours`` Sollfahrplan-Stunden (ab der aktuellen LOKALEN
    Stunde Europe/Berlin) plus die aktuellen Aenderungen (/fchg) geholt + gemerged,
    dedupliziert ueber die Stop-``id``, nach (geplanter) Zeit sortiert, auf
    ``limit`` gekuerzt. Rueckgabe: ``{"slug": slug, result_key: [...]}``. Leere Tafel
    -> leere Liste (-> Route mappt no_data). ``raise_for_status`` Pflicht (Fassade).
    """
    headers = {
        "DB-Client-Id": client_id,
        "DB-Api-Key": api_key,
        "Accept": "application/xml",
    }
    local = now.astimezone(_TZ)
    by_id: dict[str, dict] = {}

    for eva in evas:
        changes_bytes = await _get(http, f"{_BASE}/fchg/{eva}", headers)
        changes_root = _guarded_parse(changes_bytes) if changes_bytes else None
        changes = (
            _parse_changes(changes_root, tag=tag) if changes_root is not None else {}
        )

        for h in range(horizon_hours):
            slot = local + timedelta(hours=h)
            url = f"{_BASE}/plan/{eva}/{slot:%y%m%d}/{slot:%H}"
            plan_bytes = await _get(http, url, headers)
            root = _guarded_parse(plan_bytes) if plan_bytes else None
            if root is None:
                continue
            for entry in _parse_board(
                root, changes=changes, tag=tag, place_key=place_key,
                path_index=path_index, station=root.get("station"),
            ):
                if entry["stop_id"] and entry["stop_id"] not in by_id:
                    by_id[entry["stop_id"]] = entry

    entries = sorted(by_id.values(), key=lambda d: d["_sort"])[:limit]
    for entry in entries:
        entry.pop("_sort", None)
    return {"slug": slug, result_key: entries}


async def fetch_station_departures(
    http: httpx.AsyncClient,
    *,
    slug: str,
    evas: tuple[str, ...],
    client_id: str,
    api_key: str,
    now: datetime,
    horizon_hours: int = 2,
    limit: int = 40,
) -> dict:
    """Live-Abfahrtstafel (``<dp>``, ``destination`` = letztes ppth-Glied).

    Rueckgabe-Keys (exakt was ``map_station_departures`` erwartet): ``slug``,
    ``departures``.
    """
    return await _fetch_board(
        http, slug=slug, evas=evas, client_id=client_id, api_key=api_key, now=now,
        tag="dp", place_key="destination", path_index=-1, result_key="departures",
        horizon_hours=horizon_hours, limit=limit,
    )


async def fetch_station_arrivals(
    http: httpx.AsyncClient,
    *,
    slug: str,
    evas: tuple[str, ...],
    client_id: str,
    api_key: str,
    now: datetime,
    horizon_hours: int = 2,
    limit: int = 40,
) -> dict:
    """Live-Ankunftstafel (``<ar>``, ``origin`` = erstes ppth-Glied).

    Rueckgabe-Keys (exakt was ``map_station_arrivals`` erwartet): ``slug``,
    ``arrivals``.
    """
    return await _fetch_board(
        http, slug=slug, evas=evas, client_id=client_id, api_key=api_key, now=now,
        tag="ar", place_key="origin", path_index=0, result_key="arrivals",
        horizon_hours=horizon_hours, limit=limit,
    )
