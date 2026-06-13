"""Transit-Auflösung und Positionsschätzung gegen statisches DELFI-GTFS.

Reine, testbare Bausteine der Phase 19 (kein Netz, keine Systemuhr, kein Redis):
- ``resolver``: on-demand Auflösungsindex trip_id/route_id/stop gegen das
  statische GTFS (memory-konstant gestreamt).
- ``interpolation``: lineare Positionsschätzung mit injizierter Zeit.

Das Caching (Redis) und das Polling erfolgen im Aufrufer (Plan 19-04), nicht in
diesen reinen Funktionen.
"""
