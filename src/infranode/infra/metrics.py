"""Graceful Redis-Metrik-Helper fuer das Admin-Dashboard (OPS-02).

Reine Redis-Helper ohne Routen-/Middleware-Abhaengigkeit: Counter fuer Cache-
Status (HIT/MISS/STALE/STALE-ON-ERROR), Request-Zaehler (gesamt + je Status-Code
+ je Endpunkt) und ein gekappter Ringpuffer der letzten Request-Logs. Die
Anzeige-Schicht (Plan 13-03) liest diese Werte aus und berechnet die Hit-Rate.

Graceful Degradation (Muster aus cache.py, Pitfall 2): JEDER Redis-Zugriff ist in
try/except gekapselt. Faellt Redis aus, geht eine Metrik verloren, der Request-Pfad
crasht aber nie (incr/push degradieren still, read_* liefern leere/Null-Defaults).

decode_responses-agnostisch: Leseergebnisse werden vor ``orjson.loads`` ueber den
lokalen ``_to_bytes``-Helper (identisch zu cache.py) auf bytes normalisiert, sodass
die Helper sowohl mit dem Prod-Pool (decode_responses=True) als auch mit dem
fake_redis-Test-Client (decode_responses=False) funktionieren.
"""

from __future__ import annotations

import orjson
import structlog

from infranode.config import get_settings

log = structlog.get_logger()

# Redis-Key-Konstanten (zentral, damit Lese- und Schreibseite denselben Namen
# nutzen). _LOG_KEY ist die Liste des Request-Log-Ringpuffers; der Cache-Counter-
# Praefix wird mit dem normalisierten Status-Bucket zusammengesetzt; die Request-
# Keys sind ein Zaehler (count) plus zwei Hashes (status-Code/Endpunkt).
_LOG_KEY = "metrics:logs"
_CACHE_PREFIX = "metrics:cache:"
_REQ_COUNT_KEY = "metrics:req:count"
_REQ_STATUS_KEY = "metrics:req:status"
_REQ_ENDPOINT_KEY = "metrics:req:endpoint"

# Aktive-Consumer-Tracking (OPS): je UTC-Stunde ein Hash ident->Request-Anzahl
# plus ein Meta-Hash ident->"user-agent\tletzter-Pfad". ident = echte Client-IP
# (oder "mcp" fuer interne MCP-Server-Aufrufe). Selbst-ablaufend (TTL), damit kein
# unbegrenztes Wachstum. Das Filtern interner Monitoring-IPs macht die Auswerte-
# Schicht (der Box-Digest kennt die eigene IP), nicht der heisse Request-Pfad.
_CONSUMER_PREFIX = "metrics:consumers:"
_CONSUMER_TTL = 10800  # 3 h: deckt die stuendliche Auswertung + Verzug sicher ab.

# Die vier Cache-Status-Buckets (Quelle: CacheStatus StrEnum). Bucket-Name ist der
# kleingeschriebene Status mit "-" -> "_" (STALE-ON-ERROR -> stale_on_error).
_CACHE_BUCKETS = ("hit", "miss", "stale", "stale_on_error")


def _to_bytes(raw: bytes | str) -> bytes:
    """Normalisiert ein Redis-Leseergebnis auf bytes (decode_responses-agnostisch)."""
    if isinstance(raw, str):
        return raw.encode()
    return raw


def _bucket(status: str) -> str:
    """Bildet einen Cache-Status auf den Redis-Counter-Bucket ab (HIT -> hit)."""
    return status.lower().replace("-", "_")


async def incr_cache_status(redis, status: str) -> None:
    """Erhoeht den Cache-Status-Counter (HIT/MISS/STALE/STALE-ON-ERROR).

    Graceful: ein Redis-Fehler verliert die Metrik, crasht aber nie den Request.
    """
    try:
        await redis.incr(f"{_CACHE_PREFIX}{_bucket(status)}")
    except Exception as exc:
        log.debug("metrics_incr_cache_failed", status=status, error=str(exc))


async def incr_request(redis, *, endpoint: str, status_code: int) -> None:
    """Zaehlt einen Request: Gesamt-Counter + Status-Code-Hash + Endpunkt-Hash.

    Graceful: jeder Redis-Fehler degradiert still (Metrik-Verlust, kein Crash).
    """
    try:
        await redis.incr(_REQ_COUNT_KEY)
        await redis.hincrby(_REQ_STATUS_KEY, str(status_code), 1)
        await redis.hincrby(_REQ_ENDPOINT_KEY, endpoint, 1)
    except Exception as exc:
        log.debug("metrics_incr_request_failed", endpoint=endpoint, error=str(exc))


async def push_log(redis, entry: dict, max: int | None = None) -> None:
    """Schiebt einen Log-Eintrag in den gekappten Ringpuffer (neuester zuerst).

    ``max`` ist absichtlich ein None-Sentinel und wird NICHT als Default direkt
    aus ``get_settings()`` gebunden: sonst wuerde der Settings-Wert zur Import-Zeit
    eingefroren und der Test-Determinismus (monkeypatched admin_log_max) bricht.
    Erst innerhalb der Funktion auf den Settings-Wert zurueckgreifen. LPUSH legt
    den neuesten Eintrag an den Kopf, LTRIM kappt auf die letzten ``max`` Eintraege.
    Graceful: ein Redis-Fehler verliert den Log-Eintrag, crasht aber nie.
    """
    if max is None:
        max = get_settings().admin_log_max
    try:
        pipe = redis.pipeline()
        pipe.lpush(_LOG_KEY, orjson.dumps(entry).decode())
        pipe.ltrim(_LOG_KEY, 0, max - 1)
        await pipe.execute()
    except Exception as exc:
        log.debug("metrics_push_log_failed", error=str(exc))


async def read_logs(redis, n: int) -> list[dict]:
    """Liest die letzten ``n`` Log-Eintraege (neuester zuerst).

    Graceful: bei einem Redis-Fehler -> leere Liste statt Crash.
    """
    try:
        raw = await redis.lrange(_LOG_KEY, 0, n - 1)
    except Exception:
        return []
    return [orjson.loads(_to_bytes(item)) for item in raw]


async def read_cache_counts(redis) -> dict[str, int]:
    """Liest die vier Cache-Status-Counter (fehlende/Fehler -> 0).

    Graceful: bei einem Redis-Fehler -> alle Buckets 0.
    """
    try:
        raw = [await redis.get(f"{_CACHE_PREFIX}{b}") for b in _CACHE_BUCKETS]
    except Exception:
        return dict.fromkeys(_CACHE_BUCKETS, 0)
    return {
        b: int(v) if v is not None else 0
        for b, v in zip(_CACHE_BUCKETS, raw, strict=False)
    }


def consumer_hour(now) -> str:
    """UTC-Stunden-Bucket-Schluessel (z.B. ``2026-06-14T17``)."""
    return now.strftime("%Y-%m-%dT%H")


async def record_consumer(
    redis, *, ident: str, user_agent: str, path: str, status_code: int, now
) -> None:
    """Zaehlt einen aktiven Consumer in den Stunden-Bucket (Anzahl + letzte Meta).

    ``ident`` = echte Client-IP oder ``"mcp"`` (interner MCP-Server-Aufruf). Der
    Meta-Hash haelt User-Agent + letzten Pfad + letzten HTTP-Status (last-write-
    wins, tab-getrennt) zur App-Erkennung und damit im Digest sichtbar ist, ob ein
    (Scanner-)Pfad 200 oder 404 zurueckgab. Beide Keys laufen nach ``_CONSUMER_TTL``
    selbst ab. Graceful: jeder Redis-Fehler degradiert still und crasht NIE den
    Request.
    """
    try:
        hour = consumer_hour(now)
        ckey = f"{_CONSUMER_PREFIX}{hour}"
        mkey = f"{_CONSUMER_PREFIX}meta:{hour}"
        meta = f"{(user_agent or '')[:200]}\t{path}\t{status_code}"
        pipe = redis.pipeline()
        pipe.hincrby(ckey, ident, 1)
        pipe.hset(mkey, ident, meta)
        pipe.expire(ckey, _CONSUMER_TTL)
        pipe.expire(mkey, _CONSUMER_TTL)
        await pipe.execute()
    except Exception as exc:
        log.debug("record_consumer_failed", error=str(exc))


async def read_consumers(redis, hour: str) -> list[dict]:
    """Liest die aktiven Consumer eines Stunden-Buckets (Anzahl + UA + Pfad + Status).

    Rueckgabe je Eintrag: ``{ident, count, user_agent, last_path, last_status}``,
    nach Anzahl absteigend. ``last_status`` ist der HTTP-Status des letzten Requests
    als String (``""`` fuer Alt-Eintraege ohne Status-Feld). Graceful: bei einem
    Redis-Fehler -> leere Liste.
    """
    try:
        counts = await redis.hgetall(f"{_CONSUMER_PREFIX}{hour}")
        meta = await redis.hgetall(f"{_CONSUMER_PREFIX}meta:{hour}")
    except Exception:
        return []
    meta = {
        _to_bytes(k).decode(): _to_bytes(v).decode() for k, v in (meta or {}).items()
    }
    out = []
    for ident_raw, count_raw in (counts or {}).items():
        ident = _to_bytes(ident_raw).decode()
        # Tab-getrennt: UA \t Pfad \t Status. Alt-Eintraege (ohne Status) -> "".
        parts = meta.get(ident, "").split("\t")
        ua = parts[0] if parts else ""
        last_path = parts[1] if len(parts) > 1 else ""
        last_status = parts[2] if len(parts) > 2 else ""
        out.append(
            {
                "ident": ident,
                "count": int(count_raw),
                "user_agent": ua,
                "last_path": last_path,
                "last_status": last_status,
            }
        )
    out.sort(key=lambda c: c["count"], reverse=True)
    return out


def compute_hit_rate(counts: dict[str, int]) -> float:
    """Berechnet die Cache-Hit-Rate: hit / (hit + miss + stale + stale_on_error).

    STALE fliesst in den Nenner mit ein (der Cache lieferte, der Refresh lief im
    Hintergrund), wird im Dashboard aber separat ausgewiesen. Division durch 0
    (noch keine Requests) -> 0.0, niemals ein ZeroDivisionError.
    """
    total = sum(counts.get(b, 0) for b in _CACHE_BUCKETS)
    if total == 0:
        return 0.0
    return counts.get("hit", 0) / total


async def read_request_counts(redis) -> dict:
    """Liest die Request-Statistik: Gesamtzahl + Status-Code-Hash + Endpunkt-Hash.

    Graceful: bei einem Redis-Fehler -> Defaults (count 0, leere Hashes).
    """
    try:
        count_raw = await redis.get(_REQ_COUNT_KEY)
        status_raw = await redis.hgetall(_REQ_STATUS_KEY)
        endpoint_raw = await redis.hgetall(_REQ_ENDPOINT_KEY)
    except Exception:
        return {"count": 0, "status": {}, "endpoint": {}}
    count = int(count_raw) if count_raw is not None else 0
    status = {_to_bytes(k).decode(): int(v) for k, v in (status_raw or {}).items()}
    endpoint = {_to_bytes(k).decode(): int(v) for k, v in (endpoint_raw or {}).items()}
    return {"count": count, "status": status, "endpoint": endpoint}
