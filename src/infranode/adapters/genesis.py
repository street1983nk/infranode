"""Account-gated GENESIS-Live-POST-Adapter fetch_demographics (DATA-17, Tier A).

Lädt Demografie-Stammwerte (Bevölkerungsstand je Gemeinde) von der
Regionalstatistik-GENESIS-API über den gepoolten httpx-Client. Der Dienst ist
account-gated: Nutzername/Passwort kommen als ``SecretStr``-Parameter aus den
Settings rein (NIE im Modul hartkodiert) und gelangen ausschließlich in die
HTTP-Header (``username``/``password``), NIE in das zurückgegebene raw-dict
(T-08-CRED, Negativtest). Seit dem GENESIS-Update (Header-Auth-Pflicht, sonst
Code 15 "nicht berechtigt") gehören die Credentials NICHT mehr in den Body
(identisch zu ``fetch_genesis_table`` und dem regionalstatistik-Ingest).

Sicherheit (T-08-SSRF, Tampering): Der Default-Host ist in ``_BASE`` hartkodiert.
Der ``base_url``-Parameter (Wiederverwendungs-Vertrag für Plan 08-07 GENESIS
23111 auf www-genesis.destatis.de und den Zensus-2022-Host) MUSS in der
hartkodierten Allowlist ``_ALLOWED_HOSTS`` liegen, sonst ``ValueError`` (kein
roher User-Input als Ziel-URL). Die ``regionalschluessel`` (AGS) stammt
ausschließlich aus dem Register (``entry.ags``), nie aus User-Input.

POST-only (T-08-GET, Tampering): Der GENESIS-GET-Endpunkt ist seit dem
27.11.2025 abgeschaltet (RESEARCH Pitfall 1); der Adapter nutzt AUSSCHLIESSLICH
``http.post``. ``resp.raise_for_status()`` ist Pflicht, damit ein 5xx als
``httpx.HTTPError`` an die Fassade durchschlägt und der STALE-ON-ERROR-Pfad
greift.

Datenfehler-Schutz ([ASSUMED] Felder, T-08-CRED): Die GENESIS-POST-Body-
Feldnamen und der Tabellen-Code sind [ASSUMED]-Konstanten; der Live-Abgleich ist
Manual-Only nach Deploy (Owner, Plan 08-01 Task 3). Die Antwort wird daher
defensiv per ``.get()``/``[]``-Fallback gelesen; fehlende/unbekannte Felder
führen NICHT zu einem Crash, sondern zu ``None``.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade).
"""

from __future__ import annotations

import httpx
from pydantic import SecretStr

# Default-Host hartkodiert (T-08-SSRF): die Regionalstatistik-GENESIS-Instanz.
_BASE = "https://www.regionalstatistik.de/genesisws/rest/2020"

# Hartkodierte Allowlist aller erlaubten GENESIS-Instanzen (RESEARCH Pitfall 2,
# T-08-SSRF). Der base_url-Parameter MUSS einer dieser Werte sein; alles andere
# löst einen ValueError aus (kein roher User-Input als Ziel-URL). Diese Liste
# ist der Wiederverwendungs-Vertrag für Plan 08-07 (GENESIS 23111 Krankenhaus
# auf www-genesis.destatis.de) und Zensus-2022 (eigener Host).
_ALLOWED_HOSTS = {
    "https://www.regionalstatistik.de/genesisws/rest/2020",
    "https://www-genesis.destatis.de/genesisws/rest/2020",
    "https://ergebnisse.zensus2022.de/api/rest/2020",
}

# Kuratierter Default-Tabellen-Code (Bevölkerungsstand je Gemeinde). [ASSUMED]-
# Konstante: der echte GENESIS-Tabellen-Code wird Manual-Only nach Deploy
# verifiziert (Owner, Plan 08-01 Task 3). None-Fallback in der Antwort.
_DEMOGRAPHICS_TABLE = "12411-01-01-4"  # [ASSUMED], Live-Abgleich Manual-Only.


def _to_int(value: object) -> int | None:
    """Konvertiert einen rohen GENESIS-Wert defensiv nach int oder None."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


async def fetch_demographics(
    http: httpx.AsyncClient,
    *,
    slug: str,
    ags: str,
    username: str,
    password: SecretStr,
    table: str = _DEMOGRAPHICS_TABLE,
    base_url: str = _BASE,
) -> dict:
    """Holt GENESIS-Demografie-Stammwerte je Gemeinde als raw-dict (POST-only).

    Postet AUSSCHLIESSLICH an ``f"{base_url}/data/table"`` (kein GET, T-08-GET).
    Der ``base_url`` MUSS in ``_ALLOWED_HOSTS`` liegen, sonst ``ValueError``
    (SSRF-Guard T-08-SSRF, Wiederverwendungs-Vertrag für Plan 08-07/Zensus).
    Die Credentials gehen NUR in die HTTP-Header (``username`` /
    ``password.get_secret_value()``; Header-Auth-Pflicht seit dem GENESIS-Update,
    sonst Code 15) und erscheinen NIE im Rückgabe-dict (T-08-CRED, Negativtest
    ``str(raw)``).

    Die Antwort-Felder sind [ASSUMED] (Live-Abgleich Manual-Only); der Adapter
    liest defensiv ``.get()``/``[]`` aus der GENESIS-JSON-Struktur
    (``Object.Data``) und fällt je Feld auf ``None`` zurück. Rückgabe-Keys
    (exakt das, was ``map_demographics`` erwartet): ``slug``, ``ags`` plus die
    defensiv geparsten Felder ``population``/``households``/``buildings``/
    ``rent_avg``/``reference_year``. Ein 5xx schlägt via
    ``resp.raise_for_status()`` als ``httpx.HTTPError`` durch (STALE-ON-ERROR).
    """
    # SSRF-Guard (T-08-SSRF): nur hartkodierte GENESIS-Instanzen sind erlaubt.
    if base_url not in _ALLOWED_HOSTS:
        raise ValueError(f"base_url nicht in der GENESIS-Allowlist: {base_url!r}")

    # Credentials NUR in den HTTP-Headern (Header-Auth-Pflicht seit GENESIS-Update,
    # sonst Code 15 "nicht berechtigt"; identisch zu fetch_genesis_table/Ingest).
    # Body-Feldnamen sind [ASSUMED]-Konstanten (Live-Abgleich Manual-Only).
    #
    # K1-Fix (Audit 2026-06-29): format=json (NICHT ffcsv). Diese Funktion liest die
    # Antwort als JSON-Wrapper mit den Stammwerten unter Object.Data (BEVSTD/
    # HAUSHALTE/GEBAEUDE); ffcsv liefert dagegen ein ZIP/CSV, das hier NICHT geparst
    # wird (-> demographics blieb still null). Der GENESIS-Endpunkt liefert bei
    # format=json genau die unten erwartete Object.Data-Struktur. [ASSUMED] bleibt
    # nur der Tabellen-Code + die Feld-Keys (Live-Abgleich Manual-Only, kein Account).
    resp = await http.post(
        f"{base_url}/data/table",
        headers={"username": username, "password": password.get_secret_value()},
        data={
            "name": table,
            "area": "all",
            "regionalschluessel": ags,
            "format": "json",
            "language": "de",
        },
    )
    resp.raise_for_status()

    # Antwort defensiv lesen ([ASSUMED] Struktur, None-Fallback). Die GENESIS-
    # JSON trägt die Datensätze unter Object.Data; der erste Eintrag hält die
    # Gemeinde-Stammwerte. Jeder Zugriff ist .get()/[]-defensiv (kein Crash).
    body = resp.json()
    obj = body.get("Object") if isinstance(body, dict) else None
    data = obj.get("Data") if isinstance(obj, dict) else None
    row: dict = data[0] if isinstance(data, list) and data else {}
    if not isinstance(row, dict):
        row = {}

    return {
        "slug": slug,
        "ags": ags,
        "population": _to_int(row.get("BEVSTD")),
        "households": _to_int(row.get("HAUSHALTE")),
        "buildings": _to_int(row.get("GEBAEUDE")),
        "rent_avg": None,  # [ASSUMED]: kein Mietwert in dieser Tabelle.
        "reference_year": _to_int(row.get("jahr")),
    }


# Kuratierter Krankenhaus-Tabellen-Code (Grunddaten der Krankenhäuser, EVAS 23111).
# [ASSUMED]-Konstante (Live-Abgleich Manual-Only nach Deploy, Owner). None-Fallback.
_HOSPITAL_TABLE = "23111-01-01-4"  # [ASSUMED], Live-Abgleich Manual-Only.


async def fetch_hospitals(
    http: httpx.AsyncClient,
    *,
    slug: str,
    ags: str,
    username: str,
    password: SecretStr,
    table: str = _HOSPITAL_TABLE,
    base_url: str = _BASE,
) -> dict:
    """Holt GENESIS-Krankenhaus-Grunddaten je Gemeinde als raw-dict (POST-only).

    K2-Fix (Audit 2026-06-29): EIGENE Funktion für das Krankenhaus-Schema (EVAS
    23111), getrennt von ``fetch_demographics``. Bisher missbrauchte die
    health-Route ``fetch_demographics(table=_HOSPITAL_TABLE)``, das aber fest auf
    das DEMOGRAFIE-Schema (BEVSTD/HAUSHALTE/GEBAEUDE) verdrahtet ist und nur
    ``population``/``households``/... zurückgibt; ``map_hospital`` liest jedoch
    ``count``/``hospitals``/``reference_date`` -> die kamen NIE -> ``count=0``,
    ``hospitals=[]`` selbst bei perfektem GENESIS.

    Postet AUSSCHLIESSLICH an ``f"{base_url}/data/table"`` (kein GET, T-08-GET) mit
    ``format=json`` (wie ``fetch_demographics``: die Antwort trägt die Datensätze
    unter ``Object.Data``). Der ``base_url`` MUSS in ``_ALLOWED_HOSTS`` liegen
    (SSRF-Guard T-08-SSRF). Credentials gehen NUR in die HTTP-Header (Header-Auth-
    Pflicht seit GENESIS-Update, sonst Code 15) und erscheinen NIE im Rückgabe-dict
    (T-08-CRED). Ein 5xx schlägt via ``resp.raise_for_status()`` als
    ``httpx.HTTPError`` durch (STALE-ON-ERROR).

    Rückgabe-Keys (exakt das, was ``map_hospital`` erwartet): ``slug``, ``ags``,
    ``count`` (Anzahl Krankenhäuser, defensiv 0 bei fehlendem Wert), ``hospitals``
    (Liste je Fachabteilung mit ``name``/``betten``), ``reference_date`` (Stichtag/
    Stichjahr). Schema-Feld-Keys sind [ASSUMED] (Live-Abgleich Manual-Only); jeder
    Zugriff ist ``.get()``-defensiv (kein Crash, None/0-Fallback).
    """
    # SSRF-Guard (T-08-SSRF): nur hartkodierte GENESIS-Instanzen sind erlaubt.
    if base_url not in _ALLOWED_HOSTS:
        raise ValueError(f"base_url nicht in der GENESIS-Allowlist: {base_url!r}")

    resp = await http.post(
        f"{base_url}/data/table",
        headers={"username": username, "password": password.get_secret_value()},
        data={
            "name": table,
            "area": "all",
            "regionalschluessel": ags,
            "format": "json",
            "language": "de",
        },
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
    )
    resp.raise_for_status()

    # Antwort defensiv lesen ([ASSUMED] Schema, None-Fallback). Die GENESIS-JSON
    # trägt die Datensätze unter Object.Data; jede Zeile ist eine Fachabteilung
    # (bzw. die Insgesamt-Zeile). [ASSUMED]: KH-Anzahl unter ``KRH01``, Betten unter
    # ``BETT01``, Fachabteilungsname unter ``GEN``/``DINSG`` (Live-Abgleich Manual-
    # Only). Stichtag aus ``stichtag`` oder ``jahr``.
    body = resp.json()
    obj = body.get("Object") if isinstance(body, dict) else None
    data = obj.get("Data") if isinstance(obj, dict) else None
    rows: list = data if isinstance(data, list) else []

    count: int | None = None
    reference_date: str | None = None
    hospitals: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if reference_date is None:
            stichtag = row.get("stichtag") or row.get("jahr")
            reference_date = str(stichtag).strip() if stichtag is not None else None
        # Anzahl Krankenhäuser aus der Insgesamt-Zeile (KRH01).
        krh = _to_int(row.get("KRH01"))
        if krh is not None and count is None:
            count = krh
        # Je Fachabteilung Name + Bettenzahl als schlankes dict (None fällt weg).
        name = row.get("GEN") or row.get("DINSG")
        betten = _to_int(row.get("BETT01"))
        if name or betten is not None:
            entry: dict = {}
            if name:
                entry["name"] = str(name).strip()
            if betten is not None:
                entry["betten"] = betten
            if entry:
                hospitals.append(entry)

    return {
        "slug": slug,
        "ags": ags,
        # map_hospital erwartet count als int (HospitalPayload.count: int); 0 als
        # ehrlicher Default, wenn die Insgesamt-Zeile keine Anzahl trägt.
        "count": count if count is not None else 0,
        "hospitals": hospitals,
        "reference_date": reference_date,
    }


def _num_de(value: str | None) -> float | int | None:
    """Parst einen deutschen datencsv-Zahlwert (Dezimalkomma) zu int/float/None.

    GENESIS-datencsv nutzt das Dezimalkomma OHNE Tausenderpunkt (z.B. ``218315``
    oder ``10,3``). Fehlwerte sind ``""``/``-``/``.`` -> ``None``. Ganzzahlige
    Werte werden als ``int`` zurückgegeben, sonst ``float``.
    """
    if value is None:
        return None
    s = value.strip()
    if s in ("", "-", ".", "...", "/", "x"):
        return None
    s = s.replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _parse_datencsv_latest(
    content: str, ags5: str, col_specs: dict[str, int]
) -> dict | None:
    """Liest aus einer GENESIS-datencsv die jüngste Datenzeile EINES Kreises.

    Eine Datenzeile hat die Form ``JAHR;AGS5;Name;werte...`` (Semikolon-getrennt,
    Header-/Fusszeilen ignoriert). Gesucht wird die Zeile mit ``ags5`` und dem
    höchsten Jahr. ``col_specs`` mappt Kennzahl-Namen auf den 0-basierten
    Spaltenindex der ``;``-Zerlegung (0=Jahr, 1=AGS, 2=Name, ab 3 die Werte).
    Gibt ``None``, wenn keine passende Zeile existiert (graceful no_data).
    """
    best_year = -1
    best: list[str] | None = None
    for line in content.splitlines():
        parts = line.split(";")
        if len(parts) < 3:
            continue
        year_str = parts[0].strip()
        if not (year_str.isdigit() and len(year_str) == 4):
            continue
        if parts[1].strip() != ags5:
            continue
        year = int(year_str)
        if year > best_year:
            best_year = year
            best = parts
    if best is None:
        return None
    values = {
        name: (_num_de(best[idx]) if idx < len(best) else None)
        for name, idx in col_specs.items()
    }
    return {
        "reference_year": best_year,
        "region_name": best[2].strip() if len(best) > 2 else None,
        "values": values,
    }


async def fetch_genesis_table(
    http: httpx.AsyncClient,
    *,
    table: str,
    ags5: str,
    username: str,
    password: SecretStr,
    col_specs: dict[str, int],
    base_url: str = _BASE,
) -> dict:
    """Holt eine GENESIS-Regionalstatistik-Tabelle je Kreis (POST, Header-Auth).

    Seit dem GENESIS-Update 27.11.2025 gehören die Credentials in die HTTP-Header
    (``username``/``password``), NICHT in den Body (sonst Code 15 "nicht
    berechtigt"). Der Regionalfilter nutzt ``regionalvariable=KREISE`` +
    ``regionalkey=<5-stelliger AGS>``. Der Host ist hartkodiert (SSRF-Guard,
    ``base_url`` MUSS in ``_ALLOWED_HOSTS`` liegen).

    Die Antwort ist ein JSON-Wrapper mit der Tabelle als datencsv-Text in
    ``Object.Content``; die jüngste Zeile des Kreises wird über ``col_specs``
    extrahiert. Credentials erscheinen NIE im Rückgabe-dict (T-08-CRED). Gibt
    immer ein dict zurück (``values`` leer = kein Treffer -> die Route meldet
    no_data); ein 5xx schlägt via ``raise_for_status`` als ``httpx.HTTPError``
    durch (STALE-ON-ERROR).
    """
    if base_url not in _ALLOWED_HOSTS:
        raise ValueError(f"base_url nicht in der GENESIS-Allowlist: {base_url!r}")

    # GENESIS generiert die Tabelle on-demand und ist sehr träge (~25 s je
    # Abruf); der konservative Pool-Default (read=5 s) würde IMMER timeouten.
    # Daher ein großzügiger per-Request-Timeout. Der tägliche Akkrual-Timer
    # hält den Cache warm, sodass Clients selten den kalten Abruf treffen.
    #
    # H1-Fix (Audit 2026-06-29): format=datencsv (NICHT ffcsv). Der nachgelagerte
    # Parser _parse_datencsv_latest erwartet das datencsv-Wide-Format (eine Zeile je
    # Kreis/Jahr: JAHR;AGS;Name;werte... mit festen Spaltenindizes in col_specs).
    # ffcsv ist dagegen Long-Format (eine Zeile je Merkmalskombination) und liegt
    # außerdem als ZIP/CSV statt im Object.Content-JSON-Wrapper vor -> die col_specs-
    # Indizes griffen ins Leere/falsche Spalte. datencsv liefert die Tabelle als
    # Text in Object.Content, genau wie der Parser + die Tests es erwarten.
    resp = await http.post(
        f"{base_url}/data/table",
        headers={"username": username, "password": password.get_secret_value()},
        data={
            "name": table,
            "area": "all",
            "regionalvariable": "KREISE",
            "regionalkey": ags5,
            "format": "datencsv",
            "language": "de",
        },
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
    )
    resp.raise_for_status()

    body = resp.json()
    obj = body.get("Object") if isinstance(body, dict) else None
    content = obj.get("Content") if isinstance(obj, dict) else None
    parsed = (
        _parse_datencsv_latest(content, ags5, col_specs)
        if isinstance(content, str)
        else None
    )
    if parsed is None:
        return {"reference_year": None, "region_name": None, "values": {}}
    return parsed
