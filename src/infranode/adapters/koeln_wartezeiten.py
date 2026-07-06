"""Keyloser Koeln-Behoerden-Wartezeiten-Adapter ``fetch_koeln_wartezeiten``.

Direkter Zugang zu den Live-Wartezeiten der Koelner Kundenzentren + Kfz-
Zulassungsstelle ueber den offenen JSON-Feed der Stadt Koeln (KEIN Key, KEINE
Mobilithek, [VERIFIED 2026-07-05], HTTPS 200 application/json):

- GET ``waiting-od.php`` liefert ``{"success": true, "items": [ {...}, ... ]}``.
  Je Standort ein flaches Item mit ausschliesslich STRING-Feldern: ``title_anz``
  (Standortname), ``timestamp`` (Lokalzeit Europe/Berlin ohne TZ, z.B.
  "2026-07-04 00:00:03"), ``link`` (Detailseite), ``status`` ("1"=offen,
  "2"=geschlossen), ``sondertext`` (Klartext) und ``wartezeit_minuten``
  (Wartezeit in Minuten als String). 9 Kundenzentren + Kfz-Zulassungsstelle.

Rueckgabe ist das raw-dict, das ``map_koeln_wartezeiten`` erwartet: ``slug`` =
"koeln" und ``items`` (die rohe, ungefilterte Items-Liste). Der Adapter macht
KEIN Mapping/CanonicalRecord und kennt KEIN Cache/Breaker (das liefert die
Resilienz-Fassade). ``resp.raise_for_status()`` ist Pflicht, damit ein 5xx als
``httpx.HTTPError`` durchschlaegt und der STALE-ON-ERROR-Pfad greift.

Lizenz: Datenlizenz Deutschland Zero 2.0 (govdata.de/dl-de/zero-2-0) = Tier A
(offenedaten-koeln.de, Dataset kundenzentren-koeln-wartezeiten). Siehe
``mappers/koeln_wartezeiten.map_koeln_wartezeiten``.

Sicherheit:
- T-Q-01 (SSRF): Der Host ist in ``_URL`` hartkodiert; es fliesst kein
  User-Input in die URL (fester Pfad, keine Query aus Argumenten).
- T-Q-02 (DoS): ``raise_for_status`` + defensiver Body-Cap vor ``json()``.
"""

from __future__ import annotations

import json

import httpx

# Host + Pfad hartkodiert (SSRF-Schutz, T-Q-01). Kein User-Input in der URL.
_URL = "https://www.stadt-koeln.de/externe-dienste/open-data/waiting-od.php"

# Defensiver Body-Cap vor json() (T-Q-02): der Feed ist klein (10 Standorte);
# 1 MiB deckt ihn mit grossem Puffer ab und begrenzt den Speicher bei einem
# unerwartet grossen/kaputten Body.
_MAX_BYTES = 1_048_576


async def fetch_koeln_wartezeiten(http: httpx.AsyncClient) -> dict:
    """Holt die Live-Wartezeiten Koeln und liefert das raw-dict fuer den Mapper.

    Rueckgabe-Keys (exakt das, was ``map_koeln_wartezeiten`` erwartet): ``slug``
    ("koeln") und ``items`` (die rohe Items-Liste, oder ``[]`` wenn der Body kein
    ``items``-Array traegt). ``raise_for_status`` ist Pflicht (5xx -> Fassade
    STALE-ON-ERROR). Zero-Trust: ein kaputter/fehlender Body fuehrt zu leeren
    ``items``, nie zu einem Fehler.
    """
    resp = await http.get(_URL)
    resp.raise_for_status()

    content = resp.content
    if len(content) > _MAX_BYTES:
        # T-Q-02 DoS: zu grosser Body -> leere items (kein OOM, kein Parse).
        return {"slug": "koeln", "items": []}

    try:
        body = json.loads(content)
    except (ValueError, TypeError):
        body = None

    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        items = []

    return {"slug": "koeln", "items": items}
