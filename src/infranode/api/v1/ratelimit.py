"""Rate-Limiting-Vertraege (API-06): Limiter + key_func + Tier-Konstanten.

Wave 1 verdrahtet die echte sync-Redis-URI (Pitfall 1: slowapi teilt NICHT den
async-Pool ``app.state.redis``, sondern oeffnet ueber ``storage_uri`` eine EIGENE
synchrone redis-py-Verbindung zum SELBEN Redis-Server). ``build_limiter`` leitet
die Storage-URI aus den Settings ab (``limit_storage_uri or redis_url``).

Die Header werden auf die IETF-Standard-Namen ``RateLimit-Limit`` /
``RateLimit-Remaining`` / ``RateLimit-Reset`` normalisiert (D-02): slowapi
emittiert per Default die aelteren ``X-RateLimit-*``-Namen; ueber
``_header_mapping`` mappen wir sie auf die Standard-Namen ohne ``X-``-Praefix.

``real_client_ip`` ist PFLICHT statt slowapis ``get_remote_address`` (T-11-RL-
SPOOF): hinter Caddy/Cloudflare liest ``request.client.host`` nur die Proxy-IP.
Die echte Client-IP kommt zuerst aus dem Cloudflare-Header, dann aus der ersten
IP von X-Forwarded-For, sonst dem direkten Peer.
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.extension import HEADERS

from infranode.config import Settings

# IETF-Standard-RateLimit-Header (D-02, ohne X--Praefix). slowapi nutzt per
# Default X-RateLimit-*; dieses Mapping normalisiert die Namen.
_STANDARD_HEADER_MAPPING = {
    HEADERS.LIMIT: "RateLimit-Limit",
    HEADERS.REMAINING: "RateLimit-Remaining",
    HEADERS.RESET: "RateLimit-Reset",
    HEADERS.RETRY_AFTER: "Retry-After",
}


def ANON_LIMIT() -> str:
    """IP-Budget fuer alle Clients (frische Settings(), Test-Override-sicher).

    Frisch instanziiert statt get_settings()-Cache (Konvention Toggle-Lookup), da
    @limiter.limit das Limit pro Request liest und per-Test gesetzte INFRANODE_-
    Env-Vars greifen muessen.
    """
    return Settings().limit_anon


def ADMIN_LOGIN_LIMIT() -> str:
    """Striktes Budget am Admin-Login gegen Brute-Force (Audit HIGH-1)."""
    return Settings().limit_admin_login


def real_client_ip(request: Request) -> str:
    """Echte Client-IP: CF-Connecting-IP -> X-Forwarded-For[0] -> Peer (PFLICHT).

    Nie slowapis ``get_remote_address`` (liest nur die Proxy-IP, T-11-RL-SPOOF).

    VERTRAUENS-VORBEDINGUNG (Audit HIGH-2, 2026-06-10): Diese Header sind nur
    vertrauenswuerdig, wenn das Origin AUSSCHLIESSLICH von Cloudflare erreichbar
    ist (Firewall-Pflichtschritt im Runbook) und Caddy ein client-gesendetes
    X-Forwarded-For strippt (Caddyfile.prod). Ohne beides koennte ein Angreifer
    pro Request eine Zufalls-IP setzen und sich frische Rate-Limit-Buckets
    erschleichen.
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def rate_key(request: Request) -> str:
    """Zaehlschluessel pro Client: ``ip:<client-ip>`` (keylose, offene API)."""
    return f"ip:{real_client_ip(request)}"


def _storage_uri(settings: Settings) -> str:
    """Sync-Storage-URI fuer slowapi: limit_storage_uri sonst redis_url (Pitfall 1).

    slowapi oeffnet damit eine EIGENE synchrone redis-py-Verbindung zum SELBEN
    Redis-Server (nicht der async app.state.redis-Pool). Das erfuellt "ueber
    Worker geteilt + ueberlebt Neustart" faktisch (RESEARCH Open Q1, Variante a).
    """
    return settings.limit_storage_uri or settings.redis_url


def build_limiter(settings: Settings) -> Limiter:
    """Baut den slowapi-Limiter aus den Settings (Test-Override-sicher).

    ``headers_enabled=True`` laesst slowapi die RateLimit-Header emittieren; das
    ``_header_mapping`` normalisiert sie auf die IETF-Standard-Namen (D-02).

    ``default_limits=[ANON_LIMIT]`` (Live-Report M2): das IP-Budget (default
    60/min) gilt als DEFAULT fuer JEDE Route, die die RateLimitMiddleware sieht,
    also auch die City-/Meta-GETs ohne eigenen @limiter.limit-Decorator. Routen
    MIT eigenem Decorator (/sources, /compare, /admin/login) behalten ihr eigenes
    Limit (slowapi zieht fuer dekorierte Routen im Middleware-Pfad NICHT
    zusaetzlich das Default). So tragen alle GET-Routen ein Limit + RateLimit-
    Header, ohne dass jede Route dekoriert werden muss.

    Die API ist keylos/offen: alle Clients teilen sich das IP-Budget (ANON_LIMIT),
    es gibt keine Key-/Tier-Differenzierung mehr.
    """
    lim = Limiter(
        key_func=rate_key,
        default_limits=[ANON_LIMIT],
        headers_enabled=True,
        storage_uri=_storage_uri(settings),
    )
    # Vor dem ersten Request gesetzt: extension._init bewahrt vorhandene Eintraege
    # (header_mapping.get(..., default)), also schlagen die Standard-Namen durch.
    lim._header_mapping.update(_STANDARD_HEADER_MAPPING)
    return lim


# Modul-Limiter mit Settings-abgeleiteter Storage-URI. create_app() ueberschreibt
# diese Instanz NICHT, sondern verdrahtet sie an app.state.limiter; die Storage-URI
# wird zur Import-Zeit aus den (Test-)Settings gelesen.
limiter = build_limiter(Settings())
