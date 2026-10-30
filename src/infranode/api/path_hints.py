"""Agentenfreundliche 404-Hints fuer unbekannte Pfade unter /api/v1/ (DX-404-HINT).

Ein Maschinen-Client ohne unsere Prompt-Regeln, der einen falschen Pfad rief
(z.B. GET /api/v1/fuel statt .../fuel-prices), soll ohne externe Doku zurueck auf
einen gueltigen Pfad finden, analog zum Stadt-Slug-Resolver-Hint. Dieses Modul
baut dazu einen reinen, testbaren Hint aus (a) der festen Pfadstruktur und (b)
einem difflib-basierten "Meintest du"-Vorschlag gegen die bekannten Datenart-Keys
und Top-Level-Routen.

Sicherheit (Zero-Trust-Input, REST-Regel 5): das rohe Pfadsegment wird VOR jeder
Verwendung auf ``[a-z0-9-]`` normalisiert und auf ``_MAX_SEG_LEN`` gekappt
(T-404-01 Reflexion / T-404-02 DoS). Der Rueckgabe-String enthaelt NIE das rohe
Segment, nur feste Prosa + Werte aus der eigenen Kandidatenmenge.

Importzyklen-frei: auf Modulebene NUR stdlib (``difflib``, ``functools``, ``re``);
``CITY_DATA_CATALOG`` wird ausschliesslich LAZY innerhalb einer gecachten Funktion
importiert (registry -> api/errors -> path_hints wuerde sonst zyklisch werden).
"""

from __future__ import annotations

import difflib
import functools
import re

API_V1_PREFIX = "/api/v1"

# Laengen-Cap gegen pathologische difflib-Eingaben (T-404-02 DoS-Mitigation).
_MAX_SEG_LEN = 64

# Bereinigung auf [a-z0-9-] (T-404-01: kein roher Input im Ergebnis).
_SEG_RE = re.compile(r"[^a-z0-9-]")

# Top-Level-Routen (erstes Segment nach /api/v1/), damit z.B. citis -> cities.
_TOP_LEVEL_ROUTES: frozenset[str] = frozenset(
    {"cities", "sources", "compare", "tenders", "health", "stations", "live"}
)

# Fester Struktur-Hinweis (deutsche Prosa, echte Umlaute). {slug}/{resource} sind
# LITERALE Platzhalter -> bewusst KEIN f-String an dieser Stelle.
_STRUCTURE_HINT = (
    "Datenarten liegen unter /api/v1/cities/{slug}/{resource}, die Städte-Liste "
    "unter /api/v1/cities, der Katalog je Stadt unter /api/v1/cities/{slug}/overview."
)


def path_is_under_api_v1(path: str) -> bool:
    """True, wenn ``path`` gleich ``/api/v1`` ist oder mit ``/api/v1/`` beginnt.

    Ein blosser Praefix-Bluff (``/api/v1foo``) zaehlt NICHT als unter /api/v1/.
    """
    return path == API_V1_PREFIX or path.startswith(API_V1_PREFIX + "/")


def _normalize_segment(seg: str) -> str:
    """Bereinigt ein rohes Pfadsegment auf ``[a-z0-9-]`` und kappt auf _MAX_SEG_LEN.

    Zero-Trust-Input (REST-Regel 5): wird VOR jedem difflib-Aufruf angewandt, damit
    weder roher Input reflektiert wird (T-404-01) noch eine absurd lange Eingabe den
    Fuzzy-Match belastet (T-404-02).
    """
    return _SEG_RE.sub("", seg.lower())[:_MAX_SEG_LEN]


@functools.lru_cache(maxsize=1)
def _candidates() -> tuple[str, ...]:
    """Gecachte, sortierte Kandidatenmenge fuer den did-you-mean-Vergleich.

    LAZY-Import von ``CITY_DATA_CATALOG`` (Zyklus-Vermeidung, siehe Modul-Docstring):
    alle Datenart-Keys + die Meta-Ressourcen ``overview``/``base`` + die
    Top-Level-Routen.
    """
    from infranode.registry.catalog import CITY_DATA_CATALOG

    keys = {dt.key for dt in CITY_DATA_CATALOG} | {"overview", "base"}
    return tuple(sorted(keys | _TOP_LEVEL_ROUTES))


def _did_you_mean(segment: str) -> str | None:
    """Bester Fuzzy-Treffer aus der Kandidatenmenge oder None.

    Cutoff bewusst 0.5 (nicht 0.7 wie beim Stadt-Resolver): Datenart-Keys aehneln
    ihrem gaengigen Falschnamen weniger als Stadtnamen-Tippfehler. ``fuel`` vs.
    ``fuel-prices`` ergibt in difflib nur ~0.53, soll aber vorgeschlagen werden,
    waehrend ein voellig unbekanntes Segment keinen Treffer liefern darf. Der
    Rueckgabewert ist immer ein Wert aus der eigenen Kandidatenmenge, nie roher
    Input.
    """
    norm = _normalize_segment(segment)
    if not norm:
        return None
    match = difflib.get_close_matches(norm, _candidates(), n=1, cutoff=0.5)
    return match[0] if match else None


def _city_slug_for(segment: str) -> str | None:
    """Kanonischer Stadt-Slug, wenn ``segment`` DETERMINISTISCH eine Stadt ist.

    LAZY-Import aus demselben Grund wie ``_candidates`` (Zyklus, siehe
    Modul-Docstring). Bewusst der Nicht-Fuzzy-Resolver: nur ein echter Treffer
    darf den Stadt-Hinweis ausloesen, damit eine Datenart, die zufaellig einem
    Stadtnamen aehnelt, weiterhin den Datenart-Vorschlag bekommt. Rueckgabe ist
    immer ein Wert aus der Registry, nie roher Input (T-404-01).
    """
    from infranode.registry import resolve_city_slug

    norm = _normalize_segment(segment)
    return resolve_city_slug(norm) if norm else None


def build_unknown_path_hint(path: str) -> str:
    """Baut den agentenfreundlichen 404-Hint fuer einen unbekannten /api/v1-Pfad.

    Nennt immer die Pfadstruktur. Ist das letzte Pfadsegment in Wahrheit eine
    bekannte STADT (``/api/v1/recklinghausen`` statt
    ``/api/v1/cities/recklinghausen``), nennt der Hint zuerst den korrekten Pfad:
    hier ist der Weg zum Ziel bekannt, ein Fuzzy-Vorschlag gegen die
    Datenart-Keys waere dann bestenfalls Rauschen. Sonst wie gehabt ein
    "Meintest du '<kandidat>'? " bei genuegender Aehnlichkeit (Wortlaut analog
    registry._unknown_city_hint). Der Ergebnis-String enthaelt NIE das rohe
    Segment.
    """
    segment = path.rstrip("/").rsplit("/", 1)[-1]
    if not segment:
        return _STRUCTURE_HINT

    city = _city_slug_for(segment)
    if city is not None:
        return (
            f"'{city}' ist eine Stadt: nutze GET /api/v1/cities/{city} fuer die "
            f"Stammdaten bzw. GET /api/v1/cities/{city}/overview fuer den "
            "Katalog aller Datenarten dieser Stadt. " + _STRUCTURE_HINT
        )

    suggestion = _did_you_mean(segment)
    if suggestion is not None:
        return f"Meintest du '{suggestion}'? " + _STRUCTURE_HINT
    return _STRUCTURE_HINT
