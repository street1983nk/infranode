"""Keyloser UBA-Adapter fetch_air_uba (DATA-10, Tier A).

Lädt Luftqualitäts-Messwerte vom keylosen Umweltbundesamt-
Air-Data-API über den gepoolten httpx-Client. Zwei-Schritt-Flow:

1. ``GET /stations/json`` liefert alle Messstationen; der Adapter sortiert sie
   nach Grad-Distanz zu (``lat``, ``lon``) (kein Haversine, vgl.
   ``autobahn._within_bbox``: Don't-Hand-Roll) und hält die N nächsten.
2. ``GET /measures/json`` liefert je v3-Komponente (PM10/PM2.5/NO2/O3/SO2) die
   Stundenwerte; der Adapter nimmt je Komponente den jüngsten Messzeitpunkt.

KRITISCH (Audit K4): Nicht jede Station misst jede Komponente. Verkehrsnahe
Stationen führen z.B. kein O3. Würde für ALLE Komponenten nur die EINE
nächste Station abgefragt, fielen o3/so2 unnötig auf ``None``, obwohl eine
Nachbarstation wenige Kilometer weiter den Wert hat. Daher fährt der Adapter
PRO Komponente eine Fallback-Kaskade über die ``_FALLBACK_STATIONS`` nächsten
Stationen, bis ein aktueller Wert gefunden ist. Findet keine nahe Station eine
Komponente (typisch SO2), bleibt der Wert ehrlich ``None``.

Rückgabe ist ein flaches raw-dict, das auf das bestehende ``AirQualityPayload``
passt: ``slug``/``station_id``/``lat``/``lon``/``observed_at``/``pm10``/``pm25``/
``no2``/``o3``/``so2`` (fehlender Wert -> ``None``, T-07-IN).

KRITISCH (Lizenz-Klassifikation): UBA ist Tier A (offene Lizenz) und wird über
die Route ``/air-uba`` (archivierter Tier-A-Bestand) sowie über den älteren,
nicht persistierten Pfad ``/air`` ausgeliefert. UBA ist die einzige
Luftqualitätsquelle und liefert alle fünf Schadstoffe.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (T-07-IN, SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon
stammen aus dem validierten Register und fließen nur als Query-Parameter ein.
Das verschachtelte UBA-measures-Format wird defensiv gelesen (keine festen
Index-Zugriffe ohne Guard): ein fehlerhaftes/leeres Feld liefert ``None`` statt
einen KeyError/IndexError auszulösen.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime

import httpx
import structlog

# Host hartkodiert (T-07-IN SSRF): nur diese eine öffentliche UBA-Instanz.
# 2026-06-13: UBA-Luftdaten-API umgezogen. Der alte Host www.umweltbundesamt.de
# /api/air_data antwortet mit 301 auf luftdaten.umweltbundesamt.de/api/air-data
# (Unterstrich -> Bindestrich); der Adapter folgt Redirects bewusst nicht (SSRF),
# daher lief er ins Leere. Neue Basis verifiziert: stations/components/measures = 200.
log = structlog.get_logger()

_BASE = "https://luftdaten.umweltbundesamt.de/api/air-data/v3"

# v3-Komponenten-IDs (Adapter-lokal). Korrektes Schema: 1=PM10, 9=PM2,5,
# 5=NO2, 3=O3, 4=SO2. Wert-Key im raw-dict je Komponente. Am 2026-06-26 live gegen
# components/json (autoritativ) und measures/json verifiziert (Station 143).
# Das frühere Mapping (pm25=5, no2=3, o3=7) war falsch und lieferte systematisch
# vertauschte Werte (pm25 zog NO2, no2 zog O3, o3 zog den leeren BaP-Kanal).
# SO2 (component 4) wird an vielen Stationen stündlich nicht gemessen
# (scope 2 leer) -> so2=None ist dort ehrlich korrekt, kein Bug.
_COMPONENTS: dict[str, int] = {"pm10": 1, "pm25": 9, "no2": 5, "o3": 3, "so2": 4}

# Stunden-Mittelwert-Scope (UBA scope-id 2). Adapter-lokal hartkodiert.
_SCOPE = 2

# Anzahl der nächsten AKTIVEN Stationen, über die je Komponente eine Fallback-
# Kaskade fährt (Audit K4). Die Kaskade bricht je Komponente beim ersten Treffer
# ab -> für Städte, deren nächste Station meldet, bleibt es bei 1 Request;
# nur bei Lücken werden mehr Stationen probiert. 10 statt 5 (Audit-Rerun-Followup
# 2026-06-30): in Frankfurt liefern die 8 nächsten aktiven Stationen zeitweise
# GAR NICHTS, erst die 9.-nächste (669 "Friedberger Landstraße", ~1,7 km, also
# weiterhin im Stadtgebiet) meldet -> mit Tiefe 5 kam /air dort leer/null zurück.
_FALLBACK_STATIONS = 10


def _deg_distance(alat: float, alon: float, blat: float, blon: float) -> float:
    """Einfache breitengrad-korrigierte Grad-Distanz für die Stationsauswahl.

    Bewusst KEIN Haversine (Don't-Hand-Roll, vgl. autobahn._within_bbox): für die
    grobe Auswahl der nächsten Messstation reicht eine euklidische Grad-Distanz
    mit ``cos(lat)``-korrigierter Längen-Achse.
    """
    cos_lat = math.cos(math.radians(alat))
    dlat = blat - alat
    dlon = (blon - alon) * cos_lat
    return math.hypot(dlat, dlon)


def _nearest_stations(
    stations: dict,
    lat: float,
    lon: float,
    *,
    limit: int,
    today: str | None = None,
    measuring: frozenset[str] | None = None,
) -> list[tuple[str, float, float]]:
    """Liefert die ``limit`` nächsten AKTIVEN Stationen zu (lat, lon), nach Distanz.

    ``indices`` ist die Spaltennamen-Liste, ``data`` ein dict
    ``station_id -> Werte-Array`` in ``indices``-Reihenfolge. Defensive Lesung:
    Stationen ohne gültige Koordinaten werden übersprungen. Rückgabe je Station
    ``(station_id, lat, lon)``; die erste ist die nächste (Audit K4: Basis für
    die Pro-Komponenten-Fallback-Kaskade).

    Audit-Rerun (2026-06-29): STILLGELEGTE Stationen werden ausgeschlossen. Das
    Feld ``station active to`` trägt das Betriebsende (``None``/leer = aktiv). Ohne
    diesen Filter wählt die reine Distanz z.B. die DDR-Altstation "Alex_MD"
    (aktiv bis 1990) als nächste Berlin-Station, die DEBW-Station in Hamburg
    (bis 2013) bzw. Frankfurt-Römerberg (bis 2023) - alle liefern dann
    durchgängig ``null`` (observed_at null), obwohl aktive Stationen wenige km
    weiter messen. ``today`` (ISO ``YYYY-MM-DD``) ist injizierbar (Tests);
    Default = heute (UTC). Fehlt die Spalte, wird nicht gefiltert (Format-Toleranz).
    """
    indices = stations.get("indices") or []
    try:
        lon_idx = indices.index("station longitude")
        lat_idx = indices.index("station latitude")
    except ValueError:
        # Format unerwartet -> keine Auswahl möglich.
        raise httpx.HTTPError("UBA /stations/json: erwartete Spalten fehlen") from None

    try:
        active_to_idx: int | None = indices.index("station active to")
    except ValueError:
        active_to_idx = None
    if today is None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")

    candidates: list[tuple[float, str, float, float]] = []
    active: list[tuple[float, str, float, float]] = []
    for station_id, row in (stations.get("data") or {}).items():
        if not isinstance(row, list) or len(row) <= max(lon_idx, lat_idx):
            continue
        try:
            slon = float(row[lon_idx])
            slat = float(row[lat_idx])
        except (TypeError, ValueError):
            continue
        entry = (_deg_distance(lat, lon, slat, slon), str(station_id), slat, slon)
        candidates.append(entry)
        # Aktiv = kein Enddatum ODER Enddatum >= heute (ISO-Strings sortieren korrekt).
        active_to = (
            row[active_to_idx]
            if active_to_idx is not None and len(row) > active_to_idx
            else None
        )
        if not active_to or str(active_to) >= today:
            active.append(entry)

    # Messende Stationen bevorzugen, dann aktive, dann alle: jede Stufe ist ein
    # Rückfall, nie ein Fehler. ``measuring`` kommt aus ``_measuring_stations``
    # und ist leer, wenn die Liste nicht zu holen war; dann greift exakt das
    # Verhalten von vor dem 2026-09-17.
    # Warum die Stufe überhaupt nötig ist (Vorfall 2026-09-17): "station active
    # to" ist KEINE Aussage darüber, ob eine Station heute Werte liefert. Station
    # 1195 (Köln) und 881 (Rostock) gelten dort als aktiv, stehen aber nicht in
    # der Messliste des Tages und antworten auf jede measures-Abfrage mit einem
    # leeren Datenblock. Der Adapter fuhr deshalb die volle Kaskade (fünf
    # Komponenten mal zehn Stationen = bis zu 50 Abfragen je Stadt) vergeblich,
    # und genau dieser Burst hat den 429 der Quelle ausgelöst.
    measuring_pool = (
        [entry for entry in active if entry[1] in measuring] if measuring else []
    )
    pool = measuring_pool or active or candidates
    if not pool:
        raise httpx.HTTPError("UBA /stations/json: keine Station mit Koordinaten")

    pool.sort(key=lambda c: c[0])
    return [(sid, slat, slon) for _, sid, slat, slon in pool[:limit]]


def _nearest_station(
    stations: dict, lat: float, lon: float
) -> tuple[str, float, float]:
    """Naechste Station zu (lat, lon) als ``(station_id, lat, lon)``.

    Dünner Kompatibilitäts-Wrapper um ``_nearest_stations`` (limit=1) für
    Aufrufer, die genau die EINE nächste Station brauchen (z.B. der
    Quality-Backfill, der je Komponente kein Nachbarstation-Fallback fahrt).
    """
    return _nearest_stations(stations, lat, lon, limit=1)[0]


def _latest_value(measures: dict, station_id: str) -> tuple[float | None, str | None]:
    """Liest defensiv den jüngsten GEFÜLLTEN Messwert + Zeitpunkt aus dem Body.

    ``data`` ist ``station_id -> {datetime: [component_id, scope_id, value, ...]}``.
    Rückgabe (value, observed_at_iso) der spätesten Zeitscheibe MIT Wert; bei
    leerem/fehlerhaftem Body ``(None, None)`` statt KeyError/IndexError (T-07-IN).

    Warum nicht einfach die späteste Zeitscheibe (Vorfall 2026-09-17): die
    Quelle legt die laufende Stunde bereits als Scheibe an und trägt den Wert
    erst nach, ``[1, 2, None, "2026-09-17 18:00:00", None]``. Wer stur
    ``max(keys)`` nimmt, liest an einer voll messenden Station ``None``, obwohl
    17 gefüllte Stunden darunter liegen. Der Aufrufer wertete das als "Station
    hat nichts" und kaskadierte durch alle zehn Nachbarstationen mal fünf
    Komponenten - dieser Burst war es, der den 429 der Quelle auslöste, und
    genau deshalb standen Städte wie Schwerin und Hannover trotz messender
    Station auf einem leeren Datenblock.
    """
    by_time = (measures.get("data") or {}).get(station_id) or {}
    if not isinstance(by_time, dict) or not by_time:
        return None, None

    # Absteigend über die Zeitscheiben, bis eine einen echten Wert trägt. Der
    # Zeitstempel gehört zum gefundenen Wert, nicht zur leeren Scheibe darüber.
    value: float | None = None
    latest_key: str | None = None
    for key in sorted(by_time.keys(), reverse=True):
        row = by_time.get(key)
        if not isinstance(row, list) or len(row) < 3:
            continue
        try:
            value = float(row[2])
        except (TypeError, ValueError):
            continue
        latest_key = key
        break

    if latest_key is None:
        return None, None

    # UBA-Zeitstempel "YYYY-MM-DD HH:MM:SS" -> ISO-8601 UTC.
    observed_at: str | None = None
    try:
        observed_at = (
            datetime.strptime(latest_key, "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=UTC)
            .isoformat()
        )
    except (TypeError, ValueError):
        observed_at = None

    return value, observed_at


# Messliste des Tages: Stations-IDs, die im Tagesfenster ueberhaupt Werte
# fuehren. Prozess-lokal je Tag gehalten, weil die Liste ueber den Tag stabil ist
# und rund 500 KB gross. Der Cache haelt genau einen Tag; ein Tageswechsel
# raeumt den alten Eintrag weg.
_MEASURING_CACHE: dict[str, frozenset[str]] = {}

# Single-Flight fuer den Messlisten-Abruf. Ohne ihn startet JEDE gleichzeitige
# Stadtabfrage ihren eigenen Abruf, solange der Cache noch leer ist: der
# Collector faehrt alle 84 Staedte parallel an, und am 2026-09-17 um 18:32:00
# schlugen dadurch binnen einer Sekunde vier Messlisten-Abrufe und vierzehn 429
# der Quelle auf. Mit dem Lock holt genau ein Aufruf die Liste, alle anderen
# warten kurz und lesen sie dann aus dem Cache.
_MEASURING_LOCK = asyncio.Lock()

# Kurze Sperre nach einem Fehlschlag. Ohne sie rennt dieselbe Welle sofort
# wieder los und haelt das Quota der Quelle unten. Eine Minute ist kurz genug,
# dass sich ein Abruf im selben Collector-Zyklus noch erholen kann.
_MEASURING_FAIL_COOLDOWN_S = 60.0
_MEASURING_FAILED_UNTIL: dict[str, float] = {}

# Kuerzer als bei der Messliste, und das mit Absicht: ohne Stationsliste
# scheitert JEDER Stadtabruf, und die Sperre leert sich nur ueber einen
# erfolgreichen Abruf, den sie selbst so lange verhindert. Sie soll den Ansturm
# einer Welle abfangen, nicht die Erholung um eine Minute verzoegern. Fuer die
# Messwerte gilt dasselbe.
_STATIONS_FAIL_COOLDOWN_S = 10.0
_MEASURES_FAIL_COOLDOWN_S = 10.0

# Deckel fuer den Metadaten-Abruf. Er ist die groesste Antwort der Quelle und
# darf einen Stadtabruf nicht aufhalten: laeuft er in den Deckel, faellt der
# Adapter auf die alte Auswahl zurueck, statt den Abruf scheitern zu lassen.
_META_TIMEOUT_S = 15.0


async def _measuring_stations(http: httpx.AsyncClient, *, today: str) -> frozenset[str]:
    """Stations-IDs, die am Tag ``today`` tatsaechlich Messwerte fuehren.

    Quelle ist ``GET {_BASE}/meta/json?use=measure`` mit demselben Tagesfenster
    wie die Messabfragen. Die Antwort traegt unter ``stations`` nur die Stationen
    mit Messbetrieb im Fenster (am 2026-09-17: 420 von 2400 aus
    ``stations/json``).

    Rueckgabe ist bewusst eine leere Menge, wenn die Liste nicht zu holen ist:
    der Aufrufer filtert dann nicht und verhaelt sich wie zuvor. Jede Stoerung
    der Zusatzabfrage degradiert also still, sie darf den Stadtabruf nie
    scheitern lassen.

    Der Abruf laeuft unter ``_MEASURING_LOCK`` (Single-Flight): der erste
    Aufrufer holt die Liste, alle gleichzeitigen warten und lesen danach den
    Cache. Ein Fehlschlag sperrt den Abruf fuer ``_MEASURING_FAIL_COOLDOWN_S``,
    damit dieselbe Welle nicht sofort erneut gegen die Quelle laeuft.
    """
    cached = _MEASURING_CACHE.get(today)
    if cached is not None:
        return cached
    if _MEASURING_FAILED_UNTIL.get(today, 0.0) > time.monotonic():
        return frozenset()

    async with _MEASURING_LOCK:
        # Zweite Pruefung unter dem Lock: waehrend des Wartens kann ein anderer
        # Aufrufer die Liste geholt oder die Sperre gesetzt haben.
        cached = _MEASURING_CACHE.get(today)
        if cached is not None:
            return cached
        if _MEASURING_FAILED_UNTIL.get(today, 0.0) > time.monotonic():
            return frozenset()
        return await _fetch_measuring_stations(http, today=today)


async def _fetch_measuring_stations(
    http: httpx.AsyncClient, *, today: str
) -> frozenset[str]:
    """Holt die Messliste EINMAL und legt sie ab; nur aus ``_measuring_stations``.

    Getrennt gehalten, damit der Lock-Abschnitt oben lesbar bleibt. Jeder
    Fehlschlag degradiert still auf die leere Menge und setzt die kurze Sperre.
    """
    try:
        resp = await http.get(
            f"{_BASE}/meta/json",
            params={
                "use": "measure",
                "lang": "de",
                "date_from": today,
                "time_from": "1",
                "date_to": today,
                "time_to": "24",
            },
            timeout=_META_TIMEOUT_S,
        )
        resp.raise_for_status()
        rows = resp.json().get("stations") or {}
        ids = frozenset(str(key) for key in rows)
    except Exception as exc:  # jede Stoerung faellt auf das alte Verhalten zurueck
        _MEASURING_FAILED_UNTIL[today] = time.monotonic() + _MEASURING_FAIL_COOLDOWN_S
        log.warning(
            "uba_measuring_list_unavailable",
            error=type(exc).__name__,
            cooldown_s=_MEASURING_FAIL_COOLDOWN_S,
        )
        return frozenset()
    if not ids:
        _MEASURING_FAILED_UNTIL[today] = time.monotonic() + _MEASURING_FAIL_COOLDOWN_S
        log.warning("uba_measuring_list_empty", day=today)
        return frozenset()
    _MEASURING_CACHE.clear()
    _MEASURING_FAILED_UNTIL.clear()
    _MEASURING_CACHE[today] = ids
    return ids


# Stationsliste des Tages. Sie ist Stammdatenbestand, aendert sich innerhalb
# eines Tages praktisch nicht und ist mit rund 560 KB die zweitgroesste Antwort
# der Quelle. Vorfall 2026-09-17: sie wurde fuer JEDE der 84 Staedte neu geholt,
# also rund 47 MB je Collector-Lauf, alles in derselben Sekunde. Genau wie bei
# der Messliste holt sie jetzt ein Aufrufer je Tag, alle anderen warten kurz.
_STATIONS_CACHE: dict[str, dict] = {}
_STATIONS_LOCK = asyncio.Lock()
_STATIONS_FAILED_UNTIL: dict[str, float] = {}


async def _stations_payload(http: httpx.AsyncClient, *, today: str) -> dict:
    """Die Stationsliste des Tages, hoechstens einmal je Tag geholt.

    Anders als die Messliste darf sie NICHT still degradieren: ohne sie ist
    keine Station waehlbar, der Stadtabruf muss dann scheitern und den
    STALE-ON-ERROR-Pfad ausloesen. Ein Fehlschlag wird kurz gemerkt, damit die
    83 wartenden Abrufe derselben Welle nicht einzeln nachschlagen; sie sehen
    denselben Fehler, ohne die Quelle erneut anzufassen.
    """
    cached = _STATIONS_CACHE.get(today)
    if cached is not None:
        return cached
    if _STATIONS_FAILED_UNTIL.get(today, 0.0) > time.monotonic():
        raise httpx.HTTPError("UBA /stations/json: kurz zuvor fehlgeschlagen")

    async with _STATIONS_LOCK:
        cached = _STATIONS_CACHE.get(today)
        if cached is not None:
            return cached
        if _STATIONS_FAILED_UNTIL.get(today, 0.0) > time.monotonic():
            raise httpx.HTTPError("UBA /stations/json: kurz zuvor fehlgeschlagen")
        try:
            # Mit rund 560 KB die groesste Antwort der Quelle. Ohne eigenes
            # Timeout liefe ausgerechnet sie in den straffen Client-Default
            # (read 5 s), waehrend die kleineren Abrufe 15 s bekommen, und ein
            # Timeout hier reisst den Breaker fuer die ganze Quelle mit.
            resp = await http.get(
                f"{_BASE}/stations/json",
                params={"lang": "de"},
                timeout=_META_TIMEOUT_S,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            _STATIONS_FAILED_UNTIL[today] = time.monotonic() + _STATIONS_FAIL_COOLDOWN_S
            raise
        _STATIONS_CACHE.clear()
        _STATIONS_FAILED_UNTIL.clear()
        _STATIONS_CACHE[today] = payload
        return payload


async def fetch_air_uba(
    http: httpx.AsyncClient, *, slug: str, lat: float, lon: float
) -> dict:
    """Holt UBA-Luftqualität (2-Step) und liefert das flache raw-dict.

    Schritt 1 ``GET {_BASE}/stations/json`` (``lang=de``): die ``_FALLBACK_STATIONS``
    nächsten Stationen zu (``lat``, ``lon``). Schritt 2 ``GET {_BASE}/measures/json``
    je v3-Komponente (PM10/PM2.5/NO2/O3/SO2) mit Tagesfenster: jüngster Stundenwert
    je Komponente, PRO Komponente über die Nachbarstationen kaskadiert (Audit K4),
    bis ein Wert gefunden ist.

    Rückgabe-Keys (exakt das, was ``map_air_uba`` erwartet): ``slug``,
    ``station_id`` (UBA-Station-ID der NÄCHSTEN Station als ``str``), ``lat``,
    ``lon`` (Geo der nächsten Station, stabiler record_id-Schlüssel),
    ``observed_at`` (ÄLTESTER Messzeitpunkt über alle gefüllten Komponenten)
    sowie ``pm10``/``pm25``/``no2``/``o3``/``so2`` (fehlender Wert -> ``None``).
    Der Host ist hartkodiert (SSRF-Schutz, T-07-IN); ``resp.raise_for_status()``
    ist Pflicht (STALE-ON-ERROR-Pfad).
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    measuring = await _measuring_stations(http, today=today)
    stations = await _stations_payload(http, today=today)
    nearest = _nearest_stations(
        stations,
        lat,
        lon,
        limit=_FALLBACK_STATIONS,
        measuring=measuring,
    )

    # Die nächste Station bestimmt station_id/Geo (stabiler record_id-Schlüssel,
    # ARCH-02); die weiteren dienen nur dem Pro-Komponenten-Fallback.
    primary_id, primary_lat, primary_lon = nearest[0]

    raw: dict = {
        "slug": slug,
        "station_id": primary_id,
        "lat": primary_lat,
        "lon": primary_lon,
        "observed_at": None,
        "pm10": None,
        "pm25": None,
        "no2": None,
        "o3": None,
        "so2": None,
    }

    # Der AELTESTE gefuellte Messzeitpunkt stempelt den Record, nicht der
    # juengste (Owner-Entscheid 2026-09-17). Die fuenf Schadstoffe stammen nicht
    # zwingend aus derselben Stunde: am 17.09. lagen zwischen dem juengsten und
    # dem aeltesten Wert einer Stadt bis zu sieben Stunden (guetersloh,
    # bielefeld), weil manche Stationen eine Komponente nur selten melden. Das
    # Maximum haette einem sieben Stunden alten SO2-Wert denselben frischen
    # Stempel gegeben wie einem aktuellen PM10. Das Minimum irrt dagegen in die
    # sichere Richtung: der Record erscheint hoechstens aelter als sein
    # frischester Wert, nie frischer als sein aeltester. Bei 74 der 84 Staedte
    # stammen ohnehin alle Werte aus derselben Stunde, dort aendert sich nichts.
    oldest_observed: str | None = None
    for key, component_id in _COMPONENTS.items():
        # Fallback-Kaskade je Komponente: erste Station, die einen Wert liefert,
        # gewinnt. SO2 darf weiterhin ehrlich None bleiben, wenn keine nahe
        # Station es misst (Audit K4).
        for station_id, _slat, _slon in nearest:
            value, observed_at = await _fetch_component(
                http, station_id=station_id, component_id=component_id, today=today
            )
            if value is None:
                continue
            raw[key] = value
            if observed_at is not None and (
                oldest_observed is None or observed_at < oldest_observed
            ):
                oldest_observed = observed_at
            break

    raw["observed_at"] = oldest_observed
    return raw


# Messwerte je Komponente, fuer ALLE Stationen in einem Abruf. Laesst man den
# station-Parameter weg, antwortet die Quelle mit dem kompletten Feld (am
# 2026-09-17: 342 Stationen, 371 KB je Komponente). Vorher fragte der Adapter
# Station fuer Station: 84 Staedte mal fuenf Komponenten sind 420 Abrufe je
# Collector-Lauf, alle in derselben Sekunde, und genau die rissen weiterhin das
# Quota der Quelle (zehn 429 noch im Lauf um 19:12). Jetzt sind es fuenf.
#
# Kurze Haltezeit statt Tagescache: das sind MESSWERTE, keine Stammdaten. Fuenf
# Minuten decken den Ansturm eines Laufs ab, ohne die stuendliche Aktualitaet zu
# verlieren, auf die der Stadt-Cache (fresh 600 s) aufsetzt.
_MEASURES_TTL_S = 300.0
# Gekeyt nach (Tag, Komponente), nicht nur nach Komponente: der Body wurde mit
# date_from=today geholt. Ohne den Tag im Schluessel wuerde ueber den
# UTC-Tageswechsel hinweg bis zu _MEASURES_TTL_S lang der Body des Vortags
# ausgeliefert. Der Tageswechsel raeumt die alten Eintraege weg.
_MEASURES_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_MEASURES_LOCKS: dict[tuple[str, int], asyncio.Lock] = {}

# Ohne diese Sperre kehrt der Burst genau im Fehlerfall zurueck: faellt der
# Abruf aus, holt sich jeder der 84 gleichzeitigen Stadtabrufe nacheinander den
# Lock und feuert seinen eigenen, seriell hinter bis zu 83 Round-Trips. Also
# dieselbe Menge Abrufe, die dieser Weg gerade beseitigt hat, und ausgerechnet
# in dem Zustand, der den Vorfall ausgeloest hat.
_MEASURES_FAILED_UNTIL: dict[tuple[str, int], float] = {}


async def _measures_for_component(
    http: httpx.AsyncClient, *, component_id: int, today: str
) -> dict:
    """Der measures-Body EINER Komponente fuer alle Stationen, kurz gehalten.

    Gehalten wird je (Tag, Komponente): der Body traegt das Tagesfenster, ein
    Eintrag des Vortags waere nach Mitternacht UTC schlicht falsch.

    Ein Fehlschlag wird NICHT zwischengespeichert und nicht geschluckt: ohne
    Messwerte muss der Stadtabruf scheitern und den STALE-ON-ERROR-Pfad
    ausloesen, so wie der Einzelabruf es vorher tat.
    """
    schluessel = (today, component_id)
    entry = _MEASURES_CACHE.get(schluessel)
    if entry is not None and entry[0] > time.monotonic():
        return entry[1]
    if _MEASURES_FAILED_UNTIL.get(schluessel, 0.0) > time.monotonic():
        raise httpx.HTTPError("UBA /measures/json: kurz zuvor fehlgeschlagen")

    lock = _MEASURES_LOCKS.setdefault(schluessel, asyncio.Lock())
    async with lock:
        entry = _MEASURES_CACHE.get(schluessel)
        if entry is not None and entry[0] > time.monotonic():
            return entry[1]
        if _MEASURES_FAILED_UNTIL.get(schluessel, 0.0) > time.monotonic():
            raise httpx.HTTPError("UBA /measures/json: kurz zuvor fehlgeschlagen")
        try:
            resp = await http.get(
                f"{_BASE}/measures/json",
                params={
                    "date_from": today,
                    "time_from": "1",
                    "date_to": today,
                    "time_to": "24",
                    # kein station-Parameter: die Quelle liefert alle Stationen
                    "component": str(component_id),
                    "scope": str(_SCOPE),
                    # Audit-156: index=id explizit. Die UBA-API liefert "id"
                    # zwar bereits als Default (im request-Echo sichtbar), aber
                    # _latest_value verlässt sich auf
                    # data->station_id->{datetime:[...]}; explizit setzen
                    # härtet gegen eine stille Default-Änderung der Quelle.
                    "index": "id",
                },
                timeout=_META_TIMEOUT_S,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            _MEASURES_FAILED_UNTIL[schluessel] = (
                time.monotonic() + _MEASURES_FAIL_COOLDOWN_S
            )
            raise

        # Der Adapter verlaesst sich jetzt darauf, dass die Quelle ohne
        # station-Parameter das KOMPLETTE Feld liefert. Kaeme sie eines Tages
        # gekappt oder paginiert zurueck, laese _latest_value fuer jede Station
        # (None, None), und der leere Record wuerde still fortgeschrieben.
        # Ein leeres Feld ist allerdings ein LEGITIMER Zustand: misst gerade
        # keine Station im Land diese Komponente, ist genau das die richtige
        # Antwort (die Tests zu SO2 und zum Komponenten-Mapping decken das ab).
        # Es darf deshalb nicht scheitern, aber es soll sichtbar sein.
        if not (payload.get("data") or {}):
            log.warning("uba_measures_feld_leer", component=component_id, day=today)

        # Tageswechsel: alles raeumen, was nicht zu heute gehoert. Damit
        # wachsen weder Cache noch Lock-Verzeichnis ueber die Tage.
        for alt in [k for k in _MEASURES_CACHE if k[0] != today]:
            del _MEASURES_CACHE[alt]
        for alt in [k for k in _MEASURES_LOCKS if k[0] != today]:
            del _MEASURES_LOCKS[alt]
        for alt in [k for k in _MEASURES_FAILED_UNTIL if k[0] != today]:
            del _MEASURES_FAILED_UNTIL[alt]
        _MEASURES_CACHE[schluessel] = (time.monotonic() + _MEASURES_TTL_S, payload)
        return payload


async def _fetch_component(
    http: httpx.AsyncClient,
    *,
    station_id: str,
    component_id: int,
    today: str,
) -> tuple[float | None, str | None]:
    """Der jüngste gefüllte Stundenwert einer Komponente an EINER Station.

    Liest aus dem gebündelten Body aller Stationen. Rückgabe
    ``(value, observed_at)``; fehlt der Wert an dieser Station, ``(None, None)``
    -> die Kaskade in ``fetch_air_uba`` probiert die nächste Station.
    """
    payload = await _measures_for_component(
        http, component_id=component_id, today=today
    )
    return _latest_value(payload, station_id)
