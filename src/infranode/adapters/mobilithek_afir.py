"""Keyloser eRound-AFIR-DATEX-II-V3-Adapter (LIVE-11, Phase 20).

Die einzige DATEX-II-**V3**-Quelle der Phase: das eRound-AFIR-Recharging-Abo
(EnergyInfrastructureStatusPublication, Ladesäulen-Belegung in Echtzeit,
schließt die zweite Hälfte der DATA-09-Lücke). Getrennt vom V2-Pfad gehalten
(``adapters/mobilithek_datex2.py``), damit die 8 V2-Quellen nicht blockiert
werden (RESEARCH Pitfall 4: der V2-Parser greift bei einem V3-Body NICHT).

REALITÄT (Mobilithek-Portal verifiziert 2026-06-12): das eRound-Angebot liefert
DATEX II V3 als **JSON** (Datenmodell "DATEX II V3", Syntax "JSON"), NICHT als
XML. Daher parst dieser Adapter stdlib-``json`` (kein lxml, kein ElementTree).
Das weicht vom ursprünglichen Plan-Wortlaut (XML, iterparse) ab; die
JSON-Realität ist im SUMMARY als Deviation dokumentiert.

Härtung (JSON-Variante):
- **Kein XXE-Vektor**: stdlib ``json`` expandiert keine externen Entities; der
  DOCTYPE/ENTITY-Pre-Parse-Guard des V2-Adapters entfällt ersatzlos (es gibt
  keinen XML-Parser, der angegriffen werden könnte).
- **Size-Cap** ``_MAX_BYTES`` (T-20-XXE/DoS): ein zu großer Body -> ``ValueError``
  VOR ``json.loads`` (DoS-Schutz bleibt, identisch zum V2-Adapter).
- **Root-Typ-Verzweigung** (Pitfall 4): der Publication-Typ wird VOR dem Auslesen
  geprüft; ein fremder/V2-Body liefert leere ``points`` statt eines Fehl-Parse.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper), kennt KEIN Cache/Breaker (das liefert
die Fassade) und schreibt KEIN Archiv. Der ``fetch_afir``-Wrapper ruft den
Mobilithek-mTLS-Client (``pull_subscription``) mit der eRound-spezifischen
Query-URL-Variante (``build_pull_url(..., style="query")``), mappt HTTP 422 auf
``no_data`` und gibt ein ehrliches leeres Ergebnis zurück, wenn der Size-Cap
greift oder der Body kein valides V3-JSON ist.
"""

from __future__ import annotations

import json

from infranode.infra.mobilithek import build_pull_url, pull_subscription

# Size-Cap (T-20-XXE / DoS): konservativ über dem erwarteten AFIR-Feed. Ein
# größerer Body wird gar nicht erst geparst. Identisch zum V2-Adapter.
_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB

# DATEX-II-V3 AFIR-Recharging-Profil (real verifiziert 2026-07-03 nach dem
# Feed-Update des Anbieters). Die Belegung liegt unter
# messageContainer.payload[].aegiEnergyInfrastructureStatusPublication ->
# energyInfrastructureSiteStatus[] -> energyInfrastructureStationStatus[] ->
# refillPointStatus[] -> aegiElectricChargingPointStatus. Fehlt der
# Publication-Key (fremder/V2-Body), bleiben die points ehrlich leer statt eines
# Fehl-Parse (Pitfall 4).
_PUBLICATION_KEY = "aegiEnergyInfrastructureStatusPublication"
_CHARGING_POINT_KEY = "aegiElectricChargingPointStatus"


def _coerce_list(value) -> list:
    """Normalisiert ein DATEX-II-Feld zu einer Liste (dict-Wert ODER Liste).

    DATEX-II-JSON trägt wiederholbare Elemente je nach Serialisierung mal als
    einzelnes Objekt, mal als Array. Diese Helfer macht beides zu einer Liste
    (None -> leere Liste), damit der Parser robust über beide Formen iteriert.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _extract_refill_point(entry: dict) -> dict | None:
    """Liest refill_point_id + status (+ observed_at) aus einem refillPointStatus.

    Der eigentliche Ladepunkt-Status liegt in einem typspezifischen Wrapper
    (real: ``aegiElectricChargingPointStatus``); für Robustheit gegen Profil-/
    Präfix-Varianten wird sonst das erste verschachtelte dict mit ``status``/
    ``reference`` genommen. ``refill_point_id`` aus ``reference.idG`` (oder
    ``id``), ``status`` aus ``status.value`` (z.B. "available"/"occupied", oder
    flach), ``observed_at`` aus dem ersten ``energyRateUpdate[].lastUpdated``
    (oder flachem ``lastUpdated``). Ein komplett leerer Eintrag -> ``None``
    (fällt aus, statt 500).
    """
    if not isinstance(entry, dict):
        return None

    cps = entry.get(_CHARGING_POINT_KEY)
    if not isinstance(cps, dict):
        cps = next(
            (
                v
                for v in entry.values()
                if isinstance(v, dict) and ("status" in v or "reference" in v)
            ),
            entry,
        )

    refill_point_id: str | None = None
    ref = cps.get("reference")
    if isinstance(ref, dict):
        rid = ref.get("idG") or ref.get("id")
        if rid is not None:
            refill_point_id = str(rid)
    if refill_point_id is None and cps.get("id") is not None:
        refill_point_id = str(cps["id"])

    status = cps.get("status")
    if isinstance(status, dict):
        # V3 kapselt den Wert als {"value": "available"}.
        status = status.get("value")
    status = str(status) if status is not None else None

    observed_at: str | None = None
    for rate in _coerce_list(cps.get("energyRateUpdate")):
        if isinstance(rate, dict) and rate.get("lastUpdated"):
            observed_at = str(rate["lastUpdated"])
            break
    if observed_at is None:
        flat = cps.get("lastUpdated") or cps.get("timeStamp")
        observed_at = str(flat) if flat is not None else None

    if refill_point_id is None and status is None:
        return None

    point: dict = {"refill_point_id": refill_point_id}
    if status is not None:
        point["status"] = status
    if observed_at is not None:
        point["observed_at"] = observed_at
    return point


def parse_afir_v3(body: bytes, *, slug: str) -> dict:
    """Parst eine DATEX-II-V3 AFIR-``EnergyInfrastructureStatusPublication`` (JSON).

    Navigiert ``messageContainer.payload[].aegiEnergyInfrastructureStatusPublication``
    -> ``energyInfrastructureSiteStatus[]`` -> ``energyInfrastructureStationStatus[]``
    -> ``refillPointStatus[]`` und liest je Ladepunkt Status + observed_at. Gibt
    ``{"slug": slug, "points": [...], "as_of": <publicationTime>}`` zurück. Reiner,
    synchroner Parse (testbar ohne Netz).

    Haertung: Size-Cap VOR ``json.loads`` (DoS, T-20-XXE). Ein nicht-JSON-Body
    -> ``ValueError`` (ehrlicher Fehlpfad). Fehlt der Publication-Key
    ``aegiEnergyInfrastructureStatusPublication`` (fremder/V2-Body), bleiben die
    ``points`` leer statt eines Fehl-Parse (Pitfall 4).
    """
    # Size-Cap (T-20-XXE/DoS): zu große Bodies gar nicht erst parsen.
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

    # Container: real unter "messageContainer", sonst doc selbst (Profil-Varianz).
    container = doc.get("messageContainer")
    if not isinstance(container, dict):
        container = doc

    points: list[dict] = []
    as_of: str | None = None
    # payload[] -> aegiEnergyInfrastructureStatusPublication -> siteStatus[] ->
    # stationStatus[] -> refillPointStatus[] (jede Ebene dict ODER Liste).
    for payload in _coerce_list(container.get("payload")):
        if not isinstance(payload, dict):
            continue
        pub = payload.get(_PUBLICATION_KEY)
        if not isinstance(pub, dict):
            continue
        if as_of is None and pub.get("publicationTime"):
            as_of = str(pub["publicationTime"])
        for site in _coerce_list(pub.get("energyInfrastructureSiteStatus")):
            if not isinstance(site, dict):
                continue
            for station in _coerce_list(site.get("energyInfrastructureStationStatus")):
                if not isinstance(station, dict):
                    continue
                for rp in _coerce_list(station.get("refillPointStatus")):
                    point = _extract_refill_point(rp)
                    if point is not None:
                        points.append(point)

    return {"slug": slug, "points": points, "as_of": as_of}


async def fetch_afir(mtls_client, *, abo_id: str, slug: str) -> dict:
    """Pullt das eRound-AFIR-V3-Abo und parst es (LIVE-11).

    Live-Pfad (untrusted): baut die Pull-URL aus der Allowlist-``abo_id`` mit der
    eRound-spezifischen Query-Variante (``build_pull_url(..., style="query")``;
    Host hartkodiert -> SSRF-Invariante), pullt über den mTLS-Client
    (``pull_subscription``) und parst die V3-JSON-Antwort.

    HTTP 422 (Abo aktiv, kein Datenpaket) liefert ``status="no_data"`` -> ein
    ehrliches leeres Ergebnis (kein ``raise``, T-20-422). Ein vom Size-Cap
    abgelehnter oder nicht-JSON-Body (``ValueError``) liefert ebenfalls ein
    ehrliches leeres Ergebnis (no_data), statt eine feindliche Payload zu parsen
    oder die Route mit 5xx zu treffen. 5xx/Netzfehler schlagen via
    ``pull_subscription`` durch an die resiliente Fassade (STALE-ON-ERROR).

    Rückgabe-Keys (exakt was der Mapper erwartet): ``slug`` + ``points``, plus
    ``as_of`` (publicationTime, optional) für den Live-Envelope.
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
