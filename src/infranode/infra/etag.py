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

# Ressourcen, die NIE am CDN/Browser zwischengespeichert werden duerfen ->
# "no-store". Echtzeit-Endpunkte unter /api/v1/live/* (Resource-Segment "live":
# HVV-Abfahrten, GTFS-RT-Transit, Dortmund-Parken, Koeln/Berlin-Live u.a.)
# liefern minuetlich wechselnde Daten. Ohne no-store cached Cloudflare die
# Antwort bis zu seiner Browser-Cache-TTL (beobachtet: 4 h Override trotz
# origin max-age=300) und serviert Live-Daten massiv stale; ein transienter
# no_data-Zustand bliebe stundenlang eingefroren. no-store haelt /live/
# cache-frei (Origin-Last bleibt klein, da der resiliente Redis-Cache davor
# liegt). Clients steuern ihren Poll-Takt ueber meta.refresh_seconds.
NO_STORE_RESOURCES = frozenset({"live"})


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

    Ressourcen in ``NO_STORE_RESOURCES`` (Echtzeit-Endpunkte /api/v1/live/*)
    liefern stattdessen ``no-store``, damit Cloudflare/Browser sie nicht
    zwischenspeichern (sonst werden Live-Daten bis zur CDN-Browser-TTL stale).
    """
    if resource in NO_STORE_RESOURCES:
        return "no-store"
    ttl = CACHE_TTL.get(resource or "default", CACHE_TTL["default"])
    # stale-while-revalidate + stale-if-error (Security-Haertung 2026-06-21):
    # Nach Ablauf der max-age liefert ein Shared Cache (Cloudflare) die Antwort
    # SOFORT weiter und revalidiert asynchron im Hintergrund -> kein Thundering
    # Herd aufs Origin bei populaeren Endpunkten (DoS-/Scraping-Last-Glaettung).
    # stale-if-error haelt die API bei Origin-Ueberlast/-Ausfall antwortfaehig
    # (das CDN serviert die letzte gute Antwort statt eines Fehlers). Fenster =
    # ttl. Greift nur an einem Shared Cache; Browser ignorieren swr i. d. R.
    return f"public, max-age={ttl}, stale-while-revalidate={ttl}, stale-if-error={ttl}"
