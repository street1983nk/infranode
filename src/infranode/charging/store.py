"""Redis-Store der akkumulierten eRound-Belegungs-Deltas (DATA-42, Stufe 2).

Der dynamische eRound-Feed ist eine DRAIN-QUEUE (live verifiziert 2026-07-03:
pull1=14, pull2=4 Punkte, 0 Overlap): jeder Pull liefert nur die Änderungen
seit dem letzten Pull, NIE den Vollzustand. Der Vollzustand entsteht erst durch
AKKUMULATION der Deltas in Redis.

Key-Layout (versioniert, Muster ``transit/store.py``):
- ``eround_charging:v1:{refill_point_id}`` -> orjson ``{status, observed_at}``
  (SET mit ``ex=ttl``).

Jeder Key trägt die TTL als ehrliches Staleness-Fenster: fällt der Poller aus,
verfallen veraltete Stati automatisch (kein ewig eingefrorenes "available").
KEIN Archiv-Write (reine Live-Daten, T-20-ARCHIVE).
"""

from __future__ import annotations

import orjson

_KEY_PREFIX = "eround_charging:v1:"

#: Snapshot des juengsten Delta-Pull-Ergebnisses (fuer den /live-Read-Pfad).
#: Der Request-Pfad pullt NIE selbst (strikte Entkopplung Datenupdate vom
#: Request-Worker): der Poller ist der EINZIGE Upstream-Puller und legt hier
#: das letzte Pull-Ergebnis ab; die /live-Route liest nur diesen Key.
_LATEST_KEY = "eround_charging:latest"

#: Frische-Fenster des Snapshots: 3 Poll-Ticks (300 s) Gnade, danach ehrliches
#: no_data statt eines eingefrorenen Alt-Stands (Poller tot = sichtbar).
LATEST_TTL_S = 900

#: Staleness-Fenster: ein Ladepunkt-Status ohne frisches Delta gilt maximal
#: 24 h (der Feed liefert nur Änderungen; ein unveränderter Punkt bleibt
#: dadurch länger gültig als die Poll-Kadenz, aber nicht ewig).
STATUS_TTL_S = 24 * 60 * 60

#: MGET-Chunk-Größe für den Lese-Pfad (Hamburg hat ~2700 Punkte; ein einzelnes
#: Riesen-MGET bleibt vermeidbar).
_MGET_CHUNK = 1000


def _key(refill_point_id: str) -> str:
    return f"{_KEY_PREFIX}{refill_point_id}"


async def store_point_statuses(redis, points, *, ttl: int = STATUS_TTL_S) -> int:
    """Akkumuliert Belegungs-Deltas in Redis (je Punkt SET mit TTL).

    ``points`` sind die Adapter-dicts aus ``adapters/mobilithek_afir.py``
    (``refill_point_id`` + ``status`` [+ ``observed_at``]). Einträge ohne ID
    oder Status fallen ehrlich raus. Rückgabe: Anzahl geschriebener Punkte.
    Idempotent (ein erneutes Schreiben desselben Delta-Stands ist harmlos).
    """
    pipe = redis.pipeline()
    written = 0
    for point in points or []:
        if not isinstance(point, dict):
            continue
        rp_id = point.get("refill_point_id")
        status = point.get("status")
        if not rp_id or not status:
            continue
        value = orjson.dumps(
            {"status": str(status), "observed_at": point.get("observed_at")}
        )
        pipe.set(_key(str(rp_id)), value, ex=ttl)
        written += 1
    if written:
        await pipe.execute()
    return written


async def store_latest_delta(redis, raw: dict, *, ttl: int = LATEST_TTL_S) -> None:
    """Legt das juengste Delta-Pull-Ergebnis als Snapshot ab (nur der Poller).

    ``raw`` ist das Adapter-dict aus ``fetch_afir`` (``points`` + ``as_of``).
    Auch ein LEERES Ergebnis wird geschrieben: es haelt den Snapshot frisch und
    laesst den Read-Pfad ehrlich ``no_data`` melden (Feed lieferte nichts),
    statt einen Alt-Stand einzufrieren.
    """
    value = orjson.dumps({"points": raw.get("points") or [], "as_of": raw.get("as_of")})
    await redis.set(_LATEST_KEY, value, ex=ttl)


async def read_latest_delta(redis) -> dict | None:
    """Liest den juengsten Delta-Snapshot (oder ``None`` bei Miss/kaputt)."""
    raw = await redis.get(_LATEST_KEY)
    if raw is None:
        return None
    try:
        value = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


async def get_point_statuses(redis, rp_ids) -> dict[str, dict]:
    """Liest die akkumulierten Stati fuer eine ID-Menge (MGET in Chunks).

    Rückgabe: ``{refill_point_id: {status, observed_at}}`` NUR für Punkte mit
    frischem (nicht abgelaufenem) Status; unbekannte/abgelaufene IDs fehlen
    ehrlich. Ein kaputter Einzelwert wird übersprungen (kein 500).
    """
    ids = [str(i) for i in rp_ids]
    result: dict[str, dict] = {}
    for start in range(0, len(ids), _MGET_CHUNK):
        chunk = ids[start : start + _MGET_CHUNK]
        raw_values = await redis.mget([_key(i) for i in chunk])
        for rp_id, raw in zip(chunk, raw_values, strict=True):
            if raw is None:
                continue
            try:
                value = orjson.loads(raw)
            except orjson.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("status"):
                result[rp_id] = value
    return result
