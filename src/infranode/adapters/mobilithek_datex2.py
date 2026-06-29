"""Keyloser Mobilithek-DATEX-II-V2-Adapter (LIVE-05/06/07, Phase 20).

Generischer DATEX-II-V2-Parse-Pfad gegen den Mobilithek-mTLS-Pull-Client
(infra/mobilithek.py). Schablone ist ``adapters/mobidata_bw.py`` (exakt): die
DoS/XXE-Härtung ist identisch, je Publication-Typ wechselt nur das gesuchte
Element.

Zwei Publication-Typen (CONTEXT, an Köln verifiziert):
- ``SituationPublication`` -> ``situationRecord`` (Baustellen/Ereignisse, LIVE-07).
  ``parse_datex2_situations`` filtert per BBox um die Stadt (analog mobidata_bw).
- ``MeasuredDataPublication`` -> ``siteMeasurements``/``measuredValue``
  (Verkehrslage dynamisch, LIVE-06). ``parse_datex2_measured`` liest je Messpunkt
  die ``measurementSiteReference``-ID (station_id) + die Messwerte
  (Geschwindigkeit/Flow). Der dynamische Feed trägt nur ID-Referenzen, kein Geo;
  station_id wird durchgereicht (Join gegen das statische Pendant ist ein Folge-
  Detail, RESEARCH Open Question 3).

KEINE neue Dependency (CLAUDE.md / Decision 1, projektweit untersagt): stdlib
``xml.etree.ElementTree.iterparse``. ABER Mobilithek ist ein LIVE-Request-Pfad
(untrusted) -> PFLICHT-Härtung OHNE neue Dependency (T-20-XXE), exakt wie
mobidata_bw.py:

1. Pre-Parse-Guard: ``<!DOCTYPE`` / ``<!ENTITY`` im Body -> ``ValueError`` BEVOR
   ``iterparse`` ihn sieht (verhindert XXE / Billion-Laughs).
2. Size-Cap ``_MAX_BYTES``: ein zu großer Body -> ``ValueError`` (DoS-Schutz).
3. ``# noqa: S314, S405``: stdlib-Parse bewusst gewählt (Decision 1); die
   XXE/DoS-Mitigation ist der Pre-Parse-Guard + Size-Cap (untrusted Live-Feed).

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper), kennt KEIN Cache/Breaker (das liefert
die Fassade) und schreibt KEIN Archiv. Der ``fetch_datex2``-Wrapper ruft den
Mobilithek-mTLS-Client (``pull_subscription``), mappt HTTP 422 auf ``no_data``
und gibt ein ehrliches leeres Ergebnis zurück, wenn der Guard/Size-Cap greift.
"""

from __future__ import annotations

import io
from xml.etree.ElementTree import iterparse  # noqa: S405

from infranode.adapters.autobahn import _within_bbox
from infranode.infra.mobilithek import build_pull_url, pull_subscription

# Size-Cap (T-20-XXE / DoS): konservativ über der erwarteten Köln-Variante
# (~48 KB) und allen anderen V2-Feeds. Ein größerer Body wird nicht geparst.
_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB

# DATEX-II V2 Namespace (RESEARCH). Nur Doku-Konstante: der Parse strippt den NS
# ohnehin per _localname, daher robust gegen NS-Detail-Drift.
_NS = "{http://datex2.eu/schema/2/2_0}"

# Parking-Status-Element (LIVE-09, RESEARCH Open Question 2): die dynamische
# Dortmund-Belegung steht in einer ``ParkingStatusPublication``; je Parkhaus ein
# ``parkingStatus``-Container mit der Parkhaus-Referenz
# (``parkingRecordReference``/``parkingRecordStatus``, ID-Attribut) und den
# Belegungswerten (``parkingNumberOfVacantSpaces`` = freie Plätze,
# ``parkingNumberOfSpacesOverride`` = Kapazität, ``parkingOccupancy`` = Auslastung
# in Prozent). ANNAHME (nicht am realen Feed verifiziert, kein Server-Zugriff): das
# exakte Publication-Element des Dortmund-Abos ist anhand der DATEX-II-V2-Spec +
# RESEARCH angenommen. Falls der reale Abo-Feed andere lokale Tag-Namen nutzt,
# genügt es, diese Konstanten anzupassen (der Parse ist NS-robust per _localname).
_PARKING_STATUS_TAG = "parkingStatus"
_PARKING_REF_TAGS = ("parkingRecordReference", "parkingRecordStatus")
_PARKING_VACANT_TAG = "parkingNumberOfVacantSpaces"
_PARKING_CAPACITY_TAG = "parkingNumberOfSpacesOverride"
_PARKING_OCCUPANCY_TAG = "parkingOccupancy"


def _localname(tag: str) -> str:
    """Gibt den lokalen Tag-Namen ohne XML-Namespace-Präfix zurück."""
    return tag.rsplit("}", 1)[-1]


def _guard(xml_bytes: bytes) -> None:
    """Pre-Parse-Guard + Size-Cap (T-20-XXE), gemeinsam für beide Parser.

    PFLICHT vor jedem ``iterparse`` (untrusted Live-Feed): ein DOCTYPE/ENTITY-
    Body oder ein Body größer ``_MAX_BYTES`` wird mit ``ValueError`` abgelehnt,
    BEVOR der Parser ihn sieht (verhindert XXE / Billion-Laughs / DoS).
    """
    # Size-Cap (T-20-XXE): zu große Bodies gar nicht erst parsen.
    if len(xml_bytes) > _MAX_BYTES:
        raise ValueError(
            f"Mobilithek-DATEX-II-Body ueberschreitet _MAX_BYTES ({_MAX_BYTES})"
        )
    # Pre-Parse-Guard (Decision 1): DOCTYPE/ENTITY -> ABLEHNEN vor Parse. KEIN
    # iterparse auf solchem Body (verhindert Entity-Expansion / XXE).
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise ValueError(
            "Mobilithek-DATEX-II-Body enthaelt DOCTYPE/ENTITY (XXE/Billion-Laughs "
            "abgelehnt vor Parse, Pre-Parse-Guard T-20-XXE)"
        )


def parse_datex2_situations(
    xml_bytes: bytes,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Parst eine DATEX-II-V2-``SituationPublication`` und filtert auf die BBox.

    Sucht je ``situationRecord`` die erste ``pointCoordinates``
    (``latitude``/``longitude``); nur Einträge innerhalb der Bounding-Box um
    (``lat``, ``lon``) passieren den ``_within_bbox``-Filter (Baustellen/
    Ereignisse, LIVE-07). Reiner, synchroner Parse (testbar ohne Netz).

    Haertung: ``_guard`` (Pre-Parse-Guard + Size-Cap) läuft VOR ``iterparse``.
    Rueckgabe: ``{"slug": slug, "events": [...]}`` (leere Publication -> ``[]``).
    """
    _guard(xml_bytes)

    events: list[dict] = []
    bio = io.BytesIO(xml_bytes)
    # noqa S314: stdlib-Parse bewusst (Decision 1, stdlib-only). XXE/DoS-Mitigation
    # ist der Pre-Parse-Guard + Size-Cap oben (untrusted Live-Feed).
    for _event, elem in iterparse(bio):  # noqa: S314
        if _localname(elem.tag) != "situationRecord":
            continue
        coords = _extract_point(elem)
        if coords is not None:
            elat, elon = coords
            if _within_bbox(elat, elon, lat, lon, radius_km):
                events.append(
                    {
                        "id": elem.get("id"),
                        "type": elem.get(
                            "{http://www.w3.org/2001/XMLSchema-instance}type"
                        ),
                        "comment": _first_comment(elem),
                        "latitude": elat,
                        "longitude": elon,
                    }
                )
        # Memory-konstant: das geparste Element sofort freigeben.
        elem.clear()

    return {"slug": slug, "events": events}


def parse_datex2_measured(
    xml_bytes: bytes,
    *,
    slug: str,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 30.0,
) -> dict:
    """Parst eine DATEX-II-V2-``MeasuredDataPublication`` zu Messwerten (LIVE-06).

    Liest je ``siteMeasurements`` die ``measurementSiteReference``-ID
    (``station_id``) und die enthaltenen Messwerte (Geschwindigkeit
    ``averageVehicleSpeed/speed``, Verkehrsstärke ``vehicleFlow/vehicleFlowRate``).
    Der dynamische Köln-Feed trägt nur ID-Referenzen, keine Koordinaten; daher
    KEIN BBox-Filter (Geo-Auflösung gegen das statische Pendant ist ein Folge-
    Detail, RESEARCH Open Question 3) - ``lat``/``lon`` bleiben Schnittstellen-
    konform optional. Reiner, synchroner Parse (testbar ohne Netz).

    Haertung: ``_guard`` (Pre-Parse-Guard + Size-Cap) läuft VOR ``iterparse``.
    Rueckgabe: ``{"slug": slug, "measurements": [...]}`` (je Messpunkt ein dict
    mit ``station_id`` + den gelesenen Werten).
    """
    _guard(xml_bytes)

    measurements: list[dict] = []
    bio = io.BytesIO(xml_bytes)
    # noqa S314: siehe parse_datex2_situations (stdlib-only + Pre-Parse-Guard).
    for _event, elem in iterparse(bio):  # noqa: S314
        if _localname(elem.tag) != "siteMeasurements":
            continue
        entry = _extract_measurement(elem)
        if entry is not None:
            measurements.append(entry)
        # Memory-konstant: das geparste Element sofort freigeben.
        elem.clear()

    return {"slug": slug, "measurements": measurements}


def parse_datex2_parking(
    xml_bytes: bytes,
    *,
    slug: str,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 30.0,
) -> dict:
    """Parst eine DATEX-II-V2-``ParkingStatusPublication`` (Parkhaus-Belegung, LIVE-09).

    STATUS (Audit 2026-06-29, Finding 184): dieser Parse-Zweig ist derzeit an KEINE
    Live-Route verdrahtet - kein Endpunkt ruft ``fetch_datex2(publication="parking")``
    auf. Die aktive Dortmund-Parken-Quelle ist der KEYLOSE Opendatasoft-Feed
    (``adapters/dortmund_parking.fetch_dortmund_parking``), nicht Mobilithek-DATEX-II.
    Die Tag-Konstanten (``_PARKING_*``) bleiben gegen die DATEX-II-V2-Spec ANGENOMMEN
    (am realen Abo-Feed nie verifiziert, kein Server-Zugriff). Der Zweig ist
    fixture-getestet und bleibt einsatzbereit für ein künftiges echtes
    Mobilithek-Parking-Abo; vor Inbetriebnahme die Konstanten am realen Feed prüfen.

    Additiver Parse-Zweig zum V2-Parser: je ``parkingStatus`` (siehe
    ``_PARKING_STATUS_TAG``) die Parkhaus-Referenz (``facility_id`` aus dem
    ``id``-Attribut der ``parkingRecordReference``) und die dynamische Belegung
    (``free`` = freie Plätze, ``capacity`` = Kapazität, ``occupancy`` =
    Auslastung in Prozent). Der dynamische Feed trägt im Status-Element keine
    Koordinaten (Geo aus dem statischen Pendant ist Folge-Detail, analog
    ``parse_datex2_measured``); daher KEIN BBox-Filter - ``lat``/``lon`` bleiben
    Schnittstellen-konform optional. Reiner, synchroner Parse (testbar ohne Netz).

    Haertung: IDENTISCH zu den V2-Parsern - ``_guard`` (Pre-Parse-Guard +
    Size-Cap, T-20-XXE) läuft VOR ``iterparse``, ``elem.clear()`` hält den
    Speicher konstant.

    Rueckgabe: ``{"slug": slug, "facilities": [...]}`` (leere/unbekannte
    Publication ohne ``parkingStatus`` -> ``[]``).
    """
    _guard(xml_bytes)

    facilities: list[dict] = []
    bio = io.BytesIO(xml_bytes)
    # noqa S314: siehe parse_datex2_situations (stdlib-only + Pre-Parse-Guard).
    for _event, elem in iterparse(bio):  # noqa: S314
        if _localname(elem.tag) != _PARKING_STATUS_TAG:
            continue
        entry = _extract_parking_facility(elem)
        if entry is not None:
            facilities.append(entry)
        # Memory-konstant: das geparste Element sofort freigeben.
        elem.clear()

    return {"slug": slug, "facilities": facilities}


def _extract_point(record) -> tuple[float, float] | None:
    """Liest eine repräsentative Koordinate (lat, lon) eines situationRecords.

    Zwei Geo-Kodierungen kommen real vor (NS-robust per ``_localname``):
    1. ``pointCoordinates`` (latitude/longitude) - Punkt-Locations (Köln-Stil).
    2. ``posList`` unter ``gmlLineString`` - lineare Locations (Berlin SenMVKU-Stil,
       LIVE-08): WGS84-Koordinatenliste "lat lon lat lon ...". Als Repräsentant
       dient das erste Koordinatenpaar (Anfang des Straßenabschnitts).
    Punkt-Koordinaten haben Vorrang; nur wenn keine vorhanden sind, greift der
    ``posList``-Fallback. Liefert ``None`` bei fehlenden/invaliden Koordinaten
    (ein Datenfehler fällt aus dem Filter, statt einen 500 auszulösen).
    """
    pos_fallback: tuple[float, float] | None = None
    for node in record.iter():
        local = _localname(node.tag)
        if local == "pointCoordinates":
            lat_val: float | None = None
            lon_val: float | None = None
            for child in node:
                cl = _localname(child.tag)
                text = (child.text or "").strip()
                if not text:
                    continue
                try:
                    if cl == "latitude":
                        lat_val = float(text)
                    elif cl == "longitude":
                        lon_val = float(text)
                except ValueError:
                    return None
            if lat_val is not None and lon_val is not None:
                return lat_val, lon_val
        elif local == "posList" and pos_fallback is None:
            pos_fallback = _first_poslist_point(node.text)
    return pos_fallback


def _first_poslist_point(text: str | None) -> tuple[float, float] | None:
    """Erstes (lat, lon)-Paar einer GML-``posList`` (WGS84, "lat lon lat lon ...").

    Reiner Parse; gibt ``None`` bei fehlendem/unvollstaendigem/invalidem Text
    zurück. Plausibilisiert grob auf DE-Bereich (lat 47-56, lon 5-16), damit eine
    vertauschte/exotische Achsenreihenfolge nicht stillschweigend Unsinn liefert.
    """
    if not text:
        return None
    parts = text.split()
    if len(parts) < 2:
        return None
    try:
        lat_val = float(parts[0])
        lon_val = float(parts[1])
    except ValueError:
        return None
    if 47.0 <= lat_val <= 56.0 and 5.0 <= lon_val <= 16.0:
        return lat_val, lon_val
    return None


def _first_comment(record) -> str | None:
    """Liest den ersten ``<value>``-Text unter ``generalPublicComment`` (NS-robust)."""
    for node in record.iter():
        if _localname(node.tag) == "value":
            text = (node.text or "").strip()
            if text:
                return text
    return None


def _extract_measurement(site) -> dict | None:
    """Liest station_id + Messwerte aus einem ``siteMeasurements``-Element.

    ``station_id`` aus dem ``id``-Attribut der ``measurementSiteReference``.
    Messwerte NS-robust per ``_localname``: ``speed`` (averageVehicleSpeed) und
    ``vehicleFlowRate`` (vehicleFlow). Felder optional (nicht jeder Messpunkt
    trägt beide). Gibt ``None`` zurück, wenn der Messpunkt komplett leer ist.
    """
    station_id: str | None = None
    speed: float | None = None
    flow: float | None = None

    for node in site.iter():
        local = _localname(node.tag)
        if local == "measurementSiteReference" and station_id is None:
            station_id = node.get("id")
            continue
        text = (node.text or "").strip()
        if not text:
            continue
        try:
            if local == "speed":
                speed = float(text)
            elif local == "vehicleFlowRate":
                flow = float(text)
        except ValueError:
            # Einzelner Datenfehler verwirft nur diesen Wert, nicht den Messpunkt.
            continue

    if station_id is None and speed is None and flow is None:
        return None

    entry: dict = {"station_id": station_id}
    if speed is not None:
        entry["speed"] = speed
    if flow is not None:
        entry["flow"] = flow
    return entry


def _extract_parking_facility(status) -> dict | None:
    """Liest facility_id + Belegungswerte aus einem ``parkingStatus``-Element.

    ``facility_id`` aus dem ``id``-Attribut der Parkhaus-Referenz
    (``_PARKING_REF_TAGS``). Belegungswerte NS-robust per ``_localname``:
    ``free`` (``_PARKING_VACANT_TAG``, int), ``capacity``
    (``_PARKING_CAPACITY_TAG``, int), ``occupancy`` (``_PARKING_OCCUPANCY_TAG``,
    float). Felder optional (nicht jedes Parkhaus trägt alle Werte). Gibt
    ``None`` zurück, wenn das Element komplett leer ist (Datenfehler fällt aus,
    statt 500). Ein einzelner unparsebarer Wert verwirft nur diesen Wert.
    """
    facility_id: str | None = None
    free: int | None = None
    capacity: int | None = None
    occupancy: float | None = None

    for node in status.iter():
        local = _localname(node.tag)
        if local in _PARKING_REF_TAGS and facility_id is None:
            facility_id = node.get("id")
            continue
        text = (node.text or "").strip()
        if not text:
            continue
        try:
            if local == _PARKING_VACANT_TAG:
                free = int(float(text))
            elif local == _PARKING_CAPACITY_TAG:
                capacity = int(float(text))
            elif local == _PARKING_OCCUPANCY_TAG:
                occupancy = float(text)
        except ValueError:
            # Einzelner Datenfehler verwirft nur diesen Wert, nicht das Parkhaus.
            continue

    if facility_id is None and free is None and capacity is None and occupancy is None:
        return None

    entry: dict = {"facility_id": facility_id}
    if free is not None:
        entry["free"] = free
    if capacity is not None:
        entry["capacity"] = capacity
    if occupancy is not None:
        entry["occupancy"] = occupancy
    return entry


def _extract_publication_time(xml_bytes: bytes) -> str | None:
    """Liest die erste ``publicationTime`` (DATEX-II ``as_of``) NS-robust.

    Gibt den ISO-Text zurück (z.B. ``2026-06-12T10:00:00+02:00``) oder ``None``.
    Reiner Parse ohne Validierung; der Wert wandert später in den Live-Envelope
    (``as_of``). Setzt ``_guard`` als bereits gelaufen voraus (interner Helfer).
    """
    bio = io.BytesIO(xml_bytes)
    for _event, elem in iterparse(bio):  # noqa: S314
        if _localname(elem.tag) == "publicationTime":
            text = (elem.text or "").strip()
            elem.clear()
            return text or None
        elem.clear()
    return None


async def fetch_datex2(
    mtls_client,
    *,
    abo_id: str,
    slug: str,
    lat: float,
    lon: float,
    publication: str,
    radius_km: float = 30.0,
) -> dict:
    """Pullt ein Mobilithek-Abo und parst es je Publication-Typ (LIVE-05/06/07).

    Live-Pfad (untrusted): baut die Pull-URL aus der Allowlist-``abo_id``
    (``build_pull_url``, Host hartkodiert -> SSRF-Invariante), pullt über den
    mTLS-Client (``pull_subscription``) und verzweigt nach ``publication``:
    ``"situation"`` -> ``parse_datex2_situations``, ``"measured"`` ->
    ``parse_datex2_measured``.

    HTTP 422 (Abo aktiv, kein Datenpaket) liefert ``status="no_data"`` -> ein
    ehrliches leeres Ergebnis (kein ``raise``, T-20-422). Ein vom Pre-Parse-Guard
    / Size-Cap abgelehnter Body (``ValueError``) liefert ebenfalls ein ehrliches
    leeres Ergebnis (no_data), statt eine feindliche Payload zu parsen oder die
    Route mit 5xx zu treffen. 5xx/Netzfehler schlagen via ``pull_subscription``
    durch an die resiliente Fassade (STALE-ON-ERROR).

    Rückgabe-Keys (exakt was die Mapper erwarten): ``slug`` + ``events``
    (situation) bzw. ``measurements`` (measured) bzw. ``facilities`` (parking),
    plus ``as_of`` (publicationTime, optional) für den Live-Envelope.
    """
    # Leer-Key je Publication (additiv um parking erweitert, bestehende Werte
    # situation/measured unverändert).
    if publication == "situation":
        empty_key = "events"
    elif publication == "parking":
        empty_key = "facilities"
    else:  # "measured"
        empty_key = "measurements"

    url = build_pull_url(abo_id)
    result = await pull_subscription(mtls_client, url)
    if result["status"] == "no_data" or result["body"] is None:
        return {"slug": slug, empty_key: [], "as_of": None}

    body: bytes = result["body"]
    try:
        if publication == "situation":
            parsed = parse_datex2_situations(
                body, slug=slug, lat=lat, lon=lon, radius_km=radius_km
            )
        elif publication == "parking":
            parsed = parse_datex2_parking(
                body, slug=slug, lat=lat, lon=lon, radius_km=radius_km
            )
        else:
            parsed = parse_datex2_measured(
                body, slug=slug, lat=lat, lon=lon, radius_km=radius_km
            )
    except ValueError:
        # Pre-Parse-Guard / Size-Cap hat den Body abgelehnt -> ehrliches no_data
        # (die Route behandelt no_data; kein Parse einer feindlichen Payload).
        return {"slug": slug, empty_key: [], "as_of": None}

    # publicationTime als as_of durchreichen (Live-Envelope). Guard lief bereits,
    # daher direkt parsen (kein zweiter _guard nötig).
    parsed["as_of"] = _extract_publication_time(body)
    return parsed


# ---------------------------------------------------------------------------
# DATEX-II-V2 ParkingFacility-Profil (Wuppertal, statisch + dynamisch gejoint).
#
# Eigenes V2-Profil, getrennt vom Köln-/Dortmund-``parkingStatus``-Pfad
# (parse_datex2_parking): Wuppertal liefert eine
# ``parkingFacilityTableStatusPublication`` (dynamisch) bzw. eine
# ``parkingFacilityTablePublication`` (statisch). GOTCHA (verifiziert
# 2026-06-22): ``parkingFacilityStatus`` ist DOPPELT belegt -- einmal als Wrapper
# je Parkplatz (trägt ein ``parkingFacilityReference``-Kind) und einmal als
# inneres Status-Enum-Feld (Text "open"/"closed"). Der Parser verarbeitet nur den
# Wrapper (erkannt am ``parkingFacilityReference``-Kind). Join-Key:
# ``parkingFacilityReference@id`` (dynamisch) == ``parkingFacility@id``
# (statisch), z.B. "32[Stadthalle]". ``parkingFacilityOccupancy`` ist ein Anteil
# 0..1 (1.0 = 100 %), wird zu Prozent normalisiert. Pull-Stil = "path".
# ---------------------------------------------------------------------------

_FACILITY_STATUS_TAG = "parkingFacilityStatus"  # Wrapper UND inneres Enum
_FACILITY_REF_TAG = "parkingFacilityReference"  # trägt id (Join-Key, nur Wrapper)
_FACILITY_VACANT_TAG = "totalNumberOfVacantParkingSpaces"
_FACILITY_OCCUPIED_TAG = "totalNumberOfOccupiedParkingSpaces"
_FACILITY_CAPACITY_TAG = "totalParkingCapacityOverride"
_FACILITY_OCCUPANCY_TAG = "parkingFacilityOccupancy"  # Anteil 0..1
_FACILITY_TREND_TAG = "parkingFacilityOccupancyTrend"
_FACILITY_TIME_TAG = "parkingFacilityStatusTime"

_FACILITY_TAG = "parkingFacility"  # statisches Record (trägt id)
_FACILITY_NAME_TAG = "parkingFacilityName"
_FACILITY_STATIC_CAPACITY_TAG = "totalParkingCapacity"
_FACILITY_LOCATION_TAG = "facilityLocation"
_VALUE_TAG = "value"
_LAT_TAG = "latitude"
_LON_TAG = "longitude"


def _find_local(elem, local: str):
    """Erstes Descendant-Element mit gegebenem lokalem Tag-Namen (oder None)."""
    for node in elem.iter():
        if _localname(node.tag) == local:
            return node
    return None


def _first_text_local(elem, local: str) -> str | None:
    """Erster nicht-leerer Text eines Descendant mit gegebenem lokalem Tag-Namen."""
    for node in elem.iter():
        if _localname(node.tag) == local:
            text = (node.text or "").strip()
            if text:
                return text
    return None


def _extract_facility_status(wrapper) -> dict | None:
    """Liest facility_id + Belegung aus einem ``parkingFacilityStatus``-Wrapper (V2).

    Belegung NS-robust: ``free`` (totalNumberOfVacantParkingSpaces, int),
    ``capacity`` (totalParkingCapacityOverride, int), ``occupied`` (int),
    ``occupancy`` (parkingFacilityOccupancy * 100 = Prozent), ``status`` (das
    INNERE parkingFacilityStatus-Enum mit Text; der Wrapper selbst hat keinen
    direkten Text), ``trend``, ``observed_at`` (parkingFacilityStatusTime).
    """
    facility_id: str | None = None
    free: int | None = None
    capacity: int | None = None
    occupied: int | None = None
    occupancy: float | None = None
    status: str | None = None
    trend: str | None = None
    observed_at: str | None = None

    for node in wrapper.iter():
        local = _localname(node.tag)
        if local == _FACILITY_REF_TAG and facility_id is None:
            facility_id = node.get("id")
            continue
        text = (node.text or "").strip()
        if not text:
            continue
        try:
            if local == _FACILITY_VACANT_TAG:
                free = int(float(text))
            elif local == _FACILITY_CAPACITY_TAG:
                capacity = int(float(text))
            elif local == _FACILITY_OCCUPIED_TAG:
                occupied = int(float(text))
            elif local == _FACILITY_OCCUPANCY_TAG:
                occupancy = round(float(text) * 100, 2)
            elif local == _FACILITY_STATUS_TAG and status is None:
                status = text
            elif local == _FACILITY_TREND_TAG and trend is None:
                trend = text
            elif local == _FACILITY_TIME_TAG and observed_at is None:
                observed_at = text
        except ValueError:
            continue

    if facility_id is None and free is None and occupancy is None:
        return None

    entry: dict = {"facility_id": facility_id}
    if free is not None:
        entry["free"] = free
    if capacity is not None:
        entry["capacity"] = capacity
    if occupied is not None:
        entry["occupied"] = occupied
    if occupancy is not None:
        entry["occupancy"] = occupancy
    if status is not None:
        entry["status"] = status
    if trend is not None:
        entry["trend"] = trend
    if observed_at is not None:
        entry["observed_at"] = observed_at
    return entry


def _extract_facility_site(record) -> dict | None:
    """Liest facility_id + Stammdaten aus einem statischen ``parkingFacility`` (V2).

    ``facility_id`` aus dem ``id``-Attribut. ``name`` aus dem ersten ``value``
    unter ``parkingFacilityName`` (gezielt, NICHT der erste ``value`` im Record).
    ``capacity`` aus ``totalParkingCapacity`` (exakter Tag, nicht ShortTerm/
    LongTerm). ``lat``/``lon`` gezielt aus ``facilityLocation``.
    """
    facility_id = record.get("id")

    name = None
    name_elem = _find_local(record, _FACILITY_NAME_TAG)
    if name_elem is not None:
        name = _first_text_local(name_elem, _VALUE_TAG)

    capacity: int | None = None
    cap_text = _first_text_local(record, _FACILITY_STATIC_CAPACITY_TAG)
    if cap_text is not None:
        try:
            capacity = int(float(cap_text))
        except ValueError:
            capacity = None

    lat: float | None = None
    lon: float | None = None
    loc = _find_local(record, _FACILITY_LOCATION_TAG)
    if loc is not None:
        lat_text = _first_text_local(loc, _LAT_TAG)
        lon_text = _first_text_local(loc, _LON_TAG)
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


def parse_facility_status_v2(xml_bytes: bytes, *, slug: str) -> dict:
    """Parst eine DATEX-II-V2 ParkingFacilityTableStatusPublication (dynamisch).

    Nur der Wrapper ``parkingFacilityStatus`` (mit ``parkingFacilityReference``-
    Kind) wird verarbeitet; das gleichnamige innere Enum-Feld wird übersprungen.
    Haertung: ``_guard`` vor ``iterparse``. Rückgabe ``{"slug", "facilities":
    [...], "as_of"}``.
    """
    _guard(xml_bytes)

    facilities: list[dict] = []
    bio = io.BytesIO(xml_bytes)
    for _event, elem in iterparse(bio):  # noqa: S314
        if _localname(elem.tag) != _FACILITY_STATUS_TAG:
            continue
        # Wrapper hat ein parkingFacilityReference-Kind; inneres Enum nicht.
        if not any(_localname(c.tag) == _FACILITY_REF_TAG for c in elem):
            continue
        entry = _extract_facility_status(elem)
        if entry is not None:
            facilities.append(entry)
        elem.clear()

    return {
        "slug": slug,
        "facilities": facilities,
        "as_of": _extract_publication_time(xml_bytes),
    }


def parse_facility_static_v2(xml_bytes: bytes, *, slug: str) -> dict:
    """Parst eine DATEX-II-V2 ParkingFacilityTablePublication (statisch, Stammdaten).

    Gibt ``{"slug", "sites": {facility_id: {...}}}`` für den Join zurück.
    Haertung: ``_guard`` vor ``iterparse``.
    """
    _guard(xml_bytes)

    sites: dict[str, dict] = {}
    bio = io.BytesIO(xml_bytes)
    for _event, elem in iterparse(bio):  # noqa: S314
        if _localname(elem.tag) != _FACILITY_TAG:
            continue
        site = _extract_facility_site(elem)
        if site is not None and site.get("facility_id"):
            sites[site["facility_id"]] = site
        elem.clear()

    return {"slug": slug, "sites": sites}


def _join_facilities(status: dict, static: dict) -> list[dict]:
    """Joint dynamische Belegung mit statischen Stammdaten über die facility_id."""
    sites: dict = static.get("sites", {})
    merged: list[dict] = []
    for fac in status.get("facilities", []):
        fid = fac.get("facility_id")
        site = sites.get(fid, {}) if fid else {}
        entry = {**{k: v for k, v in site.items() if k != "facility_id"}, **fac}
        merged.append(entry)
    return merged


async def fetch_wuppertal_parking(
    mtls_client,
    *,
    abo_id: str,
    static_abo_id: str | None,
    slug: str,
) -> dict:
    """Pullt Wuppertal-Parkdaten (dynamisch + statisch, V2) und joint sie.

    Pull-Stil "path" (Default ``build_pull_url``; verifiziert 2026-06-22, der
    container-/query-Zugriff gibt 404). Das statische Abo ist optional: fehlt es
    oder liefert es nichts, wird die dynamische Belegung ohne Stammdaten
    zurückgegeben (ehrliche Degradation). HTTP 422 / ein vom Guard abgelehnter
    Body liefern ein ehrliches leeres Ergebnis (no_data, kein ``raise``).

    Rueckgabe: ``{"slug", "facilities": [...], "as_of"}``; jedes facility trägt
    facility_id + free/capacity/occupied/occupancy/status/trend/observed_at
    (dynamisch) + name/lat/lon/capacity (statisch, Stammdaten-Anreicherung).
    """
    dyn_url = build_pull_url(abo_id)  # style="path" (Default)
    dyn_result = await pull_subscription(mtls_client, dyn_url)
    if dyn_result["status"] == "no_data" or dyn_result["body"] is None:
        return {"slug": slug, "facilities": [], "as_of": None}

    try:
        status = parse_facility_status_v2(dyn_result["body"], slug=slug)
    except ValueError:
        return {"slug": slug, "facilities": [], "as_of": None}

    static = {"slug": slug, "sites": {}}
    if static_abo_id:
        try:
            stat_result = await pull_subscription(
                mtls_client, build_pull_url(static_abo_id)
            )
            if stat_result["status"] == "ok" and stat_result["body"] is not None:
                static = parse_facility_static_v2(stat_result["body"], slug=slug)
        except ValueError:
            static = {"slug": slug, "sites": {}}

    return {
        "slug": slug,
        "facilities": _join_facilities(status, static),
        "as_of": status.get("as_of"),
    }
