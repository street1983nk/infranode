"""DB-Timetables-Adapter ``fetch_station_departures`` (DATA-34, Live, Tier A).

Live-Abfahrtstafel je Stadt-Hauptbahnhof (alle Gattungen) aus der offenen
DB-Timetables-API (DB API Marketplace, Produkt "Timetables", CC BY 4.0 = Tier A).
Zwei Bausteine je Bahnhof (EVA-Nummer), gemerged:

- ``/plan/{evaNo}/{YYMMDD}/{HH}``: der Sollfahrplan EINER Stunde (LOKALE Zeit
  Europe/Berlin!) als XML ``<timetable><s id><tl c n f/><dp pt pp ppth l fb/></s>``.
- ``/fchg/{evaNo}``: die aktuellen Abweichungen (Echtzeit) als XML, je ``<s id>``
  ein geändertes ``<dp ct cp cs/>`` (ct=geaenderte Zeit, cp=geaendertes Gleis,
  cs="c"=Ausfall). Gematcht wird über die Stop-``id``.

Aggregiert über die aufgelösten EVAs einer Stadt (kuratierte Override-Liste
oder aus dem StaDa-Katalog abgeleitet; Berlin Hbf hat z.B. zwei Ebenen mit eigenen
EVAs), dedupliziert je Stop-``id``, berechnet die Verspätung und liefert die
nächsten Abfahrten zeitsortiert.

Sicherheit:
- T-05-08 (SSRF): Host hartkodiert; nur kuratierte ODER aus dem StaDa-Katalog
  abgeleitete EVAs (cities._resolve_city_station_evas, NIE roher User-Input)
  fließen in die URL.
- T-08-CRED: Client-Id/Api-Key gehen NUR in die Request-Header, nie in
  Cache-Key/Response/Log.
- T-9-01 (untrusted Live-XML): Pre-Parse-Guard gegen DOCTYPE/ENTITY + Size-Cap VOR
  dem stdlib-Parse (kein XXE/Billion-Laughs). KEINE neue XML-Dependency.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` und kennt KEIN Cache/Breaker (Resilienz-Fassade).
``raise_for_status`` ist Pflicht (5xx -> STALE-ON-ERROR), aber JE EVA: eine
kaputte EVA wird uebersprungen, der Fehler fliegt erst weiter, wenn ALLE EVAs
scheitern (siehe ``_fetch_board``, Vorfall 2026-08-24).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from xml.etree.ElementTree import fromstring
from zoneinfo import ZoneInfo

import httpx
import structlog

log = structlog.get_logger()

# Host hartkodiert (SSRF, T-05-08): der DB-API-Marketplace-Gateway.
_BASE = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
# DB-Timetables /plan ist nach LOKALER Stunde indiziert (Bahnhofszeit).
_TZ = ZoneInfo("Europe/Berlin")
# Size-Cap (T-9-01): ein Stundenfahrplan ist klein; alles über dem Cap wird nicht
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
    except Exception:
        return None


def _parse_dt(value: str | None) -> datetime | None:
    """Parst die DB-Zeit ``YYMMDDHHmm`` zu einem zonenbehafteten datetime oder None.

    DB-Timetables liefert Bahnhofszeit (Europe/Berlin) OHNE Zonenangabe. Der
    Zeitstempel bekommt diese Zone deshalb explizit angeheftet, damit die
    ausgelieferte ISO-Zeit eindeutig ist ("2026-07-25T10:01:00+02:00") und
    Clients sie nicht als UTC missdeuten. Vor 2026-07-25 war die Ausgabe naiv.
    """
    if not value or len(value) != 10 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%y%m%d%H%M").replace(tzinfo=_TZ)
    except ValueError:
        return None


def _parse_messages(elem) -> list[dict]:
    """Liest die ``<m>``-Störungs-/Hinweismeldungen unter ``elem`` (rein).

    DB-Timetables trägt Störungen, Verspätungsgründe und Hinweise als ``<m>``-
    Elemente (Attribute: ``t`` Typ [h=HIM/Stoerung, q=Qualitaet/Grund], ``c`` Code,
    ``cat`` Kategorietext, ``ts`` Zeitstempel ``YYMMDDHHmm``). Je Meldung ein
    schlankes dict; leere Liste, wenn keine vorhanden. ``elem`` kann ``None`` sein.
    """
    if elem is None:
        return []
    out: list[dict] = []
    for m in elem.findall("m"):
        ts = _parse_dt(m.get("ts"))
        out.append(
            {
                "type": m.get("t"),
                "code": m.get("c"),
                "category": m.get("cat"),
                "timestamp": ts.isoformat() if ts else None,
            }
        )
    return out


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
    """Liest ``<s>``-Stops eines /plan-Baums für Abfahrt (``dp``)/Ankunft (``ar``).

    ``tag`` wählt das Ereignis (``dp``/``ar``); ``place_key`` ist der Ortsname im
    Ergebnis (``destination`` bei Abfahrt, ``origin`` bei Ankunft); ``path_index``
    wählt das Glied im ``ppth`` (-1 = Ziel/letztes Glied, 0 = Ursprung/erstes).
    ``station`` ist der Bahnhofsname (aus dem ``<timetable station=...>``-Wurzel-
    attribut), der je Eintrag mitgeführt wird - so unterscheidet eine Metropolen-
    Tafel die mehreren Großbahnhöfe (z.B. Hamburg Hbf/Dammtor/Harburg/Altona).
    Wendet die /fchg-Änderungen (ct/cp/cs) je Stop-``id`` an. Stops ohne das
    gewählte Ereignis (z.B. Endbahnhof ohne Abfahrt) werden übersprungen.
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
        # Stoerungen/Meldungen aus Soll (Stop + Ereignis) lesen; Echtzeit-
        # Meldungen aus /fchg kommen unten über den change-Eintrag dazu.
        messages = _parse_messages(s) + _parse_messages(ev)
        change = changes.get(sid) if sid else None
        if change is not None:
            if change.get("cp"):
                platform = change["cp"]
            cancelled = change.get("cs") == "c"
            changed = _parse_dt(change.get("ct"))
            if changed is not None and planned is not None:
                delay_minutes = round((changed - planned).total_seconds() / 60)
            messages = messages + (change.get("messages") or [])

        out.append(
            {
                # Kanonischer Name (Konsistenz-Audit 2026-07-25): die DB-``id``
                # identifiziert EINEN HALT EINER ZUGFAHRT, nicht eine Haltestelle.
                # Der fruehere Name ``stop_id`` kollidierte mit der
                # Haltestellen-ID von /live/{city}/transit/departures (DELFI
                # "de:<AGS>:<id>") und fuehrte dort taeglich zu 400ern; er war
                # seit 2026-08-01 abgekuendigt und ist zum 2026-08-31 entfernt.
                "trip_stop_id": sid,
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
                "messages": messages,
                # Sortier-Hilfsfeld: seit planned zonenbehaftet ist, muss auch der
                # Fallback aware sein (naiv vs. aware waere ein TypeError).
                "_sort": planned or datetime.max.replace(tzinfo=_TZ),
            }
        )
    return out


def _parse_changes(root, *, tag: str) -> dict[str, dict]:
    """Baut aus /fchg die Stop-``id`` -> Änderung-Map für ``tag`` (rein).

    Enthält neben Zeit/Gleis/Ausfall (ct/cp/cs) auch die Echtzeit-Störungs-/
    Hinweismeldungen (``<m>`` unter Stop und Ereignis), die im Board je Eintrag
    mit den Soll-Meldungen zusammengeführt werden.
    """
    changes: dict[str, dict] = {}
    for s in root.findall("s"):
        sid = s.get("id")
        ev = s.find(tag)
        if sid and ev is not None:
            changes[sid] = {
                "ct": ev.get("ct"),
                "cp": ev.get("cp"),
                "cs": ev.get("cs"),
                "messages": _parse_messages(s) + _parse_messages(ev),
            }
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
    Stunde Europe/Berlin) plus die aktuellen Änderungen (/fchg) geholt + gemerged,
    dedupliziert über die Stop-``id``, nach (geplanter) Zeit sortiert, auf
    ``limit`` gekürzt. Rueckgabe: ``{"slug": slug, result_key: [...]}``. Leere Tafel
    -> leere Liste (-> Route mappt no_data).

    Fehlertoleranz JE EVA (Vorfall 2026-08-24, 06:59-07:24 UTC: 87 x 503 auf
    /cities/berlin/station-departures + -arrivals): /fchg/8098160 (Berlin Hbf,
    tiefe Ebene) lieferte ~25 Minuten lang 502/503, und weil die Schleife den
    Fehler durchreichte, starb die GESAMTE Stadt-Tafel, obwohl die uebrigen
    Berliner EVAs sauber antworteten. Ein Bahnhof darf die Tafel der anderen
    nicht mitnehmen: ein httpx-Fehler EINER EVA wird uebersprungen und geloggt,
    die Tafel wird aus den gesunden EVAs gebaut. Nur wenn ALLE EVAs scheitern,
    fliegt der letzte Fehler weiter -> Breaker zaehlt, Route antwortet 503
    (DX-06 bleibt: toter Upstream ohne Cache = ehrlicher 503). Es wird dabei NIE
    ein alter Wert ausgeliefert, nur weniger frische Bahnhoefe.
    """
    headers = {
        "DB-Client-Id": client_id,
        "DB-Api-Key": api_key,
        "Accept": "application/xml",
    }
    local = now.astimezone(_TZ)
    by_id: dict[str, dict] = {}
    last_error: Exception | None = None
    failed = 0

    for eva in evas:
        try:
            changes_bytes = await _get(http, f"{_BASE}/fchg/{eva}", headers)
            changes_root = _guarded_parse(changes_bytes) if changes_bytes else None
            changes = (
                _parse_changes(changes_root, tag=tag)
                if changes_root is not None
                else {}
            )

            for h in range(horizon_hours):
                slot = local + timedelta(hours=h)
                url = f"{_BASE}/plan/{eva}/{slot:%y%m%d}/{slot:%H}"
                plan_bytes = await _get(http, url, headers)
                root = _guarded_parse(plan_bytes) if plan_bytes else None
                if root is None:
                    continue
                for entry in _parse_board(
                    root,
                    changes=changes,
                    tag=tag,
                    place_key=place_key,
                    path_index=path_index,
                    station=root.get("station"),
                ):
                    if entry["trip_stop_id"] and entry["trip_stop_id"] not in by_id:
                        by_id[entry["trip_stop_id"]] = entry
        except httpx.HTTPError as exc:
            # httpx.HTTPError deckt HTTPStatusError (5xx aus _get) UND die
            # Transportfehler (ReadTimeout/ConnectError) ab. Kein Key im Log
            # (T-08-CRED), nur EVA + Fehlerklasse.
            failed += 1
            last_error = exc
            log.info(
                "db_timetables_eva_skipped",
                slug=slug,
                eva=eva,
                tag=tag,
                error=type(exc).__name__,
            )

    if last_error is not None and failed == len(evas):
        # Alle Bahnhoefe tot -> ehrlicher Fehler an die Resilienz-Fassade.
        raise last_error

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

    Rückgabe-Keys (exakt was ``map_station_departures`` erwartet): ``slug``,
    ``departures``.
    """
    return await _fetch_board(
        http,
        slug=slug,
        evas=evas,
        client_id=client_id,
        api_key=api_key,
        now=now,
        tag="dp",
        place_key="destination",
        path_index=-1,
        result_key="departures",
        horizon_hours=horizon_hours,
        limit=limit,
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

    Rückgabe-Keys (exakt was ``map_station_arrivals`` erwartet): ``slug``,
    ``arrivals``.
    """
    return await _fetch_board(
        http,
        slug=slug,
        evas=evas,
        client_id=client_id,
        api_key=api_key,
        now=now,
        tag="ar",
        place_key="origin",
        path_index=0,
        result_key="arrivals",
        horizon_hours=horizon_hours,
        limit=limit,
    )
