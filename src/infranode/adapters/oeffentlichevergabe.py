"""Gehaerteter OCDS-ZIP-Adapter fetch_notice_export (DATA-21, oeffentlichevergabe.de).

Zieht den DE-weiten OCDS-1.1-Bulk-Export (Open Contracting Data Standard) der
Plattform ``oeffentlichevergabe.de`` (Datenservice Öffentlicher Einkauf,
Beschaffungsamt des BMI) über den Endpunkt ``/api/notice-exports`` und parst die
im ZIP enthaltenen OCDS-Release-JSONs defensiv zu schlanken, kompakten
Bekanntmachungs-dicts (Notices). Keine Stadt-Zuordnung hier (die liegt in
``infranode.tenders.matching``); kein Cache/Breaker/Store (das liefert die
Fassade). Rein in dem Sinne, dass nur der eine HTTP-Abruf I/O macht.

Sicherheit:

- **T-21-SSRF (Spoofing):** Der Host ist hartkodiert als Modul-Konstante
  ``_HOST``; es wird KEIN Host aus einem Argument gebaut. Der Aufrufer steuert
  ausschließlich den Zeitfilter (``pubMonth``/``pubDay``), nie das Ziel.
- **T-21-DOS (Denial of Service):** Der Size-Cap ``_MAX_ZIP_BYTES`` greift VOR
  dem Öffnen des ZIP (``len(resp.content)``-Check vor ``zipfile.ZipFile``); ein
  überdimensionierter Body wird abgewiesen, kein OOM. Es wird NIE ``extractall``
  benutzt; die Entries werden selektiv und in-memory gelesen.
- **T-21-ZIPSLIP (Tampering):** Entry-Namen mit ``..`` oder absolutem Pfad werden
  beim Iterieren übersprungen. Es wird ohnehin NIE auf Platte entpackt (nur
  ``zf.read(name)`` in den Speicher), sodass kein Schreiben außerhalb möglich
  ist; der Pfad-Filter ist die zusätzliche, explizite Mitigation.
- **T-21-PARSE (Denial of Service):** Jeder Entry wird in ``try/except`` geparst
  (defektes JSON -> Entry übersprungen, kein Crash); jedes OCDS-Feld wird mit
  None-Fallback gelesen (kein ungefangener KeyError). Die OCDS-Pfade sind teils
  [ASSUMED] und werden daher rein defensiv navigiert.

``MAX_OCDS_BYTES`` ist der öffentliche Alias des Size-Caps (Vertrag des
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

# Size-Cap (T-21-DOS): großzügig (ein DE-weites Monats-ZIP liegt nach
# RESEARCH/CONTEXT deutlich darunter), aber endlich. Greift VOR dem Öffnen des
# ZIP (len(resp.content)-Check vor zipfile.ZipFile), damit kein überdimensionierter
# Body entpackt wird. Bei Bedarf an einem echten Monats-ZIP nachkalibrieren
# (CONTEXT "Backfill-Volumen messen").
_MAX_ZIP_BYTES = 512 * 1024 * 1024  # 512 MiB

# Öffentlicher Alias (RED-Test-Vertrag Plan 21-01): der Size-Cap, gegen den der
# rohe ZIP-Body VOR dem Parsen geprüft wird.
MAX_OCDS_BYTES = _MAX_ZIP_BYTES


def _text(value: object) -> str | None:
    """Gibt einen getrimmten String zurück oder None (defensiv, [ASSUMED] Felder)."""
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
    """Liest die Erfüllungsorte aus ``tender.items[]`` (defensiv) in eine Liste.

    Echte OCDS-Struktur (gegen oeffentlichevergabe.de Tages-ZIP verifiziert,
    2026-06-27, 545 Releases): je Item liegt der Erfüllungsort unter
    ``deliveryAddress`` (SINGULAR, mit ``region``=NUTS-3, ``postalCode``,
    ``locality``) und optional unter ``deliveryLocation`` (NUTS/region; in der DE-
    Stichprobe meist nur ein ``description``-Freitext, daher nur für Geo-Felder
    relevant). Das früher gelesene ``deliveryAddresses`` (Plural) existiert im
    DE-Export NICHT (0 Treffer). Beide werden als Adress-dicts gebündelt und ans
    Stadt-Matching weitergereicht (PLZ aus deliveryAddress, NUTS aus beiden).
    """
    out: list[dict] = []
    items = tender.get("items")
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        delivery = item.get("deliveryAddress")
        if isinstance(delivery, dict):
            out.append(delivery)
        location = item.get("deliveryLocation")
        if isinstance(location, dict):
            # deliveryLocation trägt im OCDS-Standard region/NUTS; im DE-Export
            # ist es meist nur Freitext (description), wird aber defensiv mit-
            # gegeben, damit ein dort gesetzter NUTS-Code (region) matcht.
            out.append(location)
    return out


def _cpv_codes(tender: dict) -> str | None:
    """Ermittelt den/die CPV-Code(s) aus ``tender.items[].classification``.

    Echte OCDS-Struktur (DE-ZIP verifiziert): der CPV-Code liegt NICHT unter
    ``tender.classification`` (existiert im DE-Export nicht, 0 Treffer), sondern
    je Item unter ``items[].classification`` (``scheme == "CPV"``) plus optional
    ``items[].additionalClassifications[]`` (ebenfalls scheme CPV). Mehrere Items
    sind möglich; die Codes werden dedupliziert und in stabiler Reihenfolge des
    ersten Auftretens als kommaseparierter String zurückgegeben (Haupt-CPV
    zuerst). Kein Treffer -> None.
    """
    items = tender.get("items")
    if not isinstance(items, list):
        return None
    codes: list[str] = []
    seen: set[str] = set()

    def _collect(classification: object) -> None:
        if not isinstance(classification, dict):
            return
        if classification.get("scheme") != "CPV":
            return
        code = _text(classification.get("id"))
        if code and code not in seen:
            seen.add(code)
            codes.append(code)

    for item in items:
        if not isinstance(item, dict):
            continue
        _collect(item.get("classification"))
        additional = item.get("additionalClassifications")
        if isinstance(additional, list):
            for entry in additional:
                _collect(entry)

    if not codes:
        return None
    return ",".join(codes)


def _award_status(release: dict) -> str | None:
    """Leitet den Status aus ``awards[].status`` ab (DE-Export hat kein tender.status).

    Echte OCDS-Struktur (DE-ZIP verifiziert): ``tender.status`` ist im DE-Export
    durchgängig leer (0 Treffer); der fachliche Status steckt in
    ``awards[].status`` (z.B. "active", "unsuccessful"). Liefert den ersten
    gesetzten Award-Status (defensiv), sonst None.
    """
    awards = release.get("awards")
    if not isinstance(awards, list):
        return None
    for award in awards:
        if isinstance(award, dict):
            status = _text(award.get("status"))
            if status:
                return status
    return None


def _tender_value(tender: dict) -> tuple[float | None, str | None]:
    """Leitet (value, currency) aus ``tender.value`` ab, sonst aus ``lots[].value``.

    Echte OCDS-Struktur (DE-ZIP verifiziert): ``tender.value`` ist meist leer
    (26 von 545); der Auftragswert steckt dann je Los in ``tender.lots[].value``
    (amount/currency). Strategie: zuerst ``tender.value``; fehlt es, werden die
    ``lots[].value.amount`` aufsummiert (gleiche Währung) und als Gesamtwert
    zurückgegeben. Kein Wert -> (None, None).
    """

    def _read_value(value_obj: object) -> tuple[float | None, str | None]:
        if not isinstance(value_obj, dict):
            return None, None
        raw_amount = value_obj.get("amount")
        amount = float(raw_amount) if isinstance(raw_amount, (int, float)) else None
        return amount, _text(value_obj.get("currency"))

    value, currency = _read_value(tender.get("value"))
    if value is not None:
        return value, currency

    lots = tender.get("lots")
    if not isinstance(lots, list):
        return None, None
    total: float | None = None
    lot_currency: str | None = None
    for lot in lots:
        if not isinstance(lot, dict):
            continue
        amount, cur = _read_value(lot.get("value"))
        if amount is None:
            continue
        total = amount if total is None else total + amount
        if lot_currency is None:
            lot_currency = cur
    return total, lot_currency


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

    Liest notice_id (``tender.id``, sonst ``ocid``), notice_version (das OCDS-
    Release-``date`` als zeitliche Recency je Notice, T-21-DEDUP/H13), status/
    notice_type, buyer-Adresse (locality/postalCode/region/countryName) +
    buyer_name, tender (title/cpv/value/currency), Erfüllungsort,
    publication_date, deadline, award_date. Jedes Feld mit None-Fallback (kein
    ungefangener KeyError, T-21-PARSE). Ohne fachliche notice_id (weder
    ``tender.id`` noch ``ocid``) -> None (unbrauchbar).
    """
    if not isinstance(release, dict):
        return None

    tender = release.get("tender") if isinstance(release.get("tender"), dict) else {}

    # notice_id: der fachliche, je Notice stabile Schlüssel ist die ``tender.id``
    # (eine UUID, im DE-Export identisch mit dem ocid-Suffix); die ``ocid`` (mit
    # Plattform-Präfix) ist der Fallback. Mehrere Releases (Versionen) derselben
    # Notice teilen sich dieselbe notice_id und werden über notice_version
    # (Release-date) dedupliziert (jüngstes date gewinnt).
    notice_id = _text(tender.get("id")) or _text(release.get("ocid"))
    if not notice_id:
        return None

    # notice_version (H13): release.id/tender.id/ocid sind UUIDs - eine numerische
    # Versionsableitung daraus ist unmöglich (rsplit("-v") liefert die UUID,
    # CAST AS INTEGER = 0 -> Dedup-Vergleich "0>0" nie wahr). Die echte Recency
    # je Notice ist das OCDS-Release-``date`` (ISO-8601-Timestamp); es wird hier
    # als notice_version geführt und im Store lexikografisch/zeitlich verglichen
    # (ISO-Strings sind sortierbar). Fehlt das date, fällt es defensiv auf die
    # release.id zurück (eindeutig, vergleichbar).
    notice_version = _text(release.get("date")) or _text(release.get("id")) or notice_id

    tags = release.get("tag")
    notice_type = None
    if isinstance(tags, list) and tags:
        notice_type = _text(tags[0])
    elif isinstance(tags, str):
        notice_type = _text(tags)

    # status (H/Status): tender.status fehlt im DE-Export -> aus awards[].status.
    status = _text(tender.get("status")) or _award_status(release)
    title = _text(tender.get("title"))

    # cpv (K10): aus items[].classification (scheme==CPV), NICHT tender.classification.
    cpv = _cpv_codes(tender)

    # value (Status/Value): tender.value ist meist leer -> aus lots[].value aggregiert.
    value, currency = _tender_value(tender)

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

    Reine Funktion (kein I/O). Iteriert defensiv über ``releases``; je Release
    liefert ``_parse_release`` ein schlankes Notice-dict oder None (unbrauchbar ->
    übersprungen). Ein nicht-dict / fehlendes ``releases`` -> leere Liste, kein
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

    Verwirft Einträge mit ``..``-Segment oder absolutem Pfad (POSIX ``/`` bzw.
    Windows-Laufwerk/Backslash). Es wird ohnehin nie auf Platte entpackt; dies ist
    die explizite, zusätzliche Mitigation.
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
    """Liest einen OCDS-Bulk-ZIP-Body gehärtet zu Notice-dicts (kein extractall).

    Voraussetzung: ``len(content)`` wurde bereits gegen ``_MAX_ZIP_BYTES`` geprüft
    (Aufrufer-Vertrag). Iteriert ``namelist()`` (selektives in-memory ``zf.read``),
    überspringt unsichere Pfade (T-21-ZIPSLIP) und nicht-``.json``-Entries; je
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
                # Defektes/nicht parsbares Entry übersprungen (T-21-PARSE).
                continue
            notices.extend(parse_ocds_release(obj))
    return notices


async def fetch_notice_export(
    http: httpx.AsyncClient,
    *,
    pubMonth: str | None = None,
    pubDay: str | None = None,
) -> list[dict]:
    """Zieht den OCDS-Bulk-Export gehärtet und gibt geparste Notice-dicts zurück.

    ``pubMonth`` (YYYY-MM) und ``pubDay`` (YYYY-MM-DD) sind GEGENSEITIG EXKLUSIV:
    genau einer muss gesetzt sein, sonst ``ValueError`` (Vertrag). Baut die Query
    ``format=ocds.zip`` + den gesetzten Zeitfilter gegen den HARTKODIERTEN Host
    ``_HOST`` (T-21-SSRF), ruft GET, ``raise_for_status()`` (STALE-ON-ERROR).

    Vor dem Entpacken wird ``len(resp.content)`` gegen ``_MAX_ZIP_BYTES`` geprüft
    (T-21-DOS); ein zu großer Body -> leere Liste (kein OOM, kein ZipFile-Open).
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
    # Size-Cap VOR dem Entpacken (T-21-DOS): kein ZipFile-Open bei zu großem Body.
    if len(content) > _MAX_ZIP_BYTES:
        return []

    return _parse_zip(content)
