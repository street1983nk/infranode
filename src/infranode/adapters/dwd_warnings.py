"""DWD-Wetterwarnungen-Adapter (amtliche Warnungen, GeoNutzV, Tier A).

Der DWD liefert die bundesweite WarnApp-JSON (ein Request, alle Warncells). Die
Route cacht das volle File EINMAL (``fetch_dwd_warnings_all``) und filtert je Stadt
mit dem reinen ``extract_warncell`` heraus, damit nicht 84-mal dasselbe File
geladen wird und der Cache nicht den Filter einer anderen Stadt zurueckgibt.

Die DWD-Gemeinde-Warncell-ID ist ``"1" + achtstelliger AGS`` (z.B. Delmenhorst
AGS 03401000 -> Warncell 103401000), daher braucht es keine externe Mapping-
Tabelle; die Route bildet ``warncell_id`` aus dem Register-AGS.

Die Antwort ist JSONP (``warnWetter.loadWarnings({...});``); der Wrapper wird vor
``json.loads`` entfernt. Tageskennzahl: ``max_level`` (0 = keine Warnung, sonst
1-4 = DWD-Warnstufe), plus ``count`` und die Einzelwarnungen.

Sicherheit (T-05-08 SSRF): Host in ``_URL`` hartkodiert; ``warncell_id`` stammt
aus dem Register-AGS, nicht aus User-Input, und wird nur als dict-Key genutzt.
``raise_for_status`` ist Pflicht (5xx -> Resilienz-Fassade).
"""

from __future__ import annotations

import json
import re

import httpx

# Host hartkodiert (SSRF-Schutz, T-05-08).
_URL = "https://www.dwd.de/DWD/warnungen/warnapp/json/warnings.json"
# JSONP-Wrapper: warnWetter.loadWarnings({...});
_JSONP = re.compile(r"^[A-Za-z_.]+\((.*)\);?\s*$", re.S)


def warncell_for_ags(ags: str) -> str:
    """DWD-Gemeinde-Warncell-ID = '1' + achtstelliger AGS."""
    return f"1{ags}"


async def fetch_dwd_warnings_all(http: httpx.AsyncClient) -> dict:
    """Volle bundesweite WarnApp-JSON (JSONP entfernt). Cachebar fuer alle Staedte."""
    resp = await http.get(_URL)
    resp.raise_for_status()
    text = resp.text.strip()
    match = _JSONP.match(text)
    return json.loads(match.group(1) if match else text)


def extract_warncell(data: dict, warncell_id: str) -> dict:
    """Reiner Filter: Warnungen einer Warncell aus dem vollen File.

    Rückgabe ``{warncell_id, count, max_level, warnings}``; ``max_level`` 0 wenn
    keine Warnung (ehrliche Ruhe-Basislinie, kein None).
    """
    cell = (data.get("warnings") or {}).get(str(warncell_id)) or []
    warnings = [
        {
            "event": w.get("event"),
            "level": w.get("level"),
            "headline": w.get("headline"),
            "start": w.get("start"),
            "end": w.get("end"),
        }
        for w in cell
    ]
    levels = [w.get("level") for w in cell if isinstance(w.get("level"), (int, float))]
    return {
        "warncell_id": str(warncell_id),
        "count": len(cell),
        "max_level": max(levels) if levels else 0,
        "warnings": warnings,
    }


async def fetch_dwd_warnings(http: httpx.AsyncClient, *, warncell_id: str) -> dict:
    """Convenience: volles File holen und direkt nach Warncell filtern."""
    data = await fetch_dwd_warnings_all(http)
    return extract_warncell(data, warncell_id)
