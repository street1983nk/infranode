"""Deklarative Quellen-Registry: EINE Stelle pro Upstream-Quelle.

Single source of truth für die rein-datenhaften Quellen-Attribute, die
früher auf vier Strukturen verteilt waren:
  * KNOWN_SOURCES        (vorher api/v1/sources.py:_KNOWN_SOURCES)
  * SOURCE_LICENSE       (vorher api/v1/sources.py:SOURCE_LICENSE)
  * SOURCE_TTL           (vorher resilience/client.py:_SOURCE_TTL)
  * FRAGILE_SOURCE_COOLDOWN (vorher resilience/breaker_redis.py)

Eine neue Quelle hinzufügen = EIN SourceSpec-Eintrag hier (plus weiterhin:
der enable_<name>-Toggle in config.py, der SourceId-Wert in enums.py, der
Adapter/Mapper-Code und die wortgenaue Zeile in DATA-LICENSES.md). Die
Lizenz-Wortlaute bleiben fail-closed gegen DATA-LICENSES.md geprüft
(tests/unit/test_source_license_map.py); die Reihenfolge hier IST die
öffentliche Reihenfolge der /sources-Route.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    """Eine Upstream-Quelle, deklarativ.

    Args:
        name: Quellen-Schlüssel; MUSS exakt zum enable_<name>-Toggle
            (config.py) und zum SourceId-Wert (enums.py) passen.
        license_id: Lizenz-Kürzel (siehe LicenseId/DATA-LICENSES.md).
        attribution: wortgenaue Attribution VERBATIM aus DATA-LICENSES.md.
        ttl: (fresh_s, stale_s) Cache-Fenster; None = Default (60s/120s).
        cooldown: HALF_OPEN-Probe-Intervall (s) für fragile Upstreams;
            None = 30s-Default des Breakers.
        emergency_keep_s: Notreserve HINTER dem Stale-Fenster (Sekunden), nur
            per Opt-in. Der Redis-Key lebt um diesen Zuschlag laenger als
            stale_until, damit der Stale-on-error-Fallback nach einer Luecke
            (Deploy, stille Stadt) noch eine letzte echte Antwort findet statt
            503 (Vorfall 2026-09-07 abends: Key-TTL == Stale-Ende, also
            has_stale=false, sobald das Fenster ablaeuft, und ein kalter Key
            verliert gegen die Aggregat-Bremse). Ausgeliefert wird die Reserve
            AUSSCHLIESSLICH im Fehlerpfad (Bremse/5xx/Timeout), nie als
            regulaerer HIT/STALE; cache_status STALE-ON-ERROR und retrieved_at
            sagen es ehrlich. 0.0 = bisheriges Verhalten (Key stirbt mit dem
            Stale-Ende); NIE fuer Live-/Transit-Quellen oder Tier-C-Live-only
            setzen (deren Vorhalte-Grenzen gelten unveraendert).
    """

    name: str
    license_id: str
    attribution: str
    ttl: tuple[float, float] | None = None
    cooldown: float | None = None
    emergency_keep_s: float = 0.0


# Quick-260709-huj: Stale-Notfenster für statische/langsam-veränderliche Quellen.
# Die Frische bleibt bei 60s (unverändert = bisheriger Default-Fresh); NUR das
# Stale-on-error-Fenster wächst auf 24h. So wird ein längerer Upstream-Ausfall
# ehrlich mit dem letzten bekannten Stand bedient (stale-on-error) statt mit 503.
# Gilt AUSSCHLIESSLICH für Register-/Statistik-/Stammdaten, die sich höchstens
# täglich (meist jährlich) ändern; NIE für Live-/Transit-/Verkehr-/Parken-Quellen
# (fail-closed: die erben diese 24h-Reserve nicht, siehe die beiden moderaten
# Mobilithek-Fenster darunter).
_STATIC_STALE_24H: tuple[float, float] = (60.0, 86400.0)


# Vorfall 2026-07-26 (04:19 bis 04:57 UTC, 79 x 503 in einer Stunde bei
# Warnschwelle 25): die Mobilithek-Pulls (mobilithek.info:8443, mTLS) hängen
# sporadisch bis in den 10s-Read-Timeout, statt ein Datenpaket oder den
# dokumentierten 422 (kein Paket anstehend) zu liefern. Mit dem kurzen
# Default-Fenster (60s/120s) war der letzte bekannte Stand nach zwei Minuten aus
# Redis verschwunden, also blieb nur der ehrliche 503. Dieselbe Ursachenkette wie
# bei dwd (2h zu kurz -> 6h) und uba (-> 24h).
#
# Die Frische bleibt hier bei 60s, die Zusage "minutenfrisch" wird nicht
# angetastet; NUR das Stale-on-error-Notfenster wächst. Zwei Stufen, weil der
# Informationswert unterschiedlich schnell verfällt:
#   Fluss/Zählung (Verkehrsfluss, Zählstellen, Ladepunkte) -> 30 Min
#   Meldungen/Zonen (Baustellen, Ereignisse, Umweltzone, Verkehrsmeldungen) -> 6h
# NICHT die 24h-Reserve der Stammdaten: einen Tag alter Verkehrsfluss wäre
# inhaltlich wertlos (gleiche Abwägung wie bei dwd). Stale-Antworten sind für
# Clients erkennbar, meta.cache_status trägt dann stale_on_error.
#
# Die Mobilithek-PARKEN-Quellen bekommen stattdessen das Fenster, das die
# übrigen Parken-Quellen (dresden, hamburg, pr_hessen, db_bahnpark,
# kaiserslautern) längst tragen: ttl=(300.0, 3600.0) inline, siehe dort. Das ist
# hier doppelt richtig: gleiche Datenart, gleiches Fenster, und die 5-Minuten-
# Frische senkt zusätzlich die Zahl der Pulls gegen genau den Upstream, der auf
# häufige Pulls mit Hängern reagiert.
#
# Weiter fail-closed und bewusst NICHT verlängert: transit_rt_delfi (veraltete
# Abfahrtszeiten sind irreführend) und tankerkoenig (ToS, eigener Test).
#
# NACHZUG 2026-07-27 (Vorfall 26.07. 22:02-22:05, 6 x 503 auf
# /cities/hamburg/road-events): dieselbe Kette bei einer Quelle, die am 26.07.
# nicht in der Liste stand. hamburg_roadworks lief noch auf dem Default,
# fünfmal ReadTimeout, dann BreakerOpen, jedes Mal has_stale=false. Der Sweep
# über die Registry fand dieselbe Lücke bei allen übrigen Baustellen-,
# Verkehrsmeldungs- und Sperrungs-Quellen: bremen_roadworks und
# koeln_roadworks_live trugen das 6h-Fenster längst, ihre Geschwister nicht.
# Gleiche Datenart, gleiches Fenster; die Namen sind deshalb nicht mehr an
# "Mobilithek" gebunden, der Wert ist unverändert.
#
# Nach diesem Nachzug tragen ALLE Quellen ein bewusstes Fenster. Die neun ohne
# ttl sind eine ENTSCHEIDUNG, kein Rest, und
# test_sources_without_ttl_are_the_documented_fail_closed_set haelt sie fest:
#   Echtzeit-Abfahrten (db_timetables, delfi, gtfs_rt, hvv, hvv_geofox, vgn):
#     eine veraltete Abfahrtszeit schickt jemanden zum Bahnsteig, dessen Zug
#     laengst weg ist. Ein ehrlicher 503 ist hier besser als ein alter Wert,
#     gleiche Abwaegung wie bei transit_rt_delfi.
#   gbfs (Sharing) und koeln_wait_times: dito, eine alte Fahrzeug- oder
#     Wartezeit-Angabe kostet den Nutzer einen vergeblichen Weg.
_TRAFFIC_FLOW_STALE: tuple[float, float] = (60.0, 1800.0)
_TRAFFIC_MESSAGE_STALE: tuple[float, float] = (60.0, 21600.0)


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    # Stammdaten (CC0), ändern sich sehr selten -> 24h-Stale-Reserve nur für
    # Upstream-Ausfälle, Frische unverändert 60s.
    SourceSpec(
        name="wikidata",
        license_id="cc0",
        attribution="Wikidata",
        ttl=_STATIC_STALE_24H,
    ),
    # Fresh bleibt 10 Min; Stale-Notfenster 2h -> 6h: Brightsky lieferte am
    # 2026-07-13 für einzelne Regionen 404 ("no current weather"), Keys älter
    # als 2h waren aus Redis evakuiert -> 503 statt stale-on-error. 6h deckt
    # solche Teilausfälle, älteres Wetter wäre inhaltlich wertlos.
    SourceSpec(
        name="dwd",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
        ttl=(600.0, 21600.0),
    ),
    # overpass ist der EINE Registry-Eintrag fuer ALLE OSM-Datenarten (POIs wie
    # post-offices/parcel-lockers/recycling-centres sowie alle OSM-Features). Er
    # traegt die Quellen-Identitaet: Lizenz (ODbL) + Attribution fuer /sources,
    # Coverage, Health-Matrix und den enable_overpass-Toggle.
    # HINWEIS (Overpass-Abloesung 2026-07-19): die Routen lesen POIs read-only aus
    # dem osm_pois-Store (Precompute via ingest.osm_pois), es gibt KEIN
    # client.fetch("overpass", ...) mehr. Das ttl-Feld (Fresh/Stale) und die
    # overpass-Eintraege in resilience/client.py (Jitter/Concurrency/Cooldown) sind
    # damit RUHEND (kein Live-Fetch exerziert sie mehr); sie bleiben nur bis zum
    # geplanten Cleanup stehen und beeinflussen den Request-Pfad nicht.
    SourceSpec(
        name="overpass",
        license_id="odbl",
        attribution="© OpenStreetMap contributors",
        ttl=(604800.0, 2592000.0),
    ),
    # Baustellen/Sperrungen ändern sich im Stunden-, nicht Sekundentakt: Fresh
    # 3 Min spart >90 % der Upstream-Calls, Stale-Notreserve 6h bedient einen
    # BASt-Ausfall stale-on-error statt 503 (TTL-Tuning quick-260717-ttl).
    SourceSpec(
        name="autobahn",
        license_id="dl_de_by_2_0",
        attribution="Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
        ttl=(180.0, 21600.0),
    ),
    SourceSpec(
        name="hvv",
        license_id="dl_de_by_2_0",
        attribution="Hamburger Verkehrsverbund GmbH (HVV)",
    ),
    SourceSpec(
        name="delfi",
        license_id="cc_by_4_0",
        attribution="Datenquelle: DELFI e.V. / Mobilitätsdaten Deutschland, CC-BY 4.0",
    ),
    # Registerdaten der Bundesnetzagentur, langsam-veränderlich -> 24h-Stale-Reserve.
    SourceSpec(
        name="bnetza",
        license_id="cc_by_4_0",
        attribution="Bundesnetzagentur.de",
        ttl=_STATIC_STALE_24H,
    ),
    # UBA-Messwerte sind stündlich -> Fresh 30 Min statt 60s-Default; das
    # Stale-Notfenster wächst auf 24h (Vorfall 2026-07-13: air-uba-Keys ohne
    # Reserve lieferten 503). NICHT länger: tagealte Luftwerte sind sinnlos.
    SourceSpec(
        name="uba",
        license_id="dl_de_by_2_0",
        attribution="Umweltbundesamt (UBA)",
        ttl=(1800.0, 86400.0),
        cooldown=900.0,
    ),
    SourceSpec(
        name="pegelonline",
        license_id="dl_de_zero_2_0",
        attribution=(
            "PEGELONLINE, Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV)"
        ),
        ttl=(300.0, 7200.0),
        cooldown=600.0,
    ),
    # Hochwasserportal aktualisiert im ~15-Min-Takt: Fresh/Stale analog
    # pegelonline (5 Min / 2h), statt 120s-Default-Stale -> kein 503 bei kurzen
    # Upstream-Ausfällen (TTL-Tuning quick-260717-ttl).
    SourceSpec(
        name="lhp",
        license_id="cc_by_4_0",
        attribution="Datenquelle: www.hochwasserzentralen.de, Stand: <Zeitstempel>",
        ttl=(300.0, 7200.0),
    ),
    # DWD publiziert die Pollenvorhersage 1x täglich (~11 Uhr): Fresh 1h nimmt
    # die Tagesausgabe zeitnah mit, Stale 24h überbrückt DWD-Ausfälle; das
    # 120s-Default-Stale verwarf ein Tagesprodukt nach 2 Minuten
    # (TTL-Tuning quick-260717-ttl).
    SourceSpec(
        name="dwd_pollen",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
        ttl=(3600.0, 86400.0),
    ),
    SourceSpec(
        name="dwd_fire",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
        # ArcGIS-Re-Host kann zeitweise traege/aus sein -> grosszuegigeres
        # Cache-Fenster (taegliche Daten) + eigener HALF_OPEN-Cooldown.
        ttl=(3600.0, 86400.0),
        cooldown=900.0,
    ),
    SourceSpec(
        name="eea_bathing",
        license_id="cc_by_4_0",
        attribution=(
            "European Environment Agency (EEA), Bathing Water Directive 2006/7/EC"
        ),
        # Jahres-Saisonbewertung (quasi-statisch) -> langes Cache-Fenster.
        ttl=(86400.0, 2592000.0),
        cooldown=900.0,
    ),
    SourceSpec(
        name="klinik_atlas",
        # FAIL-CLOSED: Bundes-Klinik-Atlas weist keine explizite offene Lizenz aus
        # -> UNKNOWN/Tier C, Quelle per Default deaktiviert (s. config), bis BMG/IQTIG
        # die Lizenz bestaetigt.
        license_id="unknown",
        attribution="Bundes-Klinik-Atlas (BMG/IQTIG)",
        ttl=(86400.0, 604800.0),
    ),
    SourceSpec(
        name="db_fasta",
        license_id="cc_by_4_0",
        attribution="Deutsche Bahn / DB InfraGO AG",
        # Echtzeit-Status -> kurzes Cache-Fenster.
        ttl=(300.0, 3600.0),
        cooldown=600.0,
    ),
    SourceSpec(
        name="genesis",
        license_id="dl_de_by_2_0",
        # H15 (Owner 2026-06-29): vereinheitlicht mit der regionalstatistik-Quelle
        # (gleicher Host www.regionalstatistik.de -> "Statistische Ämter des
        # Bundes und der Länder"). zensus bleibt separat (eigene ZENSUS-Quelle).
        attribution="Statistische Ämter des Bundes und der Länder",
        ttl=(86400.0, 2592000.0),
    ),
    # Zensus (statisch, mehrjähriger Erhebungszyklus) -> 24h-Stale-Reserve.
    SourceSpec(
        name="zensus",
        license_id="dl_de_by_2_0",
        attribution="Statistisches Bundesamt (Destatis) / Regionalstatistik",
        ttl=_STATIC_STALE_24H,
    ),
    # Marktstammdatenregister (Registerdaten, langsam-veränderlich) -> 24h-Stale.
    SourceSpec(
        name="mastr",
        license_id="dl_de_by_2_0",
        attribution="Bundesnetzagentur - Marktstammdatenregister",
        ttl=_STATIC_STALE_24H,
    ),
    # SMARD liefert 15-Min-Slots: Fresh 5 Min, Stale 1h; ältere Strom-Lastdaten
    # wären irreführend, deshalb bewusst kurze Reserve (TTL-Tuning
    # quick-260717-ttl).
    SourceSpec(
        name="smard",
        license_id="cc_by_4_0",
        attribution="Bundesnetzagentur | SMARD.de",
        ttl=(300.0, 3600.0),
    ),
    # Fresh bleibt beim 60s-Default (Warnungen = Live-Charakter); Stale-
    # Notreserve 6h, damit ein Brightsky-Ausfall stale-on-error bedient wird
    # statt sofort 503 (Quelle-abgeschaltet-Vorfall 2026-07-16: die alte
    # DWD-WarnApp-JSON verschwand global, der Endpunkt fiel hart auf 503).
    # Länger als 6h wäre bei Warnlagen unehrlich; jede Warnung trägt
    # onset/expires, Konsumenten können einen Stale-Stand selbst einordnen.
    SourceSpec(
        name="dwd_warnings",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst",
        ttl=(60.0, 21600.0),
    ),
    # Kfz-Statistik (jährliche Fortschreibung) -> 24h-Stale-Reserve.
    SourceSpec(
        name="kba",
        license_id="dl_de_by_2_0",
        attribution="Kraftfahrt-Bundesamt (KBA)",
        ttl=_STATIC_STALE_24H,
    ),
    # Unfallatlas (jährliche Datenlieferung) -> 24h-Stale-Reserve.
    SourceSpec(
        name="unfallatlas",
        license_id="dl_de_by_2_0",
        attribution="Statistische Ämter des Bundes und der Länder, Unfallatlas",
        ttl=_STATIC_STALE_24H,
    ),
    # Kriminalstatistik (jährliche Veröffentlichung) -> 24h-Stale-Reserve.
    SourceSpec(
        name="bka_pks",
        license_id="dl_de_by_2_0",
        attribution="Polizeiliche Kriminalstatistik (PKS) - Bundeskriminalamt",
        ttl=_STATIC_STALE_24H,
    ),
    # BBSR-Indikatoren (jährliche Fortschreibung) -> 24h-Stale-Reserve.
    SourceSpec(
        name="inkar",
        license_id="dl_de_by_2_0",
        attribution="Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR), INKAR",
        ttl=_STATIC_STALE_24H,
    ),
    # Wegweiser Kommune: Jahresdaten aus einem lokalen Bulk (Ist bis 2023,
    # Prognosen bis 2040), jährlicher Refresh -> 24h-Stale-Reserve wie INKAR.
    # CC0 verlangt keine Attribution; wir nennen die Herkunft trotzdem.
    SourceSpec(
        name="wegweiser",
        license_id="cc0",
        attribution="Wegweiser Kommune, Bertelsmann Stiftung (CC0)",
        ttl=_STATIC_STALE_24H,
    ),
    SourceSpec(
        name="tankerkoenig",
        license_id="cc_by_4_0",
        attribution="Tankerkoenig (creativecommons.tankerkoenig.de), MTS-K",
        # Kurzlebiger Redis-Cache erlaubt (Owner-Entscheid 2026-07-08), KEINE
        # dauerhafte Speicherung (kein Archiv; Redis läuft ohne Persistence).
        # 5 min fresh entlastet den geteilten API-Key.
        #
        # Stale-Fenster 180 min (zuerst 15, am 2026-09-06 vormittags 60):
        # seit die Aggregat-Bremse auf dem echten Limit der Quelle steht
        # (1 Anfrage/Minute fuer ALLE Staedte zusammen, 0cb5e1fd), entscheidet
        # das Stale-Fenster, ob eine Stadt zwischen zwei Slots 200 (stale) oder
        # 503 bekommt. Mit 15 min fiel jede Stadt, die eine Viertelstunde nicht
        # abgefragt wurde, in den kalten Zustand und verlor gegen die Bremse:
        # 196 x 503 in 24 h. Mit 60 min blieben genau die Clients haengen, die
        # im Stundentakt abfragen: das Fenster lief exakt auf ihrer Kadenz ab,
        # der Key war wieder kalt, und ein kalter Key verliert gegen 1/min. Im
        # Nachmittagslog vom 2026-09-06 kamen 13 von 48 Bremsen-503 genau 45 bis
        # 61 min nach der vorigen Anfrage derselben Stadt. 180 min haelt auch
        # einen Stundenrhythmus (mit Ausfaellen) sicher im Cache. Der Preis:
        # eine Stadt, die drei Stunden niemand abfragt, kann bis zu drei Stunden
        # alte Preise als STALE liefern (cache_status sagt es ehrlich); das ist
        # besser als ein 503, und laenger waere bei Preisen, die sich mehrmals
        # taeglich aendern, unehrlich. Weiterhin nur zwischengespeichert, kein
        # dauerhaftes Vorhalten und kein Hintergrund-Job (ToS: on demand).
        #
        # NACHZUG 2026-09-07 (Tagesprofil, Stale 180 min -> 24 h): der Satz
        # "laenger waere bei Preisen, die sich mehrmals taeglich aendern,
        # unehrlich" stand unter altem Recht. Seit dem 2026-04-01 gilt das
        # Kraftstoffpreisanpassungsgesetz (KPAnG): Preiserhoehungen sind nur
        # EINMAL je Kalendertag zulaessig, und zwar um 12:00 Uhr
        # (Europe/Berlin), Senkungen jederzeit. Das Bundeskartellamt beobachtet
        # 96,5 % der Erhoehungen im Fenster 11:50 bis 12:10. Der Tagesverlauf
        # ist damit bekannt statt geraten (22 bis 5 Uhr fast statisch,
        # vormittags nur fallend, mittags ein Sprung, 12 bis 19 Uhr die
        # Hauptaenderungslast), und EIN fresh-Wert fuer alle Stunden ist in
        # jeder Phase falsch. Deshalb zwei Aenderungen:
        #   * fresh kommt im Live-Pfad aus dem Tagesprofil
        #     (registry/ttl_profiles.tankerkoenig_fresh_s, gekappt auf die
        #     naechste 11:50-Grenze). Die 300 hier bleiben der Rueckfall, falls
        #     die Quelle ihr Profil verliert, und sind bewusst der Wert des
        #     engsten Fensters (11:50 bis 12:20).
        #   * stale 180 min -> 24 h. Mit 180 min blieben 151 x 503 in 24 h
        #     (29 % Fehlerquote): eine Stadt, die drei Stunden niemand
        #     abfragt, wird kalt und verliert gegen die 1-Anfrage/Minute-Bremse.
        #     24 h heisst: eine einmal abgefragte Stadt bleibt einen Tag lang
        #     beantwortbar. Ehrlich ist das nur, weil der Preisverlauf
        #     gesetzlich gedeckelt ist, cache_status STALE es sagt und
        #     retrieved_at den echten Abrufzeitpunkt traegt (nicht mehr die
        #     Uhrzeit der Antwort).
        # Unveraendert: die Aggregat-Bremse (1/min), die Warte-Logik, kein
        # dauerhaftes Vorhalten, kein Timer-Abruf (ToS: on demand).
        #
        # NACHZUG 2026-09-15 (Owner-Entscheid nach der Ursachenanalyse): Verliert
        # eine Nutzeranfrage den Slot der Minute, wird die Stadt eingereiht und
        # der Abruf zeitversetzt nachgeholt (infra/demand_queue.py,
        # collector/demand_drain.py). Der Ausloeser bleibt die Useraktion, es
        # entsteht KEIN nicht user-initiierter Abruf. Grund: ohne dieses
        # Nachholen erreichte eine selten abgefragte Stadt nie wieder einen
        # freien Slot, ihr Eintrag lief nach 48 h aus, und danach kam dauerhaft
        # 503. Die Fenster hier sind davon unberuehrt.
        ttl=(300.0, 86400.0),
        # NACHZUG 2026-09-07 abends (Notreserve +24 h): das 24-h-Stale-Fenster
        # allein hat die 503-Wellen nicht beendet, weil der Redis-Key exakt mit
        # dem Stale-Ende starb (infra/cache._store: ex == ttl_stale). Nach dem
        # 161er-Deploy stand fuer etliche Staedte GAR KEIN Eintrag mehr da
        # (resilient_fetch_fallback has_stale=false), und jeder kalte Abruf
        # verlor gegen die 1/min-Bremse; die Kuma-Retries (35-s-Takt)
        # verbrannten das Budget zusaetzlich. Die Notreserve haelt den Key
        # 24 h UEBER das Stale-Ende hinaus (Alter der Antwort damit maximal
        # 48 h), ausgeliefert NUR im Fehlerpfad mit ehrlichem retrieved_at und
        # cache_status STALE-ON-ERROR. Das bleibt Zwischenspeichern, kein
        # Archiv: Redis laeuft ohne Persistence (allkeys-lru), kein
        # Hintergrund-Abruf, kein append_record. Bewusst 24 h und nicht mehr:
        # die ToS-Lesart vom 2026-07-25 ("on demand", kein Spiegeln) traegt
        # kurzlebiges Vorhalten, ein Mehrtages-Puffer waere eine neue
        # Absprache-Frage (liegt beim Owner fuer den MTS-K/TK-Kontakt).
        emergency_keep_s=86400.0,
    ),
    SourceSpec(name="gbfs", license_id="cc0", attribution="nextbike GmbH / GBFS (CC0)"),
    SourceSpec(
        name="db_timetables", license_id="cc_by_4_0", attribution="Deutsche Bahn AG"
    ),
    # Bodenrichtwerte (jährliche Feststellung) -> 24h-Stale-Reserve.
    SourceSpec(
        name="boris",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Bodenrichtwerte",
        ttl=_STATIC_STALE_24H,
    ),
    SourceSpec(
        name="stada",
        license_id="cc_by_4_0",
        attribution="Deutsche Bahn AG",
        ttl=(86400.0, 2592000.0),
    ),
    # Regionalstatistik (statisch, jährliche/mehrjährige Fortschreibung) -> 24h-Stale.
    SourceSpec(
        name="regionalstatistik",
        license_id="dl_de_by_2_0",
        attribution="Statistische Ämter des Bundes und der Länder",
        ttl=_STATIC_STALE_24H,
    ),
    # GeoBasis-DE / BKG (statische Geobasisdaten) -> 24h-Stale-Reserve.
    SourceSpec(
        name="bkg",
        license_id="dl_de_by_2_0",
        attribution="(c) GeoBasis-DE / BKG (Jahr)",
        ttl=_STATIC_STALE_24H,
    ),
    # Wahlergebnisse (statisch nach Feststellung) -> 24h-Stale-Reserve.
    SourceSpec(
        name="bundeswahl",
        license_id="dl_de_by_2_0",
        attribution="Die Bundeswahlleiterin",
        ttl=_STATIC_STALE_24H,
    ),
    # Feiertage/Schulferien (deterministisch je Bundesland) -> 24h-Stale-Reserve.
    SourceSpec(
        name="holidays",
        license_id="gemeinfrei",
        attribution="Feiertage und Schulferien je Bundesland, gemeinfrei",
        ttl=_STATIC_STALE_24H,
    ),
    SourceSpec(
        name="berlin_viz",
        license_id="dl_de_by_2_0",
        attribution="Verkehrsinformationszentrale Berlin (VIZ)",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="hamburg_roadworks",
        license_id="dl_de_by_2_0",
        attribution="Freie und Hansestadt Hamburg",
        cooldown=1800.0,
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="koeln_road_events",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="muenchen_roadworks",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="dortmund_roadworks",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Dortmund",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="rostock_roadworks",
        license_id="cc0",
        attribution="Hanse- und Universitätsstadt Rostock",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="sperrinfosys",
        license_id="dl_de_by_2_0",
        attribution="Freistaat Sachsen / LISt GmbH (SPERRINFOSYS)",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="mobidata_bw",
        license_id="dl_de_by_2_0",
        attribution="Verkehrsministerium Baden-Württemberg / MobiData BW",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    # Die Webcam-LISTE (Standorte/URLs) ist quasi statisch, die Bilder liegen
    # beim Betreiber: Fresh 1h / Stale 24h statt 60s/120s-Default
    # (TTL-Tuning quick-260717-ttl).
    SourceSpec(
        name="autobahn_webcam",
        license_id="dl_de_by_2_0",
        attribution="Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
        ttl=(3600.0, 86400.0),
    ),
    # Veranstaltungskalender ändern sich täglich, nicht minütlich: Fresh 1h /
    # Stale 24h; überbrückt Ausfälle des externen SaaS statt 503 nach 2 Minuten
    # (TTL-Tuning quick-260717-ttl).
    SourceSpec(
        name="destination_one",
        license_id="mixed",
        attribution="destination.one",
        ttl=(3600.0, 86400.0),
    ),
    SourceSpec(
        name="koeln_events",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="koeln_traffic_flow",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
        ttl=_TRAFFIC_FLOW_STALE,
    ),
    SourceSpec(
        name="koeln_roadworks_live",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="koeln_incidents_live",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="koeln_lez_live",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="berlin_traffic_reports",
        license_id="dl_de_by_2_0",
        attribution=(
            "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt (SenMVKU)"
        ),
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="dortmund_parking",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Dortmund",
        ttl=(300.0, 3600.0),  # Fenster wie die übrigen Parken-Quellen
    ),
    SourceSpec(
        name="kiel_counting_stations",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt Kiel",
        ttl=_TRAFFIC_FLOW_STALE,
    ),
    SourceSpec(
        name="eround_charging",
        license_id="cc0",
        attribution="Hamburger Energienetze GmbH / eRound",
        ttl=_TRAFFIC_FLOW_STALE,
    ),
    SourceSpec(
        name="frankfurt_parking",
        license_id="dl_de_by_2_0",
        attribution="Stadt Frankfurt am Main",
        ttl=(300.0, 3600.0),  # Fenster wie die übrigen Parken-Quellen
    ),
    SourceSpec(
        name="wuppertal_parking",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Wuppertal",
        ttl=(300.0, 3600.0),  # Fenster wie die übrigen Parken-Quellen
    ),
    # Magdeburg-Parken (Mobilithek, ifak e.V.): Datenquelle Stadt Magdeburg ->
    # deren Open-Data-Nutzungsbedingungen legen mangels anderer Kennzeichnung
    # Datenlizenz Deutschland Namensnennung 2.0 fest (Recherche 2026-06-30,
    # magdeburg.de Offene-Verwaltungsdaten), Tier A. Attribution = geforderte
    # Quellenangabe verbatim.
    SourceSpec(
        name="magdeburg_parking",
        license_id="dl_de_by_2_0",
        attribution="Datenquelle: Landeshauptstadt Magdeburg, www.magdeburg.de",
        ttl=(300.0, 3600.0),  # Fenster wie die übrigen Parken-Quellen
    ),
    # Köln-Parken (Mobilithek, DATEX II V2): Köln stellt seine Mobilithek-
    # Verkehrsdaten durchgängig unter DL-DE/Zero 2.0 bereit (Bestand
    # koeln_traffic_flow etc., DATA-LICENSES.md), Attribution informativ.
    SourceSpec(
        name="koeln_parking",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
        ttl=(300.0, 3600.0),  # Fenster wie die übrigen Parken-Quellen
    ),
    SourceSpec(
        name="bremen_roadworks",
        license_id="dl_de_by_2_0",
        attribution="Freie Hansestadt Bremen",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(
        name="hannover_traffic_reports",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt Hannover",
        ttl=_TRAFFIC_MESSAGE_STALE,
    ),
    SourceSpec(name="gtfs_rt", license_id="cc_by_sa_4_0", attribution="gtfs.de"),
    SourceSpec(
        name="hvv_geofox",
        license_id="unknown",
        attribution="Hamburger Verkehrsverbund GmbH (HVV) / Geofox",
    ),
    SourceSpec(
        name="vgn",
        license_id="cc_by_4_0",
        attribution="Verkehrs-Aktiengesellschaft Nürnberg (VAG) / VGN",
    ),
    SourceSpec(
        name="hamburg_traffic_situation",
        license_id="dl_de_by_2_0",
        attribution="Freie und Hansestadt Hamburg",
        cooldown=1800.0,
        ttl=_TRAFFIC_FLOW_STALE,
        # api.hamburg.de hat ein naechtliches Wartungsfenster von rund 39
        # Minuten (taeglich ab etwa 21:53 UTC, Kuma-Historie seit 07.09.2026).
        # Das Stale-Fenster von 30 Minuten laeuft mittendrin aus, der Rest der
        # Nacht war eine nackte 503. Zwei Stunden Notreserve decken das
        # Fenster samt Breaker-Nachlauf; die Antwort traegt STALE-ON-ERROR
        # und den echten Abrufzeitpunkt.
        emergency_keep_s=7200.0,
    ),
    SourceSpec(
        name="solar",
        license_id="ec_reuse",
        attribution="PVGIS © European Communities, 2001-2026",
        ttl=(86400.0, 2592000.0),
    ),
    # Solarkataster NRW (statischer Katasterdatensatz) -> 24h-Stale-Reserve.
    SourceSpec(
        name="solar_cadastre",
        license_id="dl_de_zero_2_0",
        attribution="Land NRW / GeoBasis NRW / LANUK (MaStR), Solarkataster NRW",
        ttl=_STATIC_STALE_24H,
    ),
    SourceSpec(
        name="muenchen_parking",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="muenchen_bike_counts",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=(86400.0, 2592000.0),
    ),
    # Quick-260729-muc: ruhender Verkehr München, drei Datenarten. Stammdaten
    # (kein Live-Anteil, Aktualisierung höchstens täglich) -> dasselbe großzügige
    # Fenster wie muenchen_parking/-radzaehl. Attribution VERBATIM identisch
    # zu mappers/muenchen_ruhver.py + DATA-LICENSES.md (T-11-SRC-DRIFT):
    # WFS-Layer des Mobilitätsreferats = Landeshauptstadt München, die drei
    # CKAN-Pakete der P+R-Anlagen = P+R Park & Ride GmbH München.
    SourceSpec(
        name="muenchen_parking_onstreet",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="muenchen_park_and_ride",
        license_id="dl_de_by_2_0",
        attribution="P+R Park & Ride GmbH München",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="muenchen_mobility_points",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="muenchen_bike_parking",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="leipzig_bike_counts",
        license_id="dl_de_by_2_0",
        attribution="Stadt Leipzig",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="hamburg_bike_counts",
        license_id="dl_de_by_2_0",
        attribution=(
            "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende"
        ),
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="berlin_bike_counts",
        license_id="dl_de_zero_2_0",
        attribution=(
            "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt Berlin"
        ),
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="stuttgart_bike_counts",
        license_id="cc_by_4_0",
        attribution="Landeshauptstadt Stuttgart",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="koeln_bike_counts",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="essen_bike_counts",
        license_id="dl_de_by_2_0",
        attribution="Stadt Essen",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="duesseldorf_bike_counts",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt Düsseldorf",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="parkendd",
        license_id="unknown",
        attribution="ParkenDD",
        ttl=(300.0, 3600.0),
    ),
    # Phase 25: Parken-Direktbezug (ParkenDD-Abloesung). Live-Parken-TTL wie
    # parkendd (300s fresh / 3600s stale). Attribution je Eintrag VERBATIM
    # identisch zum DATA-LICENSES.md-Abschnitt (T-11-SRC-DRIFT / test_license_gate).
    # Die per-Stadt-Lizenzen der MobiData-Staedte liegen im Mapper
    # (mappers/mobidata_parkapi), NICHT hier (Muster wie parkendd); dieser
    # aggregierte Eintrag traegt eine generische Quellen-Attribution.
    SourceSpec(
        name="mobidata_parkapi",
        license_id="dl_de_by_2_0",
        attribution="MobiData BW / ParkAPI",
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        name="muenster_parking",
        license_id="dl_de_by_2_0",
        attribution="Stadt Münster",
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        # Direktbezug APAG über NRW.Mobidrom (Owner-Entscheid 2026-07-19): NICHT offen
        # deklariert (CKAN isopen=false) -> konservativ unknown/Tier C (live-only, NICHT
        # public) bis zur Lizenzklärung. Attribution verbatim aus mappers/stadt_parking.
        name="aachen_parking",
        license_id="unknown",
        attribution=(
            "APAG - Aachener Parkhaus GmbH, bereitgestellt über "
            "NRW.Mobidrom (mobilitaetsdaten.nrw)"
        ),
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        # Karlsruhe Parkhäuser (Transparenzportal-Datensatz parkhaeuser, WFS-JSON über
        # mobil.trk.de/geoserver). Direkter ParkenDD-Ersatz. Lizenz verifiziert
        # 2026-07-19: CC-BY 4.0 (transparenz.karlsruhe.de) -> Tier A, public.
        name="karlsruhe_parking",
        license_id="cc_by_4_0",
        attribution="Stadt Karlsruhe",
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        name="oldenburg_parking",
        license_id="dl_de_by_2_0",
        attribution="Stadt Oldenburg (Oldb)",
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        name="kaiserslautern_parking",
        license_id="cc0",
        attribution="Stadtverwaltung Kaiserslautern",
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        name="dresden_parking",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt Dresden",
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        name="pr_hessen_parking",
        license_id="dl_de_by_2_0",
        attribution="ivm GmbH",
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        name="hamburg_parking",
        license_id="dl_de_by_2_0",
        attribution=(
            "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende"
        ),
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        name="db_bahnpark",
        license_id="dl_de_by_2_0",
        attribution=(
            "Parking Information Daten der DB BahnPark, API über den DB API "
            "Marketplace (https://developers.deutschebahn.com/db-api-marketplace/"
            "apis/product/parking-information-db-bahnpark)"
        ),
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        name="heritage",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Landesdenkmalamt Berlin, Denkmaldatenbank",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="tree_cadastre",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Straßen- und Anlagenbaumbestand",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="zensus_grid",
        license_id="dl_de_by_2_0",
        attribution="© Statistische Ämter des Bundes und der Länder, Zensus 2022",
        ttl=(604800.0, 2592000.0),
    ),
    SourceSpec(
        name="oeffentlichevergabe",
        license_id="cc0",
        attribution=(
            "Datenservice Oeffentlicher Einkauf (oeffentlichevergabe.de) / "
            "Beschaffungsamt des BMI"
        ),
        ttl=(86400.0, 2592000.0),
    ),
    # DATA-41: Fernwärme-/Wärmenetz-Versorgung je Stadt (föderiert je Stadt-WFS,
    # je Ursprung lizenzverifiziert). Berlin repräsentativ (DL-DE/Zero 2.0); Hamburg
    # DL-DE/BY 2.0 trägt der Record je Stadt aus der WFS-Registry. Batch-Ingest, kein
    # Live-Call im Request-Pfad (lange TTL).
    SourceSpec(
        name="district_heating",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Energienetze",
        ttl=(86400.0, 2592000.0),
    ),
    # Quick-260705-jgt: Koeln Behoerden-Wartezeiten (office-wait-times). Keyloser
    # Direkt-HTTP gegen waiting-od.php, DL-DE/Zero 2.0 = Tier A, reine Live-Daten.
    # Attribution "Stadt Koeln" VERBATIM identisch zum DATA-LICENSES.md-Eintrag.
    SourceSpec(
        name="koeln_wait_times",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Koeln",
    ),
    # Quick-260705-ufv: BBK NINA Bevoelkerungsschutz-Warnungen (civil-protection-
    # warnings). Keyloser GET gegen warnung.bund.de/api31/dashboard/{ARS}.json,
    # amtlicher Warntext verbatim (§ 5 Abs. 2 UrhG, amtliches Werk = Tier A). Reine
    # Live-Warnungen (kein Archiv), kurzes Cache-Fenster (60s/300s). Attribution
    # VERBATIM identisch zu mappers/bbk_nina.py + DATA-LICENSES.md (T-11-SRC-DRIFT).
    SourceSpec(
        name="bbk_nina",
        license_id="amtliches_werk",
        attribution="Bundesamt für Bevölkerungsschutz und Katastrophenhilfe (BBK)",
        ttl=(60.0, 300.0),
    ),
    # Quick-260708-tsv: kommunale Ratsinformationen (council-papers, OParl). Acht
    # lizenzgeklärte Städte mit JE EIGENER Lizenz (die per-Stadt-Lizenz trägt die
    # Route aus mappers/oparl.COUNCIL_CITY_LICENSE). Dieser aggregierte Eintrag ist
    # NUR für die /sources-Route; license_id repräsentativ (DL-DE/Zero 2.0, 4 von 8
    # Städten). attribution VERBATIM identisch zur Zeile in DATA-LICENSES.md
    # (Lizenz-Drift-Gate test_license_gate). Read-only Store -> grosszuegige TTL.
    SourceSpec(
        name="council",
        license_id="dl_de_zero_2_0",
        attribution=(
            "Kommunale Ratsinformationssysteme (OParl) der Städte Dresden, Köln, "
            "Düsseldorf, Münster, Leipzig, Magdeburg, Osnabrück und "
            "Freiburg im Breisgau"
        ),
        ttl=(86400.0, 2592000.0),
    ),
)

# --- Abgeleitete Sichten (Rückwärts-kompatibel zu den alten Strukturen) ---
KNOWN_SOURCES: tuple[str, ...] = tuple(s.name for s in SOURCE_SPECS)

SOURCE_LICENSE: dict[str, dict[str, str]] = {
    s.name: {"license_id": s.license_id, "attribution": s.attribution}
    for s in SOURCE_SPECS
}

SOURCE_TTL: dict[str, tuple[float, float]] = {
    s.name: s.ttl for s in SOURCE_SPECS if s.ttl is not None
}

FRAGILE_SOURCE_COOLDOWN: dict[str, float] = {
    s.name: s.cooldown for s in SOURCE_SPECS if s.cooldown is not None
}

# Notreserve hinter dem Stale-Fenster, nur Opt-in-Quellen (siehe SourceSpec-
# Docstring und den tankerkoenig-Eintrag). Quellen ohne Eintrag behalten das
# bisherige Verhalten: Key-TTL == Stale-Ende.
SOURCE_EMERGENCY_KEEP: dict[str, float] = {
    s.name: s.emergency_keep_s for s in SOURCE_SPECS if s.emergency_keep_s > 0.0
}
