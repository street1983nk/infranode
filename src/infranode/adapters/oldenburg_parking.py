"""Keyloser Oldenburg-Parken-Adapter ``fetch_oldenburg_parking`` (PARK-06, Tier C).

Direkter Zugang zum Parkleitsystem der Stadt Oldenburg (KEIN Mobilithek-mTLS, KEIN
Key). Seit dem DKAN-Relaunch des Open-Data-Portals (Oktober 2026) liefert die alte
Route ``/api/records/{dataset}`` 404 und der Parkleitsystem-Datensatz ist aus dem
Portal verschwunden. Quelle ist jetzt die öffentliche Parkleitsystem-Seite der
Stadt ``oldenburg-service.de/pls.php`` (Owner-Entscheid 2026-10-20).

Format: HTML-Tabelle (UTF-8 deklariert, mit möglichen Latin-1-Artefakten), Kopf
"Letzte Aktualisierung: DD.MM.YYYY HH:MM:SS" (lokale Zeit), Spalten
Name | Gesamte Plätze | Freie Plätze | Trend | Status. Status u.a. "Offen",
"Störung!". Geparst mit stdlib ``html.parser`` (keine neue Dependency). Zeilen mit
nicht-numerischen Zahlenfeldern werden übersprungen; bei "Störung!" (oder anderem
unbekannten Status) sind ``state`` und ``free`` None (keine verlässliche Belegung).
Die Quelle liefert keine IDs, Koordinaten oder Adressen: ``facility_id`` ist der
Name, ``lat``/``lon``/``address`` sind None.

Rückgabe ist das raw-dict, das ``map_oldenburg_parking`` erwartet: ``slug`` =
"oldenburg", ``as_of`` (Aktualisierungszeitpunkt der Seite, ISO 8601 mit
Europe/Berlin-Offset) und ``facilities`` (je Einrichtung ein schlankes dict im
einheitlichen Feldschema). Der Adapter baut KEINEN ``CanonicalRecord`` und kennt
KEIN Cache/Breaker (das liefert die Resilienz-Fassade). ``resp.raise_for_status()``
ist Pflicht, damit ein 5xx als ``httpx.HTTPError`` durchschlägt und der
STALE-ON-ERROR-Pfad greift.

Lizenz: Mit dem Datensatz ist die DL-DE/BY-2.0-Grundlage weggefallen. Konservativ
UNKNOWN / Tier C (live-only, NICHT public) bis zur Lizenzklärung bei der Stadt
Oldenburg, Muster ``aachen_parking``. Siehe
``mappers/stadt_parking.map_oldenburg_parking``.

Sicherheit:
- T-25-08 (SSRF): Host + Pfad sind in ``_URL`` hartkodiert; es fließt kein
  User-Input in die URL.
- T-25-09 (DoS): ``raise_for_status`` + Fassade-Timeout; ``_MAX_BYTES`` deckelt
  die Antwortgröße (ersetzt den früheren ``limit``-Query-Parameter).
"""

from __future__ import annotations

import codecs
import re
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import httpx

# Host + Pfad hartkodiert (SSRF-Schutz, T-25-08).
_URL = "https://oldenburg-service.de/pls.php"
# Size-Cap (T-25-09): die Seite hat ~6 KB; 1 MiB ist großzügige Reserve.
_MAX_BYTES = 1024 * 1024
# "Letzte Aktualisierung: DD.MM.YYYY HH:MM[:SS]" (lokale Zeit).
_DT_RE = re.compile(
    r"Aktualisierung:\s*(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?"
)
_TZ = ZoneInfo("Europe/Berlin")
# Spaltenzahl der Belegungstabelle: Name | Gesamt | Frei | Trend | Status.
_COLUMNS = 5
_STATES = {"offen": "offen", "geschlossen": "geschlossen"}
_ERRORS = "infranode_utf8_latin1_fallback"


def _latin1_fallback(exc: UnicodeError) -> tuple[str, int]:
    """Codec-Error-Handler: ungültige UTF-8-Bytes einzeln als Latin-1 lesen."""
    if not isinstance(exc, UnicodeDecodeError):
        raise exc
    return exc.object[exc.start : exc.end].decode("latin-1"), exc.end


codecs.register_error(_ERRORS, _latin1_fallback)


def _decode(body: bytes) -> str:
    """Dekodiert UTF-8, rettet eingestreute Latin-1-Bytes ("ö" statt U+FFFD)."""
    return body.decode("utf-8", errors=_ERRORS)


class _TableParser(HTMLParser):
    """Liest alle ``<td>``-Texte je ``<tr>`` sowie den Gesamttext (rein)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.text: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._close_row()
            self._row = []
        elif tag == "td" and self._row is not None:
            self._close_cell()
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._close_cell()
        elif tag in ("tr", "table"):
            self._close_row()

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def close(self) -> None:
        super().close()
        self._close_row()

    def _close_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._row:
            self.rows.append(self._row)
        self._row = None


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


def _to_int(value: str) -> int | None:
    """Parst eine nicht-negative Ganzzahl aus einer Tabellenzelle (rein) oder None."""
    value = value.strip()
    return int(value) if value.isdigit() else None


def _iso(text: str) -> str | None:
    """Liest "Letzte Aktualisierung" und gibt ISO 8601 mit Berlin-Offset zurück."""
    m = _DT_RE.search(text)
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


def _facility(cells: list[str], observed_at: str | None) -> dict | None:
    """Bildet eine Tabellenzeile auf ein schlankes facility-dict ab (rein).

    Zeilen ohne Name oder mit nicht-numerischem Gesamt-/Frei-Feld -> None
    (übersprungen). Sentinel-/Plausibilitäts-Regeln wie dortmund_parking:
    ``free > total`` -> ``free = None``. Status "Offen"/"Geschlossen" ->
    ``state`` "offen"/"geschlossen"; "Störung!" und Unbekanntes -> ``state`` None
    und ``free`` None (keine verlässliche Belegung).
    """
    name, total_s, free_s, _trend, status = cells[:_COLUMNS]
    total = _to_int(total_s)
    free = _to_int(free_s)
    if not name or total is None or free is None:
        return None
    state = _STATES.get(status.strip().rstrip("!").lower())
    if state is None or free > total:
        free = None
    return {
        "facility_id": name,
        "name": name,
        "lat": None,
        "lon": None,
        "free": free,
        "total": total,
        "occupancy": _occupancy(free, total),
        "state": state,
        "observed_at": observed_at,
        "address": None,
    }


def _parse(body: bytes) -> tuple[str | None, list[dict]]:
    """Parst die PLS-Seite (Size-Cap) zu ``(as_of, facilities)``.

    Zu großer Body -> ``ValueError`` (kein Parse). Nur Zeilen mit genau den fünf
    Belegungs-Spalten werden betrachtet (Kopf-/Layout-Tabellen fallen heraus).
    """
    if len(body) > _MAX_BYTES:
        raise ValueError("oldenburg_parking: response exceeds size cap")
    parser = _TableParser()
    parser.feed(_decode(body))
    parser.close()
    as_of = _iso(" ".join("".join(parser.text).split()))
    facilities = [
        fac
        for cells in parser.rows
        if len(cells) == _COLUMNS and (fac := _facility(cells, as_of)) is not None
    ]
    return as_of, facilities


async def fetch_oldenburg_parking(http: httpx.AsyncClient) -> dict:
    """Holt die Live-Parkbelegung Oldenburg und liefert das raw-dict für den Mapper.

    Rückgabe-Keys (exakt das, was ``map_oldenburg_parking`` erwartet): ``slug``
    ("oldenburg"), ``as_of`` (Aktualisierungszeitpunkt, ISO-String, oder None) und
    ``facilities`` (Liste schlanker dicts). ``raise_for_status`` ist Pflicht
    (5xx -> Fassade STALE-ON-ERROR).
    """
    resp = await http.get(_URL)
    resp.raise_for_status()

    as_of, facilities = _parse(resp.content)
    return {"slug": "oldenburg", "as_of": as_of, "facilities": facilities}
