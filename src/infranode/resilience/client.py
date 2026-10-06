"""ResilientSourceClient: die zentrale fetch-Fassade (Integration RES-01..05).

Diese Klasse verschmilzt die einzelnen Resilienz-Schichten zu EINER Funktion,
die Phase 4+ pro Quellen-Adapter trivial konsumiert:

- RES-01/05 (Pool + User-Agent): der gepoolte ``httpx.AsyncClient`` aus
  ``app.state.http`` wird durchgereicht; der Quellen-Adapter erhält ihn als
  einzigen I/O-Kanal.
- RES-02/03 (Cache-Aside + SWR + Single-Flight): jeder Read läuft durch
  ``cache_get_or_set`` (genau ein Upstream-Call bei HIT/Single-Flight).
- RES-04 (per-Source-Breaker): die Upstream-Coroutine wird pro Quelle durch den
  ``CircuitBreaker`` der ``BreakerRegistry`` geschützt. Eine tote Quelle trippt
  nur ihren eigenen Breaker und blockiert weder andere Quellen noch die
  Gesamt-Response (T-03-10).

Fallback-Politik (T-03-10/12): fällt der Upstream aus (Breaker OPEN ODER
``httpx.HTTPError``), liefert die Fassade einen vorhandenen (auch abgelaufenen)
Cache-Eintrag als ``STALE-ON-ERROR`` zurück. Existiert kein Cache, liefert sie
``(None, STALE-ON-ERROR)`` statt zu blockieren oder einen Stacktrace zu leaken;
der aufrufende API-Layer (Phase 4) entscheidet, ob daraus ein ``UpstreamError``
(503) wird. ``fetch`` blockiert nie und wirft keinen ungemappten Upstream-Fehler.

``fetch_fn`` ist eine reine parameterlose async-Funktion, die der Quellen-Adapter
liefert (kennt weder Cache noch Breaker). So bleibt der Adapter schlank und die
gesamte Resilienz steckt in dieser Fassade.

429-Cooldown-Schicht (Quick-260716-mq5): Quellen mit Eintrag in
``_SOURCE_429_COOLDOWN`` bekommen vor Semaphore/Pacing eine quellen-globale
Cooldown-Sperre. Ein 429 aktiviert sie (Retry-After-Sekunden bzw. eskalierender
Default, Kappe 120s); während der Sperre wartet ein Call höchstens
``_COOLDOWN_MAX_WAIT_S``, längere Restdauer wirft ``SourceCooldownActive``
(fail-fast in den Stale-/503-Pfad, kein Upstream-Call). Quota-Signale (429 der
Cooldown-Quelle, ``SourceCooldownActive``) zählen NICHT als Breaker-Failure:
Quota ist kein Gesundheitssignal, Quota-Wellen dürfen den Breaker nicht öffnen.
"""

from __future__ import annotations

import asyncio
import math
import os
import random
import time
from collections.abc import Awaitable, Callable

import httpx
import orjson
import structlog

from infranode.registry.source_specs import (
    SOURCE_EMERGENCY_KEEP as _REGISTRY_EMERGENCY_KEEP,
)
from infranode.registry.source_specs import SOURCE_TTL as _REGISTRY_TTL
from infranode.registry.ttl_profiles import (
    FRESH_PROFILES as _REGISTRY_FRESH_PROFILES,
)

from ..infra.cache import cache_get_or_set, read_entry_meta
from ..infra.metrics import incr_cache_status
from .breaker import BreakerOpen, BreakerRegistry
from .types import CacheStatus

log = structlog.get_logger()


async def _last_cache(redis, key: str):
    """Liest den (auch abgelaufenen) Cache-Value bytes-sicher; None bei Miss/Fehler.

    Graceful Degradation (T-03-09): jeder Redis-Fehler -> None statt Raise. Der
    Value-Container ist derselbe wie in ``infra/cache._store`` (payload +
    fresh_until/stale_until); base64-gewrappte bytes werden zurück dekodiert.
    """
    try:
        raw = await redis.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            raw = raw.encode()
        value = orjson.loads(raw)
    except Exception:
        return None
    payload = value.get("payload") if isinstance(value, dict) else None
    if isinstance(payload, dict) and "__b64__" in payload and len(payload) == 1:
        import base64

        return base64.b64decode(payload["__b64__"])
    return payload


# Default-Cache-Fenster (fresh_s, stale_s) für Quellen ohne expliziten Registry-
# Eintrag: bisheriges Verhalten (60s fresh, 120s stale). BEWUSST kurz gehalten
# (fail-closed, Quick-260709-huj): Zu den Quellen ohne Registry-ttl gehören viele
# ECHTZEIT-/LIVE-Quellen (ÖPNV-Abfahrten wie db_timetables/hvv_geofox/vgn/gtfs_rt,
# Verkehrslage/-meldungen, Live-Parken, Baustellen, Wetterwarnungen). Ein 24h-
# Stale-Fenster würde hier fachlich falsche (veraltete) Abfahrten/Warnungen
# ausliefern UND Tier-C-Live-only-Quellen lizenz-/ToS-widrig zu lange vorhalten.
# Deshalb wird das lange 24h-Notfenster NICHT global vergeben, sondern nur
# EXPLIZIT per Registry-Opt-in (registry/source_specs._STATIC_STALE_24H) für als
# statisch verifizierte Quellen. Alles ohne Eintrag bleibt bei 120s (verliert
# gegenüber vorher nichts). ttl_stale wird von hier IMMER explizit an
# cache_get_or_set übergeben -> der 24h-Floor in cache.py greift in Produktion nie.
_DEFAULT_TTL: tuple[float, float] = (60.0, 120.0)
# Per-Source-Cache-TTL (fresh_s, stale_s) aus der deklarativen Quellen-Registry
# (registry/source_specs.py). Quellen ohne Eintrag nutzen _DEFAULT_TTL.
_SOURCE_TTL: dict[str, tuple[float, float]] = dict(_REGISTRY_TTL)

# Notreserve hinter dem Stale-Fenster (Sekunden), nur Opt-in-Quellen (Registry,
# aktuell tankerkoenig). Verlaengert AUSSCHLIESSLICH die Redis-Key-Lebensdauer:
# HIT/STALE/MISS urteilen unveraendert ueber fresh_until/stale_until, und die
# Reserve wird nur vom Fehlerpfad unten gelesen (Vorfall 2026-09-07 abends:
# Key-TTL == Stale-Ende hiess has_stale=false nach jeder Luecke, und ein kalter
# Key verliert gegen die Aggregat-Bremse -> 503-Wellen).
_SOURCE_EMERGENCY_KEEP: dict[str, float] = dict(_REGISTRY_EMERGENCY_KEEP)

# --- Tagesprofil-Frische (Kraftstoffpreisanpassungsgesetz, 2026-09-07) --------
# Fuer Quellen, deren Nutzdaten sich ueber den Tag sehr ungleich aendern, ist
# EIN statischer fresh-Wert immer ein Kompromiss. Diese Hook-Tabelle ersetzt
# ihn durch ein Fenster je Tageszeit (reine Funktion der Uhr, kein Netz, kein
# Redis). Traegt eine Quelle KEINEN Eintrag, bleibt ihr Verhalten unveraendert;
# das Stale-Fenster ist von den Profilen nie betroffen. Aktuell genau eine
# Quelle: tankerkoenig (Begruendung in registry/ttl_profiles.py).
_FRESH_PROFILES: dict[str, Callable[[], float]] = dict(_REGISTRY_FRESH_PROFILES)

# --- Frische-Jitter (Overpass-Auto-Bann-Fix 2026-07-18) ------------------------
# Exakt gleiche fresh-TTLs lassen alle Keys einer Sweep-Generation im selben
# Moment ablaufen -> der naechste Tageslauf will ALLE gleichzeitig upstream
# erneuern, die Overpass-Kosten-Quote gibt nur einen Bruchteil her und der Rest
# erzeugt 429er. Genau diese 400/406/429-Serien zaehlt der automatisierte Bann
# des Betreibers (Antwort FOSSGIS/M. Spreng 2026-07-17; Volumen/Abstand/UA sind
# laut Betreiber ok). +-40% Streuung verteilt die Ablaufzeitpunkte einer
# Generation ueber mehrere Tage (bei 7d fresh: ~4,2 bis ~9,8 Tage), sodass je
# Tageslauf nur ein Bruchteil der Keys upstream erneuert wird.
_TTL_JITTER_SOURCES = frozenset({"overpass"})
_TTL_JITTER_RANGE = (0.6, 1.4)


def _profiled_fresh(source: str, ttl_fresh: float) -> float:
    """Ersetzt die statische fresh-TTL durch das Tagesprofil der Quelle.

    Quellen OHNE Profil-Eintrag geben ``ttl_fresh`` unveraendert zurueck (der
    Wert aus der Registry bzw. ``_DEFAULT_TTL``) -> exakt bisheriges Verhalten.
    Das Profil ist eine reine Funktion der Uhrzeit
    (``registry/ttl_profiles.py``); der statische Registry-Wert bleibt der
    Rueckfall, falls eine Quelle ihr Profil wieder verliert.
    """
    profile = _FRESH_PROFILES.get(source)
    if profile is None:
        return ttl_fresh
    return profile()


def _jittered_fresh(source: str, ttl_fresh: float) -> float:
    """Streut die fresh-TTL fuer Jitter-Quellen; andere unveraendert.

    Kein Krypto-Kontext (S311): reine Lastverteilung von Cache-Ablaeufen.
    """
    if source not in _TTL_JITTER_SOURCES:
        return ttl_fresh
    return ttl_fresh * random.uniform(*_TTL_JITTER_RANGE)  # noqa: S311


# --- Outbound-Limits je Upstream (ToS-Compliance) -----------------------------
# Obergrenze gleichzeitiger Upstream-Calls je Quelle. Geteilte VM-IP -> der
# Wikidata-WDQS-Endpoint erlaubt nur ~5 parallele Queries/IP. Tankerkönig: alle
# Nutzer teilen sich EINEN API-Key, daher hart deckeln (der fruehere Zusatz
# "ON-DEMAND ohne Redis-Cache" ist seit dem Owner-Entscheid 2026-07-08 ueberholt,
# die Route cacht kurzlebig; siehe registry/source_specs.py).
# Overpass (overpass-api.de, Fair-Use): nominell 2 Slots je IP, aber die Slots
# haben eine Kosten-Quote mit Abkühlzeit. Ein POI-Sweep riss am 2026-07-11 mit
# ungebremsten Parallel-Refreshes das Limit (429-Serie -> Breaker OPEN), und am
# 2026-07-16 leerte selbst 2 parallel + 1s Abstand die Slot-Quote nach wenigen
# Dutzend Queries erneut (429-Serie). Daher strikt seriell mit großem Abstand;
# der zweite Slot bleibt als Puffer für die Slot-Ökonomie ungenutzt.
# genesis (www.regionalstatistik.de, Header-Auth mit EINEM geteilten Credential):
# Demografie + das GENESIS-Regio-Trio (unemployment/tourism/construction) fetchen
# alle über die "genesis"-Fassade. Der Endpunkt ist langsam und credential-geteilt;
# ein ungebremster compare-Fan-out über viele Städte (bis 28) riss bei KALTEM Cache
# mehrere Städte in Timeouts (beobachtet 2026-07-17: 8 parallel -> nur ~3 ok, Rest
# per-Stadt "error"). Ein Concurrency-Cap serialisiert den kalten Fan-out in kleine
# Wellen, sodass jede Stadt durchkommt und cacht (warme compares bleiben instant).
# Quellen ohne Eintrag: unbegrenzt (Verhalten unverändert).
_SOURCE_MAX_CONCURRENCY: dict[str, int] = {
    "wikidata": 5,
    "tankerkoenig": 2,
    "overpass": 1,
    "genesis": 3,
}
# Mindestabstand (Sekunden) zwischen Upstream-Calls je Quelle (Aggregat-Rate).
# DB-Timetables-ToS: <=60 Aufrufe/Minute -> >=1.0s.
# Tankerkönig: das Limit der Quelle ist 1 Anfrage/Minute -> 60.0s. Der frühere
# Wert 1.0s stand hier mit der Begründung "cachen dürfen wir nicht"; die gilt
# seit dem Owner-Entscheid 2026-07-08 nicht mehr (kurzlebiger 5-min-Cache an der
# Route, ToS-Wortlaut am 2026-07-25 geprüft). Übrig blieb eine Bremse, die 60
# Anfragen/Minute durchließ, also das Sechzigfache des Limits. Am 2026-09-04 hat
# ein Diagnoselauf über alle 84 Städte genau das getan: Tankerkönig antwortete
# mit 429 und sperrte danach die Box-IP auf TCP-Ebene (auch Port 80), echte
# Nutzer bekamen 503. Der Cache trägt den Normalbetrieb; das Pacing trifft nur
# kalte Keys und Hintergrund-Refreshes und verhindert genau diesen Burst.
# Overpass: <=15/min Aggregat (4s Abstand), damit die Slot-Kosten-Quote des
# öffentlichen Servers auch bei langen Sweeps nicht abgeräumt wird (1s Abstand
# reichte am 2026-07-16 NICHT, 429 nach wenigen Dutzend Queries). POIs sind
# ohnehin lange gecacht, das Pacing trifft nur kalte Keys, Collector-Warm-Jobs
# und SWR-Background-Refreshes; der nächtliche Warm-Sweep wird dadurch langsam
# (~90 min), was gewollt ist.
# UBA (Eintrag seit 2026-09-17): der Adapter macht pro Stadt EINEN
# stations-Call und danach bis zu fünf Komponenten mal Nachbarstationen
# measures-Calls, also gut ein Dutzend Anfragen in wenigen hundert
# Millisekunden. Der measures-Endpunkt quittiert genau diesen Burst mit 429,
# während stations 20 Aufrufe ohne Pause anstandslos beantwortet (beides am
# 2026-09-17 reproduziert). 0.25s senken die Spitze auf vier Anfragen je
# Sekunde und halten einen kalten Stadtabruf bei rund vier Sekunden, also
# deutlich unter dem 20s-Warte-Deckel. Das genaue Limit der Quelle ist nicht
# dokumentiert; der Wert ist ein gemessener Startwert, keine bekannte Vorgabe.
# Quellen ohne Eintrag: kein Limit. Geteilte Keys -> Aggregat begrenzen.
_SOURCE_MIN_INTERVAL_S: dict[str, float] = {
    "db_timetables": 1.0,
    "tankerkoenig": 60.0,
    "overpass": 4.0,
    "uba": 0.25,
}

# --- 429-Cooldown je Quelle (Quota-Signal, KEIN Gesundheitssignal) ------------
# Overpass drosselt nach einem KOSTEN-Budget je IP: große Stadt-BBox-Queries sind
# teuer, das Budget erholt sich langsamer, als ein Dauerlauf es verbraucht. Der
# Warm-Sweep (17 tägliche osm-Jobs) bekam am 2026-07-16 trotz 1 parallel + 4s
# Mindestabstand ~15% HTTP 429 -> Route-503-Wellen im errlog/ntfy. Ein 429 ist
# hier ein QUOTA-Signal (Server lebt, Budget leer), kein Ausfall; deshalb setzt
# er eine quellen-globale Cooldown-Sperre statt den Breaker zu füttern.
# Wert = Default-Cooldown-Sekunden je Quelle; nur eingetragene Quellen nehmen
# an der Cooldown-Logik teil, alle anderen verhalten sich exakt wie bisher.
# Parameter (Owner-Rahmen 2026-07-16): 30s Default (liegt bewusst über dem
# 12s-Warte-Deckel, der Collector überbrückt via run_with_retry 0/10/30s),
# Faktor 2 je Folge-429, Kappe 120s (gilt auch für Retry-After-Header).
# Tankerkönig (Eintrag seit 2026-09-04): ein 429 ist hier das letzte Signal vor
# der IP-Sperre. Ohne Eintrag zählte jeder 429 als Breaker-Failure, der Breaker
# ging mit 24h-TTL auf OPEN, und die Aufrufe liefen bis zur Sperre weiter. Mit
# Eintrag stoppt der erste 429 alle weiteren Calls quellen-global, ohne den
# Breaker zu füttern. Default 60.0s = eine Minute, passend zum Limit von
# 1 Anfrage/Minute; Eskalation auf 120s greift bei Folge-429.
# UBA (Eintrag seit 2026-09-17): ohne Eintrag zählte jeder 429 als
# Breaker-Failure. Vorfall 2026-09-16/17: 238 HTTPStatusError auf uba-Keys
# rissen den quellen-globalen Breaker auf, danach 1040 BreakerOpen über alle
# Städte hinweg und 94 echte 503 an Nutzern, weil ein offener Breaker auch den
# Cache-Refresh der Städte verhindert, die noch gar keinen Wert hatten. Der
# Upstream war dabei gesund, er hat uns nur gedrosselt. 30s Default wie
# overpass, Eskalation und Kappe unverändert.
_SOURCE_429_COOLDOWN: dict[str, float] = {
    "overpass": 30.0,
    "tankerkoenig": 60.0,
    "uba": 30.0,
}
# Warte-Deckel im Request-Pfad: kurze Restsperren werden abgewartet (Sweep-Jobs
# laufen dann ohne Fehler weiter), längere werfen sofort SourceCooldownActive
# (interaktive Requests hängen nie minutenlang; bleibt unter Collector-read=60s
# und unter Cloudflare-Timeouts).
_COOLDOWN_MAX_WAIT_S = 12.0
# Warte-Deckel für den Mindestabstand (``_pace``): eine Restwartezeit bis hierher
# wird abgewartet, darüber bricht der Call sofort ab. Ohne Deckel würde eine
# Quelle mit strengem Limit (Tankerkönig: 60s) einen interaktiven Request bis zu
# eine Minute schlafen lassen, statt ehrlich 503 zu antworten.
#
# 20s statt der früheren 12s (Vorfall 2026-09-06, Nachmittagswelle): 27 von 48
# Bremsen-503 kamen als sofortige Wiederholung 6 bis 48 s nach der vorigen
# Anfrage derselben Stadt, also mit einer Restzeit über 12s. Ein einzelner
# Wartender darf den nächsten freien Slot jetzt abwarten (siehe ``_pace``);
# jeder weitere gleichzeitige Call derselben Quelle wird weiter sofort
# abgewiesen, die Quelle sieht also unverändert höchstens einen Call je Fenster.
#
# Warum 20 und nicht 45: der MCP-Loopback-Client liest mit
# ``mcp_loopback_read_timeout`` (Default 30.0s), der Upstream-Call selbst darf
# danach noch 2s connect + 5s read brauchen. 20 + 7 = 27s bleibt darunter, ein
# 45s-Deckel würde MCP-Aufrufe in einen Read-Timeout laufen lassen statt in eine
# ehrliche Antwort. Per ``INFRANODE_SOURCE_PACE_WAIT_MAX_S`` ohne Deploy
# einstellbar (0 bis 60; 12 stellt das Verhalten von vor dem 2026-09-06 her).
_PACE_MAX_WAIT_S = 20.0
_PACE_WAIT_MAX_ENV = "INFRANODE_SOURCE_PACE_WAIT_MAX_S"
# Harte Grenze des Env-Overrides: mehr als das Intervall der strengsten Quelle
# (60s) kann nie sinnvoll sein, und ein Tippfehler soll keinen Request minutenlang
# schlafen lassen.
_PACE_WAIT_MAX_BOUND_S = 60.0
# Obergrenze jeder Sperr-Dauer (Default-Eskalation UND Retry-After-Header).
_COOLDOWN_CAP_S = 120.0
# Eskalationsfaktor je aufeinanderfolgender 429-Episode (Streak).
_COOLDOWN_FACTOR = 2.0

_semaphores: dict[str, asyncio.Semaphore] = {}
_rate_locks: dict[str, asyncio.Lock] = {}
_last_call_monotonic: dict[str, float] = {}
# Letzte Abweisung der Bremse je Quelle: Zeitpunkt (monotonic), ab dem der
# naechste Call frei waere. Nur fuer den Retry-After-Header der 503-Antwort;
# die Bremse selbst rechnet weiter aus _last_call_monotonic.
_pace_blocked_until: dict[str, float] = {}
# Slot-Zeitpunkt (monotonic) des EINEN Wartenden je Quelle, solange er schläft.
# Nur gesetzt, wenn wirklich gewartet wird; ein weiterer gleichzeitiger Call
# liest daraus, ab wann er selbst frühestens drankäme (Slot + Intervall).
_pace_waiter_slot: dict[str, float] = {}
# Cooldown-State je Quelle: Freigabe-Zeitpunkt (monotonic) + 429-Episoden-Streak.
_cooldown_until: dict[str, float] = {}
_cooldown_streak: dict[str, int] = {}

# Mockbare Indirektionen (Muster collector/retry._sleep): Tests patchen
# client_mod._now/_sleep und brauchen so weder echte Uhren noch echte Sleeps.
_now = time.monotonic
_sleep = asyncio.sleep


class SourceCooldownActive(Exception):
    """Signal: Quelle steckt in einer aktiven 429-Cooldown-Sperre (fail-fast).

    Leichtgewichtig und HTTP-agnostisch (Vorbild ``BreakerOpen``): wird in
    ``ResilientSourceClient.fetch`` auf den vorhandenen Stale-/None-Fallback
    gemappt (STALE-ON-ERROR bzw. 503 im API-Layer), es findet KEIN
    Upstream-Call statt.
    """

    _label = "cooldown aktiv"

    def __init__(self, source: str, remaining_s: float) -> None:
        super().__init__(f"{source}: {self._label}, noch {remaining_s:.1f}s")
        self.source = source
        self.remaining_s = remaining_s


class SourcePaceExceeded(SourceCooldownActive):
    """Signal: der Mindestabstand der Quelle wäre nur mit langem Warten zu halten.

    Erbt BEWUSST von ``SourceCooldownActive``: für den Rest der Kette ist das
    dasselbe Quota-Signal (kein Upstream-Call, Stale-oder-503, kein
    Breaker-Failure), nur die Ursache unterscheidet sich. Getrennte Klasse, damit
    Log und Fehlertext nicht "cooldown" behaupten, wo in Wahrheit die eigene
    Bremse gegriffen hat.
    """

    _label = "Mindestabstand aktiv"


def _source_semaphore(source: str) -> asyncio.Semaphore | None:
    """Lazy per-Source-Semaphore (None = unbegrenzt). Single-Loop-App: prozessweit."""
    limit = _SOURCE_MAX_CONCURRENCY.get(source)
    if limit is None:
        return None
    sem = _semaphores.get(source)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        _semaphores[source] = sem
    return sem


def _pace_wait_max_s() -> float:
    """Warte-Deckel des Mindestabstands, per Env übersteuerbar (0 bis 60 Sekunden).

    Der Wert wird bei jedem Aufruf gelesen (kein Modul-Cache): so wirkt eine
    Änderung an ``INFRANODE_SOURCE_PACE_WAIT_MAX_S`` per Container-Neustart ohne
    Deploy, und Tests setzen ihn per ``monkeypatch.setenv``. Unlesbare Werte
    fallen still auf den Default zurück (ein Tippfehler in der .env darf keine
    Quelle lahmlegen), zu grosse/kleine Werte werden auf 0..60 geklemmt.
    """
    raw = os.environ.get(_PACE_WAIT_MAX_ENV)
    if raw is None:
        return _PACE_MAX_WAIT_S
    try:
        value = float(raw)
    except ValueError:
        log.info("source_pace_wait_max_invalid", value=raw)
        return _PACE_MAX_WAIT_S
    return min(max(value, 0.0), _PACE_WAIT_MAX_BOUND_S)


async def _pace(source: str) -> None:
    """Erzwingt den Mindestabstand zwischen Calls einer Quelle (no-op ohne Eintrag).

    Restwartezeiten bis ``_pace_wait_max_s()`` werden abgewartet, damit Sweep-Jobs
    einfach langsamer laufen statt zu scheitern und damit eine Anfrage kurz vor
    dem nächsten freien Slot nicht unnötig als 503 endet. Darüber bricht der Call
    sofort mit ``SourcePaceExceeded`` ab, statt einen interaktiven Request
    minutenlang schlafen zu lassen.

    EIN Wartender je Quelle (Vorfall 2026-09-06): der Lock wird nur betreten,
    wenn der eigene Aufruf danach eine Chance hat. Wartet bereits jemand auf den
    nächsten Slot, käme ein weiterer Call frühestens ein Intervall NACH dessen
    Slot dran; liegt das über dem Deckel, wird er sofort abgewiesen, statt sich
    hinter dem Wartenden aufzureihen und erst nach dessen Schlaf einen 503 zu
    bekommen. Für Tankerkönig (60s Intervall, Deckel 20s) heisst das: höchstens
    ein Wartender, alle weiteren sofort 503 mit Retry-After. Für Quellen mit
    kurzem Intervall (db_timetables 1s, overpass 4s) bleibt die Schlange
    unverändert, dort liegt auch die Wartezeit hinter dem Wartenden unter dem
    Deckel.

    Der Zeitstempel wird beim Abweisen NICHT gesetzt: ein abgewiesener Call hat
    die Quelle nicht berührt und darf das Fenster des nächsten nicht verschieben.
    Der erste Call einer Quelle wartet nie (kein 0.0-Sentinel mehr, damit eine
    gepatchte Uhr in Tests keine Phantom-Wartezeit erzeugt).
    """
    interval = _SOURCE_MIN_INTERVAL_S.get(source)
    if not interval:
        return
    lock = _rate_locks.get(source)
    if lock is None:
        lock = asyncio.Lock()
        _rate_locks[source] = lock
    max_wait = _pace_wait_max_s()
    # Zwischen dieser Prüfung und ``async with lock`` liegt kein await: ein
    # freier asyncio.Lock wird ohne Umweg über den Scheduler erworben, der
    # Test ist also verlässlich (nicht-blockierender Erwerbsversuch).
    if lock.locked():
        slot = _pace_waiter_slot.get(source, _now())
        wait = slot + interval - _now()
        if wait > max_wait:
            _pace_blocked_until[source] = _now() + wait
            log.info(
                "source_pace_reject",
                source=source,
                remaining_s=round(wait, 1),
                reason="waiter_active",
            )
            raise SourcePaceExceeded(source, wait)
    async with lock:
        last = _last_call_monotonic.get(source)
        if last is not None:
            wait = interval - (_now() - last)
            if wait > max_wait:
                _pace_blocked_until[source] = _now() + wait
                log.info(
                    "source_pace_reject",
                    source=source,
                    remaining_s=round(wait, 1),
                    reason="interval",
                )
                raise SourcePaceExceeded(source, wait)
            if wait > 0:
                _pace_waiter_slot[source] = last + interval
                log.info("source_pace_wait", source=source, wait_s=round(wait, 1))
                try:
                    await _sleep(wait)
                finally:
                    _pace_waiter_slot.pop(source, None)
        _last_call_monotonic[source] = _now()


def retry_after_s(source: str) -> int | None:
    """Sekunden bis die Quelle wieder einen Call annimmt, fuer den Retry-After-Header.

    Liefert das Maximum aus der Restzeit der Aggregat-Bremse (letzte Abweisung
    in ``_pace``) und einer aktiven 429-Cooldown-Sperre, auf ganze Sekunden
    aufgerundet und mindestens 1. ``None``, wenn nichts von beidem aktiv ist:
    dann ist ein 503 ein echter Upstream-Fehler und kein Quota-Signal, und ein
    Retry-After waere eine erfundene Zahl. Rein lesend, veraendert keinen Zustand.
    """
    now = _now()
    remaining = 0.0
    blocked = _pace_blocked_until.get(source)
    if blocked is not None:
        remaining = max(remaining, blocked - now)
    until = _cooldown_until.get(source)
    if until is not None:
        remaining = max(remaining, until - now)
    if remaining <= 0:
        return None
    return max(1, math.ceil(remaining))


async def _cooldown_gate(source: str) -> None:
    """Wartet kurze Cooldown-Restsperren ab; lange Restsperren -> fail-fast.

    No-op für Quellen ohne Registry-Eintrag oder ohne aktive Sperre. Liegt
    BEWUSST VOR dem Semaphore-Erwerb: die Sperre ist quellen-global; wer
    während der Sperre im Semaphore säße, würde die Haltezeit unnötig strecken
    und nachfolgende Caller über den 12s-Deckel hinaus blockieren.
    """
    if source not in _SOURCE_429_COOLDOWN:
        return
    until = _cooldown_until.get(source)
    if until is None:
        return
    remaining = until - _now()
    if remaining <= 0:
        return
    if remaining > _COOLDOWN_MAX_WAIT_S:
        log.info(
            "source_cooldown_reject",
            source=source,
            remaining_s=round(remaining, 1),
        )
        raise SourceCooldownActive(source, remaining)
    log.info("source_cooldown_wait", source=source, wait_s=round(remaining, 1))
    await _sleep(remaining)


def _activate_cooldown(source: str, response: httpx.Response) -> float:
    """Setzt die Cooldown-Sperre nach einem 429 und liefert die Dauer (Sekunden).

    Dauer: Retry-After-Header, falls vorhanden und rein numerisch mit Wert >= 1
    (Sekunden-Form; HTTP-Datumsform und Header-Müll wie "0" oder "kaputt"
    fallen Zero-Trust-konform auf den Default zurück, nie Sperre < 1s aus
    Fremd-Input). Sonst Default * Faktor^(Streak-1). Ergebnis stets auf
    ``_COOLDOWN_CAP_S`` gekappt und >= 1.0 floored.
    """
    streak = _cooldown_streak.get(source, 0) + 1
    _cooldown_streak[source] = streak
    header = response.headers.get("Retry-After", "").strip()
    from_header = header.isdigit() and int(header) >= 1
    if from_header:
        duration = float(header)
    else:
        duration = _SOURCE_429_COOLDOWN[source] * _COOLDOWN_FACTOR ** (streak - 1)
    duration = max(1.0, min(duration, _COOLDOWN_CAP_S))
    _cooldown_until[source] = _now() + duration
    # Beobachtbarkeit (Owner-Rahmen Punkt 4): nur Quelle/Dauer/Status/Streak,
    # KEIN Response-Body und keine URLs ins Log.
    log.warning(
        "source_429_cooldown",
        source=source,
        cooldown_s=duration,
        status=response.status_code,
        streak=streak,
        retry_after_header=bool(from_header),
    )
    return duration


def _reset_cooldown(source: str) -> None:
    """Erfolgreicher Call -> Streak zurücksetzen (nächste Episode startet beim Default).

    Der Sperr-Zeitpunkt darf stehen bleiben: nach einem Erfolg liegt er ohnehin
    in der Vergangenheit und das Gate ignoriert ihn.
    """
    _cooldown_streak.pop(source, None)


def _is_quota_signal(source: str, exc: BaseException) -> bool:
    """True für Quota-Signale, die NICHT als Breaker-Failure zählen dürfen.

    Quota-Signale sind ``SourceCooldownActive`` sowie ein 429 einer Quelle mit
    Cooldown-Registry-Eintrag. Quota-Wellen dürfen den Breaker nicht öffnen,
    sonst BreakerOpen-503 für ALLE POI-Typen inkl. interaktiver Nutzer
    (Vorfall 2026-07-11). Echte Fehler (5xx, Timeouts) zählen unverändert.
    """
    if isinstance(exc, SourceCooldownActive):
        return True
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code == 429
        and source in _SOURCE_429_COOLDOWN
    )


async def _run_limited(source: str, fetch_fn: Callable[[], Awaitable]):
    """Fuehrt ``fetch_fn`` unter Cooldown-Gate + Concurrency + Mindestabstand aus.

    Ein 429 einer Cooldown-Quelle aktiviert die Sperre und wird UNVERÄNDERT
    re-raist (kein blinder Sofort-Retry: die 30s-Default-Sperre liegt bewusst
    über dem 12s-Warte-Deckel; die Wiederholung liefert der Collector via
    run_with_retry, interaktive Caller fallen ehrlich in Stale/503).
    """
    await _cooldown_gate(source)
    sem = _source_semaphore(source)
    try:
        if sem is None:
            await _pace(source)
            result = await fetch_fn()
        else:
            async with sem:
                await _pace(source)
                result = await fetch_fn()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429 and source in _SOURCE_429_COOLDOWN:
            _activate_cooldown(source, exc.response)
        raise
    if source in _SOURCE_429_COOLDOWN:
        _reset_cooldown(source)
    return result


class ResilientSourceClient:
    """Fassade: kombiniert Pool + Cache + SWR + Single-Flight + Breaker zu fetch().

    Args:
        http: prozessweiter, gepoolter ``httpx.AsyncClient`` (app.state.http).
        redis: redis.asyncio-kompatibler Client (app.state.redis).
        breakers: prozessweite ``BreakerRegistry`` (app.state.breakers). Default:
            eine frische Registry (Breaker-State lebt dann nur für diese
            Instanz; in der App wird eine geteilte Registry injiziert, damit der
            Breaker-State request-übergreifend lebt).
        schedule: plant die SWR-Background-Refresh-Coroutine (Default: der
            asyncio-Task-Halter aus ``cache_get_or_set``).
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        redis,
        breakers: BreakerRegistry | None = None,
        schedule: Callable[[Awaitable], None] | None = None,
    ) -> None:
        self._http = http
        self._redis = redis
        self._breakers = breakers if breakers is not None else BreakerRegistry()
        self._schedule = schedule

    async def fetch(
        self,
        source: str,
        key: str,
        fetch_fn: Callable[[], Awaitable],
        *,
        store: bool = True,
    ):
        """Hole Daten der Quelle ``source`` unter ``key`` (resilient, nie blockierend).

        Reihenfolge: Cache (HIT/STALE/MISS) um eine Breaker-geschützte
        Upstream-Coroutine. Bei OPEN-Breaker oder Upstream-Fehler -> last-cache-
        Fallback (STALE-ON-ERROR) bzw. ``(None, STALE-ON-ERROR)``.

        Args:
            store: Wenn ``False``, läuft der Call ON-DEMAND: KEIN Redis-Read/Write,
                kein Stale-Fallback, kein SWR-Background-Refresh; nur der
                Breaker-Schutz um den Live-Call bleibt. Für Quellen, deren ToS
                das Spiegeln/Vorhalten verbieten (Tankerkoenig/MTS-K): Daten nur
                live bei Useraktion, nie zwischengespeichert (T-08-CRED-Folge).

        Returns:
            ``(payload, status)``-Tupel (nie None). ``status`` ist ein
            ``CacheStatus``-String (HIT/MISS/STALE/STALE-ON-ERROR).
        """
        breaker = self._breakers.get(source)
        # Optionale Redis-Persistenz des Breaker-States (RedisBreakerRegistry, C-2026):
        # hydrate ZIEHT den prozessübergreifenden State vor der Entscheidung, persist
        # SCHREIBT ihn nach jedem record_*. Duck-Typing -> die schlanke in-memory
        # BreakerRegistry (Tests/Fallback) bleibt völlig unverändert (keine Methoden).
        hydrate = getattr(self._breakers, "hydrate", None)
        persist = getattr(self._breakers, "persist", None)
        if hydrate is not None:
            await hydrate(source, breaker)

        async def refresh():
            # Breaker pro Quelle, aber EIN geteilter Pool (RES-01/04).
            if not breaker.allow_request():
                raise BreakerOpen(source)
            try:
                result = await _run_limited(source, fetch_fn)
            except Exception as exc:
                # Quota-Signale (429 einer Cooldown-Quelle, SourceCooldownActive)
                # zählen NICHT als Breaker-Failure: Quota-Wellen dürfen den
                # Breaker nicht öffnen, sonst BreakerOpen-503 für ALLE POI-Typen
                # inkl. interaktiver Nutzer (Vorfall 2026-07-11). Alle anderen
                # Exceptions zählen unverändert.
                if not _is_quota_signal(source, exc):
                    breaker.record_failure()
                    if persist is not None:
                        await persist(source, breaker)
                raise
            breaker.record_success()
            if persist is not None:
                await persist(source, breaker)
            return result

        if not store:
            # ON-DEMAND (kein Redis-Read/Write, kein Stale, kein SWR-Refresh): nur
            # der Live-Call hinter dem Breaker. Anbieter-ToS, die Spiegeln/Vorhalten
            # verbieten (Tankerkoenig/MTS-K), erlauben nur Live-Abruf bei Useraktion.
            try:
                result = await refresh()
                await incr_cache_status(self._redis, CacheStatus.MISS)
                return result, CacheStatus.MISS
            except (BreakerOpen, SourceCooldownActive, httpx.HTTPError) as exc:
                log.info(
                    "resilient_fetch_fallback",
                    source=source,
                    key=key,
                    has_stale=False,
                    error=type(exc).__name__,
                )
                await incr_cache_status(self._redis, CacheStatus.STALE_ON_ERROR)
                return None, CacheStatus.STALE_ON_ERROR

        try:
            ttl_fresh, ttl_stale = _SOURCE_TTL.get(source, _DEFAULT_TTL)
            result = await cache_get_or_set(
                self._redis,
                key,
                ttl=_jittered_fresh(source, _profiled_fresh(source, ttl_fresh)),
                ttl_stale=ttl_stale,
                fetch=refresh,
                schedule=self._schedule,
                keep_extra_s=_SOURCE_EMERGENCY_KEEP.get(source, 0.0),
            )
            # Cache-Status-Counter am EINZIGEN Chokepoint (OPS-02). result[1] ist
            # der rohe Status-str (HIT/MISS/STALE); incr_cache_status ist intern
            # try/except-gekapselt (13-01) und kann den fetch-Pfad nie blockieren.
            # NOCH IM try-Block, damit das except-Verhalten unten unverändert bleibt.
            await incr_cache_status(self._redis, result[1])
            return result
        except (BreakerOpen, SourceCooldownActive, httpx.HTTPError) as exc:
            # Upstream tot, Breaker offen ODER Cooldown-Sperre aktiv:
            # last-cache-Fallback statt Block.
            stale = await _last_cache(self._redis, key)
            # Beobachtbarkeit der Stufen: "stale" = innerhalb des Stale-Fensters,
            # "emergency_stale" = nur noch dank Notreserve vorhanden (jenseits
            # von stale_until, siehe _SOURCE_EMERGENCY_KEEP). Der Meta-Read ist
            # best effort: schlaegt er fehl, bleibt das Feld schlicht "stale".
            tier = "stale"
            if stale is not None:
                meta = await read_entry_meta(self._redis, key)
                if meta is not None and time.time() > meta.stale_until:
                    tier = "emergency_stale"
            log.info(
                "resilient_fetch_fallback",
                source=source,
                key=key,
                has_stale=stale is not None,
                served=tier if stale is not None else "none",
                error=type(exc).__name__,
            )
            # Auch der Fallback-Pfad zählt am Chokepoint (STALE-ON-ERROR-Bucket).
            await incr_cache_status(self._redis, CacheStatus.STALE_ON_ERROR)
            return stale, CacheStatus.STALE_ON_ERROR
