"""Keyloser eRound-AFIR-DATEX-II-V3-Adapter (LIVE-11, Phase 20).

Die einzige DATEX-II-**V3**-Quelle der Phase: das eRound-AFIR-Recharging-Abo
(EnergyInfrastructureStatusPublication, Ladesaeulen-Belegung in Echtzeit,
schliesst die zweite Haelfte der DATA-09-Luecke). Getrennt vom V2-Pfad gehalten
(``adapters/mobilithek_datex2.py``), damit die 8 V2-Quellen nicht blockiert
werden (RESEARCH Pitfall 4: der V2-Parser greift bei einem V3-Body NICHT).

REALITAET (Mobilithek-Portal verifiziert 2026-06-12): das eRound-Angebot liefert
DATEX II V3 als **JSON** (Datenmodell "DATEX II V3", Syntax "JSON"), NICHT als
XML. Daher parst dieser Adapter stdlib-``json`` (kein lxml, kein ElementTree).
Das weicht vom urspruenglichen Plan-Wortlaut (XML, iterparse) ab; die
JSON-Realitaet ist im SUMMARY als Deviation dokumentiert.

Haertung (JSON-Variante):
- **Kein XXE-Vektor**: stdlib ``json`` expandiert keine externen Entities; der
  DOCTYPE/ENTITY-Pre-Parse-Guard des V2-Adapters entfaellt ersatzlos (es gibt
  keinen XML-Parser, der angegriffen werden koennte).
- **Size-Cap** ``_MAX_BYTES`` (T-20-XXE/DoS): ein zu grosser Body -> ``ValueError``
  VOR ``json.loads`` (DoS-Schutz bleibt, identisch zum V2-Adapter).
- **Root-Typ-Verzweigung** (Pitfall 4): der Publication-Typ wird VOR dem Auslesen
  geprueft; ein fremder/V2-Body liefert leere ``points`` statt eines Fehl-Parse.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper), kennt KEIN Cache/Breaker (das liefert
die Fassade) und schreibt KEIN Archiv. Der ``fetch_afir``-Wrapper ruft den
Mobilithek-mTLS-Client (``pull_subscription``) mit der eRound-spezifischen
Query-URL-Variante (``build_pull_url(..., style="query")``), mappt HTTP 422 auf
``no_data`` und gibt ein ehrliches leeres Ergebnis zurueck, wenn der Size-Cap
greift oder der Body kein valides V3-JSON ist.
"""

from __future__ import annotations

import json

from infranode.infra.mobilithek import build_pull_url, pull_subscription

# Size-Cap (T-20-XXE / DoS): konservativ ueber dem erwarteten AFIR-Feed. Ein
# groesserer Body wird gar nicht erst geparst. Identisch zum V2-Adapter.
_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB

# DATEX-II-V3 Publication-Typ des AFIR-Recharging-Profils (Pitfall 4). Nur dieser
# Typ traegt refillPointStatus-Eintraege; ein anderer Publication-Typ (z.B. ein
# V2-SituationPublication-Body) liefert ehrlich leere points.
_PUBLICATION_TYPE = "EnergyInfrastructureStatusPublication"


def _coerce_list(value) -> list:
    """Normalisiert ein DATEX-II-Feld zu einer Liste (dict-Wert ODER Liste).

    DATEX-II-JSON traegt wiederholbare Elemente je nach Serialisierung mal als
    einzelnes Objekt, mal als Array. Diese Helfer macht beides zu einer Liste
    (None -> leere Liste), damit der Parser robust ueber beide Formen iteriert.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _extract_refill_point(entry: dict) -> dict | None:
    """Liest refill_point_id + status (+ observed_at) aus einem refillPointStatus.

    ``refill_point_id`` aus der ``reference.id`` (oder einem flachen ``id``).
    ``status`` aus dem ``status``-Feld (z.B. "available"/"occupied").
    ``observed_at`` aus ``lastUpdated`` falls vorhanden. Felder optional; ein
    komplett leerer Eintrag -> ``None`` (faellt aus, statt 500).
    """
    if not isinstance(entry, dict):
        return None

    refill_point_id: str | None = None
    ref = entry.get("reference")
    if isinstance(ref, dict):
        rid = ref.get("id")
        if rid is not None:
            refill_point_id = str(rid)
    if refill_point_id is None and entry.get("id") is not None:
        refill_point_id = str(entry["id"])

    status = entry.get("status")
    if isinstance(status, dict):
        # Manche V3-Serialisierungen kapseln den Wert (z.B. {"value": "..."}).
        status = status.get("value")
    status = str(status) if status is not None else None

    observed_at = entry.get("lastUpdated") or entry.get("timeStamp")
    observed_at = str(observed_at) if observed_at is not None else None

    if refill_point_id is None and status is None:
        return None

    point: dict = {"refill_point_id": refill_point_id}
    if status is not None:
        point["status"] = status
    if observed_at is not None:
        point["observed_at"] = observed_at
    return point


def parse_afir_v3(body: bytes, *, slug: str) -> dict:
    """Parst eine DATEX-II-V3-``EnergyInfrastructureStatusPublication`` (JSON, LIVE-11).

    Liest je ``refillPointStatus`` den Ladepunkt-Status (status/availability je
    Ladepunkt) und gibt ``{"slug": slug, "points": [...], "as_of": <publicationTime>}``
    zurueck. Reiner, synchroner Parse (testbar ohne Netz).

    Haertung: Size-Cap VOR ``json.loads`` (DoS, T-20-XXE). Ein nicht-JSON-Body
    -> ``ValueError`` (ehrlicher Fehlpfad). Root-Typ-Verzweigung (Pitfall 4): nur
    der V3-Publication-Typ ``EnergyInfrastructureStatusPublication`` wird
    ausgelesen; ein fremder/V2-Body liefert leere ``points`` statt eines
    Fehl-Parse.
    """
    # Size-Cap (T-20-XXE/DoS): zu grosse Bodies gar nicht erst parsen.
    if len(body) > _MAX_BYTES:
        raise ValueError(
            f"eRound-AFIR-V3-Body ueberschreitet _MAX_BYTES ({_MAX_BYTES})"
        )

    try:
        doc = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # Kein valides JSON -> ehrlicher ValueError (kein 500). Der Fetch-Wrapper
        # mappt das auf no_data; die Route behandelt no_data.
        raise ValueError("eRound-AFIR-V3-Body ist kein valides JSON") from exc

    if not isinstance(doc, dict):
        return {"slug": slug, "points": [], "as_of": None}

    # Der Payload kann direkt oder unter "payload" liegen (DATEX-II-JSON-Profil).
    payload = doc.get("payload") if isinstance(doc.get("payload"), dict) else doc

    # Root-Typ-Verzweigung (Pitfall 4): nur den V3-AFIR-Publication-Typ auslesen.
    pub_type = payload.get("type")
    if pub_type is not None and _PUBLICATION_TYPE not in str(pub_type):
        return {"slug": slug, "points": [], "as_of": None}

    points: list[dict] = []
    for status_container in _coerce_list(payload.get("energyInfrastructureStatus")):
        if not isinstance(status_container, dict):
            continue
        for rp in _coerce_list(status_container.get("refillPointStatus")):
            point = _extract_refill_point(rp)
            if point is not None:
                points.append(point)

    # Wenn der Body weder den V3-Typ noch energyInfrastructureStatus traegt
    # (fremder/V2-Body ohne explizites type), bleibt points leer (Pitfall 4).
    as_of = payload.get("publicationTime")
    return {"slug": slug, "points": points, "as_of": str(as_of) if as_of else None}


async def fetch_afir(mtls_client, *, abo_id: str, slug: str) -> dict:
    """Pullt das eRound-AFIR-V3-Abo und parst es (LIVE-11).

    Live-Pfad (untrusted): baut die Pull-URL aus der Allowlist-``abo_id`` mit der
    eRound-spezifischen Query-Variante (``build_pull_url(..., style="query")``;
    Host hartkodiert -> SSRF-Invariante), pullt ueber den mTLS-Client
    (``pull_subscription``) und parst die V3-JSON-Antwort.

    HTTP 422 (Abo aktiv, kein Datenpaket) liefert ``status="no_data"`` -> ein
    ehrliches leeres Ergebnis (kein ``raise``, T-20-422). Ein vom Size-Cap
    abgelehnter oder nicht-JSON-Body (``ValueError``) liefert ebenfalls ein
    ehrliches leeres Ergebnis (no_data), statt eine feindliche Payload zu parsen
    oder die Route mit 5xx zu treffen. 5xx/Netzfehler schlagen via
    ``pull_subscription`` durch an die resiliente Fassade (STALE-ON-ERROR).

    Rueckgabe-Keys (exakt was der Mapper erwartet): ``slug`` + ``points``, plus
    ``as_of`` (publicationTime, optional) fuer den Live-Envelope.
    """
    url = build_pull_url(abo_id, style="query")
    result = await pull_subscription(mtls_client, url)
    if result["status"] == "no_data" or result["body"] is None:
        return {"slug": slug, "points": [], "as_of": None}

    try:
        return parse_afir_v3(result["body"], slug=slug)
    except ValueError:
        # Size-Cap / kein valides JSON -> ehrliches no_data (kein Parse einer
        # feindlichen Payload; die Route behandelt no_data).
        return {"slug": slug, "points": [], "as_of": None}
