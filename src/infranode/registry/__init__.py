"""Stadt-Register-Library: Grossstaedte + Lookup mit 404-Pfad (CORE-03/CORE-04).

Re-exportiert das ``CityRegistryEntry``-Modell und die ``CITY_REGISTRY``-
Konstante und stellt den ``get_city``-Lookup bereit. Ein unbekannter Slug wirft
``NotFoundError`` (aus der bestehenden Phase-1-Fehler-Infrastruktur), das der
zentrale Handler auf den einheitlichen 404-Envelope mit Hint mappt. Die
Schicht-Kopplung registry -> api/errors ist eine bewusste, dokumentierte
MVP-Entscheidung (02-RESEARCH Pattern 4 Variante a / Open Question 2).
"""

from __future__ import annotations

from infranode.api.errors import NotFoundError
from infranode.registry.cities import _BY_SLUG, CITY_REGISTRY
from infranode.registry.models import CityRegistryEntry

__all__ = [
    "CITY_REGISTRY",
    "CityRegistryEntry",
    "get_city",
    "list_cities",
]


def get_city(slug: str) -> CityRegistryEntry:
    """Liefert den Stadt-Eintrag zum Slug (case-insensitive) oder wirft 404."""
    entry = _BY_SLUG.get(slug.lower())
    if entry is None:
        raise NotFoundError(
            f"Unbekannte Stadt '{slug}'.",
            hint="Nutze GET /api/v1/cities fuer alle unterstuetzten Staedte.",
        )
    return entry


def list_cities() -> tuple[CityRegistryEntry, ...]:
    """Gibt alle registrierten Staedte zurueck (28 Kern + >100k-EW-Expansion)."""
    return CITY_REGISTRY
