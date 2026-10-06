"""Tageszeit-abhängige Frische-Fenster (``fresh``) einzelner Quellen.

Ergänzt die statischen ``ttl``-Fenster aus ``source_specs.py``: dort steht je
Quelle EIN fresh-Wert für den ganzen Tag. Für Quellen, deren Nutzdaten sich
über den Tag sehr ungleich ändern, ist dieser eine Wert immer ein Kompromiss,
nachts zu kurz (unnötige Upstream-Last) und zur Änderungsspitze zu lang
(veraltete Werte). Ein Profil ersetzt für genau diese Quellen den fresh-Wert
durch ein Fenster je Tageszeit; das Stale-Fenster bleibt statisch.

``FRESH_PROFILES`` ist die Hook-Tabelle, die ``resilience/client.py`` liest.
Eine Quelle OHNE Eintrag verhält sich exakt wie bisher (statischer fresh-Wert
aus der Registry bzw. das Default-Fenster). Die Profile sind reine Funktionen
der Uhrzeit: kein Netz, kein Redis, keine Nebenwirkung, testbar mit gestellter
Uhr.

Aktuell trägt GENAU EINE Quelle ein Profil: ``tankerkoenig`` (Spritpreise,
MTS-K). Begründung siehe ``tankerkoenig_fresh_s``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

# Die Preisregeln des Kraftstoffpreisanpassungsgesetzes hängen an der deutschen
# Wanduhr, nicht an UTC: ein Profil in UTC wäre im Sommer eine Stunde falsch.
# tzdata ist als Live-Dependency gepinnt (siehe pyproject.toml), das
# Modul-Level-``ZoneInfo`` löst deshalb überall auf (Prod, Tests, Windows).
_BERLIN = ZoneInfo("Europe/Berlin")

# Die einzige Uhrzeit, zu der eine Preiserhöhung überhaupt beginnen darf, ist
# 12:00 Uhr (KPAnG). Gekappt wird zehn Minuten früher: das Bundeskartellamt
# beobachtet die Erhöhungen im Fenster 11:50 bis 12:10, die Mehrheit also erst
# nach 12:00, ein Teil aber schon davor.
_RAISE_HOUR = 11
_RAISE_MINUTE = 50
_RAISE_MINUTE_OF_DAY = _RAISE_HOUR * 60 + _RAISE_MINUTE

# Nachtfenster (22:00 bis 05:00): zwischen 22 und 5 Uhr ist die Preislage
# praktisch statisch. Steht als eigene Konstante, weil das Fenster über
# Mitternacht läuft und deshalb in zwei Profil-Einträgen vorkommt.
_NIGHT_FRESH_S = 14400.0

# Tagesprofil als (Startminute des Tages, fresh-Sekunden), lückenlos und
# aufsteigend ab Minute 0. Gelesen wird der letzte Eintrag, dessen Startminute
# nicht in der Zukunft liegt (siehe ``_window_fresh_s``).
#
#   22:00 bis 05:00   4 h    fast statische Nachtlage
#   05:00 bis 11:50  60 min  vormittags fallen Preise nur, nie steigend
#   11:50 bis 12:20   5 min  Erhöhungsfenster (Kartellamt: 11:50 bis 12:10)
#   12:20 bis 19:00  20 min  Hauptänderungslast, stufenweises Absinken
#   19:00 bis 22:00  45 min  Abendlage, nur noch wenige Schritte
_FUEL_DAY_PROFILE: tuple[tuple[int, float], ...] = (
    (0, _NIGHT_FRESH_S),  # 00:00 (zweite Hälfte des Nachtfensters)
    (5 * 60, 3600.0),  # 05:00
    (_RAISE_MINUTE_OF_DAY, 300.0),  # 11:50
    (12 * 60 + 20, 1200.0),  # 12:20
    (19 * 60, 2700.0),  # 19:00
    (22 * 60, _NIGHT_FRESH_S),  # 22:00 (erste Hälfte des Nachtfensters)
)

# Untergrenze der gekappten Frische. Direkt vor der 11:50-Grenze bleiben sonst
# Bruchteile einer Sekunde oder 0 übrig; 0 hieße "sofort stale" und würde für
# den Rest der Sekunde jeden Abruf in den Hintergrund-Refresh schicken.
_MIN_FRESH_S = 1.0


def _window_fresh_s(minute_of_day: int) -> float:
    """Frische-Fenster (Sekunden) für eine Minute des Tages (0 bis 1439).

    Nimmt den letzten Profil-Eintrag, dessen Startminute erreicht ist. Der
    erste Eintrag startet bei Minute 0, das Profil ist damit für jede gültige
    Minute definiert (kein Rückfall nötig).
    """
    fresh = _FUEL_DAY_PROFILE[0][1]
    for start, value in _FUEL_DAY_PROFILE:
        if minute_of_day < start:
            break
        fresh = value
    return fresh


def _seconds_to_next_raise(moment: datetime) -> float:
    """Echte Sekunden von ``moment`` bis zur nächsten 11:50-Grenze (Wanduhr).

    ``moment`` muss aware und bereits in ``Europe/Berlin`` sein. Die Addition
    von einem Tag läuft absichtlich auf der Wanduhr (aware ``datetime`` +
    ``timedelta``), damit die Grenze am Folgetag wieder 11:50 Ortszeit ist.

    Die Differenz wird dagegen ZWINGEND über UTC gebildet: subtrahiert man zwei
    aware ``datetime`` mit demselben ``tzinfo``-Objekt, ignoriert Python die
    Zeitzone und rechnet auf der Wanduhr (dokumentiertes Verhalten). Über eine
    Zeitumstellung hinweg wäre das Ergebnis dann um eine Stunde falsch, und
    zwar genau in der Nacht vor dem kritischen Mittag. Mit der Konvertierung
    sind es echte Sekunden, an einem Umstellungstag also 23 bzw. 25 Stunden je
    Tag; auch die doppelt vorhandene Stunde (``fold``) wird korrekt getrennt.
    11:50 selbst existiert an jedem Tag genau einmal (die Umstellung liegt um
    02:00 bzw. 03:00), die Grenze ist also immer eindeutig.
    """
    boundary = moment.replace(
        hour=_RAISE_HOUR, minute=_RAISE_MINUTE, second=0, microsecond=0
    )
    if moment >= boundary:
        boundary = boundary + timedelta(days=1)
    return (boundary.astimezone(UTC) - moment.astimezone(UTC)).total_seconds()


def tankerkoenig_fresh_s(now: datetime | None = None) -> float:
    """Frische-Fenster der Spritpreise nach dem Tagesprofil (Sekunden).

    Seit dem 2026-04-01 gilt das Kraftstoffpreisanpassungsgesetz (KPAnG):
    Preiserhöhungen sind nur EINMAL je Kalendertag zulässig, und zwar um 12:00
    Uhr (Europe/Berlin); Senkungen bleiben jederzeit möglich. Damit ist der
    Tagesverlauf der Daten bekannt, statt geraten: nachts steht die Preislage
    fast still, vormittags kann sie nur fallen, um die Mittagsgrenze springt
    sie, nachmittags sinkt sie stufenweise. Das Profil gibt jeder dieser Phasen
    ihr eigenes Fenster (siehe ``_FUEL_DAY_PROFILE``).

    Zusätzlich wird das Ergebnis IMMER auf die nächste 11:50-Grenze gekappt.
    Ohne diese Kappung würde ein Preis, der im 60-Minuten-Fenster um 11:00 Uhr
    geholt wurde, bis 12:00 als frisch gelten und damit über den Mittagssprung
    hinaus einen zu niedrigen Preis behaupten. Mit Kappung endet er um 11:50.

    Warum das überhaupt zählt: Tankerkönig erlaubt EINE Anfrage je Minute für
    alle Städte zusammen (Aggregat-Bremse in ``resilience/client.py``). Je
    länger ein einmal geholter Stand für seine Stadt gilt, desto seltener
    verliert ein wieder kalter Abruf gegen diese Bremse. Die Bremse selbst und
    die Warte-Logik bleiben davon unberührt; es gibt weiterhin keinen
    Timer-Abruf (ToS: nur auf Nutzeraktion). Seit dem 2026-09-15 wird eine
    Nutzeranfrage, die den Slot der Minute verloren hat, eingereiht und
    zeitversetzt nachgeholt (infra/demand_queue.py); an diesem Profil ändert
    das nichts.

    Args:
        now: Zeitpunkt, für den das Fenster gilt (aware; Default: jetzt in UTC).
            Wird nach ``Europe/Berlin`` konvertiert. Nur für Tests gedacht.

    Returns:
        Frische in Sekunden, mindestens ``_MIN_FRESH_S``.
    """
    moment = (now if now is not None else datetime.now(UTC)).astimezone(_BERLIN)
    window = _window_fresh_s(moment.hour * 60 + moment.minute)
    capped = min(window, _seconds_to_next_raise(moment))
    return max(_MIN_FRESH_S, capped)


# Hook-Tabelle: Quelle -> Profil-Funktion ohne Argumente. Quellen ohne Eintrag
# behalten ihren statischen fresh-Wert (fail-closed: ein Profil gilt nur da,
# wo es bewusst eingetragen ist).
FRESH_PROFILES: dict[str, Callable[[], float]] = {
    "tankerkoenig": tankerkoenig_fresh_s,
}
