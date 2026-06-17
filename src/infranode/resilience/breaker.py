"""Eigenbau per-Source Circuit-Breaker (RES-04, CLOSED/OPEN/HALF_OPEN).

Warum Eigenbau (Orchestrator-Entscheidung 1, RESEARCH Pattern 3 Option B):
``pybreaker`` ist nicht asyncio-nativ und ``purgatory`` waere eine zusaetzliche
Runtime-Dependency. Die Zustandslogik eines Circuit-Breakers ist klein (~60 LOC)
und rein synchron (Zaehl-/Zeitlogik, kein I/O), daher fuehren wir keine neue
Abhaengigkeit ein. Der State lebt in-process pro Uvicorn-Worker (MVP: single
worker akzeptabel, T-03-13 accept; Upgrade-Pfad Redis-backed bei multi-worker).

Der Breaker isoliert pro Quelle (``BreakerRegistry`` haelt je ``source_name``
einen eigenen ``CircuitBreaker``): eine tote Quelle trippt nur ihren eigenen
Breaker und laesst andere Quellen unberuehrt (RES-04, T-03-10). Bei OPEN
liefert der Breaker fail-fast (kein Hammering auf eine kranke Quelle, T-03-11),
bis nach ``cooldown`` ein einzelner HALF_OPEN-Probe-Call zugelassen wird:
Erfolg -> CLOSED (failure_count 0), Fehler -> wieder OPEN.

Reine Zustandslogik, unit-testbar ohne Netz (gleiche Trennung wie
registry/models.py). ``BreakerOpen`` ist eine leichte Signal-Exception, die in
client.py auf ``UpstreamError`` (503) gemappt wird und selbst KEINEN HTTP-Status
traegt.
"""

from __future__ import annotations

import enum
import time
from collections.abc import Callable


class BreakerOpen(Exception):
    """Signal: der Breaker dieser Quelle ist offen (fail-fast, kein Upstream-Call).

    Leichtgewichtig und HTTP-agnostisch; client.py mappt sie auf
    ``UpstreamError`` (503), damit der zentrale Handler die Envelope baut.
    """


class BreakerState(enum.StrEnum):
    """Die drei Breaker-Zustaende (als String direkt log-/header-tauglich)."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """In-process Circuit-Breaker einer EINZELNEN Quelle (CLOSED/OPEN/HALF_OPEN).

    Args:
        failure_threshold: Anzahl aufeinanderfolgender Fehler bis OPEN.
        cooldown: Sekunden, die OPEN gehalten wird, bevor ein HALF_OPEN-Probe
            zugelassen wird.
        now: injizierbare Uhr (``Callable[[], float]``, Default ``time.monotonic``)
            -> deterministische Tests ohne ``sleep``.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown: float = 30.0,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._now = now
        self.failure_count = 0
        self.state: BreakerState = BreakerState.CLOSED
        self.opened_at: float | None = None

    def is_open(self) -> bool:
        """True, solange der Breaker effektiv offen ist (vor Ablauf des Cooldown).

        Nach Ablauf des Cooldown ist der Breaker bereit fuer einen HALF_OPEN-Probe
        und gilt nicht mehr als (blockierend) offen.
        """
        if self.state is not BreakerState.OPEN:
            return False
        return not self._cooldown_elapsed()

    def _cooldown_elapsed(self) -> bool:
        """True, wenn seit dem Oeffnen mindestens ``cooldown`` vergangen ist."""
        if self.opened_at is None:
            return True
        return (self._now() - self.opened_at) >= self.cooldown

    def allow_request(self) -> bool:
        """Darf ein Call durch? CLOSED ja; OPEN nur nach Cooldown (HALF_OPEN-Probe).

        Bei abgelaufenem Cooldown wechselt der Breaker auf HALF_OPEN und laesst
        GENAU diesen Probe-Call durch. Vor Ablauf bleibt OPEN -> fail-fast.
        """
        if self.state is BreakerState.CLOSED:
            return True
        if self.state is BreakerState.HALF_OPEN:
            return True
        # OPEN: nur nach Cooldown einen einzelnen Probe-Call zulassen.
        if self._cooldown_elapsed():
            self.state = BreakerState.HALF_OPEN
            return True
        return False

    def record_success(self) -> None:
        """Erfolgreicher Call -> Breaker schliessen, Fehlerzaehler zuruecksetzen."""
        self.failure_count = 0
        self.state = BreakerState.CLOSED
        self.opened_at = None

    def record_failure(self) -> None:
        """Fehlgeschlagener Call -> Zaehler hoch; bei Schwelle (oder HALF_OPEN) OPEN."""
        # Ein Fehler waehrend des HALF_OPEN-Probes oeffnet sofort wieder.
        if self.state is BreakerState.HALF_OPEN:
            self._open()
            return
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        """Versetzt den Breaker in OPEN und merkt den Oeffnungszeitpunkt."""
        self.state = BreakerState.OPEN
        self.opened_at = self._now()


class BreakerRegistry:
    """Prozessweites Register {source_name -> CircuitBreaker} (per-Source-Isolation).

    Jede Quelle bekommt einen eigenen ``CircuitBreaker`` mit identischer
    Konfiguration. Ein offener Breaker einer Quelle laesst andere Quellen
    unberuehrt (RES-04, T-03-10). Der State lebt request-uebergreifend, solange
    die Registry am ``app.state`` gehalten wird.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown: float = 30.0,
        *,
        now: Callable[[], float] = time.monotonic,
        cooldowns: dict[str, float] | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._now = now
        # Per-Source-Cooldown-Override (2026-06-14): fragile/langsam erholende
        # Quellen (z.B. zeitweise gestoerte Behoerden-APIs) bekommen einen langen
        # Cooldown, damit der OPEN-Breaker den kranken Upstream selten probt (wenig
        # Fehler-Laerm), sich aber dennoch SELBST wieder schliesst, sobald der
        # Upstream zurueck ist. So heilen solche Quellen automatisch, ohne dass man
        # sie manuell per enable_*-Toggle abschalten muss. Fehlt ein Eintrag, gilt
        # der globale Default-Cooldown.
        self._cooldowns = cooldowns or {}
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, source: str) -> CircuitBreaker:
        """Liefert den Breaker der Quelle (legt ihn beim ersten Zugriff an).

        Der Cooldown ist per Quelle ueberschreibbar (``cooldowns``-Map); ohne
        Eintrag greift der globale Default.
        """
        breaker = self._breakers.get(source)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self.failure_threshold,
                cooldown=self._cooldowns.get(source, self.cooldown),
                now=self._now,
            )
            self._breakers[source] = breaker
        return breaker
