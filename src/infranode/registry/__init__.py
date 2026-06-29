"""Stadt-Register-Library: Großstädte + Lookup mit 404-Pfad (CORE-03/CORE-04).

Re-exportiert das ``CityRegistryEntry``-Modell und die ``CITY_REGISTRY``-
Konstante und stellt den ``get_city``-Lookup bereit. Ein unbekannter Slug wirft
``NotFoundError`` (aus der bestehenden Phase-1-Fehler-Infrastruktur), das der
zentrale Handler auf den einheitlichen 404-Envelope mit Hint mappt. Die
Schicht-Kopplung registry -> api/errors ist eine bewusste, dokumentierte
MVP-Entscheidung (02-RESEARCH Pattern 4 Variante a / Open Question 2).
"""

from __future__ import annotations

from infranode.api.errors import NotFoundError
from infranode.registry.catalog import CITY_DATA_CATALOG
from infranode.registry.cities import _BY_SLUG, CITY_REGISTRY
from infranode.registry.models import CityRegistryEntry

__all__ = [
    "CITY_REGISTRY",
    "CityRegistryEntry",
    "get_city",
    "list_cities",
]

# Bekannte per-Stadt Sub-Ressourcen (Datenart-Keys aus dem Katalog + die Meta-
# Discovery-Ressource "overview"). Dient dem DX-Hinweis: ruft jemand
# /cities/<datenart> statt /cities/<stadt>/<datenart> ab, ist der "Slug" in
# Wahrheit eine Datenart, keine Stadt -> gezielter Korrektur-Hinweis.
_CITY_SUBRESOURCES: frozenset[str] = frozenset(
    {dt.key for dt in CITY_DATA_CATALOG} | {"overview"}
)


def _unknown_city_hint(slug: str) -> str:
    """Baut den 404-Hint für einen unbekannten Stadt-Slug.

    Ist der Slug in Wahrheit eine Datenart (z.B. ``overview``, ``crime-stats``),
    hat der Aufrufer vermutlich den Stadt-Slug vergessen
    (``/cities/overview`` statt ``/cities/<stadt>/overview``); dann zusätzlich
    auf den per-Stadt-Pfad verweisen. Sonst der generische Städte-Listen-Hint.
    """
    base = "Nutze GET /api/v1/cities fuer alle unterstuetzten Staedte."
    key = slug.lower()
    if key in _CITY_SUBRESOURCES:
        return (
            f"'{slug}' ist eine Datenart, keine Stadt. Du hast vermutlich den "
            f"Stadt-Slug vergessen, z.B. GET /api/v1/cities/berlin/{key}. " + base
        )
    return base


def get_city(slug: str) -> CityRegistryEntry:
    """Liefert den Stadt-Eintrag zum Slug (case-insensitive) oder wirft 404."""
    entry = _BY_SLUG.get(slug.lower())
    if entry is None:
        raise NotFoundError(
            f"Unbekannte Stadt '{slug}'.",
            hint=_unknown_city_hint(slug),
        )
    return entry


def list_cities() -> tuple[CityRegistryEntry, ...]:
    """Gibt alle registrierten Städte zurück (28 Kern + >100k-EW-Expansion)."""
    return CITY_REGISTRY
