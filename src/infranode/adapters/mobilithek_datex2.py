"""Keyloser Mobilithek-DATEX-II-V2-Adapter (LIVE-05/06/07, Phase 20).

Generischer DATEX-II-V2-Parse-Pfad gegen den Mobilithek-mTLS-Pull-Client
(infra/mobilithek.py). Schablone ist ``adapters/mobidata_bw.py`` (exakt): die
DoS/XXE-Haertung ist identisch, je Publication-Typ wechselt nur das gesuchte
Element.

Zwei Publication-Typen (CONTEXT, an Koeln verifiziert):
- ``SituationPublication`` -> ``situationRecord`` (Baustellen/Ereignisse, LIVE-07).
  ``parse_datex2_situations`` filtert per BBox um die Stadt (analog mobidata_bw).
- ``MeasuredDataPublication`` -> ``siteMeasurements``/``measuredValue``
  (Verkehrslage dynamisch, LIVE-06). ``parse_datex2_measured`` liest je Messpunkt
  die ``measurementSiteReference``-ID (station_id) + die Messwerte
  (Geschwindigkeit/Flow). Der dynamische Feed traegt nur ID-Referenzen, kein Geo;
  station_id wird durchgereicht (Join gegen das statische Pendant ist ein Folge-
  Detail, RESEARCH Open Question 3).

KEINE neue Dependency (CLAUDE.md / Decision 1, projektweit untersagt): stdlib
``xml.etree.ElementTree.iterparse``. ABER Mobilithek ist ein LIVE-Request-Pfad
(untrusted) -> PFLICHT-Haertung OHNE neue Dependency (T-20-XXE), exakt wie
mobidata_bw.py:

1. Pre-Parse-Guard: ``<!DOCTYPE`` / ``<!ENTITY`` im Body -> ``ValueError`` BEVOR
   ``iterparse`` ihn sieht (verhindert XXE / Billion-Laughs).
2. Size-Cap ``_MAX_BYTES``: ein zu grosser Body -> ``ValueError`` (DoS-Schutz).
3. ``# noqa: S314, S405``: stdlib-Parse bewusst gewaehlt (Decision 1); die
   XXE/DoS-Mitigation ist der Pre-Parse-Guard + Size-Cap (untrusted Live-Feed).

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper), kennt KEIN Cache/Breaker (das liefert
die Fassade) und schreibt KEIN Archiv. Der ``fetch_datex2``-Wrapper ruft den
Mobilithek-mTLS-Client (``pull_subscription``), mappt HTTP 422 auf ``no_data``
und gibt ein ehrliches leeres Ergebnis zurueck, wenn der Guard/Size-Cap greift.
"""

from __future__ import annotations

import io
from xml.etree.ElementTree import iterparse  # noqa: S405

from infranode.adapters.autobahn import _within_bbox
from infranode.infra.mobilithek import build_pull_url, pull_subscription

# Size-Cap (T-20-XXE / DoS): konservativ ueber der erwarteten Koeln-Variante
# (~48 KB) und allen anderen V2-Feeds. Ein groesserer Body wird nicht geparst.
_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB

# DATEX-II V2 Namespace (RESEARCH). Nur Doku-Konstante: der Parse strippt den NS
# ohnehin per _localname, daher robust gegen NS-Detail-Drift.
_NS = "{http://datex2.eu/schema/2/2_0}"

# Parking-Status-Element (LIVE-09, RESEARCH Open Question 2): die dynamische
# Dortmund-Belegung steht in einer ``ParkingStatusPublication``; je Parkhaus ein
# ``parkingStatus``-Container mit der Parkhaus-Referenz
# (``parkingRecordReference``/``parkingRecordStatus``, ID-Attribut) und den
# Belegungswerten (``parkingNumberOfVacantSpaces`` = freie Plaetze,
# ``parkingNumberOfSpacesOverride`` = Kapazitaet, ``parkingOccupancy`` = Auslastung
# in Prozent). ANNAHME (nicht am realen Feed verifiziert, kein Server-Zugriff): das
# exakte Publication-Element des Dortmund-Abos ist anhand der DATEX-II-V2-Spec +
# RESEARCH angenommen. Falls der reale Abo-Feed andere lokale Tag-Namen nutzt,
# genuegt es, diese Konstanten anzupassen (der Parse ist NS-robust per _localname).
_PARKING_STATUS_TAG = "parkingStatus"
_PARKING_REF_TAGS = ("parkingRecordReference", "parkingRecordStatus")
_PARKING_VACANT_TAG = "parkingNumberOfVacantSpaces"
_PARKING_CAPACITY_TAG = "parkingNumberOfSpacesOverride"
_PARKING_OCCUPANCY_TAG = "parkingOccupancy"


def _localname(tag: str) -> str:
    """Gibt den lokalen Tag-Namen ohne XML-Namespace-Praefix zurueck."""
    return tag.rsplit("}", 1)[-1]


def _guard(xml_bytes: bytes) -> None:
    """Pre-Parse-Guard + Size-Cap (T-20-XXE), gemeinsam fuer beide Parser.

    PFLICHT vor jedem ``iterparse`` (untrusted Live-Feed): ein DOCTYPE/ENTITY-
    Body oder ein Body groesser ``_MAX_BYTES`` wird mit ``ValueError`` abgelehnt,
    BEVOR der Parser ihn sieht (verhindert XXE / Billion-Laughs / DoS).
    """
    # Size-Cap (T-20-XXE): zu grosse Bodies gar nicht erst parsen.
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
    (``latitude``/``longitude``); nur Eintraege innerhalb der Bounding-Box um
    (``lat``, ``lon``) passieren den ``_within_bbox``-Filter (Baustellen/
    Ereignisse, LIVE-07). Reiner, synchroner Parse (testbar ohne Netz).

    Haertung: ``_guard`` (Pre-Parse-Guard + Size-Cap) laeuft VOR ``iterparse``.
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
    ``averageVehicleSpeed/speed``, Verkehrsstaerke ``vehicleFlow/vehicleFlowRate``).
    Der dynamische Koeln-Feed traegt nur ID-Referenzen, keine Koordinaten; daher
    KEIN BBox-Filter (Geo-Aufloesung gegen das statische Pendant ist ein Folge-
    Detail, RESEARCH Open Question 3) - ``lat``/``lon`` bleiben Schnittstellen-
    konform optional. Reiner, synchroner Parse (testbar ohne Netz).

    Haertung: ``_guard`` (Pre-Parse-Guard + Size-Cap) laeuft VOR ``iterparse``.
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

    Additiver Parse-Zweig zum V2-Parser: je ``parkingStatus`` (siehe
    ``_PARKING_STATUS_TAG``) die Parkhaus-Referenz (``facility_id`` aus dem
    ``id``-Attribut der ``parkingRecordReference``) und die dynamische Belegung
    (``free`` = freie Plaetze, ``capacity`` = Kapazitaet, ``occupancy`` =
    Auslastung in Prozent). Der dynamische Feed traegt im Status-Element keine
    Koordinaten (Geo aus dem statischen Pendant ist Folge-Detail, analog
    ``parse_datex2_measured``); daher KEIN BBox-Filter - ``lat``/``lon`` bleiben
    Schnittstellen-konform optional. Reiner, synchroner Parse (testbar ohne Netz).

    Haertung: IDENTISCH zu den V2-Parsern - ``_guard`` (Pre-Parse-Guard +
    Size-Cap, T-20-XXE) laeuft VOR ``iterparse``, ``elem.clear()`` haelt den
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
    """Liest die erste ``pointCoordinates`` (latitude/longitude) eines Records.

    NS-robust per ``_localname``. Liefert ``None``, wenn keine validen
    Koordinaten gefunden werden (ein Datenfehler faellt damit aus dem Filter,
    statt einen 500 auszuloesen).
    """
    for node in record.iter():
        if _localname(node.tag) != "pointCoordinates":
            continue
        lat_val: float | None = None
        lon_val: float | None = None
        for child in node:
            local = _localname(child.tag)
            text = (child.text or "").strip()
            if not text:
                continue
            try:
                if local == "latitude":
                    lat_val = float(text)
                elif local == "longitude":
                    lon_val = float(text)
            except ValueError:
                return None
        if lat_val is not None and lon_val is not None:
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
    traegt beide). Gibt ``None`` zurueck, wenn der Messpunkt komplett leer ist.
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
    float). Felder optional (nicht jedes Parkhaus traegt alle Werte). Gibt
    ``None`` zurueck, wenn das Element komplett leer ist (Datenfehler faellt aus,
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

    Gibt den ISO-Text zurueck (z.B. ``2026-06-12T10:00:00+02:00``) oder ``None``.
    Reiner Parse ohne Validierung; der Wert wandert spaeter in den Live-Envelope
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
    (``build_pull_url``, Host hartkodiert -> SSRF-Invariante), pullt ueber den
    mTLS-Client (``pull_subscription``) und verzweigt nach ``publication``:
    ``"situation"`` -> ``parse_datex2_situations``, ``"measured"`` ->
    ``parse_datex2_measured``.

    HTTP 422 (Abo aktiv, kein Datenpaket) liefert ``status="no_data"`` -> ein
    ehrliches leeres Ergebnis (kein ``raise``, T-20-422). Ein vom Pre-Parse-Guard
    / Size-Cap abgelehnter Body (``ValueError``) liefert ebenfalls ein ehrliches
    leeres Ergebnis (no_data), statt eine feindliche Payload zu parsen oder die
    Route mit 5xx zu treffen. 5xx/Netzfehler schlagen via ``pull_subscription``
    durch an die resiliente Fassade (STALE-ON-ERROR).

    Rueckgabe-Keys (exakt was die Mapper erwarten): ``slug`` + ``events``
    (situation) bzw. ``measurements`` (measured) bzw. ``facilities`` (parking),
    plus ``as_of`` (publicationTime, optional) fuer den Live-Envelope.
    """
    # Leer-Key je Publication (additiv um parking erweitert, bestehende Werte
    # situation/measured unveraendert).
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
    # daher direkt parsen (kein zweiter _guard noetig).
    parsed["as_of"] = _extract_publication_time(body)
    return parsed
