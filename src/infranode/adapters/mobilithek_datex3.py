"""Keyloser Mobilithek-DATEX-II-V3-Parking-Adapter (Frankfurt am Main).

Frankfurt liefert seine Parkdaten als DATEX-II **V3** im **XML**-Profil
(Namespace ``http://datex2.eu/schema/3/parking``) über den Mobilithek-mTLS-Pull
(``infra/mobilithek.py``). Das ist die einzige DATEX-II-V3-**XML**-Quelle:
``adapters/mobilithek_afir`` ist V3 als JSON, ``adapters/mobilithek_datex2`` ist
V2 als XML. Der V2-Parser greift bei einem V3-Body NICHT (anderes Status-Element
``parkingRecordStatus`` statt ``parkingStatus``, verschachteltes
``parkingOccupancy``), daher ein eigener V3-Parser. Die DoS/XXE-Härtung
(``_guard``: Pre-Parse-Guard + Size-Cap) wird aus dem V2-Adapter wiederverwendet.

Zwei Abos, im Adapter gejoint (ein nützlicher Datensatz):
- **dynamisch** (``ParkingSiteStatus``): je ``parkingRecordStatus`` die
  Belegung -- ``free`` (parkingNumberOfVacantSpaces), ``occupancy`` (Prozent),
  ``occupancy_graded``, ``observed_at`` (parkingStatusOriginTime) + die
  ``facility_id`` aus der ``parkingRecordReference``-ID.
- **statisch** (``UrbanParkingSite``): je ``parkingRecord`` die Stammdaten --
  ``name`` (parkingName), ``capacity`` (parkingNumberOfSpaces),
  ``lat``/``lon`` (parkingLocation/pointCoordinates).

Der Join über die ``parkingRecord``-ID reichert die dynamische Belegung um
Name/Geo/Kapazitaet an; der dynamische Feed ist der Treiber (liefert die
Belegung), das statische Pendant nur Anreicherung.

REALITÄT (Pull-Test 2026-06-22, Box): der vom Portal angezeigte
``soap/datexv3``-Endpoint gibt bei GET HTTP 405 (SOAP braucht POST); der
``container``-Zugriffspunkt (``build_pull_url(..., style="container")``) liefert
das reine DATEX-II-V3-XML mit HTTP 200. ``Accept-Encoding: gzip`` ist PFLICHT
(im mTLS-Client gesetzt).

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper), kennt KEIN Cache/Breaker (das liefert
die Fassade) und schreibt KEIN Archiv.
"""

from __future__ import annotations

import io
from xml.etree.ElementTree import iterparse  # noqa: S405

from infranode.adapters.mobilithek_datex2 import _guard, _localname
from infranode.infra.mobilithek import build_pull_url, pull_subscription

# DATEX-II V3 Parking-Namespace (RESEARCH/Pull-Test). Nur Doku-Konstante: der
# Parse strippt den NS per ``_localname``, daher robust gegen NS-Detail-Drift.
_NS_V3_PARKING = "{http://datex2.eu/schema/3/parking}"

# Dynamisch: Belegungs-Status je Parkplatz (verifiziert 2026-06-22).
_STATUS_TAG = "parkingRecordStatus"
_STATUS_REF_TAG = "parkingRecordReference"  # trägt das id-Attribut (Join-Key)
_STATUS_ORIGIN_TAG = "parkingStatusOriginTime"
_STATUS_VACANT_TAG = "parkingNumberOfVacantSpaces"
_STATUS_OCCUPANCY_TAG = "parkingOccupancy"  # ACHTUNG: Container UND Prozentwert
_STATUS_GRADED_TAG = "parkingOccupancyGraded"

# Statisch: Stammdaten je Parkplatz (verifiziert 2026-06-22).
_RECORD_TAG = "parkingRecord"  # trägt das id-Attribut (Join-Key)
_RECORD_NAME_TAG = "parkingName"
_RECORD_CAPACITY_TAG = "parkingNumberOfSpaces"
_RECORD_LOCATION_TAG = "parkingLocation"
_RECORD_LAT_TAG = "latitude"
_RECORD_LON_TAG = "longitude"
_RECORD_VALUE_TAG = "value"


def _first_text(elem, local: str) -> str | None:
    """Erster nicht-leerer Text eines Descendant mit gegebenem lokalem Tag-Namen."""
    for node in elem.iter():
        if _localname(node.tag) == local:
            text = (node.text or "").strip()
            if text:
                return text
    return None


def _find(elem, local: str):
    """Erstes Descendant-Element mit gegebenem lokalem Tag-Namen (oder None)."""
    for node in elem.iter():
        if _localname(node.tag) == local:
            return node
    return None


def _extract_parking_status(status) -> dict | None:
    """Liest facility_id + Belegung aus einem ``parkingRecordStatus`` (V3 dynamisch).

    ``facility_id`` aus dem ``id``-Attribut der ``parkingRecordReference``.
    Belegung NS-robust: ``free`` (``parkingNumberOfVacantSpaces``, int),
    ``occupancy`` (Prozent, float -- der ``parkingOccupancy`` MIT Textwert; das
    gleichnamige Container-Element trägt keinen direkten Text und wird daher
    übersprungen), ``occupancy_graded`` (str), ``observed_at``
    (``parkingStatusOriginTime``). Felder optional; ein komplett leeres Element
    -> ``None`` (Datenfehler fällt aus, statt 500). Ein einzelner unparsebarer
    Wert verwirft nur diesen Wert.
    """
    facility_id: str | None = None
    free: int | None = None
    occupancy: float | None = None
    graded: str | None = None
    observed_at: str | None = None

    for node in status.iter():
        local = _localname(node.tag)
        if local == _STATUS_REF_TAG and facility_id is None:
            facility_id = node.get("id")
            continue
        text = (node.text or "").strip()
        if not text:
            # Das Container-``parkingOccupancy`` hat keinen direkten Text -> hier
            # übersprungen; nur der innere Prozentwert trägt Text.
            continue
        try:
            if local == _STATUS_VACANT_TAG:
                free = int(float(text))
            elif local == _STATUS_OCCUPANCY_TAG:
                occupancy = float(text)
            elif local == _STATUS_GRADED_TAG and graded is None:
                graded = text
            elif local == _STATUS_ORIGIN_TAG and observed_at is None:
                observed_at = text
        except ValueError:
            # Einzelner Datenfehler verwirft nur diesen Wert, nicht das Parkhaus.
            continue

    if facility_id is None and free is None and occupancy is None and graded is None:
        return None

    entry: dict = {"facility_id": facility_id}
    if free is not None:
        entry["free"] = free
    if occupancy is not None:
        entry["occupancy"] = occupancy
    if graded is not None:
        entry["occupancy_graded"] = graded
    if observed_at is not None:
        entry["observed_at"] = observed_at
    return entry


def _extract_parking_site(record) -> dict | None:
    """Liest facility_id + Stammdaten aus einem ``parkingRecord`` (V3 statisch).

    ``facility_id`` aus dem ``id``-Attribut. ``name`` aus dem ersten ``value``
    unter ``parkingName`` (gezielt, NICHT der erste ``value`` im ganzen Record --
    parkingAlias/parkingDescription tragen ebenfalls ``value``). ``capacity`` aus
    dem ersten ``parkingNumberOfSpaces`` (Gesamtkapazität auf Record-Ebene).
    ``lat``/``lon`` gezielt aus ``parkingLocation`` (NICHT aus parkingAccess-
    Zufahrten, die eigene Koordinaten tragen). Felder optional; ein Record ohne
    jede verwertbare Angabe -> ``None``.
    """
    facility_id = record.get("id")

    name = None
    name_elem = _find(record, _RECORD_NAME_TAG)
    if name_elem is not None:
        name = _first_text(name_elem, _RECORD_VALUE_TAG)

    capacity: int | None = None
    cap_text = _first_text(record, _RECORD_CAPACITY_TAG)
    if cap_text is not None:
        try:
            capacity = int(float(cap_text))
        except ValueError:
            capacity = None

    lat: float | None = None
    lon: float | None = None
    loc = _find(record, _RECORD_LOCATION_TAG)
    if loc is not None:
        lat_text = _first_text(loc, _RECORD_LAT_TAG)
        lon_text = _first_text(loc, _RECORD_LON_TAG)
        try:
            if lat_text is not None and lon_text is not None:
                lat = float(lat_text)
                lon = float(lon_text)
        except ValueError:
            lat = lon = None

    if facility_id is None and name is None and capacity is None:
        return None

    site: dict = {"facility_id": facility_id}
    if name is not None:
        site["name"] = name
    if capacity is not None:
        site["capacity"] = capacity
    if lat is not None and lon is not None:
        site["lat"] = lat
        site["lon"] = lon
    return site


def parse_parking_status_v3(xml_bytes: bytes, *, slug: str) -> dict:
    """Parst eine DATEX-II-V3-Parking-Status-Publication (dynamisch, Belegung).

    Sucht je ``parkingRecordStatus`` die Belegung (siehe
    ``_extract_parking_status``). Reiner, synchroner Parse (testbar ohne Netz).
    Haertung: ``_guard`` (Pre-Parse-Guard + Size-Cap, T-20-XXE) läuft VOR
    ``iterparse``; ``elem.clear()`` hält den Speicher konstant.

    Rueckgabe: ``{"slug": slug, "facilities": [...], "as_of": <publicationTime>}``.
    """
    _guard(xml_bytes)

    facilities: list[dict] = []
    bio = io.BytesIO(xml_bytes)
    # noqa S314: stdlib-Parse bewusst (Decision 1); XXE/DoS-Mitigation ist
    # _guard oben (untrusted Live-Feed).
    for _event, elem in iterparse(bio):  # noqa: S314
        if _localname(elem.tag) != _STATUS_TAG:
            continue
        entry = _extract_parking_status(elem)
        if entry is not None:
            facilities.append(entry)
        elem.clear()

    return {
        "slug": slug,
        "facilities": facilities,
        "as_of": _publication_time(xml_bytes),
    }


def parse_parking_static_v3(xml_bytes: bytes, *, slug: str) -> dict:
    """Parst eine DATEX-II-V3-Parking-Stammdaten-Publication (statisch).

    Sucht je ``parkingRecord`` die Stammdaten (siehe ``_extract_parking_site``)
    und gibt sie als dict ``{facility_id: site}`` für den Join zurück. Reiner,
    synchroner Parse. Härtung identisch (``_guard`` vor ``iterparse``,
    ``elem.clear()``).

    Rueckgabe: ``{"slug": slug, "sites": {facility_id: {...}}}``.
    """
    _guard(xml_bytes)

    sites: dict[str, dict] = {}
    bio = io.BytesIO(xml_bytes)
    for _event, elem in iterparse(bio):  # noqa: S314
        if _localname(elem.tag) != _RECORD_TAG:
            continue
        site = _extract_parking_site(elem)
        if site is not None and site.get("facility_id"):
            sites[site["facility_id"]] = site
        elem.clear()

    return {"slug": slug, "sites": sites}


def _publication_time(xml_bytes: bytes) -> str | None:
    """Liest die erste ``publicationTime`` (DATEX-II ``as_of``) NS-robust.

    Setzt voraus, dass ``_guard`` bereits gelaufen ist (interner Helfer).
    """
    bio = io.BytesIO(xml_bytes)
    for _event, elem in iterparse(bio):  # noqa: S314
        if _localname(elem.tag) == "publicationTime":
            text = (elem.text or "").strip()
            elem.clear()
            return text or None
        elem.clear()
    return None


def _join(status: dict, static: dict) -> list[dict]:
    """Joint dynamische Belegung mit statischen Stammdaten über die facility_id.

    Der dynamische Feed ist der Treiber (liefert die Belegung); jedes facility
    wird um ``name``/``lat``/``lon``/``capacity`` aus dem statischen Pendant
    angereichert (falls vorhanden). Dynamische Werte haben Vorrang bei
    Schlüssel-Kollision (es gibt keine).
    """
    sites: dict = static.get("sites", {})
    merged: list[dict] = []
    for fac in status.get("facilities", []):
        fid = fac.get("facility_id")
        site = sites.get(fid, {}) if fid else {}
        entry = {**{k: v for k, v in site.items() if k != "facility_id"}, **fac}
        merged.append(entry)
    return merged


async def fetch_frankfurt_parking(
    mtls_client,
    *,
    abo_id: str,
    static_abo_id: str | None,
    slug: str,
) -> dict:
    """Pullt Frankfurt-Parkdaten (dynamisch + statisch) und joint sie.

    Live-Pfad (untrusted): baut die Pull-URLs aus den Allowlist-Abo-IDs mit der
    ``container``-Variante (``build_pull_url(..., style="container")``; Host
    hartkodiert -> SSRF-Invariante), pullt über den mTLS-Client
    (``pull_subscription``) und parst beide V3-XML-Antworten. Das statische Abo
    ist optional: fehlt es (oder liefert es nichts), wird die dynamische Belegung
    ohne Stammdaten zurückgegeben (ehrliche Degradation, kein Fehler).

    HTTP 422 (Abo aktiv, kein Datenpaket) und ein vom Guard/Size-Cap abgelehnter
    Body (``ValueError``) liefern ein ehrliches leeres Ergebnis (no_data, kein
    ``raise``). 5xx/Netzfehler des dynamischen Pulls schlagen via
    ``pull_subscription`` durch an die resiliente Fassade (STALE-ON-ERROR).

    Rückgabe (exakt was der Mapper erwartet): ``{"slug", "facilities": [...],
    "as_of"}``; jedes facility trägt facility_id + free/occupancy/
    occupancy_graded/observed_at (dynamisch) + name/lat/lon/capacity (statisch).
    """
    dyn_url = build_pull_url(abo_id, style="container")
    dyn_result = await pull_subscription(mtls_client, dyn_url)
    if dyn_result["status"] == "no_data" or dyn_result["body"] is None:
        return {"slug": slug, "facilities": [], "as_of": None}

    try:
        status = parse_parking_status_v3(dyn_result["body"], slug=slug)
    except ValueError:
        # Guard / Size-Cap hat den Body abgelehnt -> ehrliches no_data.
        return {"slug": slug, "facilities": [], "as_of": None}

    # Statisches Pendant best-effort dazuladen (Stammdaten-Anreicherung). Ein
    # Fehlschlag des statischen Pulls darf die Live-Belegung NICHT kippen.
    static = {"slug": slug, "sites": {}}
    if static_abo_id:
        try:
            stat_url = build_pull_url(static_abo_id, style="container")
            stat_result = await pull_subscription(mtls_client, stat_url)
            if stat_result["status"] == "ok" and stat_result["body"] is not None:
                static = parse_parking_static_v3(stat_result["body"], slug=slug)
        except ValueError:
            static = {"slug": slug, "sites": {}}

    return {
        "slug": slug,
        "facilities": _join(status, static),
        "as_of": status.get("as_of"),
    }
