"""Reine lineare Positionsschätzung zwischen zwei GTFS-Halten.

Schätzt aus dem Soll-Fahrplan (sortierte Halte mit Geo + scheduled_epoch) und der
aktuellen Verspätung die Position einer Fahrt linear zwischen dem zuletzt
passierten und dem nächsten Halt (RESEARCH Pattern 4). Die lineare Interpolation
auf lat/lon ist eine Näherung (folgt nicht der echten Streckenführung) und wird
deshalb mit ``estimated=True`` ausgewiesen.

Muster "reine Funktion mit injizierter Zeit" (analog
``mappers/mobilithek_koeln.py``: ``retrieved_at`` keyword-only, keine Systemuhr im
Kern): ``now_epoch`` und ``service_day_epoch`` werden injiziert. Damit ist die
Funktion deterministisch testbar und enthält keinen nicht-reproduzierbaren
Zustand (T-19-CLOCK). KEINE Systemuhr im Kern (kein Aufruf einer Wanduhr-Funktion
aus ``datetime`` oder ``time``).
"""

from __future__ import annotations


def estimate_position(
    stops: list[dict], *, delay_s: int, now_epoch: int
) -> dict | None:
    """Interpoliert die Position einer Fahrt linear zwischen zwei Halten.

    ``stops`` sind nach Soll-Zeit sortierte Halte mit den Keys ``scheduled_epoch``
    (int), ``lat`` (float), ``lon`` (float) und ``stop_id`` (str). ``delay_s``
    verschiebt die effektive Soll-Zeit: ``adjusted = now_epoch - delay_s`` (eine
    aktuelle Verspätung bedeutet, dass die Fahrt einer früheren Soll-Zeit
    entspricht).

    Findet ``prev`` (letzter Halt mit ``scheduled_epoch <= adjusted``) und ``nxt``
    (erster Halt danach). Ist einer von beiden ``None`` -> Rückgabe ``None``
    (ehrlich vor Abfahrt bzw. nach Ankunft, keine Fantasie-Position). Bei
    ``span <= 0`` -> ``frac = 0.0`` (kein ``ZeroDivisionError``).

    Liefert ``{"lat", "lon", "estimated": True, "between": [prev_id, nxt_id]}``.
    """
    adjusted = now_epoch - delay_s  # Soll-Zeit, der die Fahrt jetzt entspricht
    prev: dict | None = None
    nxt: dict | None = None
    for s in stops:
        if s["scheduled_epoch"] <= adjusted:
            prev = s
        else:
            nxt = s
            break
    if prev is None or nxt is None:
        return None  # vor Abfahrt / nach Ankunft -> ehrlich None
    span = nxt["scheduled_epoch"] - prev["scheduled_epoch"]
    frac = 0.0 if span <= 0 else (adjusted - prev["scheduled_epoch"]) / span
    return {
        "lat": prev["lat"] + (nxt["lat"] - prev["lat"]) * frac,
        "lon": prev["lon"] + (nxt["lon"] - prev["lon"]) * frac,
        "estimated": True,  # Schätzung kennzeichnen (lineare Näherung)
        "between": [prev["stop_id"], nxt["stop_id"]],
    }


def gtfs_time_to_epoch(hms: str, *, service_day_epoch: int) -> int:
    """Rechnet eine GTFS-Zeit ``"HH:MM:SS"`` gegen einen Betriebstag in Epoch um.

    GTFS-Zeiten sind relativ zum Betriebstag und können >24:00:00 sein (z.B.
    ``25:30:00`` = 01:30 des Folgetags). ``service_day_epoch`` (Mitternacht des
    Betriebstags als Unix-Epoch) wird injiziert (keine Systemuhr im Kern):
    ``service_day_epoch + HH*3600 + MM*60 + SS``.
    """
    h, m, s = (int(part) for part in hms.split(":"))
    return service_day_epoch + h * 3600 + m * 60 + s
