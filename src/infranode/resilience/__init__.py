"""Resilienz-Bausteine: gepoolter HTTP-Pool, Cache-Aside/SWR, Circuit-Breaker.

Dieses Paket buendelt die Resilienz-Schicht der Phase 3. ``types.py`` liefert
die reinen Vertraege (``SourceConfig``, ``CacheStatus``) ohne I/O, die die
Cache- und Fassaden-Plans (03-03/03-04) konsumieren.
"""

from __future__ import annotations
