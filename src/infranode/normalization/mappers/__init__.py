"""Reine Quellen-Mapper der Normalisierungs-Library (CORE-02).

Jeder Mapper ist eine reine Funktion ``map_<source>(raw, *, retrieved_at)``
ohne I/O und ohne Zeit-Seiteneffekt; sie uebersetzt heterogene Quelldaten
verlustfrei in den kanonischen ``CanonicalRecord``. Dieses Paket re-exportiert
die oeffentlichen Mapper-Funktionen.
"""

from __future__ import annotations

from infranode.normalization.mappers.wikidata import map_wikidata_city

__all__ = ["map_wikidata_city"]
