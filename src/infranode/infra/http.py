"""Gepoolter httpx-AsyncClient (RES-01) + descriptive User-Agent (RES-05).

Analog zum ``infra/redis.py``-create/close-Paar: genau EIN ``httpx.AsyncClient``
bedient alle Upstreams. Der Client wird im Lifespan-Startup erzeugt
(``create_http_client``) und im Shutdown via ``close_http_client`` geschlossen.

Pool-Isolation je Upstream-Host (Strukturfix Vorfall 30.08.2026): der Client
routet intern über einen ``PerHostTransport``, der je Upstream-Host einen
EIGENEN Kind-Transport mit eigenem Connection-Pool hält. Beim Vorfall belegten
380 CLOSE-WAIT-Sockets eines einzigen kranken Hosts (apis.deutschebahn.com) den
damals globalen 100er-Pool und ALLE anderen Quellen bekamen PoolTimeout. Mit
Pool je Host kann ein hängender Upstream höchstens seinen eigenen Pool sättigen;
die Call-Sites (``app.state.http``) bleiben unverändert ein einziger Client.

Pool-Limits und ein konservativer Default-Timeout schützen vor hängenden
Upstreams; per-Source-Timeout ist je Request überschreibbar
(``per_source_timeout``), ohne den Pool zu vervielfachen. Der User-Agent trägt
"InfraNode" plus Repo-URL auf JEDEM Request (Fair-Use, T-03-04).
"""

from __future__ import annotations

import asyncio

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from infranode import __version__

#: Nur idempotente Methoden werden wiederholt. Ein POST/PUT/PATCH/DELETE darf sich
#: beim Retry NICHT verdoppeln (kein doppelter Schreib-/Nebeneffekt-Call).
_RETRY_METHODS = frozenset({"GET", "HEAD"})

#: Transiente Upstream-Statuscodes, die einen erneuten Versuch rechtfertigen
#: (voruebergehende Server-/Gateway-Fehler). 4xx (404/429) NICHT: die sind
#: deterministisch und ein Retry wuerde nur Last erzeugen.
_RETRY_STATUS = frozenset({502, 503, 504})

#: Transiente Transport-Ausnahmen (Verbindungs-/Lesetimeouts), die geglaettet
#: werden sollen. Andere httpx-Fehler werden NICHT wiederholt.
_RETRY_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
)

#: Maximale Gesamtzahl der Versuche je Request: 1 Versuch + 2 Retries. Als EINE
#: Konstante, damit die Stop-Bedingung der Retry-Schleife und die
#: Letzter-Versuch-Pruefung (direkter Return statt Retry-Raise) nicht
#: auseinanderdriften koennen.
_MAX_ATTEMPTS = 3


class _TransientStatusError(Exception):
    """Interner Retry-Marker: transiente Statusantwort (502/503/504) soll retryen.

    Wird NUR auf den nicht-letzten Versuchen innerhalb der Retry-Schleife
    geworfen und dort von tenacity gefangen; die verworfene Zwischenantwort ist
    beim Raise bereits geschlossen (Pool-Slot zurueckgegeben). Der letzte
    Versuch returnt seine Antwort direkt, die Ausnahme verlaesst die Schleife
    also nie und traegt darum auch keine Response mehr.
    """


class RetryTransport(httpx.AsyncHTTPTransport):
    """httpx-Transport mit zentralem tenacity-Retry fuer idempotente GET/HEAD.

    Wiederholt einen Request maximal 3x gesamt (2 Retries) bei transienten
    Transport-Ausnahmen ODER transienten Statuscodes (502/503/504), aber
    ausschliesslich fuer idempotente Methoden (GET/HEAD). Nicht-idempotente
    Methoden und 4xx-Antworten werden unveraendert einmal durchgereicht.

    Latenz-Budget (bewusst klein gehalten): der Default read-timeout betraegt 5s
    je Versuch (infra/http.create_http_client); der Backoff ist 0.2s, dann 0.4s.
    Worst-Case bei einem durchgehend toten Upstream: ~ 3x5s Timeout + 0.6s Backoff
    ~ 15.6s, aber NUR fuer eine ohnehin sterbende Quelle, die anschliessend in den
    Circuit-Breaker/stale-on-error-Pfad faellt. Bei gesunden Requests entsteht
    KEINE Zusatzlatenz: ein erfolgreicher erster Versuch kehrt sofort zurueck; nur
    transiente Aussetzer werden geglaettet.

    Pool-Slot-Verhalten (Fix Vorfall 21.09.2026, VRR): verworfene
    Zwischenantworten werden VOR jedem Retry geschlossen (Slot geht an den
    httpcore-Pool zurueck); nur die letzte Antwort geht mit offenem Stream an
    den Aufrufer, der sie wie bisher liest bzw. schliesst.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Nicht-idempotente Methoden: kein Retry (POST/PUT/PATCH/DELETE einmalig).
        if request.method not in _RETRY_METHODS:
            return await super().handle_async_request(request)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(_MAX_ATTEMPTS),
            wait=wait_exponential(multiplier=0.2, max=0.4),
            retry=retry_if_exception_type((*_RETRY_EXCEPTIONS, _TransientStatusError)),
            reraise=True,
        ):
            with attempt:
                response = await super().handle_async_request(request)
                if response.status_code in _RETRY_STATUS:
                    if attempt.retry_state.attempt_number >= _MAX_ATTEMPTS:
                        # Letzter Versuch: die transiente Antwort ehrlich und mit
                        # OFFENEM Stream zurueckgeben, statt als RetryError zu
                        # eskalieren (der Aufrufer in resilience/client.py liest
                        # sie wie bisher fuer 503-Mapping/stale-on-error).
                        return response
                    # Zwischenantwort VOR dem Retry schliessen: httpcore gibt den
                    # Pool-Slot erst zurueck, wenn der Response-Stream gelesen
                    # oder geschlossen wurde. Ohne aclose leakt jede verworfene
                    # Zwischenantwort dauerhaft einen Slot des Host-Pools, bis
                    # ALLE Requests des Hosts in PoolTimeout enden, auch nach
                    # Erholung des Upstreams (Vorfall 21.09.2026, VRR: Pool nach
                    # ~10 GETs voll, 14 h Ausfall, manueller api-Neustart).
                    await response.aclose()
                    raise _TransientStatusError()
                return response
        # Unerreichbar (die Schleife kehrt via return zurueck oder reraist eine
        # transiente Transport-Ausnahme), aber Typechecker-freundlicher Fallback:
        raise RuntimeError("RetryTransport: unerreichbarer Pfad")  # pragma: no cover


#: Pool-Limits JE Upstream-Host (statt global): ein kranker Host kann höchstens
#: seinen eigenen Pool sättigen und hungert keine andere Quelle mehr aus.
#: 20 Verbindungen je Host und Worker (4 Uvicorn-Worker = max. 80 Sockets je
#: Host und Box) reichen für jede unserer Quellen bequem; der frühere globale
#: 100er-Pool war nie als Budget je Host gedacht.
#:
#: Keepalive AUS für ALLE Hosts (Vorfall 11.09.2026, vorher 30.08.2026): vom
#: Server geschlossene Keepalive-Verbindungen räumt der httpx-Pool nicht ab
#: (``keepalive_expiry`` hat das nachweislich NICHT verhindert); die Leichen
#: bleiben in CLOSE-WAIT liegen und sättigen den Host-Pool -> PoolTimeout für
#: die Quelle. Am 30.08. war das apis.deutschebahn.com (damals nur dort per
#: Override abgestellt), am 11.09. luftdaten.umweltbundesamt.de und
#: verkehr.autobahn.de plus Rest-Leichen auf praktisch jedem Host: das
#: Verhalten ist generisch, ein Override je auffälligem Host wäre Whack-a-mole.
#: Ohne Keepalive wird jede Verbindung nach dem Request geschlossen; der Preis
#: ist ein TLS-Handshake je Request, was für unsere Poll-Quellen verkraftbar ist.
_PER_HOST_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=0,
)

#: Host-spezifische Limit-Ausnahmen (aktuell leer: Keepalive ist seit dem
#: Vorfall 11.09.2026 für alle Hosts aus, der frühere DB-Override damit
#: gegenstandslos). Mechanik bleibt für künftige Sonderfälle bestehen.
_HOST_LIMITS_OVERRIDES: dict[str, httpx.Limits] = {}


def limits_for_host(host: str) -> httpx.Limits:
    """Liefert die Pool-Limits für einen Upstream-Host (Override oder Default)."""
    return _HOST_LIMITS_OVERRIDES.get(host, _PER_HOST_LIMITS)


class PerHostTransport(httpx.AsyncBaseTransport):
    """Routet jeden Request auf einen eigenen Kind-Transport je Upstream-Host.

    Jeder Kind-Transport ist ein ``RetryTransport`` (Retry-Verhalten unverändert)
    mit EIGENEN Pool-Limits. Kind-Transporte entstehen lazy beim ersten Request
    an einen Host und leben bis ``aclose`` (Lifespan-Shutdown des Clients).
    Die Erzeugung ist per Lock serialisiert, damit zwei parallele Erst-Requests
    an denselben Host nicht zwei Pools bauen (der zweite würde sonst leaken).
    """

    def __init__(self) -> None:
        self._transports: dict[str, RetryTransport] = {}
        self._lock = asyncio.Lock()

    async def _transport_for(self, host: str) -> RetryTransport:
        transport = self._transports.get(host)
        if transport is not None:
            return transport
        async with self._lock:
            transport = self._transports.get(host)
            if transport is None:
                transport = RetryTransport(limits=limits_for_host(host))
                self._transports[host] = transport
            return transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Schlüssel ist der reine Host; Ports trennt der Kind-Pool selbst nach
        # Origin (Schema, Host, Port), ein Transport je Host genügt also.
        transport = await self._transport_for(request.url.host or "")
        return await transport.handle_async_request(request)

    async def aclose(self) -> None:
        transports = list(self._transports.values())
        self._transports.clear()
        for transport in transports:
            await transport.aclose()


#: Descriptive User-Agent auf JEDEM Upstream-Request (RES-05, T-03-04). Die Version
#: stammt aus der einzigen Quelle ``infranode.__version__`` (kein hartkodierter
#: Versionsstring, der mit Releases driftet).
USER_AGENT = (
    f"InfraNodeAPI/{__version__} "
    "(+https://github.com/street1983nk/infranode-api; open data proxy)"
)

#: Prozessweiter Client-Singleton. ``create_http_client`` gibt für denselben
#: Prozess dieselbe Instanz zurück (RES-01); die Connection-Pools darunter
#: sind je Upstream-Host getrennt (PerHostTransport).
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
        # Routing-Transport mit Pool je Upstream-Host (Strukturfix 30.08.2026):
        # jeder Host bekommt lazy einen eigenen RetryTransport samt eigener
        # Limits (siehe _PER_HOST_LIMITS/_HOST_LIMITS_OVERRIDES). Die Pool-Limits
        # leben an den Kind-Transporten (bei explizitem transport= ignoriert der
        # Client sein eigenes limits=-Argument), Timeout/UA/follow_redirects
        # bleiben am Client.
        _client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},  # RES-05: UA auf JEDEM Request
            transport=PerHostTransport(),
            # Konservativer Default; per-Source per Request überschreibbar (T-03-03).
            timeout=httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=1.0),
            # KEINE automatischen Redirects (Audit MEDIUM-1, 2026-06-10): die
            # SSRF-Invariante der Adapter (hartkodierte Hosts/Allowlists) schützt
            # nur den ERSTEN Request; ein 30x eines (kompromittierten) Upstreams
            # würde sonst blind verfolgt, auch auf interne Ziele (Metadaten-IP,
            # redis). Ein legitimer Redirect schlägt jetzt als Fehler durch und
            # fällt in der Beta im Smoke/Monitoring auf; der betroffene Adapter
            # zieht dann gezielt auf die finale URL nach.
            follow_redirects=False,
        )
    return _client


def per_source_timeout(settings, *, source: str) -> httpx.Timeout:
    """Liefert den per-Source-Timeout, der den Client-Default je Request überschreibt.

    Der Pool bleibt EIN Singleton; nur der Timeout variiert je Quelle (eine
    träge Quelle wie Wikidata-SPARQL darf länger lesen als eine schnelle
    REST-Quelle, Pitfall 5).
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
