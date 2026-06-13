"""GTFS-Entry-Streamer (cp1252, memory-konstant, DATA-05).

``stream_entry(zip_path, entry_name)`` öffnet AUSSCHLIESSLICH den benannten
Entry der GTFS-ZIP per Name (kein ``extractall``, kein ``raw.read()``) und gibt
die Zeilen zeilenweise als ``dict`` zurück (Iterator). ``stream_stops`` ist die
spezialisierte Bequemlichkeit für ``stops.txt`` und ruft intern
``stream_entry(zip_path, "stops.txt")``. Damit bleibt der Speicherbedarf
konstant, auch wenn die echte DELFI-ZIP entpackt 431 MB stops.txt und 2,8 GB
stop_times.txt enthält.

Memory-/Sicherheits-Vertrag (T-06-03/T-06-05/T-19-MEM/T-19-ZIP):
- NIE ``ZipFile.extractall`` (Zip-Slip-Schutz) und NIE ``raw.read()`` (OOM-Schutz).
- Auch ``stream_entry`` darf nur per Namen öffnen und zeilenweise streamen.
  ``stop_times.txt`` (mehrere GB) wird ausschließlich gestreamt und gefiltert,
  NIE komplett geladen (siehe ``transit/resolver.py``).
- Dekodierung mit ``encoding="cp1252", errors="replace"``: DELFI liefert
  Windows-1252-kodierte Feeds, in denen undefinierte Bytes (z.B. 0x8d) vorkommen
  können. ``errors="replace"`` verhindert einen ungefangenen
  ``UnicodeDecodeError`` und liefert stattdessen das Ersatzzeichen.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path


def stream_entry(zip_path: str | Path, entry_name: str) -> Iterator[dict[str, str]]:
    """Streamt die Zeilen eines beliebigen GTFS-Entries aus der ZIP (cp1252).

    Öffnet ausschließlich den Entry ``entry_name`` per Namen (``z.open``) und
    gibt jede CSV-Zeile als ``dict`` (Spaltenname -> Wert) zurück. Yield-basiert:
    es wird nie die ganze Datei in den Speicher gelesen.

    Sicherheits-/Memory-Vertrag (T-06-03/T-19-MEM/T-19-ZIP): NIE ``extractall``
    (Zip-Slip), NIE ``raw.read()`` (OOM). Auch für ``stop_times.txt`` (mehrere
    GB) gilt: nur zeilenweise streamen und im Aufrufer filtern, NIE komplett
    laden.
    """
    with zipfile.ZipFile(zip_path) as z:
        with z.open(entry_name) as raw:
            text = io.TextIOWrapper(
                raw, encoding="cp1252", errors="replace", newline=""
            )
            yield from csv.DictReader(text)


def stream_stops(zip_path: str | Path) -> Iterator[dict[str, str]]:
    """Streamt die Zeilen von ``stops.txt`` aus der GTFS-ZIP (cp1252).

    Spezialisierung von :func:`stream_entry` auf ``stops.txt`` (kein
    Verhaltensbruch zur bisherigen Implementierung).
    """
    yield from stream_entry(zip_path, "stops.txt")
