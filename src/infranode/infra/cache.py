"""Hand-gerollter Cache-Aside-Helper mit Stale-While-Revalidate + Single-Flight.

Deckt RES-02 (Cache-Aside + per-Source-TTL: ein wiederholter Aufruf trifft den
Redis-Cache statt erneut den Upstream) und RES-03 (Stale-While-Revalidate +
Single-Flight gegen Cache-Stampede: N parallele Requests auf einen kalten Key
erzeugen genau EINEN Upstream-Call) ab.

Redis kennt nur EINE TTL pro Key. Deshalb kodieren wir das Fresh- und das
Stale-Fenster IM Value (``fresh_until`` / ``stale_until`` als Unix-Zeitstempel).
GET -> Fresh: sofort liefern (HIT). Stale: sofort liefern UND genau einen
Hintergrund-Refresh planen (STALE), abgesichert durch einen kurzen
``SET NX EX``-Single-Flight-Lock, damit nur ein Worker refetcht. Missing/expired:
synchron fetchen und speichern (MISS).

decode_responses-Aufloesung (Orchestrator-Entscheidung 5): Diese Cache-Schicht
arbeitet bytes-sicher und ist unabhaengig vom ``decode_responses``-Modus des
uebergebenen Clients. Beim Lesen wird ein str-Ergebnis (decode_responses=True)
vor ``orjson.loads`` zu bytes kodiert; beim Schreiben gehen immer
``orjson.dumps``-bytes an Redis. So funktioniert der Helper sowohl mit dem
bestehenden ``decode_responses=True``-Pool (app.state.redis) als auch mit einem
``decode_responses=False``-Cache-Client, ohne einen zweiten Connection-Pool
einzufuehren (schlanker, MVP-tauglich).

Graceful Degradation (Pitfall 2): Jeder Redis-Zugriff ist in try/except gekapselt
(Muster aus health.py). Faellt Redis aus, degradiert der Pfad zu einem direkten
Fetch (Cache-Miss) statt zu crashen.

Cache-Poisoning-Schutz (T-03-06): ``build_cache_key`` baut versionierte Keys nur
aus validierten Slugs/Params via stabilem sha256-Param-Hash, nie aus rohen
User-Strings.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import orjson
import structlog

log = structlog.get_logger()

# Mindest-Stale-Fenster (Sekunden), damit auch bei ttl=0 (sofort stale) ein
# Stale-While-Revalidate-Pfad existiert, statt direkt als Cache-Miss zu zaehlen.
_DEFAULT_STALE_PAD = 60.0

# Lock-Lebensdauer (Sekunden) fuer den Single-Flight-Lock. Faellt ein Halter aus,
# gibt die Redis-TTL den Lock automatisch wieder frei (kein Deadlock).
_LOCK_TTL = 10

# Wartezeit-Parameter fuer Verlierer des Single-Flight-Locks auf einem kalten Key.
_WAIT_POLL = 0.02
_WAIT_MAX = 5.0


@dataclass(frozen=True)
class EntryMeta:
    """Metadaten eines Cache-Eintrags (Fresh-/Stale-Fenster als Unix-Zeit)."""

    fresh_until: float
    stale_until: float


def _to_bytes(raw: bytes | str) -> bytes:
    """Normalisiert ein Redis-Leseergebnis auf bytes (decode_responses-agnostisch)."""
    if isinstance(raw, str):
        return raw.encode()
    return raw


# Marker fuer base64-kodierte bytes-Payloads (orjson kann bytes nicht direkt
# serialisieren; HTTP-Responses liefern aber rohe bytes via resp.content).
_BYTES_TAG = "__b64__"


def _encode_payload(payload):
    """Macht beliebige Payloads orjson-serialisierbar (bytes -> base64-Container)."""
    if isinstance(payload, bytes):
        return {_BYTES_TAG: base64.b64encode(payload).decode("ascii")}
    return payload


def _decode_payload(payload):
    """Kehrt ``_encode_payload`` um (base64-Container -> bytes)."""
    if isinstance(payload, dict) and _BYTES_TAG in payload and len(payload) == 1:
        return base64.b64decode(payload[_BYTES_TAG])
    return payload


def build_cache_key(source: str, *, city_slug: str, params: dict | None = None) -> str:
    """Baut einen versionierten, kollisionssicheren Cache-Key.

    Schema: ``source:{source}:v1:{city_slug}:{param_hash}``. Der Param-Hash ist
    ein stabiler sha256 ueber die sortierten Items (orjson-serialisiert), sodass
    Reihenfolge-Varianten denselben Key ergeben. Nur aus validierten Slugs/Params
    bauen (T-03-06: kein roher User-String -> kein Cache-Poisoning). Versioniert
    (``:v1:``), damit ein Phase-4-Schema-Wechsel keine Fremd-Keys flushen muss.
    """
    items = sorted((params or {}).items())
    digest = hashlib.sha256(orjson.dumps(items)).hexdigest()[:16]
    return f"source:{source}:v1:{city_slug}:{digest}"


async def read_entry_meta(redis, key: str) -> EntryMeta | None:
    """Liest die Fresh-/Stale-Metadaten eines Cache-Eintrags (oder None bei Miss)."""
    try:
        raw = await redis.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    v = orjson.loads(_to_bytes(raw))
    return EntryMeta(fresh_until=v["fresh_until"], stale_until=v["stale_until"])


async def _store(redis, key: str, payload, ttl_fresh: float, ttl_stale: float) -> None:
    """Schreibt Payload + Fresh-/Stale-Fenster; Redis-Key-TTL = Stale-Ende."""
    now = time.time()
    value = {
        "payload": _encode_payload(payload),
        "fresh_until": now + ttl_fresh,
        "stale_until": now + ttl_stale,
    }
    # ex muss >= 1 sein; bei winzigem ttl_stale runden wir auf 1s auf.
    ex = max(1, int(round(ttl_stale)))
    await redis.set(key, orjson.dumps(value), ex=ex)


async def _refresh_and_store(
    redis,
    key: str,
    ttl_fresh: float,
    ttl_stale: float,
    fetch: Callable[[], Awaitable],
) -> None:
    """Single-Flight-Refresh-Coroutine: fetcht neu und speichert (Lock via ex aus)."""
    payload = await fetch()
    try:
        await _store(redis, key, payload, ttl_fresh, ttl_stale)
    except Exception as exc:
        # Redis-Schreibfehler beim Hintergrund-Refresh degradiert ignorieren.
        log.debug("cache_refresh_store_failed", key=key, error=str(exc))


def _default_schedule(coro: Awaitable) -> None:
    """Plant eine Refresh-Coroutine als losgeloesten Task (Referenz gegen GC)."""
    task = asyncio.ensure_future(coro)
    _default_schedule._tasks.add(task)  # type: ignore[attr-defined]
    task.add_done_callback(_default_schedule._tasks.discard)  # type: ignore[attr-defined]


_default_schedule._tasks = set()  # type: ignore[attr-defined]


async def cache_get_or_set(
    redis,
    key: str,
    *,
    ttl: float,
    fetch: Callable[[], Awaitable],
    ttl_stale: float | None = None,
    schedule: Callable[[Awaitable], None] | None = None,
):
    """Cache-Aside + Stale-While-Revalidate + Single-Flight um ``fetch``.

    Args:
        redis: redis.asyncio-kompatibler Client (decode_responses egal).
        key: vorab gebauter Cache-Key (siehe ``build_cache_key``).
        ttl: Fresh-Fenster in Sekunden. Innerhalb davon: HIT.
        fetch: parameterlose async-Funktion, die die frische Payload liefert.
        ttl_stale: Stale-Fenster in Sekunden (Default: ttl + Mindest-Pad).
        schedule: plant die Hintergrund-Refresh-Coroutine (Default: asyncio-Task).

    Returns:
        ``(payload, status)`` mit status in {"HIT", "STALE", "MISS"}.

    Pfade:
        - Fresh (now < fresh_until): sofort liefern -> HIT.
        - Stale (fresh_until <= now < stale_until): sofort stale liefern +
          genau einen Refresh planen (SET NX EX Single-Flight-Lock) -> STALE.
        - Miss/expired: synchron fetchen + speichern -> MISS. Bei N parallelen
          kalten Requests gewinnt genau einer den Lock und fetcht; die uebrigen
          warten kurz auf den frischen Eintrag (genau 1 Upstream-Call).
        - Redis down: try/except -> direkter Fetch, kein Crash (MISS).
    """
    if ttl_stale is None:
        ttl_stale = ttl + _DEFAULT_STALE_PAD
    if schedule is None:
        schedule = _default_schedule

    # 1. Cache lesen (Graceful Degradation: Redis-Fehler -> Cache-Miss-Pfad).
    raw = None
    redis_ok = True
    try:
        raw = await redis.get(key)
    except Exception:
        redis_ok = False

    now = time.time()
    if raw is not None:
        v = orjson.loads(_to_bytes(raw))
        if now < v["fresh_until"]:
            return _decode_payload(v["payload"]), "HIT"
        if now < v["stale_until"]:
            # Single-Flight: nur EIN Worker bekommt den Lock und refetcht.
            try:
                got_lock = await redis.set(f"lock:{key}", b"1", nx=True, ex=_LOCK_TTL)
            except Exception:
                got_lock = False
            if got_lock:
                schedule(_refresh_and_store(redis, key, ttl, ttl_stale, fetch))
            return _decode_payload(v["payload"]), "STALE"

    # 2. Miss/expired. Single-Flight auch fuer den kalten Pfad, damit N parallele
    #    Requests genau einen Upstream-Call erzeugen.
    if redis_ok:
        try:
            got_lock = await redis.set(f"lock:{key}", b"1", nx=True, ex=_LOCK_TTL)
        except Exception:
            got_lock = False

        if not got_lock:
            # Verlierer: kurz auf den frischen Eintrag des Gewinners warten.
            waited = 0.0
            while waited < _WAIT_MAX:
                await asyncio.sleep(_WAIT_POLL)
                waited += _WAIT_POLL
                try:
                    raw = await redis.get(key)
                except Exception:
                    raw = None
                    break
                if raw is not None:
                    v = orjson.loads(_to_bytes(raw))
                    now = time.time()
                    status = "HIT" if now < v["fresh_until"] else "STALE"
                    return _decode_payload(v["payload"]), status
            # Timeout/Redis-Fehler beim Warten -> selbst fetchen (kein Hang).

    # 3. Synchron fetchen + speichern (Lock-Halter oder degradierter Pfad).
    payload = await fetch()
    try:
        await _store(redis, key, payload, ttl, ttl_stale)
    except Exception as exc:
        # Redis-Schreibfehler ignorieren (Graceful Degradation, Pitfall 2).
        log.debug("cache_store_failed", key=key, error=str(exc))
    return payload, "MISS"
