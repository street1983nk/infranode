"""Gehaerteter OCDS-ZIP-Adapter fetch_notice_export (DATA-21, oeffentlichevergabe.de).

Zieht den DE-weiten OCDS-1.1-Bulk-Export (Open Contracting Data Standard) der
Plattform ``oeffentlichevergabe.de`` (Datenservice Oeffentlicher Einkauf,
Beschaffungsamt des BMI) ueber den Endpunkt ``/api/notice-exports`` und parst die
im ZIP enthaltenen OCDS-Release-JSONs defensiv zu schlanken, kompakten
Bekanntmachungs-dicts (Notices). Keine Stadt-Zuordnung hier (die liegt in
``infranode.tenders.matching``); kein Cache/Breaker/Store (das liefert die
Fassade). Rein in dem Sinne, dass nur der eine HTTP-Abruf I/O macht.

Sicherheit:

- **T-21-SSRF (Spoofing):** Der Host ist hartkodiert als Modul-Konstante
  ``_HOST``; es wird KEIN Host aus einem Argument gebaut. Der Aufrufer steuert
  ausschliesslich den Zeitfilter (``pubMonth``/``pubDay``), nie das Ziel.
- **T-21-DOS (Denial of Service):** Der Size-Cap ``_MAX_ZIP_BYTES`` greift VOR
  dem Oeffnen des ZIP (``len(resp.content)``-Check vor ``zipfile.ZipFile``); ein
  ueberdimensionierter Body wird abgewiesen, kein OOM. Es wird NIE ``extractall``
  benutzt; die Entries werden selektiv und in-memory gelesen.
- **T-21-ZIPSLIP (Tampering):** Entry-Namen mit ``..`` oder absolutem Pfad werden
  beim Iterieren uebersprungen. Es wird ohnehin NIE auf Platte entpackt (nur
  ``zf.read(name)`` in den Speicher), sodass kein Schreiben ausserhalb moeglich
  ist; der Pfad-Filter ist die zusaetzliche, explizite Mitigation.
- **T-21-PARSE (Denial of Service):** Jeder Entry wird in ``try/except`` geparst
  (defektes JSON -> Entry uebersprungen, kein Crash); jedes OCDS-Feld wird mit
  None-Fallback gelesen (kein ungefangener KeyError). Die OCDS-Pfade sind teils
  [ASSUMED] und werden daher rein defensiv navigiert.

``MAX_OCDS_BYTES`` ist der oeffentliche Alias des Size-Caps (Vertrag des
RED-Tests aus Plan 21-01).
"""

from __future__ import annotations

import io
import json
import zipfile

import httpx

# Hartkodierter Host (T-21-SSRF): KEIN Host aus Argument. Der Aufrufer steuert nur
# den Zeitfilter, nie das Ziel.
_HOST = "https://oeffentlichevergabe.de"
_PATH = "/api/notice-exports"

# Size-Cap (T-21-DOS): grosszuegig (ein DE-weites Monats-ZIP liegt nach
# RESEARCH/CONTEXT deutlich darunter), aber endlich. Greift VOR dem Oeffnen des
# ZIP (len(resp.content)-Check vor zipfile.ZipFile), damit kein ueberdimensionierter
# Body entpackt wird. Bei Bedarf an einem echten Monats-ZIP nachkalibrieren
# (CONTEXT "Backfill-Volumen messen").
_MAX_ZIP_BYTES = 512 * 1024 * 1024  # 512 MiB

# Oeffentlicher Alias (RED-Test-Vertrag Plan 21-01): der Size-Cap, gegen den der
# rohe ZIP-Body VOR dem Parsen geprueft wird.
MAX_OCDS_BYTES = _MAX_ZIP_BYTES


def _text(value: object) -> str | None:
    """Gibt einen getrimmten String zurueck oder None (defensiv, [ASSUMED] Felder)."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _first_address(release: dict) -> dict | None:
    """Liefert die Adresse der ersten ``buyer``-Partei (OCDS-Rolle) oder None."""
    parties = release.get("parties")
    if not isinstance(parties, list):
        return None
    for party in parties:
        if not isinstance(party, dict):
            continue
        roles = party.get("roles") or []
        if "buyer" in roles:
            address = party.get("address")
            if isinstance(address, dict):
                return address
    return None


def _buyer_name(release: dict) -> str | None:
    """Liefert den Namen der ersten ``buyer``-Partei (oder None)."""
    parties = release.get("parties")
    if not isinstance(parties, list):
        return None
    for party in parties:
        if not isinstance(party, dict):
            continue
        roles = party.get("roles") or []
        if "buyer" in roles:
            return _text(party.get("name"))
    return None


def _delivery_addresses(tender: dict) -> list[dict]:
    """Liest alle ``tender.items[].deliveryAddresses`` (defensiv) in eine Liste."""
    out: list[dict] = []
    items = tender.get("items")
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        delivery = item.get("deliveryAddresses")
        if not isinstance(delivery, list):
            continue
        out.extend(addr for addr in delivery if isinstance(addr, dict))
    return out


def _award_date(release: dict) -> str | None:
    """Liefert das Datum des ersten Awards (oder None), defensiv."""
    awards = release.get("awards")
    if not isinstance(awards, list):
        return None
    for award in awards:
        if isinstance(award, dict):
            date = _text(award.get("date"))
            if date:
                return date
    return None


def _parse_release(release: dict) -> dict | None:
    """Bildet ein einzelnes OCDS-Release defensiv auf ein schlankes Notice-dict ab.

    Liest notice_id (``tender.id``, sonst ``ocid``), notice_version (numerischer
    Suffix aus ``id``, sonst ``id``), status/notice_type, buyer-Adresse (locality/
    postalCode/region/countryName) + buyer_name, tender (title/cpv/value/currency),
    Erfuellungsort, publication_date, deadline, award_date. Jedes Feld mit
    None-Fallback (kein ungefangener KeyError, T-21-PARSE). Ohne fachliche
    notice_id (weder ``tender.id`` noch ``ocid``) -> None (unbrauchbar).
    """
    if not isinstance(release, dict):
        return None

    tender = release.get("tender") if isinstance(release.get("tender"), dict) else {}

    # notice_id: der fachliche, stabile Schluessel ist die ``tender.id``
    # (z.B. "DE-2026-AWARD-0001"); die ``ocid`` (mit Plattform-Praefix) ist der
    # Fallback. Mehrere Releases derselben Notice teilen sich dieselbe notice_id.
    notice_id = _text(tender.get("id")) or _text(release.get("ocid"))
    if not notice_id:
        return None

    # notice_version: numerischer Suffix aus der Release-id ("...-v2" -> "2"),
    # sonst die volle id, sonst "1" (defensiv).
    release_id = _text(release.get("id"))
    notice_version = "1"
    if release_id:
        suffix = release_id.rsplit("-v", 1)
        if len(suffix) == 2 and suffix[1].isdigit():
            notice_version = suffix[1]
        else:
            notice_version = release_id

    tags = release.get("tag")
    notice_type = None
    if isinstance(tags, list) and tags:
        notice_type = _text(tags[0])
    elif isinstance(tags, str):
        notice_type = _text(tags)

    status = _text(tender.get("status"))
    title = _text(tender.get("title"))

    classification = tender.get("classification")
    cpv = None
    if isinstance(classification, dict):
        cpv = _text(classification.get("id"))

    value_obj = tender.get("value")
    value = None
    currency = None
    if isinstance(value_obj, dict):
        raw_amount = value_obj.get("amount")
        if isinstance(raw_amount, (int, float)):
            value = float(raw_amount)
        currency = _text(value_obj.get("currency"))

    deadline = None
    tender_period = tender.get("tenderPeriod")
    if isinstance(tender_period, dict):
        deadline = _text(tender_period.get("endDate"))

    buyer_address = _first_address(release) or {}
    delivery = _delivery_addresses(tender)

    return {
        "notice_id": notice_id,
        "notice_version": notice_version,
        "notice_type": notice_type,
        "status": status,
        "title": title,
        "buyer_name": _buyer_name(release),
        "buyer_locality": _text(buyer_address.get("locality")),
        "buyer_postal_code": _text(buyer_address.get("postalCode")),
        "buyer_region": _text(buyer_address.get("region")),
        "buyer_country": _text(buyer_address.get("countryName")),
        "cpv": cpv,
        "value": value,
        "currency": currency,
        "publication_date": _text(release.get("date")),
        "deadline": deadline,
        "award_date": _award_date(release),
        "buyer_address": buyer_address or None,
        "delivery_addresses": delivery,
    }


def parse_ocds_release(obj: dict) -> list[dict]:
    """Parst ein OCDS-Release-Paket (mit ``releases[]``) zu Notice-dicts.

    Reine Funktion (kein I/O). Iteriert defensiv ueber ``releases``; je Release
    liefert ``_parse_release`` ein schlankes Notice-dict oder None (unbrauchbar ->
    uebersprungen). Ein nicht-dict / fehlendes ``releases`` -> leere Liste, kein
    Crash (T-21-PARSE). Mehrfachversionen (gleiche ``ocid``, mehrere Releases)
    werden BEIDE als eigene Notice-dicts geliefert; die Dedup-/juengste-Version-
    Logik liegt im Store (Plan 21-04).
    """
    if not isinstance(obj, dict):
        return []
    releases = obj.get("releases")
    if not isinstance(releases, list):
        return []

    notices: list[dict] = []
    for release in releases:
        parsed = _parse_release(release)
        if parsed is not None:
            notices.append(parsed)
    return notices


def _is_safe_entry(name: str) -> bool:
    """Prueft einen ZIP-Entry-Namen gegen Zip-Slip (T-21-ZIPSLIP).

    Verwirft Eintraege mit ``..``-Segment oder absolutem Pfad (POSIX ``/`` bzw.
    Windows-Laufwerk/Backslash). Es wird ohnehin nie auf Platte entpackt; dies ist
    die explizite, zusaetzliche Mitigation.
    """
    if not name or name.endswith("/"):
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    if len(normalized) >= 2 and normalized[1] == ":":  # Windows-Laufwerk (C:/...)
        return False
    parts = normalized.split("/")
    return ".." not in parts


def _parse_zip(content: bytes) -> list[dict]:
    """Liest einen OCDS-Bulk-ZIP-Body gehaertet zu Notice-dicts (kein extractall).

    Voraussetzung: ``len(content)`` wurde bereits gegen ``_MAX_ZIP_BYTES`` geprueft
    (Aufrufer-Vertrag). Iteriert ``namelist()`` (selektives in-memory ``zf.read``),
    ueberspringt unsichere Pfade (T-21-ZIPSLIP) und nicht-``.json``-Entries; je
    JSON-Entry wird der Inhalt in ``try/except`` geparst (defekt -> skip,
    T-21-PARSE). Ein nicht-ZIP-Body (kein PK-Header) -> leere Liste.
    """
    if not content or not content.startswith(b"PK"):
        return []

    notices: list[dict] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return []
    with zf:
        for name in zf.namelist():
            if not _is_safe_entry(name):
                continue
            if not name.lower().endswith(".json"):
                continue
            try:
                raw = zf.read(name)
                obj = json.loads(raw)
            except (KeyError, ValueError, zipfile.BadZipFile):
                # Defektes/nicht parsbares Entry uebersprungen (T-21-PARSE).
                continue
            notices.extend(parse_ocds_release(obj))
    return notices


async def fetch_notice_export(
    http: httpx.AsyncClient,
    *,
    pubMonth: str | None = None,
    pubDay: str | None = None,
) -> list[dict]:
    """Zieht den OCDS-Bulk-Export gehaertet und gibt geparste Notice-dicts zurueck.

    ``pubMonth`` (YYYY-MM) und ``pubDay`` (YYYY-MM-DD) sind GEGENSEITIG EXKLUSIV:
    genau einer muss gesetzt sein, sonst ``ValueError`` (Vertrag). Baut die Query
    ``format=ocds.zip`` + den gesetzten Zeitfilter gegen den HARTKODIERTEN Host
    ``_HOST`` (T-21-SSRF), ruft GET, ``raise_for_status()`` (STALE-ON-ERROR).

    Vor dem Entpacken wird ``len(resp.content)`` gegen ``_MAX_ZIP_BYTES`` geprueft
    (T-21-DOS); ein zu grosser Body -> leere Liste (kein OOM, kein ZipFile-Open).
    Das Entpacken (``_parse_zip``) ist selektiv/in-memory, NIE ``extractall``
    (T-21-ZIPSLIP), und defensiv je Entry (T-21-PARSE).
    """
    if (pubMonth is None) == (pubDay is None):
        raise ValueError(
            "Genau eines von pubMonth (YYYY-MM) oder pubDay (YYYY-MM-DD) "
            "muss gesetzt sein (gegenseitig exklusiv)."
        )

    params: dict[str, str] = {"format": "ocds.zip"}
    if pubMonth is not None:
        params["pubMonth"] = pubMonth
    elif pubDay is not None:  # mutual exclusivity oben sichergestellt
        params["pubDay"] = pubDay

    resp = await http.get(f"{_HOST}{_PATH}", params=params)
    resp.raise_for_status()

    content = resp.content
    # Size-Cap VOR dem Entpacken (T-21-DOS): kein ZipFile-Open bei zu grossem Body.
    if len(content) > _MAX_ZIP_BYTES:
        return []

    return _parse_zip(content)
