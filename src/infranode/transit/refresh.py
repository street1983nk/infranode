"""Statik-GTFS-Refresh-Batch (TRANSIT-RT-08, RESEARCH Pattern 8).

Laedt das aktuelle statische DELFI/gtfs.de-GTFS herunter und ersetzt
``data/delfi/*.zip`` idempotent (OVERWRITE wie ``ingest/delfi.py``: GTFS ist ein
Voll-Snapshot, kein Event-Strom). Hintergrund: der gtfs.de-Basic-Statik-Feed ist
nur 7 Tage gueltig (RESEARCH Open Question 3); ohne regelmaessigen Refresh driften
die ``trip_id`` zwischen RT-Feed und veralteter Statik auseinander
(RESEARCH Pitfall 4) und die Aufloesung schlaegt fehl.

Kadenz-Empfehlung: WOECHENTLICH (an die 7-Tage-Basic-Gueltigkeit gekoppelt), nicht
monatlich. Der Batch laeuft ausschliesslich manuell bzw. per Timer
(``python -m infranode.transit.refresh <ziel.zip>``), NIE im Request-Pfad oder im
Lifespan. Die OS-Registrierung des Timers (OPS-05-Muster, systemd) erfolgt
ausserhalb dieser Phase.

Sicherheit:

- T-19-DLSSRF: die Download-URL (``GTFS_DE_STATIC_URL``) ist HARTKODIERT (gtfs.de-
  Statik-Host), wird NIE aus Config/User-Input/Funktionsargument zusammengesetzt;
  ``follow_redirects=False`` ist Pool-Default (``infra/http.py``).
- T-19-DLZIP: der Refresh entpackt nichts, nur Download + atomarer Rename. Die ZIP
  wird erst beim Resolver gestreamt (``transit/resolver.py``, stop_times nie
  vollstaendig im Speicher).
- Size-Cap (Memory-DoS): ein absurd grosser Body wird abgelehnt, bevor er auf die
  Disk geschrieben wird (analog ``adapters/gtfs_rt._MAX_FEED_BYTES``).
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from infranode.config import Settings
from infranode.infra.http import close_http_client, create_http_client

# gtfs.de-Statik-Download HARTKODIERT (T-19-DLSSRF, wie der RT-Feed-Host in
# adapters/gtfs_rt._GTFS_DE_FEED_URL): der Host wird NIE aus Config/User-Input/
# Argument zusammengesetzt.
# [OWNER-VERIFIZIEREN] Der reale gtfs.de-Statik-Download-Pfad ist im RESEARCH nicht
# verbatim verifiziert (nur der RT-Feed realtime-free.pb). Diese URL ist der
# bekannte gtfs.de-Statik-Bundle-Pfad und VOR dem echten Timer-Lauf gegen den
# Owner/das gtfs.de-Downloadportal zu bestaetigen; bleibt der Pfad falsch, schlaegt
# der Download (raise_for_status) hart fehl, statt still eine falsche ZIP zu setzen.
GTFS_DE_STATIC_URL = "https://download.gtfs.de/germany/free/latest.zip"

# Size-Cap (Memory-DoS): die statische Voll-ZIP ist mehrere hundert MB; 1 GiB laesst
# Puffer fuer Wachstum, lehnt aber einen absurd grossen/manipulierten Body ab.
_MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024  # 1 GiB


def _write_atomic(body: bytes, dest_path: str) -> None:
    """Schreibt ``body`` atomar nach ``dest_path`` (temp-Datei + ``os.replace``).

    Rein synchroner Disk-I/O-Schritt (im async-Pfad via ``asyncio.to_thread``
    aufgerufen, damit der Event-Loop nicht blockiert, ruff ASYNC240). temp-Datei
    IM Zielverzeichnis, damit der Rename atomar auf demselben Dateisystem liegt
    (cross-device-Rename waere nicht atomar). OVERWRITE: idempotent.
    """
    dest = Path(dest_path).resolve()
    dest_dir = dest.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(dest_dir), suffix=".zip.tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        os.replace(tmp_path, dest)  # atomarer OVERWRITE
    except BaseException:
        # bei jedem Fehler den temp-Rest entfernen (kein Muell im Zielverzeichnis)
        tmp_path.unlink(missing_ok=True)
        raise


async def refresh_static_gtfs(http, *, url: str, dest_path: str) -> None:
    """Laedt die Statik-GTFS-ZIP und ersetzt ``dest_path`` atomar (idempotent).

    Schreibt zunaechst in eine temp-Datei IM Zielverzeichnis und benennt sie dann
    via ``os.replace`` atomar auf ``dest_path`` um (kein Teil-Schreib-Risiko, kein
    Reader sieht je eine halbe ZIP). OVERWRITE: ein zweiter Lauf ueberschreibt die
    bestehende ZIP (GTFS ist ein Voll-Snapshot, idempotent wie ``ingest/delfi``).
    Der Refresh entpackt nichts (T-19-DLZIP). Die ``url`` MUSS der hartkodierte
    ``GTFS_DE_STATIC_URL`` sein (T-19-DLSSRF); der Parameter existiert nur fuer den
    Test, der Aufrufer reicht die Modul-Konstante durch.
    """
    resp = await http.get(url)
    resp.raise_for_status()
    body = resp.content
    if len(body) > _MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"Statik-GTFS-Body ueberschreitet _MAX_DOWNLOAD_BYTES "
            f"({_MAX_DOWNLOAD_BYTES})"
        )

    # Disk-I/O in einen Thread auslagern (Event-Loop bleibt frei, ruff ASYNC240).
    await asyncio.to_thread(_write_atomic, body, dest_path)


def main(argv: list[str] | None = None) -> None:
    """CLI-Entrypoint: ``python -m infranode.transit.refresh <ziel.zip>``.

    Ziel-Pfad aus ``argv[1]`` ODER ``Settings().gtfs_rt_static_path``; ist
    keiner gesetzt -> Hinweis auf stderr + ``sys.exit(2)`` (analog
    ``ingest/delfi.main``). Das DELFI-Zip (``delfi_gtfs_path``, Tier A) ist
    bewusst KEIN Fallback: dieser Refresh holt die gtfs.de-Statik (Tier B,
    numerische Feed-IDs) und darf den Tier-A-Lizenzraum nicht ueberschreiben.
    Sonst Download ueber einen eigenen kurzlebigen, gepoolten httpx-Client (im
    ``finally`` geschlossen) und Erfolg auf stdout. Laeuft NIE im Request-Pfad.
    """
    import asyncio

    argv = sys.argv if argv is None else argv
    settings = Settings()
    dest_path = argv[1] if len(argv) > 1 else settings.gtfs_rt_static_path
    if not dest_path:
        print(
            "Kein GTFS-ZIP-Zielpfad. Nutzung: python -m infranode.transit.refresh "
            "<ziel.zip> oder INFRANODE_GTFS_RT_STATIC_PATH setzen.",
            file=sys.stderr,
        )
        sys.exit(2)

    async def _run() -> None:
        http = create_http_client(settings)
        try:
            await refresh_static_gtfs(http, url=GTFS_DE_STATIC_URL, dest_path=dest_path)
        finally:
            await close_http_client(http)

    asyncio.run(_run())
    print(f"Statik-GTFS aktualisiert: {dest_path}")


if __name__ == "__main__":
    main(sys.argv)
