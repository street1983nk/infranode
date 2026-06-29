"""GTFS-RT-Adapter: protobuf-Parse (Size-Cap) + Quellen-Switch (Phase 19).

Schablone ist ``adapters/mobilithek_datex2.py`` (exakt): ein reiner Parser mit
DoS-Härtung VOR dem Parse plus ein ``fetch_*``-Wrapper, der zwischen den Quellen
umschaltet und HTTP 422 als ``no_data`` durchreicht. Anders als beim DATEX-II-XML
braucht protobuf KEINEN DOCTYPE/ENTITY-Pre-Parse-Guard: Entity-Expansion (XXE,
Billion-Laughs) ist XML-spezifisch und beim binären protobuf-Wire-Format
strukturell nicht möglich (T-19-PARSE, accept). Die einzige Härtung ist daher
der Size-Cap (T-19-DOS): ein absurd großer Body wird abgelehnt, BEVOR
``FeedMessage().ParseFromString`` ihn auf einer 4-GB-Box in den Speicher zieht.

Der Parse ist ein reiner CPU-Schritt: kein I/O, keine Systemuhr, kein
``CanonicalRecord`` (das macht der Mapper), kein Cache/Breaker (das liefert die
Fassade). Der ``fetch_gtfs_rt_feed``-Wrapper vereinheitlicht den Parser-Eingang
auf ``bytes``, damit NUR die Quelle (gtfs.de httpx vs. Mobilithek mTLS) wechselt,
nicht der Parser (RESEARCH Pitfall 5).

SSRF-Invariante (T-19-SSRF): gtfs.de-Host UND Mobilithek-Host sind hartkodiert
(``_GTFS_DE_FEED_URL`` bzw. ``infra/mobilithek._MOBILITHEK_BASE``), ``abo_id``
stammt ausschließlich aus der Settings-Allowlist (Aufrufer reicht sie durch),
NIE aus User-Input; ``follow_redirects=False`` ist Pool-Default (infra/http.py:53).
"""

from __future__ import annotations

from infranode.infra.mobilithek import build_pull_url, pull_subscription

# Size-Cap (T-19-DOS): der echte gtfs.de-Feed ist ~68 MB; 128 MiB lassen Puffer
# für Wachstum, lehnen aber einen absurd grossen/manipulierten Body ab, BEVOR
# FeedMessage().ParseFromString ihn in den Speicher zieht (OOM-Schutz).
_MAX_FEED_BYTES = 128 * 1024 * 1024  # 128 MiB

# gtfs.de-Feed-URL HARTKODIERT (T-19-SSRF, wie infra/mobilithek._MOBILITHEK_BASE):
# der Host wird NIE aus Config/User-Input/Funktionsargument zusammengesetzt.
_GTFS_DE_FEED_URL = "https://realtime.gtfs.de/realtime-free.pb"


def parse_trip_updates(body: bytes) -> list[dict]:
    """Parst einen GTFS-RT-Feed (protobuf) zu kompakten Trip-Update-dicts.

    Reiner CPU-Schritt: kein I/O, keine Systemuhr. Der Size-Cap (T-19-DOS) greift
    VOR ``ParseFromString`` (ein zu großer Body wird gar nicht geparst). Je
    Entity mit ``trip_update`` entsteht ein dict mit ``trip_id``, ``route_id``
    (``None`` statt leerem String, da oft erst aus der Statik aufzulösen),
    ``delay``/``timestamp`` (nur falls gesetzt), ``delay_s`` (effektive
    Verspätung je Fahrt aus dem ersten stop_time_update, siehe unten) und
    ``stop_time_updates`` (Liste je Halt mit
    stop_id/stop_sequence/arrival_*/departure_*/schedule_relationship).

    Audit-Fix K6 (2026-06-29): Die Trip-Update-Ebene ``tu.delay`` ist im echten
    gtfs.de-Feed in 0 von 72.483 Fällen gesetzt; die tatsächliche Verspätung
    steht je Halt in ``stop_time_update.departure.delay`` bzw. ``arrival.delay``
    (1,1 Mio Werte). Daher wird ``delay_s`` als effektive Fahrt-Verspätung aus
    dem ersten Halt mit verfügbarem Delay abgeleitet (departure bevorzugt, sonst
    arrival) und fällt nur dann auf ``tu.delay`` zurück, wenn kein Halt einen
    Delay trägt (ehrlich ``None`` statt immer ``null``).
    """
    # Size-Cap (T-19-DOS) ZWINGEND vor dem Parse: nie einen Body parsen, der die
    # Box sprengen könnte. Bewusst vor dem protobuf-Import.
    if len(body) > _MAX_FEED_BYTES:
        raise ValueError(
            f"GTFS-RT-Body ueberschreitet _MAX_FEED_BYTES ({_MAX_FEED_BYTES})"
        )

    # Import erst nach dem Size-Cap (kein teurer Import bei abgelehntem Body).
    from google.transit import gtfs_realtime_pb2

    feed = gtfs_realtime_pb2.FeedMessage()
    # protobuf parst defensiv ohne Entity-Expansion (T-19-PARSE, accept); der
    # Size-Cap oben deckt den DoS-Vektor ab, daher kein zusätzlicher Guard.
    feed.ParseFromString(body)

    # Audit-Fix (MITTEL): der Feed-Header trägt den globalen Aktualisierungs-
    # Zeitstempel; die Trip-Ebene (tu.timestamp) ist im gtfs.de-Feed meist leer.
    # Header als observed_at-Fallback durchreichen (sonst bleibt observed_at null).
    header_ts = feed.header.timestamp if feed.header.HasField("timestamp") else None

    updates: list[dict] = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        stop_time_updates = [_stop_time_update(stu) for stu in tu.stop_time_update]
        tu_delay = tu.delay if tu.HasField("delay") else None
        update: dict = {
            "trip_id": tu.trip.trip_id,
            # route_id leer -> None (oft erst aus der Statik aufzulösen).
            "route_id": tu.trip.route_id or None,
            "delay": tu_delay,
            # Audit-Fix K6: effektive Verspätung aus den stop_time_updates ableiten
            # (departure.delay bevorzugt, sonst arrival.delay); nur wenn kein Halt
            # einen Delay hat, fällt es auf die Trip-Ebene tu.delay zurück.
            "delay_s": _effective_delay(stop_time_updates, tu_delay),
            # tu.timestamp bevorzugt, sonst Feed-Header-Timestamp (entnullt
            # observed_at).
            "timestamp": (tu.timestamp if tu.HasField("timestamp") else None)
            or header_ts,
            "stop_time_updates": stop_time_updates,
        }
        updates.append(update)
    return updates


def _effective_delay(stop_time_updates: list[dict], tu_delay: int | None) -> int | None:
    """Leitet die effektive Fahrt-Verspätung (Sekunden) aus den Halten ab.

    Audit-Fix K6: Der echte gtfs.de-Feed trägt die Verspätung NICHT auf der
    Trip-Update-Ebene (``tu.delay`` = 0 von 72.483 Fällen), sondern je Halt in
    ``stop_time_update.departure.delay`` bzw. ``arrival.delay``. Diese Funktion
    nimmt den ersten Halt mit verfügbarem Delay (``departure_delay`` bevorzugt,
    sonst ``arrival_delay``) als repräsentativen Live-Stand der Fahrt. Hat kein
    Halt einen Delay, fällt sie auf die Trip-Ebene ``tu_delay`` zurück (sonst
    ``None``: ehrlich, kein erzwungener Wert).
    """
    for stu in stop_time_updates:
        dep = stu.get("departure_delay")
        if dep is not None:
            return dep
        arr = stu.get("arrival_delay")
        if arr is not None:
            return arr
    return tu_delay


def _stop_time_update(stu) -> dict:
    """Extrahiert ein kompaktes stop_time_update-dict (arrival/departure rein)."""
    return {
        "stop_id": stu.stop_id or None,
        "stop_sequence": stu.stop_sequence if stu.HasField("stop_sequence") else None,
        "arrival_delay": stu.arrival.delay if stu.HasField("arrival") else None,
        "arrival_time": stu.arrival.time if stu.HasField("arrival") else None,
        "departure_delay": stu.departure.delay if stu.HasField("departure") else None,
        "departure_time": stu.departure.time if stu.HasField("departure") else None,
        "schedule_relationship": stu.schedule_relationship,
    }


async def fetch_gtfs_rt_feed(
    http,
    mtls_client,
    *,
    source: str,
    abo_id: str | None,
) -> bytes | None:
    """Holt die GTFS-RT-Feed-Bytes je Quelle (Quellen-Switch, RESEARCH Pattern 7).

    Vereinheitlicht den Parser-Eingang auf ``bytes`` (Pitfall 5): NUR die Quelle
    wechselt, nicht der Parser. ``abo_id`` MUSS aus der Settings-Allowlist stammen
    (T-19-SSRF), nie aus User-Input; der Mobilithek-Host bleibt in
    ``build_pull_url`` hartkodiert.

    - ``source == "mobilithek_delfi"``: ohne ``mtls_client`` ODER ohne ``abo_id``
      -> ``None`` (Graceful Degradation = disabled). Sonst Pull über den
      mTLS-Client; HTTP 422 (kein Datenpaket) liefert ``body=None`` (no_data),
      kein ``raise``.
    - sonst (gtfs_de): GET auf den hartkodierten gtfs.de-Host,
      ``raise_for_status`` (5xx schlägt an die Fassade durch), ``resp.content``.
    """
    if source == "mobilithek_delfi":
        if mtls_client is None or not abo_id:
            return None  # Graceful Degradation -> disabled
        # Legacy-Datenmodell (Service Desk 2026-06-15): style="container"
        # (/container/subscription?subscriptionID=...), NICHT der path-Zugriff
        # (Kap. 6.2.1 -> 4xx für dieses Abo).
        url = build_pull_url(abo_id, style="container")
        result = await pull_subscription(mtls_client, url)
        return result["body"]  # None bei 422 = no_data

    resp = await http.get(_GTFS_DE_FEED_URL)
    resp.raise_for_status()
    return resp.content
