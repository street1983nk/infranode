"""DWD-Wetterwarnungen-Adapter (amtliche Warnungen, GeoNutzV, Tier A).

Der DWD liefert die bundesweite WarnApp-JSON (ein Request, alle Warncells). Die
Route cacht das volle File EINMAL (``fetch_dwd_warnings_all``) und filtert je Stadt
mit dem reinen ``extract_warncell`` heraus, damit nicht 84-mal dasselbe File
geladen wird und der Cache nicht den Filter einer anderen Stadt zurückgibt.

Die DWD-Gemeinde-Warncell-ID ist ``"1" + achtstelliger AGS`` (z.B. Delmenhorst
AGS 03401000 -> Warncell 103401000), daher braucht es keine externe Mapping-
Tabelle; die Route bildet ``warncell_id`` aus dem Register-AGS.

Die Antwort ist JSONP (``warnWetter.loadWarnings({...});``); der Wrapper wird vor
``json.loads`` entfernt. Tageskennzahl: ``max_level`` (0 = keine Warnung, sonst
1-4 = DWD-Warnstufe), plus ``count`` und die Einzelwarnungen.

KRITISCH (Audit K5): Der DWD mischt im ``level``-Feld zwei Skalen. Reguläre
Wetterwarnungen tragen Stufe 1-4 (gelb/orange/rot/violett), Hitze-/UV-/Sonder-
warnungen tragen dagegen Sondercodes ab 50 (z.B. 51 = starke Wärmebelastung).
Ein naiver ``max()`` über beide Skalen ließe eine Hitzewarnung (51) jede echte
Sturm-Stufe überstrahlen. Daher wird ``max_level`` AUSSCHLIESSLICH über die
regulären Stufen 1-4 gebildet; die Sonderwarnungen (Code >= 50) werden NICHT
verworfen, sondern separat in ``special_warnings`` mit ihrem echten Code geführt.

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

# Untergrenze der DWD-Sondercodes (Hitze/UV/...). Reguläre Wetter-Warnstufen
# liegen bei 1-4; Codes >= 50 sind eine eigene Skala und gehören NICHT in
# max_level (Audit K5).
_SPECIAL_LEVEL_MIN = 50


def warncell_for_ags(ags: str) -> str:
    """DWD-Gemeinde-Warncell-ID = '1' + achtstelliger AGS."""
    return f"1{ags}"


async def fetch_dwd_warnings_all(http: httpx.AsyncClient) -> dict:
    """Volle bundesweite WarnApp-JSON (JSONP entfernt). Cachebar für alle Städte."""
    resp = await http.get(_URL)
    resp.raise_for_status()
    text = resp.text.strip()
    match = _JSONP.match(text)
    return json.loads(match.group(1) if match else text)


def extract_warncell(data: dict, warncell_id: str) -> dict:
    """Reiner Filter: Warnungen einer Warncell aus dem vollen File.

    Rückgabe ``{warncell_id, count, max_level, warnings, special_warnings}``;
    ``max_level`` 0 wenn keine reguläre Warnung (ehrliche Ruhe-Basislinie, kein
    None). ``warnings`` enthält ALLE aktiven Warnungen der Zelle (regulär +
    Sonder); ``special_warnings`` ist die Teilmenge der Sonderwarnungen mit Code
    >= 50 (Hitze/UV), die NICHT in ``max_level`` einfließen (Audit K5).
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
    # max_level NUR über die regulären Stufen 1-4 (Sondercodes >= 50 raus).
    regular_levels = [
        w.get("level")
        for w in cell
        if isinstance(w.get("level"), (int, float))
        and w.get("level") < _SPECIAL_LEVEL_MIN
    ]
    # Sonderwarnungen (Hitze/UV, Code >= 50) separat führen, nicht verwerfen.
    special_warnings = [
        w
        for w in warnings
        if isinstance(w.get("level"), (int, float)) and w["level"] >= _SPECIAL_LEVEL_MIN
    ]
    return {
        "warncell_id": str(warncell_id),
        "count": len(cell),
        "max_level": max(regular_levels) if regular_levels else 0,
        "warnings": warnings,
        "special_warnings": special_warnings,
    }


async def fetch_dwd_warnings(http: httpx.AsyncClient, *, warncell_id: str) -> dict:
    """Convenience: volles File holen und direkt nach Warncell filtern."""
    data = await fetch_dwd_warnings_all(http)
    return extract_warncell(data, warncell_id)
