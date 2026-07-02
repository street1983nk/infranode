"""Rate-Limiting-Verträge (API-06): Limiter + key_func + Tier-Konstanten.

Wave 1 verdrahtet die echte sync-Redis-URI (Pitfall 1: slowapi teilt NICHT den
async-Pool ``app.state.redis``, sondern öffnet über ``storage_uri`` eine EIGENE
synchrone redis-py-Verbindung zum SELBEN Redis-Server). ``build_limiter`` leitet
die Storage-URI aus den Settings ab (``limit_storage_uri or redis_url``).

Die Header werden auf die IETF-Standard-Namen ``RateLimit-Limit`` /
``RateLimit-Remaining`` / ``RateLimit-Reset`` normalisiert (D-02): slowapi
emittiert per Default die älteren ``X-RateLimit-*``-Namen; über
``_header_mapping`` mappen wir sie auf die Standard-Namen ohne ``X-``-Präfix.

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
from infranode.infra.allowlist import ip_allowlisted, parse_allowlist

# IETF-Standard-RateLimit-Header (D-02, ohne X--Präfix). slowapi nutzt per
# Default X-RateLimit-*; dieses Mapping normalisiert die Namen.
_STANDARD_HEADER_MAPPING = {
    HEADERS.LIMIT: "RateLimit-Limit",
    HEADERS.REMAINING: "RateLimit-Remaining",
    HEADERS.RESET: "RateLimit-Reset",
    HEADERS.RETRY_AFTER: "Retry-After",
}


def ANON_LIMIT() -> str:
    """Kombiniertes IP-Budget: Burst (limit_anon) + nachhaltiges Fenster.

    Gibt beide Limits semikolon-getrennt zurück; slowapi/limits ``parse_many``
    liest das als MEHRERE gleichzeitig geltende Limits (Burst pro Minute bremst
    Spitzen, das Stunden-Limit bremst Dauer-Scraping). Ist nur limit_anon gesetzt
    (z.B. Test-Override INFRANODE_LIMIT_ANON), gilt allein dieses.

    Frisch instanziiert statt get_settings()-Cache (Konvention Toggle-Lookup), da
    @limiter.limit das Limit pro Request liest und per-Test gesetzte INFRANODE_-
    Env-Vars greifen müssen.
    """
    s = Settings()
    limits = [s.limit_anon]
    if s.limit_anon_sustained:
        limits.append(s.limit_anon_sustained)
    return ";".join(limits)


def ADMIN_LOGIN_LIMIT() -> str:
    """Striktes Budget am Admin-Login gegen Brute-Force (Audit HIGH-1)."""
    return Settings().limit_admin_login


def real_client_ip(request: Request) -> str:
    """Echte Client-IP: CF-Connecting-IP -> X-Forwarded-For[0] -> Peer (PFLICHT).

    Nie slowapis ``get_remote_address`` (liest nur die Proxy-IP, T-11-RL-SPOOF).

    VERTRAUENS-VORBEDINGUNG (Audit HIGH-2, 2026-06-10): Diese Header sind nur
    vertrauenswürdig, wenn das Origin AUSSCHLIESSLICH von Cloudflare erreichbar
    ist (Firewall-Pflichtschritt im Runbook) und Caddy ein client-gesendetes
    X-Forwarded-For strippt (Caddyfile.prod). Ohne beides könnte ein Angreifer
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
    """Sync-Storage-URI für slowapi: limit_storage_uri sonst redis_url (Pitfall 1).

    slowapi öffnet damit eine EIGENE synchrone redis-py-Verbindung zum SELBEN
    Redis-Server (nicht der async app.state.redis-Pool). Das erfüllt "ueber
    Worker geteilt + überlebt Neustart" faktisch (RESEARCH Open Q1, Variante a).
    """
    return settings.limit_storage_uri or settings.redis_url


def build_limiter(settings: Settings) -> Limiter:
    """Baut den slowapi-Limiter aus den Settings (Test-Override-sicher).

    ``headers_enabled=True`` lässt slowapi die RateLimit-Header emittieren; das
    ``_header_mapping`` normalisiert sie auf die IETF-Standard-Namen (D-02).

    ``default_limits=[ANON_LIMIT]`` (Live-Report M2): das IP-Budget (default
    60/min) gilt als DEFAULT für JEDE Route, die die RateLimitMiddleware sieht,
    also auch die City-/Meta-GETs ohne eigenen @limiter.limit-Decorator. Routen
    MIT eigenem Decorator (/sources, /compare, /admin/login) behalten ihr eigenes
    Limit (slowapi zieht für dekorierte Routen im Middleware-Pfad NICHT
    zusätzlich das Default). So tragen alle GET-Routen ein Limit + RateLimit-
    Header, ohne dass jede Route dekoriert werden muss.

    Die API ist keylos/offen: alle Clients teilen sich das IP-Budget (ANON_LIMIT),
    es gibt keine Key-/Tier-Differenzierung mehr.

    ALLOWLIST-BYPASS (Connectors-Directory-Härtung 2026-07-02): der Wrapper um
    ``_check_request_limit`` ist der EINE Choke-Point, durch den slowapi ALLE
    Prüfungen zieht (default_limits via RateLimitMiddleware UND die
    @limiter.limit-Decorator von /sources, /compare, /admin/login). CIDRs aus
    INFRANODE_RATELIMIT_ALLOWLIST (z.B. Anthropic-Egress: viele Endnutzer
    hinter wenigen IPs) werden dort nicht gezählt und nie gedrosselt.
    AUSNAHME /admin*: das Admin-Login-Limit ist Brute-Force-Schutz (Auth-nah,
    HIGH-1) und gilt IMMER, auch für allowlistete IPs (NUR Limit-Bypass, KEINE
    Auth-Wirkung). Die Allowlist wird wie ANON_LIMIT pro Request frisch aus den
    Settings gelesen (Test-Override-Konvention); parse_allowlist ist lru-gecacht,
    pro Request fällt also nur der billige CIDR-Vergleich an. Fail-safe: leere/
    kaputte Konfiguration allowlistet niemanden (infra/allowlist.py).
    """
    lim = Limiter(
        key_func=rate_key,
        default_limits=[ANON_LIMIT],
        headers_enabled=True,
        storage_uri=_storage_uri(settings),
    )
    # Vor dem ersten Request gesetzt: extension._init bewahrt vorhandene Einträge
    # (header_mapping.get(..., default)), also schlagen die Standard-Namen durch.
    lim._header_mapping.update(_STANDARD_HEADER_MAPPING)

    orig_check = lim._check_request_limit

    def _check_with_allowlist(
        request: Request, endpoint_func, in_middleware: bool = False
    ) -> None:  # noqa: ANN001 - slowapi-interne Signatur (Callable | None)
        if not request.url.path.startswith("/admin") and ip_allowlisted(
            real_client_ip(request), parse_allowlist(Settings().ratelimit_allowlist)
        ):
            # Bypass: keine Zählung, kein 429. view_rate_limit explizit auf
            # None setzen, weil der slowapi-Decorator es nach der Route
            # ungeprüft liest (request.state wirft sonst AttributeError);
            # _inject_headers ist mit None ein No-op -> keine RateLimit-Header.
            request.state.view_rate_limit = None
            return
        orig_check(request, endpoint_func, in_middleware)

    # Bewusster Eingriff in die private Methode (Haus-Stil: slowapi 0.1.9 ist
    # gepinnt, s. _header_mapping oben und _Limiter__marked_for_limiting in
    # main.py); slowapi selbst bietet keinen request-basierten Exempt-Hook
    # (exempt_when/_request_filters werden OHNE Request aufgerufen).
    lim._check_request_limit = _check_with_allowlist
    return lim


# Modul-Limiter mit Settings-abgeleiteter Storage-URI. create_app() überschreibt
# diese Instanz NICHT, sondern verdrahtet sie an app.state.limiter; die Storage-URI
# wird zur Import-Zeit aus den (Test-)Settings gelesen.
limiter = build_limiter(Settings())
