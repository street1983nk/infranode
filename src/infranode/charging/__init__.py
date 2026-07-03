"""Live-Ladesäulen-Belegung je Stadt (eRound AFIR, DATA-42).

Drei Bausteine nach dem Muster von ``transit/`` (Poller schreibt Redis, der
Request-Pfad liest NUR Redis, T-19-REQPARSE analog):

- ``geomap``: reine Geo-Map-Logik (stat-Vollbestand -> refill_point_id ->
  Stadt-Slug + Koordinaten) plus der gecachte Datei-Loader für den Request-Pfad.
- ``store``: Redis-Store der akkumulierten Belegungs-Deltas (TTL = Staleness).
- ``poller``: langlebiger asyncio-Task, der das dynamische eRound-Abo je Kadenz
  pullt und die Deltas akkumuliert (der Feed ist eine Drain-Queue: jeder Pull
  liefert nur die Änderungen seit dem letzten Pull, NIE den Vollzustand).
"""
