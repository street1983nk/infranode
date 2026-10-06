"""GBFS-Sharing-Adapter ``fetch_sharing`` (DATA-33, Live, Tier A).

Aggregiert Bike-/Scooter-Sharing je Stadt aus offenen GBFS-Feeds (General
Bikeshare Feed Specification). Primärquelle Nextbike (CC0, Tier A): je Stadt ein
oder mehrere GBFS-Systeme (kuratierte Allowlist ``GBFS_SYSTEMS`` in cities.py,
NIE User-Input -> kein SSRF).

Fail-closed Tier-A (GOV-02/04): die Lizenz wird PRO System aus dem GBFS-eigenen
``system_information.license_id`` gelesen und gegen die Tier-A-Allowlist
``_TIER_A_LICENSES`` geprüft. Ein System ohne anerkannte permissive Lizenz wird
VERWORFEN (nicht aggregiert), damit kein Datensatz mit unklarer/kommerzieller
Lizenz ins System gelangt.

Pro System werden free-floating-Fahrzeuge (``free_bike_status``/``vehicle_status``)
und stationsgebundene Fahrzeuge (``station_information`` + ``station_status``)
gelesen, per Bounding-Box auf das Stadtgebiet gefiltert (Nextbike-Systeme decken
teils ganze Regionen ab, z.B. VRNnextbike Mannheim/Heidelberg/Ludwigshafen) und
zu Stadt-Kennzahlen verdichtet.

Sicherheit:
- T-05-08 (SSRF): Der Host ist in ``_BASE`` hartkodiert; nur die kuratierten
  ``system_id`` aus der Allowlist fließen in die URL.
- Redirects: Der Pool folgt keinen Redirects (SSRF-Invariante). ``_get_json``
  folgt 3xx deshalb selbst, höchstens ``_MAX_REDIRECTS`` Sprünge, nur https und
  nur auf Hosts aus ``_REDIRECT_HOSTS`` (Nextbike leitet seit 2026-09 per 301 von
  gbfs.nextbike.net auf gbfs2.nextbike.net um, auch die Feed-URLs).
- Resilienz: Der Adapter baut KEINEN ``CanonicalRecord`` und kennt KEIN
  Cache/Breaker (das liefert die Resilienz-Fassade). ``raise_for_status`` ist
  Pflicht (5xx -> STALE-ON-ERROR).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

import httpx

from infranode.adapters.autobahn import _within_bbox


def _parse_gbfs_ts(value: object) -> str | None:
    """GBFS-``last_updated`` -> UTC-ISO-String (rein, kein ``datetime.now()``).

    GBFS v2 liefert einen POSIX-Sekunden-Integer, v3 einen RFC3339-String.
    Unbrauchbare Werte -> ``None``. UTC-normalisiert, damit ein lexikografisches
    ``max()`` dem chronologisch jüngsten Stand entspricht.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    return None


def _gbfs_text(value: object) -> str | None:
    """GBFS-Freitext (name/operator/station-name) -> String (rein).

    GBFS v2 liefert einen blanken String, v3 ein ``[{"language","text"}]``-Array
    (localized string). Bevorzugt ``de``, sonst die erste nicht-leere Sprache.
    Ein String wird unveraendert (getrimmt, leer -> None) zurueckgegeben, damit
    die bestehenden v2-Systeme (Nextbike/MobiData) unveraendert funktionieren.
    """
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        by_lang = {
            e.get("language"): e.get("text")
            for e in value
            if isinstance(e, dict) and isinstance(e.get("text"), str)
        }
        return by_lang.get("de") or next(
            (t for t in by_lang.values() if t and t.strip()), None
        )
    return None


# Host hartkodiert (SSRF, T-05-08): die Nextbike-GBFS-Auslieferung.
_BASE = "https://gbfs.nextbike.net"
# Discovery-Pfad je System (GBFS v2). Die system_id stammt NUR aus der kuratierten
# Allowlist (cities.GBFS_SYSTEMS), nie aus User-Input.
_DISCOVERY = "/maps/gbfs/v2/{system_id}/gbfs.json"

# Kuratierte Redirect-Ziele (SSRF): nur auf diese Hosts folgt ``_get_json`` einem
# 3xx. Nextbike leitet gbfs.nextbike.net -> gbfs2.nextbike.net um (301, gesehen
# 2026-09-29, Discovery UND Feeds). Jeder andere Zielhost -> Fehler (Fassade).
_REDIRECT_HOSTS = frozenset({"gbfs.nextbike.net", "gbfs2.nextbike.net"})
_MAX_REDIRECTS = 3

# Attribution der Nextbike-Primaerquelle (CC0). Verbatim wie in DATA-LICENSES.md +
# SOURCE_LICENSE. Wird verwendet, wenn eine GbfsSystem-Spec keine eigene
# Attribution traegt (also fuer alle rohen Nextbike-System-Strings).
_NEXTBIKE_ATTRIBUTION = "nextbike GmbH / GBFS (CC0)"


class GbfsSystem(NamedTuple):
    """Kuratierte GBFS-System-Spec (Basis-URL, Discovery-Pfad, Lizenz-Override).

    T-05-08 / T-9q0-01 (SSRF): ``base_url`` und ``discovery_path`` werden
    AUSSCHLIESSLICH in der kuratierten Registry (``cities.GBFS_SYSTEMS``)
    hartkodiert gesetzt, NIE aus einem Slug oder anderem User-Input gebaut. Die
    Defaults zeigen weiter auf die Nextbike-Auslieferung, damit ein roher
    ``system_id``-String unveraendert wie bisher funktioniert.

    ``license_override`` deckt kuratierte Tier-A-Quellen ab, deren GBFS-Feed KEIN
    ``system_information.license_id`` fuehrt (z.B. der MobiData-BW-Aggregator,
    DB Call a Bike, DL-DE/BY-2.0, Quelle mobidata-bw.de/dataset/bikesh). Der
    Override laeuft durch dieselbe fail-closed ``_tier_a_license``-Allowlist: ohne
    ``license_id`` UND ohne kuratierten Tier-A-Override wird das System verworfen.
    """

    system_id: str
    base_url: str = _BASE
    discovery_path: str = _DISCOVERY
    license_override: str | None = None
    attribution: str | None = None


# Obergrenze der je Anbieter ausgelieferten Stationsliste (Payload-/Archiv-Groesse:
# Großstadt-Systeme wie nextbike Berlin haben >1000 Stationen). ``station_count``
# bleibt der WAHRE Gesamtwert; ``stations`` trägt die nach Verfügbarkeit
# sortierten Top-Stationen (kein stiller Verlust der Kennzahl, nur der Detailliste).
_MAX_STATIONS = 200

# Fail-closed Tier-A-Allowlist (GOV-02/04): GBFS-``license_id`` (SPDX-/Freitext) ->
# unser kanonischer Lizenz-Tag. Ein System mit hier UNBEKANNTER license_id (oder
# ganz ohne) wird verworfen, statt mit unklarer Lizenz aggregiert zu werden. Nur
# permissive Tier-A-Lizenzen. Schlüssel case-insensitiv normalisiert (.upper()).
_TIER_A_LICENSES: dict[str, str] = {
    "CC0-1.0": "cc0",
    "CC0": "cc0",
    "CC-BY-4.0": "cc_by_4_0",
    "CC-BY 4.0": "cc_by_4_0",
    "DL-DE-BY-2.0": "dl_de_by_2_0",
    "DL-DE/BY-2.0": "dl_de_by_2_0",
}


def _tier_a_license(license_id: object) -> str | None:
    """Bildet eine GBFS-``license_id`` fail-closed auf einen Tier-A-Tag ab (rein).

    Unbekannte/fehlende Lizenz -> ``None`` (das System wird verworfen, GOV-02/04).
    """
    if not isinstance(license_id, str):
        return None
    return _TIER_A_LICENSES.get(license_id.strip().upper().replace("_", "-"))


def _feeds(discovery: dict) -> dict[str, str]:
    """Liest aus einem GBFS-``gbfs.json`` die ``{feed_name: url}``-Abbildung (rein).

    Die ``data``-Ebene trägt entweder Sprach-Schlüssel (``{"de": {"feeds": []}}``,
    GBFS v2) oder direkt ``{"feeds": []}`` (GBFS v3). ``de`` wird bevorzugt, sonst
    die erste vorhandene Sprache.
    """
    data = discovery.get("data") or {}
    # GBFS v3 traegt "feeds" direkt (keine Sprach-Ebene mehr).
    langs = {"_": data} if "feeds" in data else data
    block = langs.get("de") or (next(iter(langs.values()), {}) if langs else {})
    return {f.get("name"): f.get("url") for f in block.get("feeds", []) if f.get("url")}


async def _get_json(http: httpx.AsyncClient, url: str) -> dict:
    """Holt eine GBFS-JSON-Ressource (``raise_for_status`` Pflicht -> Fassade).

    Folgt 3xx selbst (der Pool hat ``follow_redirects=False``), aber nur auf https
    und kuratierte ``_REDIRECT_HOSTS``, höchstens ``_MAX_REDIRECTS`` Sprünge. Ein
    nicht erlaubtes Ziel oder zu viele Sprünge -> ``raise_for_status`` wirft.
    """
    resp = await http.get(url)
    for _ in range(_MAX_REDIRECTS):
        nxt = resp.next_request
        if not resp.is_redirect or nxt is None:
            break
        if nxt.url.scheme != "https" or nxt.url.host not in _REDIRECT_HOSTS:
            break
        await resp.aclose()
        resp = await http.get(nxt.url)
    resp.raise_for_status()
    return resp.json()


def _count_free_floating(
    payload: dict, *, lat: float, lon: float, radius: float
) -> int:
    """Zaehlt verfügbare free-floating-Fahrzeuge in der BBox (rein).

    GBFS v2 liefert ``data.bikes``, v3 ``data.vehicles``. Nur Fahrzeuge mit
    gültigen Koordinaten in der BBox, die weder ``is_disabled`` noch
    ``is_reserved`` sind, zählen als verfügbar. Fahrzeuge mit ``station_id``
    sind stationsgebunden (H9: Nextbike führt sie auch im free_bike_status) und
    werden hier NICHT gezählt - sie zählen über ``station_status`` (sonst
    Doppelzählung -> free_floating zu hoch).
    """
    data = payload.get("data") or {}
    vehicles = data.get("bikes") or data.get("vehicles") or []
    count = 0
    for v in vehicles:
        if not isinstance(v, dict):
            continue
        if v.get("station_id"):  # H9: stationsgebunden, nicht free-floating.
            continue
        vlat, vlon = v.get("lat"), v.get("lon")
        if not isinstance(vlat, int | float) or not isinstance(vlon, int | float):
            continue
        if v.get("is_disabled") or v.get("is_reserved"):
            continue
        if _within_bbox(float(vlat), float(vlon), lat, lon, radius):
            count += 1
    return count


def _stations(
    info: dict, status: dict, *, lat: float, lon: float, radius: float
) -> list[dict]:
    """Joint station_information + station_status, BBox-gefiltert (rein).

    Liefert je Station in der BBox ein schlankes dict (``station_id``/``name``/
    ``lat``/``lon``/``capacity``/``bikes_available``/``docks_available``/
    ``is_renting``). Stationen ohne gültige Koordinaten oder außerhalb der BBox
    fallen heraus.

    H9: ``capacity`` (Stellplatzzahl je Station, aus ``station_information``) wird
    übernommen statt verworfen. Nicht mietbare Bestände zählen NICHT als
    verfuegbar: ist eine Station explizit ``is_installed=false``/
    ``is_renting=false``/``is_disabled=true`` (GBFS-Flags, fehlend = aktiv), wird
    ``bikes_available`` auf 0 gesetzt (sonst werden gesperrte Räder gemeldet).
    """
    status_by_id = {
        s.get("station_id"): s
        for s in (status.get("data") or {}).get("stations", [])
        if isinstance(s, dict)
    }
    out: list[dict] = []
    for st in (info.get("data") or {}).get("stations", []):
        if not isinstance(st, dict):
            continue
        slat, slon = st.get("lat"), st.get("lon")
        if not isinstance(slat, int | float) or not isinstance(slon, int | float):
            continue
        if not _within_bbox(float(slat), float(slon), lat, lon, radius):
            continue
        live = status_by_id.get(st.get("station_id"), {})
        # H9: GBFS-Flags prüfen (nur ein EXPLIZITES false/true sperrt; fehlend
        # = aktiv). Gesperrte Station -> keine verfügbaren Räder.
        rentable = (
            live.get("is_installed", True) is not False
            and live.get("is_renting", True) is not False
            and live.get("is_disabled", False) is not True
        )
        # GBFS v3 benennt ``num_bikes_available`` -> ``num_vehicles_available``;
        # v2-Fallback fuer die bestehenden Nextbike/MobiData-Systeme.
        available = live.get("num_vehicles_available")
        if available is None:
            available = live.get("num_bikes_available")
        bikes_available = available if rentable else 0
        out.append(
            {
                "station_id": st.get("station_id"),
                "name": _gbfs_text(st.get("name")),
                "lat": float(slat),
                "lon": float(slon),
                "capacity": st.get("capacity"),
                "bikes_available": bikes_available,
                "docks_available": live.get("num_docks_available"),
                "is_renting": bool(rentable),
            }
        )
    return out


async def _fetch_system(
    http: httpx.AsyncClient, *, spec: GbfsSystem, lat: float, lon: float, radius: float
) -> dict | None:
    """Holt EIN GBFS-System und aggregiert es (fail-closed Tier-A, rein gegen Schema).

    Rückgabe ist ein provider-dict oder ``None``, wenn die Lizenz nicht Tier-A ist
    (fail-closed verworfen). Die Discovery-URL wird aus der kuratierten Spec gebaut
    (``spec.base_url`` + ``spec.discovery_path``, NIE User-Input -> T-05-08/T-9q0-01).
    Aggregiert free-floating- + stationsgebundene Fahrzeuge in der Stadt-BBox.
    """
    system_id = spec.system_id
    discovery_url = spec.base_url + spec.discovery_path.format(system_id=system_id)
    discovery = await _get_json(http, discovery_url)
    feeds = _feeds(discovery)

    info: dict = {}
    if "system_information" in feeds:
        info = await _get_json(http, feeds["system_information"])
    # Lizenz fail-closed aufloesen: erst der GBFS-eigene license_id, sonst der
    # kuratierte Tier-A-Override der Spec (z.B. MobiData BW / DB Call a Bike liefert
    # kein license_id-Feld, Quelle mobidata-bw.de/dataset/bikesh). Beides laeuft
    # durch DIESELBE _tier_a_license-Allowlist; None -> System verworfen (GOV-02/04).
    license_raw = (info.get("data") or {}).get("license_id") or spec.license_override
    license_tag = _tier_a_license(license_raw)
    if license_tag is None:
        # Fail-closed (GOV-02/04): keine anerkannte permissive Lizenz -> verwerfen.
        return None

    sysdata = info.get("data") or {}
    free_floating = 0
    # H9: jüngster Feed-Stand (last_updated) je System für observed_at ermitteln.
    observed_candidates: list[str] = []
    ff_feed = feeds.get("free_bike_status") or feeds.get("vehicle_status")
    if ff_feed:
        ff_json = await _get_json(http, ff_feed)
        free_floating = _count_free_floating(ff_json, lat=lat, lon=lon, radius=radius)
        ts = _parse_gbfs_ts(ff_json.get("last_updated"))
        if ts:
            observed_candidates.append(ts)

    stations: list[dict] = []
    if "station_information" in feeds and "station_status" in feeds:
        status_json = await _get_json(http, feeds["station_status"])
        info_json = await _get_json(http, feeds["station_information"])
        stations = _stations(info_json, status_json, lat=lat, lon=lon, radius=radius)
        ts = _parse_gbfs_ts(status_json.get("last_updated"))
        if ts:
            observed_candidates.append(ts)
    docked = sum(s["bikes_available"] for s in stations if s["bikes_available"])

    # station_count bleibt der wahre Gesamtwert; die ausgelieferte stations-Liste
    # wird nach verfügbaren Fahrzeugen sortiert und auf _MAX_STATIONS gedeckelt.
    top_stations = sorted(
        stations, key=lambda s: s["bikes_available"] or 0, reverse=True
    )[:_MAX_STATIONS]
    return {
        "provider": _gbfs_text(sysdata.get("name")) or system_id,
        "operator": _gbfs_text(sysdata.get("operator")),
        "system_id": sysdata.get("system_id") or system_id,
        "license_id": license_tag,
        # Attribution je Anbieter aus der Spec (sonst Nextbike-Default). Der Mapper
        # leitet daraus die record-weite Attribution/Lizenz ab.
        "attribution": spec.attribution or _NEXTBIKE_ATTRIBUTION,
        "free_floating_available": free_floating,
        "docked_available": docked,
        "station_count": len(stations),
        "observed_at": max(observed_candidates) if observed_candidates else None,
        "stations": top_stations,
    }


async def fetch_sharing(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    systems: tuple[str | GbfsSystem, ...],
    radius_km: float = 15.0,
) -> dict:
    """Holt + aggregiert die GBFS-Sharing-Daten der kuratierten Systeme einer Stadt.

    Iteriert über die kuratierten ``systems`` (NIE User-Input), filtert jedes per
    BBox um (``lat``, ``lon``) und verwirft Systeme ohne Tier-A-Lizenz fail-closed.
    Rückgabe-Keys (exakt was ``map_sharing`` erwartet): ``slug``, ``radius_km``,
    ``providers`` (Liste der akzeptierten Tier-A-Systeme), sowie die Stadt-Aggregate
    ``vehicles_available``/``free_floating_available``/``docked_available``/
    ``station_count``. Keine akzeptierten Daten -> ``providers == []`` (die Route
    mappt das auf ``no_data``). ``raise_for_status`` ist Pflicht (5xx -> Fassade).
    """
    providers: list[dict] = []
    for entry in systems:
        # Rohe Nextbike-Strings bleiben unveraendert nutzbar (Default-Spec zeigt auf
        # gbfs.nextbike.net); eine GbfsSystem-Spec traegt eigene Basis/Discovery-URL
        # + kuratierten Lizenz-Override.
        spec = entry if isinstance(entry, GbfsSystem) else GbfsSystem(entry)
        provider = await _fetch_system(
            http, spec=spec, lat=lat, lon=lon, radius=radius_km
        )
        if provider is not None:
            providers.append(provider)

    free_floating = sum(p["free_floating_available"] for p in providers)
    docked = sum(p["docked_available"] for p in providers)
    # H9: jüngster Stand über alle Systeme (UTC-ISO -> lexikografisches max =
    # chronologisches max). None, wenn kein Feed einen last_updated trug.
    observed = [p["observed_at"] for p in providers if p.get("observed_at")]
    return {
        "slug": slug,
        "radius_km": radius_km,
        "providers": providers,
        "free_floating_available": free_floating,
        "docked_available": docked,
        "vehicles_available": free_floating + docked,
        "station_count": sum(p["station_count"] for p in providers),
        "observed_at": max(observed) if observed else None,
    }
