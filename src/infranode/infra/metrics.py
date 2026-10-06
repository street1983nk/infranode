"""Graceful Redis-Metrik-Helper für das Admin-Dashboard (OPS-02).

Reine Redis-Helper ohne Routen-/Middleware-Abhaengigkeit: Counter für Cache-
Status (HIT/MISS/STALE/STALE-ON-ERROR), Request-Zähler (gesamt + je Status-Code
+ je Endpunkt) und ein gekappter Ringpuffer der letzten Request-Logs. Die
Anzeige-Schicht (Plan 13-03) liest diese Werte aus und berechnet die Hit-Rate.

Graceful Degradation (Muster aus cache.py, Pitfall 2): JEDER Redis-Zugriff ist in
try/except gekapselt. Fällt Redis aus, geht eine Metrik verloren, der Request-Pfad
crasht aber nie (incr/push degradieren still, read_* liefern leere/Null-Defaults).

decode_responses-agnostisch: Leseergebnisse werden vor ``orjson.loads`` über den
lokalen ``_to_bytes``-Helper (identisch zu cache.py) auf bytes normalisiert, sodass
die Helper sowohl mit dem Prod-Pool (decode_responses=True) als auch mit dem
fake_redis-Test-Client (decode_responses=False) funktionieren.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import orjson
import structlog

from infranode.config import get_settings

log = structlog.get_logger()

# Redis-Key-Konstanten (zentral, damit Lese- und Schreibseite denselben Namen
# nutzen). _LOG_KEY ist die Liste des Request-Log-Ringpuffers; der Cache-Counter-
# Präfix wird mit dem normalisierten Status-Bucket zusammengesetzt; die Request-
# Keys sind ein Zähler (count) plus zwei Hashes (status-Code/Endpunkt).
_LOG_KEY = "metrics:logs"
# Eigener Ringpuffer NUR für Requests mit Status >= 400: der allgemeine
# Log-Puffer hält allen Traffic und spült Fehler bei Last schnell raus; hier
# bleiben 4xx/5xx-Einträge mit Pfad und Request-ID dauerhaft sichtbar.
_ERRLOG_KEY = "metrics:errlog"
_CACHE_PREFIX = "metrics:cache:"
_REQ_COUNT_KEY = "metrics:req:count"
_REQ_STATUS_KEY = "metrics:req:status"
_REQ_ENDPOINT_KEY = "metrics:req:endpoint"

# Fehler-Tracking (Owner-Wunsch 2026-07-09): der all-time-Status-Hash zeigt
# Trends nicht. Daher zusätzlich je UTC-Tag ein Status-Hash (14 Tage TTL, ein
# Key/Tag -> kein OOM) für heute/gestern im Dashboard, plus je UTC-Stunde ein
# reiner 5xx-Zähler (48 h TTL) für den Watchdog-Alarm bei Server-Fehler-Häufung.
_STATUS_DAY_PREFIX = "metrics:req:status:day:"
_STATUS_DAY_TTL = 1209600  # 14 Tage
_ERR5XX_HOUR_PREFIX = "metrics:req:5xx:hour:"
_ERR5XX_HOUR_TTL = 172800  # 48 h

# Aktive-Consumer-Tracking (OPS): je UTC-Stunde ein Hash ident->Request-Anzahl
# plus ein Meta-Hash ident->"user-agent\tletzter-Pfad". ident = echte Client-IP
# (oder "mcp" für interne MCP-Server-Aufrufe). Selbst-ablaufend (TTL), damit kein
# unbegrenztes Wachstum. Das Filtern interner Monitoring-IPs macht die Auswerte-
# Schicht (der Box-Digest kennt die eigene IP), nicht der heiße Request-Pfad.
_CONSUMER_PREFIX = "metrics:consumers:"
_CONSUMER_TTL = 10800  # 3 h: deckt die stündliche Auswertung + Verzug sicher ab.

# MCP-/GPT-Aktions-Stunden-Buckets (quick 260716-s2t): erfolgreiche MCP-Tool- und
# GPT-Action-Aufrufe lösen keinen ntfy-Einzelpush mehr aus, sondern werden je
# UTC-Stunde gebündelt und im stündlichen consumer-digest bereitgestellt. Je
# Stunde ein Ressourcen-/Routen-Hash (Feld->Anzahl) plus ein Client-IP-/Nutzer-Set
# (SADD, distinct-Kardinalität). Dieselbe 3h-TTL wie der Consumer-Bucket, damit der
# Digest der Folgestunde den Bucket der Vorstunde noch lesen kann.
_MCP_RESOURCE_PREFIX = "metrics:mcp:resource:"
_MCP_CLIENTS_PREFIX = "metrics:mcp:clients:"
_GPT_ROUTE_PREFIX = "metrics:gpt:route:"
_GPT_USERS_PREFIX = "metrics:gpt:users:"

# Neue-Devs-Stunden-Bucket (Fix ntfy-Flut 2026-10-05): der Erstkontakt eines neuen
# Devs löste bisher je IP einen ntfy-Einzelpush aus (~235/Tag, 460 von 474
# Nachrichten in 48 h); ntfy.sh drosselte daraufhin die Upstream-Polls (429) und
# der iPhone-Push blieb aus. Jetzt landet jeder Erstkontakt in einem Hash je
# UTC-Stunde (Feld=Dev-Kennung -> "Typ\tErster Abruf\tUser-Agent") und erscheint
# als Abschnitt im stündlichen consumer-digest, also OHNE eigene Nachricht. Gleiche
# 3h-TTL wie die übrigen Stunden-Buckets; Redis-persistent, daher übersteht der
# Bucket einen api-Neustart.
_NEW_DEV_PREFIX = "metrics:newdevs:"

# Tages-Request-Zähler je Kanal (api|mcp): ein einzelner Counter-Key pro UTC-Tag
# (metrics:daily:<channel>:<YYYY-MM-DD>) für den täglichen 00:05-Digest. Bewusst
# NICHT per-IP wie die Consumer-Buckets: genau 2 Keys/Tag, daher kein Redis-OOM
# bei einer IP-Flut. Selbst-ablaufend (TTL deckt Vortag + Verzug bis zum Digest).
_DAILY_PREFIX = "metrics:daily:"
_DAILY_TTL = 172800  # 48 h: Vortag bleibt bis weit nach dem 00:05-Digest lesbar.

# Monats-Request-Zähler je Kanal (api|mcp|gpt): ein Counter-Key pro Kanal und
# UTC-Monat (metrics:monthly:<channel>:<YYYY-MM>), gefüllt im selben Pipeline wie
# der Tages-Counter (kein zusätzlicher Round-Trip). Da die Tages-Keys nach 48 h
# ablaufen, lässt sich am Monatsende NICHT über sie summieren, daher ein eigener
# Monats-Counter. Die großzügige TTL garantiert, dass der Monats-Key am 1. des
# Folgemonats (der Digest berichtet dann den letzten Vormonatstag) noch lesbar
# ist; da expire bei jedem Increment neu gesetzt wird, existieren nur ~2-3
# Monats-Keys je Kanal gleichzeitig -> vernachlässigbar, kein OOM.
_MONTHLY_PREFIX = "metrics:monthly:"
_MONTHLY_TTL = 5356800  # 62 Tage: deckt den Folgemonats-Digest sicher ab.

# Traffic-Tab (Admin): je UTC-Tag EIN Hash ident->Request-Anzahl (IPs, "mcp",
# "gpt") und EIN Hash endpunkt->Request-Anzahl. OOM-Abwägung (bewusst ein Hash je
# Tag statt vieler Keys):
#   IP-Hash: Feldzahl = unique Clients/Tag; dieselbe Kardinalitäts-Charakteristik
#   wie das bestehende Stunden-Muster (metrics:consumers:<stunde>, dort sogar 24
#   Keys/Tag plus Meta-Hash). Selbst eine IP-Flut (z.B. 100k unique IPs) bleibt ein
#   einstelliger MB-Hash; maxmemory allkeys-lru auf der Box fängt den Extremfall
#   ab. Maximal 8 Keys parallel (8 Tage TTL).
#   Endpunkt-Hash: Endpunkt-Namen sind ein begrenztes Set (Routen-Templates plus
#   mcp:/gpt:-Präfixe), kein nutzergesteuertes Wachstum, kein OOM-Risiko. Maximal
#   14 Keys parallel (14 Tage TTL, identisch zu _STATUS_DAY_TTL).
_CONSUMER_DAY_PREFIX = "metrics:consumers:day:"
_CONSUMER_DAY_TTL = 691200  # 8 Tage
_ENDPOINT_DAY_PREFIX = "metrics:req:endpoint:day:"
_ENDPOINT_DAY_TTL = 1209600  # 14 Tage

# Traffic-Tab, Wochensicht (Owner-Wunsch 2026-07-09, umschaltbare Zeitfenster;
# Monat bewusst NICHT nötig, Woche reicht): je ISO-Woche EIN Hash ident->Anzahl
# und EIN Hash endpunkt->Anzahl. Da die Tages-Hashes nach 8/14 Tagen ablaufen,
# laesst sich die Woche NICHT aus ihnen summieren -> eigener Wochen-Hash. OOM:
# gleiche Kardinalitaets-Charakteristik wie der Tages-Hash, nur ueber 7 Tage;
# maxmemory allkeys-lru fangen den Extremfall ab. Da expire bei jedem Increment
# neu gesetzt wird, existieren nur ~2 Wochen-Keys je Art.
# DATENSCHUTZ: IP-Vorhaltung ~14 Tage (nur ident->Zahl, kein Export, nur im
# Tailnet-Admin sichtbar), nahe der bestehenden 8-Tage-Linie des Tages-Hashes.
_CONSUMER_WEEK_PREFIX = "metrics:consumers:week:"
_CONSUMER_WEEK_TTL = 1209600  # 14 Tage (deckt die laufende ISO-Woche + Puffer)
_ENDPOINT_WEEK_PREFIX = "metrics:req:endpoint:week:"
_ENDPOINT_WEEK_TTL = 1209600  # 14 Tage

# Ein einzelner "letzte Meta"-Hash ident->"UA\tPfad\tStatus" (last-write-wins),
# damit die Traffic-Tabelle in JEDEM Fenster (Stunde/Heute/Woche) User-Agent und
# letzten Pfad zeigen kann, nicht nur fuer in den letzten 3 h aktive IPs. Anders
# als die per-Stunde-Meta-Hashes (3 h TTL, fuer read_consumers/Digest) lebt dieser
# so lange wie die Wochensicht. DATENSCHUTZ wie oben: nur im Tailnet-Admin.
_CONSUMER_META_KEY = "metrics:consumers:meta:latest"
_CONSUMER_META_TTL = 1209600  # 14 Tage (deckt die Wochensicht ab)

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


def _sanitize_field(value: str | None, *, max_len: int = 64) -> str:
    """Bereinigt einen aus Headern stammenden Wert vor dem Redis-Schreiben.

    Zero-Trust-Absicherung für die MCP-/GPT-Aktions-Buckets (T-s2t-01): Ressource,
    Client-IP, Route und Nutzer-Kennung kommen unvalidiert von aussen (über den
    MCP-Server bzw. ChatGPT). Der Wert wird getrimmt, auf ``max_len`` gekappt und
    auf druckbare Zeichen reduziert (Steuerzeichen/Zeilenumbrüche fallen weg, damit
    sie nicht als Redis-Feldnamen landen). Leer/None -> ``"unbekannt"``. Vorbild ist
    das bestehende Längenlimit ``[:200]`` in ``record_consumer``.
    """
    cleaned = "".join(c for c in (value or "").strip() if c.isprintable())[:max_len]
    return cleaned or "unbekannt"


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

    Zusätzlich (Fehler-Tracking): Status-Hash je UTC-Tag (heute/gestern im
    Dashboard) und bei 5xx ein Stunden-Zähler für den Watchdog-Alarm. Analog zum
    Status-Tages-Hash wird auch ein Endpunkt-Tages-Hash (Traffic-Tab, Top-Endpunkte
    heute) mitgeschrieben. Alles in EINEM Pipeline (kein zusätzlicher Round-Trip im
    heißen Pfad).

    Graceful: jeder Redis-Fehler degradiert still (Metrik-Verlust, kein Crash).
    """
    try:
        now = datetime.now(UTC)
        day_key = f"{_STATUS_DAY_PREFIX}{now.strftime('%Y%m%d')}"
        endpoint_day_key = f"{_ENDPOINT_DAY_PREFIX}{now.strftime('%Y%m%d')}"
        endpoint_week_key = f"{_ENDPOINT_WEEK_PREFIX}{now.strftime('%G-W%V')}"
        pipe = redis.pipeline()
        pipe.incr(_REQ_COUNT_KEY)
        pipe.hincrby(_REQ_STATUS_KEY, str(status_code), 1)
        pipe.hincrby(_REQ_ENDPOINT_KEY, endpoint, 1)
        pipe.hincrby(day_key, str(status_code), 1)
        pipe.expire(day_key, _STATUS_DAY_TTL)
        pipe.hincrby(endpoint_day_key, endpoint, 1)
        pipe.expire(endpoint_day_key, _ENDPOINT_DAY_TTL)
        pipe.hincrby(endpoint_week_key, endpoint, 1)
        pipe.expire(endpoint_week_key, _ENDPOINT_WEEK_TTL)
        if status_code >= 500:
            hour_key = f"{_ERR5XX_HOUR_PREFIX}{now.strftime('%Y%m%d%H')}"
            pipe.incr(hour_key)
            pipe.expire(hour_key, _ERR5XX_HOUR_TTL)
        await pipe.execute()
    except Exception as exc:
        log.debug("metrics_incr_request_failed", endpoint=endpoint, error=str(exc))


async def push_log(redis, entry: dict, max_entries: int | None = None) -> None:
    """Schiebt einen Log-Eintrag in den gekappten Ringpuffer (neuester zuerst).

    ``max_entries`` ist absichtlich ein None-Sentinel und wird NICHT als Default direkt
    aus ``get_settings()`` gebunden: sonst würde der Settings-Wert zur Import-Zeit
    eingefroren und der Test-Determinismus (monkeypatched admin_log_max) bricht.
    Erst innerhalb der Funktion auf den Settings-Wert zurückgreifen. LPUSH legt
    den neuesten Eintrag an den Kopf, LTRIM kappt auf die letzten ``max_entries``
    Einträge.
    Graceful: ein Redis-Fehler verliert den Log-Eintrag, crasht aber nie.
    """
    if max_entries is None:
        max_entries = get_settings().admin_log_max
    try:
        pipe = redis.pipeline()
        pipe.lpush(_LOG_KEY, orjson.dumps(entry).decode())
        pipe.ltrim(_LOG_KEY, 0, max_entries - 1)
        await pipe.execute()
    except Exception as exc:
        log.debug("metrics_push_log_failed", error=str(exc))


async def read_logs(redis, n: int) -> list[dict]:
    """Liest die letzten ``n`` Log-Einträge (neuester zuerst).

    Graceful: bei einem Redis-Fehler -> leere Liste statt Crash.
    """
    try:
        raw = await redis.lrange(_LOG_KEY, 0, n - 1)
    except Exception:
        return []
    return [orjson.loads(_to_bytes(item)) for item in raw]


async def push_error_log(redis, entry: dict, max_entries: int | None = None) -> None:
    """Schiebt einen Fehler-Eintrag (Status >= 400) in den Fehler-Ringpuffer.

    Identisches Muster wie ``push_log`` (None-Sentinel für ``max_entries``, LPUSH +
    LTRIM in EINEM Pipeline), nur gegen den eigenen Key ``metrics:errlog``.
    Bewusst dieselbe Obergrenze ``admin_log_max``: die Größenordnung des
    normalen Log-Puffers reicht auch für die Fehler-Sicht, ein eigener
    Settings-Wert wäre unnötige Konfiguration.
    Graceful: ein Redis-Fehler verliert den Eintrag, crasht aber nie.
    """
    if max_entries is None:
        max_entries = get_settings().admin_log_max
    try:
        pipe = redis.pipeline()
        pipe.lpush(_ERRLOG_KEY, orjson.dumps(entry).decode())
        pipe.ltrim(_ERRLOG_KEY, 0, max_entries - 1)
        await pipe.execute()
    except Exception as exc:
        log.debug("metrics_push_error_log_failed", error=str(exc))


async def read_error_logs(redis, n: int) -> list[dict]:
    """Liest die letzten ``n`` Fehler-Einträge (neuester zuerst).

    Graceful: bei einem Redis-Fehler -> leere Liste statt Crash.
    """
    try:
        raw = await redis.lrange(_ERRLOG_KEY, 0, n - 1)
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
    """UTC-Stunden-Bucket-Schlüssel (z.B. ``2026-06-14T17``)."""
    return now.strftime("%Y-%m-%dT%H")


def consumer_week(now) -> str:
    """ISO-Wochen-Bucket-Schlüssel (z.B. ``2026-W28``, Montag-basiert, UTC).

    ``%G``/``%V`` liefern ISO-Jahr + ISO-Kalenderwoche (nicht ``%Y``/``%W``, die
    am Jahreswechsel inkonsistent sind).
    """
    return now.strftime("%G-W%V")


async def record_consumer(
    redis, *, ident: str, user_agent: str, path: str, status_code: int, now
) -> None:
    """Zaehlt einen aktiven Consumer in den Stunden-Bucket (Anzahl + letzte Meta).

    ``ident`` = echte Client-IP oder ``"mcp"`` (interner MCP-Server-Aufruf). Der
    Meta-Hash hält User-Agent + letzten Pfad + letzten HTTP-Status (last-write-
    wins, tab-getrennt) zur App-Erkennung und damit im Digest sichtbar ist, ob ein
    (Scanner-)Pfad 200 oder 404 zurückgab. Beide Stunden-Keys laufen nach
    ``_CONSUMER_TTL`` selbst ab. Zusätzlich wird im selben Pipeline ein Tages-Hash
    ident->Anzahl (``metrics:consumers:day:<YYYYMMDD>``, 8 Tage TTL) für die
    Traffic-Tab-Spalte "heute" mitgeschrieben. Graceful: jeder Redis-Fehler
    degradiert still und crasht NIE den Request.
    """
    try:
        hour = consumer_hour(now)
        ckey = f"{_CONSUMER_PREFIX}{hour}"
        mkey = f"{_CONSUMER_PREFIX}meta:{hour}"
        day_key = f"{_CONSUMER_DAY_PREFIX}{now.strftime('%Y%m%d')}"
        week_key = f"{_CONSUMER_WEEK_PREFIX}{consumer_week(now)}"
        meta = f"{(user_agent or '')[:200]}\t{path}\t{status_code}"
        pipe = redis.pipeline()
        pipe.hincrby(ckey, ident, 1)
        pipe.hset(mkey, ident, meta)
        pipe.expire(ckey, _CONSUMER_TTL)
        pipe.expire(mkey, _CONSUMER_TTL)
        pipe.hincrby(day_key, ident, 1)
        pipe.expire(day_key, _CONSUMER_DAY_TTL)
        # Wochen-Hash (umschaltbare Wochensicht) + "letzte Meta" fuer alle Fenster.
        pipe.hincrby(week_key, ident, 1)
        pipe.expire(week_key, _CONSUMER_WEEK_TTL)
        pipe.hset(_CONSUMER_META_KEY, ident, meta)
        pipe.expire(_CONSUMER_META_KEY, _CONSUMER_META_TTL)
        await pipe.execute()
    except Exception as exc:
        log.debug("record_consumer_failed", error=str(exc))


async def record_mcp_action(redis, *, resource: str, client: str, now) -> None:
    """Bündelt einen erfolgreichen MCP-Tool-Aufruf in den Stunden-Bucket.

    Je UTC-Stunde ein Ressourcen-Hash (Feld=Ressource -> Anzahl) plus ein
    Client-IP-Set (SADD -> distinct-Kardinalität), beide mit 3h-TTL. Ressource und
    Client werden vor dem Schreiben über ``_sanitize_field`` bereinigt (Zero-Trust,
    T-s2t-01). Gleiches Pipeline- + try/except-Muster wie ``record_consumer``:
    graceful, ein Redis-Fehler verliert die Metrik, crasht aber NIE den Request.
    """
    try:
        hour = consumer_hour(now)
        res_key = f"{_MCP_RESOURCE_PREFIX}{hour}"
        cli_key = f"{_MCP_CLIENTS_PREFIX}{hour}"
        pipe = redis.pipeline()
        pipe.hincrby(res_key, _sanitize_field(resource), 1)
        pipe.expire(res_key, _CONSUMER_TTL)
        pipe.sadd(cli_key, _sanitize_field(client))
        pipe.expire(cli_key, _CONSUMER_TTL)
        await pipe.execute()
    except Exception as exc:
        log.debug("record_mcp_action_failed", error=str(exc))


async def record_gpt_action(redis, *, route: str, user: str, now) -> None:
    """Bündelt einen erfolgreichen GPT-Action-Aufruf in den Stunden-Bucket.

    Je UTC-Stunde ein Routen-Hash (Feld=Route -> Anzahl) plus ein Nutzer-Set
    (SADD -> distinct-Kardinalität pseudonymer Nutzer), beide mit 3h-TTL. Route und
    Nutzer werden vor dem Schreiben über ``_sanitize_field`` bereinigt (Zero-Trust,
    T-s2t-01). Graceful wie ``record_mcp_action``: crasht nie den Request.
    """
    try:
        hour = consumer_hour(now)
        route_key = f"{_GPT_ROUTE_PREFIX}{hour}"
        users_key = f"{_GPT_USERS_PREFIX}{hour}"
        pipe = redis.pipeline()
        pipe.hincrby(route_key, _sanitize_field(route), 1)
        pipe.expire(route_key, _CONSUMER_TTL)
        pipe.sadd(users_key, _sanitize_field(user))
        pipe.expire(users_key, _CONSUMER_TTL)
        await pipe.execute()
    except Exception as exc:
        log.debug("record_gpt_action_failed", error=str(exc))


async def record_new_dev(
    redis, *, ident: str, kind: str, first_call: str, user_agent: str, now
) -> None:
    """Bündelt einen Dev-Erstkontakt in den Stunden-Bucket statt eines Einzelpushs.

    ``ident`` ist die Dev-Kennung ohne Präfix (IP bzw. Key-Hash), ``kind`` "IP"
    oder "API-Key", ``first_call`` z.B. ``"GET /api/v1/... -> 200"``. Alle Werte
    werden über ``_sanitize_field`` bereinigt (Zero-Trust: User-Agent und Pfad
    kommen von aussen). Graceful wie ``record_mcp_action``: crasht nie den Request.
    """
    try:
        key = f"{_NEW_DEV_PREFIX}{consumer_hour(now)}"
        meta = "\t".join(
            (
                _sanitize_field(kind, max_len=16),
                _sanitize_field(first_call, max_len=120),
                _sanitize_field(user_agent, max_len=80),
            )
        )
        pipe = redis.pipeline()
        pipe.hset(key, _sanitize_field(ident), meta)
        pipe.expire(key, _CONSUMER_TTL)
        await pipe.execute()
    except Exception as exc:
        log.debug("record_new_dev_failed", error=str(exc))


async def read_new_devs(redis, hour: str) -> list[dict]:
    """Liest die neuen Devs eines Stunden-Buckets für den consumer-digest.

    Rückgabe je Eintrag: ``{ident, kind, first_call, user_agent}``, nach Kennung
    sortiert (stabile Reihenfolge im Push). Fehlender Key / Redis-Fehler -> leere
    Liste. decode_responses-agnostisch via ``_to_bytes``.
    """
    try:
        raw = await redis.hgetall(f"{_NEW_DEV_PREFIX}{hour}")
    except Exception:
        return []
    out = []
    for ident_raw, meta_raw in (raw or {}).items():
        parts = _to_bytes(meta_raw).decode().split("\t")
        out.append(
            {
                "ident": _to_bytes(ident_raw).decode(),
                "kind": parts[0] if parts else "",
                "first_call": parts[1] if len(parts) > 1 else "",
                "user_agent": parts[2] if len(parts) > 2 else "",
            }
        )
    out.sort(key=lambda d: d["ident"])
    return out


async def read_consumers(redis, hour: str) -> list[dict]:
    """Liest die aktiven Consumer eines Stunden-Buckets (Anzahl + UA + Pfad + Status).

    Rückgabe je Eintrag: ``{ident, count, user_agent, last_path, last_status}``,
    nach Anzahl absteigend. ``last_status`` ist der HTTP-Status des letzten Requests
    als String (``""`` für Alt-Einträge ohne Status-Feld). Graceful: bei einem
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
        # Tab-getrennt: UA \t Pfad \t Status. Alt-Einträge (ohne Status) -> "".
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


async def read_mcp_actions(redis, hour: str) -> dict:
    """Verdichtet den MCP-Aktions-Stunden-Bucket für den Digest.

    Rückgabe ``{"total": int, "by_resource": {res: count, ... absteigend},
    "distinct_clients": int}``. Fehlender Key / Redis-Fehler -> Null-Defaults
    (``total`` 0, leeres ``by_resource``, 0 ``distinct_clients``). decode_responses-
    agnostisch via ``_to_bytes``.
    """
    empty = {"total": 0, "by_resource": {}, "distinct_clients": 0}
    try:
        raw = await redis.hgetall(f"{_MCP_RESOURCE_PREFIX}{hour}")
        distinct = await redis.scard(f"{_MCP_CLIENTS_PREFIX}{hour}")
    except Exception:
        return dict(empty)
    by_resource = {_to_bytes(k).decode(): int(v) for k, v in (raw or {}).items()}
    by_resource = dict(sorted(by_resource.items(), key=lambda kv: kv[1], reverse=True))
    return {
        "total": sum(by_resource.values()),
        "by_resource": by_resource,
        "distinct_clients": int(distinct or 0),
    }


async def read_gpt_actions(redis, hour: str) -> dict:
    """Verdichtet den GPT-Aktions-Stunden-Bucket für den Digest.

    Rückgabe ``{"total": int, "top_routes": {route: count, ... absteigend},
    "distinct_users": int}``. Fehlender Key / Redis-Fehler -> Null-Defaults.
    decode_responses-agnostisch via ``_to_bytes``.
    """
    empty = {"total": 0, "top_routes": {}, "distinct_users": 0}
    try:
        raw = await redis.hgetall(f"{_GPT_ROUTE_PREFIX}{hour}")
        distinct = await redis.scard(f"{_GPT_USERS_PREFIX}{hour}")
    except Exception:
        return dict(empty)
    top_routes = {_to_bytes(k).decode(): int(v) for k, v in (raw or {}).items()}
    top_routes = dict(sorted(top_routes.items(), key=lambda kv: kv[1], reverse=True))
    return {
        "total": sum(top_routes.values()),
        "top_routes": top_routes,
        "distinct_users": int(distinct or 0),
    }


async def read_consumers_day(redis, day: str) -> list[dict]:
    """Liest den Tages-Consumer-Hash (ident->Anzahl) für ``day`` (``YYYYMMDD``).

    Rückgabe je Eintrag ``{ident, count}``, nach Anzahl absteigend sortiert.
    Graceful: bei einem Redis-Fehler oder fehlendem Key -> leere Liste.
    """
    try:
        counts = await redis.hgetall(f"{_CONSUMER_DAY_PREFIX}{day}")
    except Exception:
        return []
    out = [
        {"ident": _to_bytes(k).decode(), "count": int(v)}
        for k, v in (counts or {}).items()
    ]
    out.sort(key=lambda c: c["count"], reverse=True)
    return out


async def read_consumers_week(redis, week: str) -> list[dict]:
    """Liest den Wochen-Consumer-Hash (ident->Anzahl) für ``week`` (``YYYY-Www``).

    Rückgabe je Eintrag ``{ident, count}``, nach Anzahl absteigend sortiert.
    Graceful: bei einem Redis-Fehler oder fehlendem Key -> leere Liste.
    """
    try:
        counts = await redis.hgetall(f"{_CONSUMER_WEEK_PREFIX}{week}")
    except Exception:
        return []
    out = [
        {"ident": _to_bytes(k).decode(), "count": int(v)}
        for k, v in (counts or {}).items()
    ]
    out.sort(key=lambda c: c["count"], reverse=True)
    return out


async def read_consumer_meta(redis) -> dict[str, dict]:
    """Liest den "letzte Meta"-Hash ident->{user_agent, last_path, last_status}.

    Quelle für die Meta-Spalten der Traffic-Tabelle in ALLEN Fenstern (Stunde/
    Heute/Monat), unabhängig davon, ob die IP in den letzten 3 h aktiv war.
    Graceful: bei einem Redis-Fehler -> leeres dict.
    """
    try:
        raw = await redis.hgetall(_CONSUMER_META_KEY)
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for k, v in (raw or {}).items():
        parts = _to_bytes(v).decode().split("\t")
        out[_to_bytes(k).decode()] = {
            "user_agent": parts[0] if parts else "",
            "last_path": parts[1] if len(parts) > 1 else "",
            "last_status": parts[2] if len(parts) > 2 else "",
        }
    return out


async def read_endpoints_day(redis, day: str) -> dict[str, int]:
    """Liest den Endpunkt-Tages-Hash (endpunkt->Anzahl) für ``day`` (``YYYYMMDD``).

    Graceful: bei einem Redis-Fehler oder fehlendem Key -> leeres dict.
    """
    try:
        raw = await redis.hgetall(f"{_ENDPOINT_DAY_PREFIX}{day}")
    except Exception:
        return {}
    return {_to_bytes(k).decode(): int(v) for k, v in (raw or {}).items()}


async def read_endpoints_week(redis, week: str) -> dict[str, int]:
    """Liest den Endpunkt-Wochen-Hash (endpunkt->Anzahl) für ``week`` (``YYYY-Www``).

    Graceful: bei einem Redis-Fehler oder fehlendem Key -> leeres dict.
    """
    try:
        raw = await redis.hgetall(f"{_ENDPOINT_WEEK_PREFIX}{week}")
    except Exception:
        return {}
    return {_to_bytes(k).decode(): int(v) for k, v in (raw or {}).items()}


async def incr_daily(redis, *, channel: str, now) -> None:
    """Zaehlt einen Request in den Tages-Counter des Kanals (``api``|``mcp``).

    Ein einzelner Counter-Key je Kanal und UTC-Tag
    (``metrics:daily:<channel>:<YYYY-MM-DD>``) mit Selbst-Ablauf (``_DAILY_TTL``).
    Anders als die per-IP-Consumer-Buckets wächst das NICHT mit der Zahl der
    Clients (genau zwei Keys pro Tag), daher kein OOM-Risiko bei einer IP-Flut.
    Speist den täglichen 00:05-ntfy-Digest. Erhöht zusätzlich im selben Pipeline
    (kein zweiter Round-Trip) den Monats-Counter ``metrics:monthly:<channel>:
    <YYYY-MM>`` für den Monats-Abschnitt des Digests am Monatsende. Graceful:
    jeder Redis-Fehler degradiert still (Metrik-Verlust), crasht aber NIE den
    Request-Pfad.
    """
    try:
        key = f"{_DAILY_PREFIX}{channel}:{now.strftime('%Y-%m-%d')}"
        monthly_key = f"{_MONTHLY_PREFIX}{channel}:{now.strftime('%Y-%m')}"
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _DAILY_TTL)
        pipe.incr(monthly_key)
        pipe.expire(monthly_key, _MONTHLY_TTL)
        await pipe.execute()
    except Exception as exc:
        log.debug("incr_daily_failed", channel=channel, error=str(exc))


async def read_daily(redis, *, day: str) -> dict[str, int]:
    """Liest die Tages-Counter aller Kanäle (``api``|``mcp``|``gpt``) für ``day``.

    ``day`` ist ein UTC-Datum ``YYYY-MM-DD``. Fehlende Keys -> 0. Graceful: bei
    einem Redis-Fehler -> alle 0 (nie ein Crash im Digest).
    """
    out = {"api": 0, "mcp": 0, "gpt": 0}
    try:
        for channel in out:
            raw = await redis.get(f"{_DAILY_PREFIX}{channel}:{day}")
            if raw is not None:
                out[channel] = int(raw)
    except Exception:
        return {"api": 0, "mcp": 0, "gpt": 0}
    return out


async def read_monthly(redis, *, month: str) -> dict[str, int]:
    """Liest die Monats-Counter aller Kanäle (``api``|``mcp``|``gpt``) für ``month``.

    ``month`` ist ein UTC-Monat ``YYYY-MM``. Fehlende Keys -> 0. Graceful: bei
    einem Redis-Fehler -> alle 0 (nie ein Crash im Digest). Strukturell identisch
    zu ``read_daily``, nur über den Monats-Präfix.
    """
    out = {"api": 0, "mcp": 0, "gpt": 0}
    try:
        for channel in out:
            raw = await redis.get(f"{_MONTHLY_PREFIX}{channel}:{month}")
            if raw is not None:
                out[channel] = int(raw)
    except Exception:
        return {"api": 0, "mcp": 0, "gpt": 0}
    return out


def compute_hit_rate(counts: dict[str, int]) -> float:
    """Berechnet die Cache-Hit-Rate: hit / (hit + miss + stale + stale_on_error).

    STALE fließt in den Nenner mit ein (der Cache lieferte, der Refresh lief im
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


def _error_buckets(status: dict[str, int]) -> dict:
    """Verdichtet einen Status-Hash zu Fehler-Kennzahlen (4xx/5xx + Breakdown).

    3xx (303/304 etc.) zählen NICHT als Fehler. Nicht-numerische Hash-Felder
    werden defensiv übersprungen.
    """
    client = 0
    server = 0
    breakdown: dict[str, int] = {}
    for code_raw, n in status.items():
        try:
            code = int(code_raw)
        except ValueError:
            continue
        if code >= 500:
            server += n
        elif code >= 400:
            client += n
        else:
            continue
        breakdown[str(code)] = breakdown.get(str(code), 0) + n
    ordered = dict(sorted(breakdown.items(), key=lambda kv: kv[1], reverse=True))
    return {"client_4xx": client, "server_5xx": server, "breakdown": ordered}


async def read_error_stats(redis) -> dict:
    """Liest die Fehler-Statistik: heute, gestern (UTC-Tages-Hashes) und gesamt.

    Graceful: bei einem Redis-Fehler -> Null-Defaults, das Dashboard rendert
    dann einfach Nullen statt zu crashen.
    """
    empty = {"client_4xx": 0, "server_5xx": 0, "breakdown": {}}
    now = datetime.now(UTC)
    today_key = f"{_STATUS_DAY_PREFIX}{now.strftime('%Y%m%d')}"
    yesterday_key = (
        f"{_STATUS_DAY_PREFIX}{(now - timedelta(days=1)).strftime('%Y%m%d')}"
    )
    try:
        today_raw = await redis.hgetall(today_key)
        yesterday_raw = await redis.hgetall(yesterday_key)
        total_raw = await redis.hgetall(_REQ_STATUS_KEY)
    except Exception:
        return {"today": dict(empty), "yesterday": dict(empty), "total": dict(empty)}

    def _decode(raw) -> dict[str, int]:
        return {_to_bytes(k).decode(): int(v) for k, v in (raw or {}).items()}

    return {
        "today": _error_buckets(_decode(today_raw)),
        "yesterday": _error_buckets(_decode(yesterday_raw)),
        "total": _error_buckets(_decode(total_raw)),
    }


async def read_5xx_hour(redis, now: datetime | None = None) -> int:
    """Liest den 5xx-Zähler der aktuellen UTC-Stunde (Watchdog-Alarm-Quelle).

    Graceful: Redis-Fehler oder fehlender Key -> 0.
    """
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d%H")
    try:
        raw = await redis.get(f"{_ERR5XX_HOUR_PREFIX}{stamp}")
    except Exception:
        return 0
    return int(raw) if raw is not None else 0
