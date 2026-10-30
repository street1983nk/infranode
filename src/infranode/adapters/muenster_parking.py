"""Keyloser Münster-Parkleitsystem-Adapter ``fetch_muenster_parking`` (PARK-06, Tier A).

Direkter Zugang zur offenen Parkleitsystem-Belegung der Stadt Münster (KEIN
Mobilithek-mTLS, KEIN Key). Seit dem DKAN-Relaunch des Open-Data-Portals
(Oktober 2026) liefert die alte Route ``/api/records/{dataset}`` 404; die
offizielle Ressource des Datensatzes "Parkleitsystem Parkhausbelegung aktuell"
ist die XML-Datei ``PLS-INet.xml`` des Tiefbauamts (verifiziert 2026-10-20).

Format (ISO-8859-1, ~4 KB): ``<parkhaeuser>`` mit je ``<parkhaus>``
(bezeichnung/gesamt/frei/status/zeitstempel). Der Zeitstempel ist deutsch
("20.10.2026 13:06", lokale Zeit) und wird nach ISO 8601 mit Europe/Berlin-Offset
überführt. Die Quelle liefert keine IDs, Koordinaten oder Adressen: ``facility_id``
ist die Bezeichnung, ``lat``/``lon``/``address`` sind None.

Rückgabe ist das raw-dict, das ``map_muenster_parking`` erwartet: ``slug`` =
"muenster", ``as_of`` (jüngster ``zeitstempel`` aller Einrichtungen) und
``facilities`` (je Einrichtung ein schlankes dict im einheitlichen Feldschema).
Der Adapter baut KEINEN ``CanonicalRecord`` und kennt KEIN Cache/Breaker (das
liefert die Resilienz-Fassade). ``resp.raise_for_status()`` ist Pflicht, damit ein
5xx als ``httpx.HTTPError`` durchschlägt und der STALE-ON-ERROR-Pfad greift.

Lizenz: Datenlizenz Deutschland Namensnennung 2.0 (DL-DE/BY 2.0), Attribution
"Stadt Münster" = Tier A (unverändert, gleiche Datensatz-Ressource). Siehe
``mappers/stadt_parking.map_muenster_parking``.

Sicherheit:
- T-25-08 (SSRF): Host + Pfad sind in ``_URL`` hartkodiert; es fließt kein
  User-Input in die URL.
- T-25-09 (DoS): ``raise_for_status`` + Fassade-Timeout; ``_MAX_BYTES`` deckelt
  die Antwortgröße (ersetzt den früheren ``limit``-Query-Parameter).
- T-25-12 (XXE): Pre-Parse-Guard (DOCTYPE/ENTITY) vor dem stdlib-Parse (Muster
  ``hamburg_parking``).
"""

from __future__ import annotations

import re
from datetime import datetime
from xml.etree.ElementTree import Element, fromstring
from zoneinfo import ZoneInfo

import httpx

# Host + Pfad hartkodiert (SSRF-Schutz, T-25-08).
_URL = "https://www.stadt-muenster.de/ms/tiefbauamt/pls/PLS-INet.xml"
# Size-Cap (T-25-09): die Datei hat ~4 KB; 1 MiB ist großzügige Reserve.
_MAX_BYTES = 1024 * 1024
# Deutscher Zeitstempel "DD.MM.YYYY HH:MM" (Sekunden optional).
_DT_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?")
_TZ = ZoneInfo("Europe/Berlin")


def _occupancy(free: int | None, capacity: int | None) -> float | None:
    """Auslastung in PROZENT (0..100) aus free/capacity (rein); unplausibel -> None.

    Wortgleich zu ``adapters/dortmund_parking._occupancy`` (Einheitlichkeit, eine
    Nachkommastelle), damit alle Parken-Quellen occupancy identisch interpretierbar
    liefern (Dortmund-Audit-Lehre 2026-06-29).
    """
    if not isinstance(free, int) or not isinstance(capacity, int) or capacity <= 0:
        return None
    used = capacity - free
    if used < 0:
        return None
    return round(used / capacity * 100, 1)


def _to_int(value: str | None) -> int | None:
    """Parst eine Ganzzahl aus dem XML-Text (rein) oder None."""
    if value is None:
        return None
    value = value.strip()
    return int(value) if value.lstrip("-").isdigit() else None


def _iso(value: str | None) -> str | None:
    """Deutscher Zeitstempel (lokale Zeit) -> ISO 8601 mit Berlin-Offset, sonst None."""
    if not value:
        return None
    m = _DT_RE.search(value)
    if not m:
        return None
    day, month, year, hour, minute, second = m.groups()
    try:
        dt = datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            tzinfo=_TZ,
        )
    except ValueError:
        return None
    return dt.isoformat()


def _text(node: Element, tag: str) -> str | None:
    """Getrimmter Text des Kind-Elements ``tag`` (rein) oder None."""
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _facility(node: Element) -> dict:
    """Bildet ein ``<parkhaus>``-Element auf ein schlankes facility-dict ab (rein).

    Sentinel-/Plausibilitäts-Regeln wie dortmund_parking: ``free < 0`` oder
    ``free > total`` -> ``free = None`` (occupancy dann ebenfalls None).
    """
    name = _text(node, "bezeichnung")
    total = _to_int(_text(node, "gesamt"))
    free = _to_int(_text(node, "frei"))
    if isinstance(free, int) and (
        free < 0 or (isinstance(total, int) and free > total)
    ):
        free = None
    return {
        "facility_id": name,
        "name": name,
        "lat": None,
        "lon": None,
        "free": free,
        "total": total,
        "occupancy": _occupancy(free, total),
        "state": _text(node, "status"),
        "observed_at": _iso(_text(node, "zeitstempel")),
        "address": None,
    }


def _parse(xml_bytes: bytes) -> list[dict]:
    """Parst die PLS-INet-XML mit Size-Cap + Pre-Parse-Guard zu facility-dicts.

    Zu großer Body oder DOCTYPE/ENTITY -> ``ValueError`` (kein Parse). Das
    XML-Encoding (ISO-8859-1) wird über die XML-Deklaration korrekt aufgelöst,
    daher bekommt der Parser die rohen Bytes.
    """
    if len(xml_bytes) > _MAX_BYTES:
        raise ValueError("muenster_parking: response exceeds size cap")
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise ValueError("muenster_parking: DOCTYPE/ENTITY rejected")
    if not xml_bytes.strip():
        return []
    root = fromstring(xml_bytes)  # noqa: S314 - Guard oben, stdlib
    return [_facility(node) for node in root.iter("parkhaus")]


async def fetch_muenster_parking(http: httpx.AsyncClient) -> dict:
    """Holt die Live-Parkbelegung Münster und liefert das raw-dict für den Mapper.

    Rückgabe-Keys (exakt das, was ``map_muenster_parking`` erwartet): ``slug``
    ("muenster"), ``as_of`` (jüngster ``zeitstempel``, ISO-String, oder None) und
    ``facilities`` (Liste schlanker dicts). ``raise_for_status`` ist Pflicht
    (5xx -> Fassade STALE-ON-ERROR).
    """
    resp = await http.get(_URL)
    resp.raise_for_status()

    facilities = _parse(resp.content)
    timestamps = [f["observed_at"] for f in facilities if f.get("observed_at")]
    as_of = max(timestamps, key=datetime.fromisoformat) if timestamps else None

    return {"slug": "muenster", "as_of": as_of, "facilities": facilities}
