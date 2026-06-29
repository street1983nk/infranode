"""Keyloser MobiData-BW-DATEX-II-Adapter (DATA-15, Success Criterion 2).

Beweist den keylosen DATEX-II-V2-Parse-Pfad über den landesweiten BW-Feed von
MobiData BW (Verkehrsministerium Baden-Württemberg), BBox-gefiltert auf Stuttgart.
Der Feed ist eine ~20-MB-DATEX-II-XML-Datei (``SituationPublication``) mit
Namespace ``http://datex2.eu/schema/2/2_0``.

KEINE neue Dependency (Orchestrator-Decision 1, projektweit untersagt, CLAUDE.md):
das XML wird mit stdlib ``xml.etree.ElementTree.iterparse`` geparst, analog
``ingest/mastr.py`` (``# noqa S314/S405``). ABER anders als mastr.py (Offline-Bulk,
trusted) ist MobiData ein LIVE-Request-Pfad -> XXE / Billion-Laughs ist relevant.
Daher PFLICHT-Härtung OHNE neue Dependency (T-9-01):

1. Pre-Parse-Guard: die Response-Bytes werden VOR dem Parsen auf ``<!DOCTYPE`` und
   ``<!ENTITY`` geprüft; bei Fund wird der Body abgelehnt (``ValueError``), BEVOR
   ``iterparse`` ihn sieht. Damit findet nie eine Entity-Expansion statt.
2. Size-Cap ``_MAX_BYTES``: ein Body größer als der Cap wird nicht geparst
   (Begrenzung der ~20-MB-Variante / DoS-Schutz).
3. ``# noqa: S314, S405``: der Import von ``xml.etree.ElementTree`` triggert S405,
   der ``iterparse``-Call S314. Beide werden bewusst per noqa unterdrückt, weil
   die DoS/XXE-Mitigation hier der Pre-Parse-Guard + Size-Cap ist (KEINE neue
   stdlib-fremde XML-Dependency, Decision 1), und der untrusted Live-Feed-
   Charakter (anders als mastr.py) ist genau der Grund für den Guard.

Sicherheit (T-9-02 SSRF): der Host ist in ``_BASE`` hartkodiert; kein User-Input
gelangt in die URL. Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut
KEINEN ``CanonicalRecord`` (das macht der Mapper) und kennt KEIN Cache/Breaker
(das liefert die Fassade). Route-Anbindung in 09-06.
"""

from __future__ import annotations

import io
from xml.etree.ElementTree import iterparse  # noqa: S405

import httpx

from infranode.adapters.autobahn import _within_bbox

# Host hartkodiert (T-9-02 SSRF): nur diese eine öffentliche MobiData-Instanz.
_BASE = "https://api.mobidata-bw.de"

# DATEX-II-Roadworks-Ressource des landesweiten BW-Feeds (SVZ BW), RESEARCH Z. 449.
_RESOURCE = "/datex2/v2/roadworks_svzbw.datex2.xml"

# Size-Cap (T-9-01 DoS): konservativ über der erwarteten ~20-MB-Variante. Ein
# größerer Body wird gar nicht erst geparst, sondern als no_data behandelt.
_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB

# DATEX-II V2 Namespace (RESEARCH Pitfall 3). Nur als Doku-Konstante: der Parse
# strippt den NS ohnehin per _localname, daher robust gegen NS-Detail-Drift.
_NS = "{http://datex2.eu/schema/2/2_0}"


def _localname(tag: str) -> str:
    """Gibt den lokalen Tag-Namen ohne XML-Namespace-Präfix zurück."""
    return tag.rsplit("}", 1)[-1]


def parse_mobidata_datex2(
    xml_bytes: bytes,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Parst einen DATEX-II-V2-Body und filtert die situationRecords auf die BBox.

    Reiner, synchroner Parse-Pfad (testbar ohne Netz): nimmt die rohen Bytes,
    härtet sie (Pre-Parse-Guard + Size-Cap) und parst sie streaming via stdlib
    ``iterparse``. Je ``situationRecord`` werden ``pointCoordinates``
    (``latitude``/``longitude``) gelesen; nur Einträge innerhalb der Bounding-Box
    um (``lat``, ``lon``) passieren den ``_within_bbox``-Filter.

    Härtung (T-9-01, untrusted Live-Feed):
    - Pre-Parse-Guard: ``<!DOCTYPE`` / ``<!ENTITY`` im Body -> ``ValueError`` BEVOR
      ``iterparse`` läuft (verhindert XXE / Billion-Laughs, stdlib-only).
    - Size-Cap ``_MAX_BYTES``: ein zu großer Body -> ``ValueError`` (kein Parse).

    Rueckgabe: ``{"slug": slug, "events": [...]}``; eine leere
    ``SituationPublication`` liefert ``events == []``.
    """
    # Size-Cap (T-9-01): zu große Bodies gar nicht erst parsen.
    if len(xml_bytes) > _MAX_BYTES:
        raise ValueError(
            f"MobiData-DATEX-II-Body ueberschreitet _MAX_BYTES ({_MAX_BYTES})"
        )

    # Pre-Parse-Guard (T-9-01, Decision 1): DOCTYPE/ENTITY -> ABLEHNEN vor Parse.
    # KEIN iterparse auf solchem Body (verhindert Entity-Expansion / XXE).
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise ValueError(
            "MobiData-DATEX-II-Body enthaelt DOCTYPE/ENTITY (XXE/Billion-Laughs "
            "abgelehnt vor Parse, Pre-Parse-Guard T-9-01)"
        )

    events: list[dict] = []
    bio = io.BytesIO(xml_bytes)
    # noqa S314: stdlib-Parse bewusst gewählt (Decision 1, stdlib-only). Die
    # XXE/DoS-Mitigation ist der Pre-Parse-Guard + Size-Cap oben (untrusted Live-
    # Feed, anders als der trusted Offline-Bulk in ingest/mastr.py).
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
                        "type": _localname(elem.get(f"{_NS}type", "") or "")
                        or elem.get("{http://www.w3.org/2001/XMLSchema-instance}type"),
                        "comment": _first_comment(elem),
                        "latitude": elat,
                        "longitude": elon,
                    }
                )
        # Memory-konstant: das geparste Element sofort freigeben.
        elem.clear()

    return {"slug": slug, "events": events}


def _extract_point(record) -> tuple[float, float] | None:
    """Liest die erste ``pointCoordinates`` (latitude/longitude) eines Records.

    NS-robust per ``_localname`` (kein NS-Präfix nötig). Liefert ``None``, wenn
    keine validen Koordinaten gefunden werden (ein Datenfehler fällt damit aus
    dem Filter, statt einen 500 auszulösen).
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


async def fetch_mobidata_road_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt den DATEX-II-Roadworks-Feed und filtert ihn auf die Stadt-BBox.

    Live-Pfad (untrusted): lädt den hartkodierten ``_BASE`` + ``_RESOURCE``,
    erzwingt ``raise_for_status`` (5xx -> ``httpx.HTTPError`` an die Fassade ->
    STALE-ON-ERROR) und gibt die Bytes an den gehärteten ``parse_mobidata_datex2``
    weiter (Size-Cap + Pre-Parse-Guard + iterparse). Ein abgelehnter Body
    (DOCTYPE/ENTITY oder zu groß) liefert ``no_data`` (leere events), statt eine
    Entity-Expansion zu riskieren.

    Rückgabe-Keys (exakt was ``map_mobidata_road_events`` erwartet): ``slug`` und
    ``events``.
    """
    resp = await http.get(_BASE + _RESOURCE)
    resp.raise_for_status()

    # Size-Cap vorab gegen den Content-Length-Header (T-9-01): einen offensichtlich
    # zu großen Body gar nicht erst materialisieren/parsen.
    content_length = resp.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_BYTES:
                return {"slug": slug, "events": []}
        except ValueError:
            pass

    try:
        return parse_mobidata_datex2(
            resp.content, slug=slug, lat=lat, lon=lon, radius_km=radius_km
        )
    except ValueError:
        # Pre-Parse-Guard / Size-Cap hat den Body abgelehnt -> ehrliches no_data
        # (die Route behandelt no_data; kein Parse einer feindlichen Payload).
        return {"slug": slug, "events": []}
