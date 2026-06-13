"""ETag-/Cache-Control-Vertraege (API-08): compute_etag + CACHE_TTL-Map.

``compute_etag`` baut einen stabilen ETag aus dem serialisierten Response-Body
(sha256-Idiom analog infra/cache.py:build_cache_key, hier ueber Body-Bytes). Der
ETag wird serverseitig berechnet; If-None-Match wird nur verglichen, nie als
Cache-Schluessel verwendet (Cache-Poisoning-Schutz). Die TTL-Map liefert je
Ressource das Cache-Control-Fenster (Sekunden); ``default`` greift sonst.

Die ETag-/304-Middleware selbst (nur GET/200 cachen, nie Fehler-Envelopes) wird
in Wave 3 verdrahtet; hier stehen die importierbaren Helper-Vertraege fest.
"""

from __future__ import annotations

import hashlib

# Cache-Control-TTL je Ressource (Sekunden). default greift, wenn keine
# spezifische Ressource passt. Additiv erweiterbar ohne Logik-Aenderung.
CACHE_TTL = {
    "dwd": 1800,
    "uba": 600,
    "wikidata": 86400,
    "default": 300,
}


def compute_etag(body: bytes) -> str:
    """ETag aus dem serialisierten Body: gequoteter sha256[:32]-Hex.

    Deterministisch ueber die rohen Response-Bytes (ORJSONResponse liefert
    bytes). Gleicher Body -> gleicher ETag -> If-None-Match-Match -> 304.
    """
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def cache_control_for(resource: str | None = None) -> str:
    """Cache-Control-Wert je Ressource aus der CACHE_TTL-Map.

    Waehlt die passende max-age-TTL ("public, max-age=<ttl>"); faellt auf
    ``default`` (300 s) zurueck, wenn keine spezifische Ressource passt. Der
    Wert ist additiv erweiterbar, ohne die Middleware-Logik zu aendern.
    """
    ttl = CACHE_TTL.get(resource or "default", CACHE_TTL["default"])
    return f"public, max-age={ttl}"
