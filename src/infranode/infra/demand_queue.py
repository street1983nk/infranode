"""Nachfragegetriebene Warteschlange fuer Quellen mit strenger Aggregat-Bremse.

Warum es diese Warteschlange gibt (RCA 2026-09-15, Owner-Entscheid):
Tankerkoenig erlaubt EINE Upstream-Anfrage je Minute fuer ALLE Staedte
zusammen. Die Aggregat-Bremse in ``resilience/client.py`` haelt dieses Limit
zuverlaessig ein, vergibt den Slot aber ausschliesslich im Moment einer
Anfrage. Der Hauptverkehr auf ``/fuel-prices`` ist ein externer Sweeper, der
die rund 84 Staedte im Block abfragt: von seinen 84 Anfragen gewinnen ein bis
zwei den Slot der Minute, der Rest verfaellt ungenutzt. Rechnerisch braucht es
rund 42 Auffrischungen je Tag (84 Staedte bei 48 Stunden Key-Lebensdauer),
erreicht wurden 10 bis 15. Also fiel eine Stadt nach der anderen ueber die
48-Stunden-Klippe und lieferte danach dauerhaft 503. Die Kapazitaet ist
reichlich (1.440 Slots je Tag), die ZUTEILUNG war das Problem.

ToS-Grundlage (der eigentliche Kern dieses Entwurfs): Die
Tankerkoenig-Nutzungsbedingungen (Wortlaut geprueft 2026-07-25) verlangen
"Requests on Demand, auf Useraktion" und "Regelmaessige, nicht explizit vom
User initiierte Requests sind zu vermeiden". Ein Timer, der von sich aus
Staedte abholt, waere genau so ein nicht user-initiierter Request. Diese
Warteschlange dreht das um: ein Eintrag entsteht AUSSCHLIESSLICH dann, wenn
eine echte Nutzeranfrage den Slot der Minute verloren hat. Jeder spaetere
Upstream-Abruf geht also auf eine belegte Useraktion zurueck, er wird nur
zeitversetzt beantwortet. Eine Stadt, die niemand abfragt, landet nie in der
Warteschlange und laeuft aus. Das ist gewollt: nichts wird auf Vorrat geholt,
nichts gespiegelt, nichts dauerhaft vorgehalten.

Datenmodell (Redis Sorted Set je Quelle, ``demand:{source}``):
- Member = Stadt-Slug, Score = Zeitpunkt der ERSTEN unbeantworteten Nachfrage.
- Dedupliziert je Stadt (Set-Semantik): ``ZADD NX`` laesst den urspruenglichen
  Zeitpunkt stehen, wiederholte Nachfrage schiebt eine wartende Stadt also
  nicht ans Ende (keine Aushungerung) und verlaengert ihre Verfallszeit nicht.
- Verfallszeit ``_TTL_S`` (6 h): danach ist die Nachfrage veraltet, niemand
  wartet mehr auf die Antwort, der Eintrag faellt weg. Umgesetzt beim Schreiben
  UND beim Lesen ueber ``ZREMRANGEBYSCORE``; zusaetzlich traegt der Key selbst
  ein ``EXPIRE``, damit eine stillgelegte Quelle keinen Muell hinterlaesst.
- Harte Obergrenze ``_MAX_ENTRIES``: das Register hat 84 Staedte, mehr kann es
  also gar nicht geben. Die Kappe ist trotzdem eingezogen (Zero-Trust gegen
  einen kuenftigen Registerwuchs oder einen Fehler im Aufrufer); bei Ueberlauf
  fliegt die JUENGSTE Nachfrage raus, die aelteste Wartende bleibt.

Fehlerverhalten: ALLE Funktionen sind fail-open. Ist Redis nicht erreichbar,
wird still nicht eingereiht bzw. nichts gelesen; der Antwortpfad der API bleibt
davon unberuehrt. Eine kaputte Warteschlange darf nie eine Nutzerantwort
kosten.
"""

from __future__ import annotations

import time

import structlog

log = structlog.get_logger()

# Verfallszeit einer Nachfrage in Sekunden (6 h). Danach ist die Useraktion, die
# den Eintrag ausgeloest hat, so alt, dass eine Antwort niemandem mehr nuetzt.
_TTL_S = 6 * 60 * 60.0

# Harte Obergrenze der Eintraege je Quelle. 84 Register-Staedte sind das
# natuerliche Maximum; die Kappe liegt knapp darueber und begrenzt den Schaden,
# falls das Register waechst oder ein Aufrufer Unsinn einreiht.
_MAX_ENTRIES = 100


def queue_key(source: str) -> str:
    """Redis-Key der Warteschlange einer Quelle.

    Der Key traegt NUR den Quellennamen, nie einen API-Key und nie Nutzerdaten
    (gleiche Regel wie ``infra.cache.build_cache_key``).
    """
    return f"demand:{source}"


async def enqueue(redis, *, source: str, slug: str, now: float | None = None) -> bool:
    """Reiht eine Stadt ein, deren Nutzeranfrage den Slot der Minute verlor.

    NUR aus dem Verlustpfad aufrufen (503 mit Retry-After oder ausgelieferte
    Notreserve STALE-ON-ERROR), NIE bei HIT oder frischem Fetch: sonst waere der
    spaetere Abruf nicht mehr durch eine unbeantwortete Useraktion gedeckt.

    Vier Schritte in einer Pipeline (ein Roundtrip, kein Lua noetig, keine
    Atomaritaetsanforderung ueber die Schritte hinweg):
    1. Verfallene Eintraege raeumen,
    2. ``ZADD NX``: dedupliziert, der erste Nachfragezeitpunkt gewinnt,
    3. Kappe: alles jenseits von ``_MAX_ENTRIES`` faellt weg, und weil der Rang
       nach Score aufsteigt, trifft es die juengste Nachfrage (im Ueberlauf also
       genau die gerade eingereihte), nie die am laengsten Wartende,
    4. ``EXPIRE`` auf den Key als Rueckfall-Aufraeumung.

    Returns:
        ``True``, wenn der Schreibvorgang durchlief; ``False`` bei jedem Fehler
        (Redis weg, Protokollfehler). ``True`` heisst NICHT, dass der Slug neu
        war: ein bereits wartender Slug ist ein erwarteter, erfolgreicher Lauf.
    """
    moment = time.time() if now is None else now
    key = queue_key(source)
    try:
        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, "-inf", moment - _TTL_S)
        pipe.zadd(key, {slug: moment}, nx=True)
        pipe.zremrangebyrank(key, _MAX_ENTRIES, -1)
        pipe.expire(key, int(_TTL_S))
        await pipe.execute()
    except Exception as exc:
        # Fail-open: die Nutzerantwort haengt nicht an der Warteschlange.
        log.info(
            "demand_queue_enqueue_failed",
            source=source,
            city_slug=slug,
            error=type(exc).__name__,
        )
        return False
    return True


async def peek(redis, *, source: str, now: float | None = None) -> str | None:
    """Liest die am laengsten wartende Stadt, ohne sie zu entfernen.

    Raeumt vorher die verfallenen Eintraege weg, damit eine veraltete Nachfrage
    nicht doch noch einen Upstream-Abruf ausloest. Entfernt wird der Eintrag
    erst nach einem erfolgreichen Abruf (``drop``); ein fehlgeschlagener Abruf
    laesst ihn stehen, begrenzt durch die Verfallszeit.

    Returns:
        Den Stadt-Slug oder ``None`` (leere Warteschlange ODER Redis-Fehler).
        Beides heisst fuer den Aufrufer dasselbe: nichts zu tun.
    """
    moment = time.time() if now is None else now
    key = queue_key(source)
    try:
        await redis.zremrangebyscore(key, "-inf", moment - _TTL_S)
        entries = await redis.zrange(key, 0, 0)
    except Exception as exc:
        log.info("demand_queue_peek_failed", source=source, error=type(exc).__name__)
        return None
    if not entries:
        return None
    first = entries[0]
    return first.decode() if isinstance(first, bytes) else str(first)


async def drop(redis, *, source: str, slug: str) -> bool:
    """Entfernt eine Stadt aus der Warteschlange (Nachfrage ist beantwortet).

    Wird NUR nach einem erfolgreichen Abruf gerufen. Scheitert das Entfernen,
    bleibt der Eintrag stehen und wird spaetestens ueber die Verfallszeit
    aufgeraeumt; ein doppelter Abruf kostet hoechstens einen Slot, ein
    verlorener Eintrag koennte dagegen eine Stadt zurueck in die 503-Falle
    schicken.
    """
    try:
        await redis.zrem(queue_key(source), slug)
    except Exception as exc:
        log.info(
            "demand_queue_drop_failed",
            source=source,
            city_slug=slug,
            error=type(exc).__name__,
        )
        return False
    return True


async def pending(redis, *, source: str, now: float | None = None) -> int:
    """Anzahl der noch nicht verfallenen Nachfragen (Beobachtbarkeit).

    Fuer Logzeilen und Tests. Fehler ergeben ``0``, nie eine Ausnahme.
    """
    moment = time.time() if now is None else now
    key = queue_key(source)
    try:
        await redis.zremrangebyscore(key, "-inf", moment - _TTL_S)
        return int(await redis.zcard(key))
    except Exception as exc:
        log.info("demand_queue_pending_failed", source=source, error=type(exc).__name__)
        return 0
