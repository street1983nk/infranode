"""Gepoolter httpx-AsyncClient (RES-01) + descriptive User-Agent (RES-05).

Analog zum ``infra/redis.py``-create/close-Paar: genau EIN ``httpx.AsyncClient``
bedient alle Upstreams. Der Client wird im Lifespan-Startup erzeugt
(``create_http_client``) und im Shutdown via ``close_http_client`` geschlossen.
Pool-Limits und ein konservativer Default-Timeout schuetzen vor haengenden
Upstreams; per-Source-Timeout ist je Request ueberschreibbar
(``per_source_timeout``), ohne den Pool zu vervielfachen. Der User-Agent traegt
"InfraNode" plus Repo-URL auf JEDEM Request (Fair-Use, T-03-04).
"""

from __future__ import annotations

import httpx

from infranode import __version__

#: Descriptive User-Agent auf JEDEM Upstream-Request (RES-05, T-03-04). Die Version
#: stammt aus der einzigen Quelle ``infranode.__version__`` (kein hartkodierter
#: Versionsstring, der mit Releases driftet).
USER_AGENT = (
    f"InfraNodeAPI/{__version__} "
    "(+https://github.com/street1983nk/infranode-api; open data proxy)"
)

#: Prozessweiter Pool-Singleton. ``create_http_client`` gibt fuer denselben
#: Prozess dieselbe Instanz zurueck (geteilter Connection-Pool, RES-01).
_client: httpx.AsyncClient | None = None


def create_http_client(settings) -> httpx.AsyncClient:
    """Liefert den prozessweiten, gepoolten AsyncClient (RES-01/05).

    Beim ersten Aufruf wird der Client gebaut und gemerkt; Folgeaufrufe liefern
    dieselbe Instanz (ein geteilter Pool, kein Client pro Request). Wurde der
    gemerkte Client zwischenzeitlich geschlossen (Lifespan-Shutdown), wird ein
    frischer gebaut. Synchron (kein await beim Bau).
    """
    global _client
    if _client is None or _client.is_closed:
        user_agent = getattr(settings, "http_user_agent", None) or USER_AGENT
        _client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},  # RES-05: UA auf JEDEM Request
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
            # Konservativer Default; per-Source per Request ueberschreibbar (T-03-03).
            timeout=httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=1.0),
            # KEINE automatischen Redirects (Audit MEDIUM-1, 2026-06-10): die
            # SSRF-Invariante der Adapter (hartkodierte Hosts/Allowlists) schuetzt
            # nur den ERSTEN Request; ein 30x eines (kompromittierten) Upstreams
            # wuerde sonst blind verfolgt, auch auf interne Ziele (Metadaten-IP,
            # redis). Ein legitimer Redirect schlaegt jetzt als Fehler durch und
            # faellt in der Beta im Smoke/Monitoring auf; der betroffene Adapter
            # zieht dann gezielt auf die finale URL nach (wie divi_live auf www).
            follow_redirects=False,
        )
    return _client


def per_source_timeout(settings, *, source: str) -> httpx.Timeout:
    """Liefert den per-Source-Timeout, der den Client-Default je Request ueberschreibt.

    Der Pool bleibt EIN Singleton; nur der Timeout variiert je Quelle (eine
    traege Quelle wie Wikidata-SPARQL darf laenger lesen als OpenAQ, Pitfall 5).
    Quellenspezifische Werte kommen ab Phase 4 aus ``SourceConfig``; bis dahin
    gilt der konservative Default.
    """
    return httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=1.0)


async def close_http_client(client: httpx.AsyncClient | None) -> None:
    """Schliesst den gepoolten Client samt Pool sauber (no-op bei None)."""
    global _client
    if client is not None:
        await client.aclose()
    _client = None
