"""BBK-NINA-Adapter (amtliche Bevoelkerungsschutz-Warnungen, § 5 Abs. 2 UrhG, Tier A).

Die BBK NINA-API (``https://warnung.bund.de/api31``, KEYLOS) liefert je Kreis-ARS
ein Dashboard-JSON mit den aktiven Warnungen (MOWAS/KATWARN/BIWAPP/POLICE/DWD/LHP).
Die Route bildet den 12-stelligen Kreis-ARS aus dem Register-AGS ab
(``ars_for_ags``) und weist mit ``coverage_granularity`` ehrlich aus, ob der ARS
die Stadt selbst (kreisfrei) oder ihren ganzen Kreis (kreisangehoerig) abdeckt.

Der reine ``parse_nina_dashboard`` reicht je Warnung den amtlichen Text VERBATIM
durch (headline unveraendert); die Provider DWD/LHP werden je Warnung ueber
``duplicate_of`` auf die bereits vorhandenen Datenarten ``weather-warnings`` bzw.
``flood`` markiert (reine Metadaten, KEINE Textaenderung).

Sicherheit (T-ufv-SSRF): Host in ``_BASE_URL`` hartkodiert
(``https://warnung.bund.de/api31``); der ARS stammt aus dem Register-AGS
(``ars_for_ags``), NICHT aus User-Input, und wird nur als Pfadsegment genutzt.
``raise_for_status`` ist Pflicht (5xx -> Resilienz-Fassade STALE-ON-ERROR).
"""

from __future__ import annotations

import httpx

# Host hartkodiert (SSRF-Schutz, T-ufv-SSRF). Kein User-Input in der Basis-URL.
_BASE_URL = "https://warnung.bund.de/api31"

# Defensiver Body-Cap vor json() (DoS): das Dashboard je Kreis ist klein; 4 MiB
# deckt es mit grossem Puffer ab und begrenzt den Speicher bei kaputtem Body.
_MAX_BYTES = 4_194_304

# Provider, die bereits ueber eine eigene Datenart abgedeckt sind. Wert = der
# Katalog-Key der Datenart, auf die je Warnung via duplicate_of verwiesen wird.
_PROVIDER_DUPLICATE_OF: dict[str, str] = {
    "DWD": "weather-warnings",
    "LHP": "flood",
}


def ars_for_ags(ags: str) -> str:
    """Leitet den 12-stelligen Kreis-ARS aus dem 8-stelligen Register-AGS ab.

    Der Kreis-ARS ist die Kreis-Kennung (die ersten 5 AGS-Stellen: Land + RB +
    Kreis), rechts mit "0000000" auf 12 Stellen aufgefuellt. Beispiel Koeln
    ``05315000`` -> ``053150000000``, Muenchen ``09162000`` -> ``091620000000``.
    """
    return f"{ags[:5]}0000000"


def coverage_granularity(ags: str) -> str:
    """Ehrliche Regionsschaerfe des Kreis-ARS zum Register-AGS.

    ``"city"`` wenn die Stadt kreisfrei ist (AGS-Gemeindeteil == "000" -> der Kreis
    IST die Stadt, ARS deckt genau die Stadt ab); sonst ``"district"`` (die Stadt
    ist eine kreisangehoerige Gemeinde, der Kreis-ARS deckt den ganzen Kreis ab).
    """
    return "city" if ags[5:8] == "000" else "district"


def _duplicate_of(provider: object) -> str | None:
    """Reine Ableitung: DWD -> 'weather-warnings', LHP -> 'flood', sonst None."""
    if not isinstance(provider, str):
        return None
    return _PROVIDER_DUPLICATE_OF.get(provider.upper())


def _warning(item: dict) -> dict:
    """Normalisiert ein rohes NINA-Dashboard-Item Zero-Trust zu einer Warnung.

    Der amtliche Warntext (``headline``) wird VERBATIM durchgereicht. Fehlende/
    kaputte Felder werden zu ``None`` (nie ein Fehler). ``detail_url`` zeigt auf die
    offizielle Einzel-Warnung ``{_BASE_URL}/warnings/{id}.json`` (nur wenn eine id
    vorliegt). ``duplicate_of`` markiert DWD/LHP-Provider (reine Metadaten).
    """
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}

    wid = item.get("id")
    provider = data.get("provider")
    return {
        "id": wid,
        "event": payload.get("type"),
        # Amtlicher Warntext VERBATIM (§ 5 Abs. 2 UrhG): NICHT umformulieren.
        "headline": data.get("headline"),
        "provider": provider,
        "severity": data.get("severity"),
        "sent": item.get("sent"),
        "onset": item.get("onset") or item.get("effective"),
        "expires": item.get("expires"),
        "detail_url": f"{_BASE_URL}/warnings/{wid}.json" if wid else None,
        "duplicate_of": _duplicate_of(provider),
    }


def parse_nina_dashboard(
    items: object,
    *,
    ars: str,
    granularity: str,
) -> dict:
    """Reiner Filter: rohe NINA-Dashboard-Liste -> schlankes Warnungs-dict.

    Rueckgabe ``{ars, coverage_granularity, count, warnings}``. Zero-Trust: eine
    Nicht-Liste oder Nicht-dict-Items werden uebersprungen, fehlende Felder werden
    zu ``None``, nie zu einer Exception. Leere Liste -> leere ``warnings``,
    ``count`` 0 (keine Warnung ist KEIN Fehler).
    """
    warnings: list[dict] = []
    if isinstance(items, list):
        warnings = [_warning(item) for item in items if isinstance(item, dict)]
    return {
        "ars": ars,
        "coverage_granularity": granularity,
        "count": len(warnings),
        "warnings": warnings,
    }


async def fetch_nina_dashboard(http: httpx.AsyncClient, *, ars: str) -> dict:
    """Holt das NINA-Dashboard eines Kreis-ARS und liefert das raw-dict fuer den Mapper.

    GET auf ``{_BASE_URL}/dashboard/{ars}.json`` (Host hartkodiert, ARS aus dem
    Register-AGS = kein User-Input). ``raise_for_status`` ist Pflicht (5xx ->
    Resilienz-Fassade). Zero-Trust: ein kaputter/zu grosser Body fuehrt zu leeren
    ``warnings`` (count 0), nie zu einem Fehler.
    """
    resp = await http.get(f"{_BASE_URL}/dashboard/{ars}.json")
    resp.raise_for_status()

    granularity = "district"
    content = resp.content
    if len(content) > _MAX_BYTES:
        # DoS: zu grosser Body -> leere warnings (kein OOM, kein Parse).
        return parse_nina_dashboard([], ars=ars, granularity=granularity)

    try:
        items = resp.json()
    except (ValueError, TypeError):
        items = []
    return parse_nina_dashboard(items, ars=ars, granularity=granularity)


async def fetch_for_ags(http: httpx.AsyncClient, *, ags: str) -> dict:
    """Convenience: leitet ARS + granularity aus dem AGS ab und ruft das Dashboard.

    Die ehrliche ``coverage_granularity`` (city|district) haengt am AGS, nicht am
    ARS (der ARS ist immer Kreis-scharf), deshalb wird sie hier gesetzt.
    """
    ars = ars_for_ags(ags)
    raw = await fetch_nina_dashboard(http, ars=ars)
    raw["coverage_granularity"] = coverage_granularity(ags)
    return raw
