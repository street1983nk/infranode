"""Zentrale Konfiguration (FND-02).

Eine einzige ``Settings``-Quelle liest ``.env`` + Umgebungsvariablen mit dem
Prefix ``INFRANODE_``. Per-Source ``enable_*``-Flags ermoeglichen Graceful
Degradation; Schluessel-Felder sind ``SecretStr | None`` (Default None =
Quelle nicht nutzbar, kein Secret im Code).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validierte Anwendungs-Settings aus Env/.env (Prefix INFRANODE_)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="INFRANODE_",
        extra="ignore",
    )

    log_level: str = "INFO"
    redis_url: str = "redis://redis:6379/0"
    # CORS: die oeffentliche API ist KEYLOS, READ-ONLY und liefert offene Daten,
    # die explizit fuer beliebige Browser-/Client-Apps gedacht sind (Vibecoder,
    # Dashboards, Starter-Templates auf Vercel/Netlify/localhost). Fuer so eine
    # oeffentliche Datendienst-API ist "*" der Standard (vgl. Open-Meteo,
    # Nominatim): die alte Whitelist hat jeden Cross-Origin-Browser-Client still
    # blockiert. Bewusste Abkehr von der frueheren "nie *"-Regel; sie galt fuer
    # credentialed APIs. Hier wird allow_credentials in main.py auf False
    # gesetzt, sobald "*" aktiv ist (CORS-Spec: "*" + credentials schliessen sich
    # aus). Das Admin-Dashboard ist same-origin (Cookie cs_admin SameSite=strict)
    # und von CORS unberuehrt. Per INFRANODE_CORS_ORIGINS auf eine Whitelist
    # einschraenkbar (dann wird wieder credentialed CORS verwendet).
    cors_origins: list[str] = ["*"]

    # Rate-Limit (API-06), limits/slowapi-Format ("<zahl>/<einheit>"). Die API ist
    # keylos/offen; limit_anon ist das IP-Budget fuer ALLE Clients (DoS-Schutz).
    # 300/min (= 18.000/h pro IP): grosszuegig genug fuer Bulk-/Data-Science-Scans
    # ueber alle Staedte x Endpunkte, ohne Scraping-Freibrief. Echter DoS-Schutz
    # liegt bei Cloudflare + Circuit-Breaker (Upstream), nicht am App-Limit.
    limit_anon: str = "300/minute"
    # Striktes Budget am Admin-Login gegen Passwort-Brute-Force (Security-Audit
    # 2026-06-10, HIGH-1). Eigener strenger @limiter.limit-Decorator auf der Route.
    limit_admin_login: str = "5/minute"
    # Sync-Redis-URI fuer slowapis eigene limits-Storage (Pitfall 1: slowapi teilt
    # NICHT den async-Pool app.state.redis, sondern oeffnet eine eigene sync-
    # Verbindung zum SELBEN Redis-Server). None = in der Anwendung auf redis_url
    # zurueckfallen (gleicher Server, getrennte Verbindung).
    limit_storage_uri: str | None = None

    # Phase 13: Admin-Dashboard (OPS-01/OPS-02). admin_password schuetzt /admin per
    # Cookie-Session (fail-closed: None = Login unmoeglich, Best-Practice 2). Beide
    # Secret-Felder sind SecretStr, damit der Wert nie im Klartext geloggt/serialisiert
    # wird. admin_session_secret signiert das Session-Cookie (itsdangerous, >=32 Byte
    # empfohlen). admin_log_max begrenzt den Redis-Ringpuffer der Request-Logs.
    # admin_cookie_https_only setzt das Secure-Flag des Cookies (Default True; nur in
    # Tests/lokal ohne TLS auf False stellbar).
    admin_password: SecretStr | None = None
    admin_session_secret: SecretStr | None = None
    admin_log_max: int = 200
    admin_cookie_https_only: bool = True
    # Defense-in-Depth fuer /admin (T-18-15): Code-seitiger Netzwerk-Guard.
    # Betrieblich ist /admin bereits Tailnet-only (Caddy gibt oeffentlich 404,
    # ``tailscale serve`` laeuft ohne Funnel, ufw oeffnet 80/443 nur fuer
    # Cloudflare). Dieser Guard blockt zusaetzlich JEDE Anfrage mit oeffentlich-
    # routbarer Client-IP (real_client_ip) mit 404, falls die Caddy-404-Regel je
    # entfaellt. Loopback/private/Tailnet-CGNAT (100.64.0.0/10) sind als nicht-
    # global routbar immer erlaubt; admin_trusted_networks erlaubt optional
    # zusaetzliche (auch global routbare) CIDR (leer = nur die nicht-globale Regel).
    admin_trusted_networks: list[str] = []

    # Per-Source-Toggles. Quellen kommen ab Phase 4; hier schon definiert.
    enable_wikidata: bool = True
    enable_openaq: bool = False
    enable_dwd: bool = True
    enable_overpass: bool = True
    enable_autobahn: bool = True
    enable_hvv: bool = False
    enable_delfi: bool = False
    # Phase 7: alle fuenf Tier-A-Quellen sind keylos und bundesweit,
    # daher Default True (analog enable_dwd/enable_autobahn). Der Toggle-Name muss
    # exakt zu _KNOWN_SOURCES (sources.py) passen (getattr(settings, f"enable_{name}")).
    # enable_lhp steuert die Hochwasser-Quelle (Record-Tag hochwasser).
    # enable_bnetza steuert NUR die /charging-Route (Snapshot-Read); die Daten
    # kommen seit dem ArcGIS-Aus aus einem offline aktualisierten CSV-Datensatz,
    # nicht mehr live.
    enable_bnetza: bool = True
    enable_uba: bool = True
    enable_pegelonline: bool = True
    enable_lhp: bool = True
    enable_dwd_pollen: bool = True
    # Phase 8: account-gated Quellen Default False (analog enable_openaq), bis
    # Credentials gesetzt sind. enable_genesis steuert Demografie + Krankenhaus
    # (regionalstatistik.de POST-API), enable_zensus den Zensus-Host, enable_divi
    # die klinikscharfe DIVI-Live-Quelle (Tier C, optional). Keylose Bulk-/Seed-
    # Quellen Default True (Toggle steuert nur die Route, nicht den Offline-Ingest).
    enable_genesis: bool = False
    # GENESIS-Regionalstatistik-Trio (Arbeitslosenquote/Tourismus/Bautaetigkeit je
    # Kreis, DATA-28). Eigener Toggle, damit das Trio mit dem korrekten Header-Auth-
    # Adapter live gehen kann, ohne den (separaten) Demografie-Pfad zu beruehren.
    # Braucht dieselben genesis_username/genesis_password-Credentials.
    enable_genesis_regio: bool = True
    enable_zensus: bool = False
    enable_divi: bool = False
    enable_mastr: bool = True
    # SMARD-Strommarktdaten (Verbrauch/Netzlast + Day-ahead-Preis), keylos CC BY 4.0.
    enable_smard: bool = True
    # DWD-Wetterwarnungen (amtliche Warnungen, WarnApp-JSON), keylos GeoNutzV.
    enable_dwd_warnings: bool = True
    # KBA Pkw-Bestand + Elektro-Anteil je Zulassungsbezirk (Bulk, keylos DL-DE/BY).
    enable_kba: bool = True
    # Unfallatlas (Strassenverkehrsunfaelle je Kreis, Bulk-CSV, keylos DL-DE/BY).
    enable_unfallatlas: bool = True
    # INKAR/BBSR sozialoekonomische Indikatoren je Kreis (Bulk, keylos DL-DE/BY).
    enable_inkar: bool = True
    # Tankerkoenig Spritpreise (MTS-K, CC BY 4.0). KEYED Live-Quelle: Toggle Default
    # True, aber ohne tankerkoenig_api_key liefert die Route 200 disabled (analog
    # hvv_geofox). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    enable_tankerkoenig: bool = True
    # DATA-33: GBFS-Bike-/Scooter-Sharing (Live, aggregiert, Primaer Nextbike CC0).
    # Keylos -> Default True analog der uebrigen keylosen Live-Quellen. Pro System
    # wird die Lizenz fail-closed gegen die Tier-A-Allowlist geprueft. Toggle-Name
    # == SourceId-Wert (gbfs) == _KNOWN_SOURCES-Eintrag.
    enable_gbfs: bool = True
    # DATA-34: DB Timetables (Bahnhof-Abfahrten Metropolen-Hbf inkl. Fernverkehr).
    # KEYED Live-Quelle: Toggle Default True, aber ohne db_client_id/db_api_key
    # liefert die Route 200 disabled (analog tankerkoenig/hvv_geofox). Toggle-Name
    # == SourceId-Wert (db_timetables) == _KNOWN_SOURCES-Eintrag.
    enable_db_timetables: bool = True
    # DATA-35: BORIS amtliche Bodenrichtwerte je Stadt (Bulk, keylos, pro
    # Bundesland foederierter WFS). Keylos -> Default True analog enable_inkar/
    # enable_kba. Read-only Store-Lesung im Request-Pfad. Toggle-Name ==
    # SourceId-Wert (boris) == _KNOWN_SOURCES-Eintrag.
    enable_boris: bool = True
    enable_bkg: bool = True
    enable_bundeswahl: bool = True
    enable_feiertage: bool = True
    # Phase 9: keylose Stadt-Verkehrs-Quellen (Baustellen/Sperrungen) je Stadt +
    # Autobahn-Webcam-Sub-Service. Alle keylos, daher Default True (analog
    # enable_autobahn). Der Toggle-Name MUSS exakt zu _KNOWN_SOURCES (sources.py)
    # passen: getattr(settings, f"enable_{name}"). Keine neuen Secrets.
    enable_berlin_viz: bool = True
    enable_hamburg_baustellen: bool = True
    enable_koeln_verkehr: bool = True
    enable_muenchen_baustellen: bool = True
    enable_mobidata_bw: bool = True
    enable_autobahn_webcam: bool = True
    # Phase 10: Stadt-Events/Veranstaltungen. destination.one ist KEYLOS: die
    # Experience "open-data" ist frei zugaenglich (Support-Bestaetigung
    # destination.one 2026-06-10, live verifiziert), daher Default True analog
    # enable_koeln_events; der fruehere licensekey-Guard ist entfallen.
    # Der Toggle-Name MUSS exakt zum _KNOWN_SOURCES-Eintrag (sources.py) und zum
    # SourceId-Wert passen: getattr(settings, f"enable_{name}").
    enable_destination_one: bool = True
    enable_koeln_events: bool = True

    # Phase 20: Mobilithek-mTLS-Live-Quellen. cert_path optional (None = keine
    # Live-Quelle nutzbar, Graceful Degradation); cert_password SecretStr, damit
    # der Wert nie im Klartext geloggt/serialisiert wird (wie admin_session_secret).
    # httpx/ssl koennen .p12 nicht direkt lesen -> cryptography konvertiert beim
    # Start zu PEM (infra/mobilithek.py, Folge-Plan).
    mobilithek_cert_path: str | None = None
    mobilithek_cert_password: SecretStr | None = None
    # Per-Quelle-Toggles (Toggle-Name == SourceId-Wert ==
    # getattr(settings, f"enable_{name}")). Live = Cert + Abo noetig, daher alle
    # Default False bis Zertifikat und Abo-ID gesetzt sind.
    enable_koeln_traffic_flow: bool = False
    enable_koeln_baustellen_live: bool = False
    enable_koeln_ereignisse_live: bool = False
    enable_koeln_lez_live: bool = False
    enable_berlin_verkehrsmeldungen: bool = False
    # dortmund_parking ist seit 2026-06-13 KEYLOS (direkter Opendatasoft-Feed der
    # Stadt, kein Cert/Abo mehr) -> Default True analog der uebrigen keylosen
    # Quellen. dortmund_parking_abo_id wird nicht mehr benoetigt (bleibt fuer die
    # SSRF-Allowlist-Konsistenz erhalten, ist aber ungenutzt).
    enable_dortmund_parking: bool = True
    enable_kiel_zaehlstellen: bool = False
    enable_eround_charging: bool = False
    # DATA-31: Bremen Baustellen (Mobilithek DATEX II Situation, DL-DE/BY 2.0).
    # Toggle-Name == SourceId-Wert (bremen_baustellen) == _KNOWN_SOURCES. Default
    # False; aktiv erst wenn Toggle AN und bremen_baustellen_abo_id gesetzt.
    enable_bremen_baustellen: bool = False
    # Abo-ID je Live-Quelle als Settings-Allowlist gegen SSRF (RESEARCH Pitfall 7):
    # die aboId im Mobilithek-Pull-URL stammt NIE aus User-Input, nur aus diesen
    # Feldern. None = Quelle nicht aufloesbar (Graceful Degradation). Abo-IDs aus
    # mobilithek.info -> Meine Abonnements -> Detailseite (HTTPS-Zugriffspunkt).
    koeln_traffic_flow_abo_id: str | None = None
    koeln_baustellen_live_abo_id: str | None = None
    koeln_ereignisse_live_abo_id: str | None = None
    koeln_lez_live_abo_id: str | None = None
    berlin_verkehrsmeldungen_abo_id: str | None = None
    dortmund_parking_abo_id: str | None = None
    kiel_zaehlstellen_abo_id: str | None = None
    eround_charging_abo_id: str | None = None
    bremen_baustellen_abo_id: str | None = None

    # Phase 19: GTFS-Realtime Trip Updates (Live-ÖPNV-Verspätungen). Toggle-Name
    # == SourceId-Wert == _KNOWN_SOURCES-Eintrag (getattr(settings, f"enable_gtfs_rt")).
    # Default False bis die Quelle aktiv geschaltet ist (analog Phase-20-Toggles).
    enable_gtfs_rt: bool = False
    # Quellen-Umschaltung (RESEARCH Pattern 7): "gtfs_de" (verifizierte Primaer-
    # quelle, kein Key) | "mobilithek_delfi" (mTLS-Pull, liefert Stand 2026-06-12
    # 422 = no_data). Default gtfs_de, bis das Mobilithek-Abo echte Pakete liefert.
    transit_rt_source: str = "gtfs_de"
    # Mobilithek-DELFI-Realtime-Abo-ID als Settings-Allowlist gegen SSRF (die aboId
    # im Pull-URL stammt NIE aus User-Input, nur aus diesem Feld). None = Quelle
    # nicht aufloesbar (Graceful Degradation). Owner-Abo 1001139879668502528 erst
    # in der gitignored .env (INFRANODE_TRANSIT_RT_DELFI_ABO_ID).
    transit_rt_delfi_abo_id: str | None = None

    # Schluessel optional; None = Quelle nicht nutzbar (Graceful Degradation).
    openaq_api_key: SecretStr | None = None
    # Phase 8 GENESIS/Zensus-Credentials (account-gated POST-API). WICHTIG: das
    # Feld heisst genesis_username (mappt auf INFRANODE_GENESIS_USERNAME via
    # env_prefix), weil der Owner genau diese Variable in der gitignored .env
    # bereits gesetzt hat (plus INFRANODE_GENESIS_PASSWORD). Zensus-Host nutzt
    # evtl. einen getrennten Account (RESEARCH A4/Pitfall 2), daher eigene Felder.
    # Passwoerter sind SecretStr (nie im Klartext geloggt/serialisiert).
    genesis_username: str | None = None
    genesis_password: SecretStr | None = None
    zensus_user: str | None = None
    zensus_password: SecretStr | None = None
    # HVV-Geofox-GTI Live-Abfahrten (DATA-24): hvv_api_key ist der HMAC-Secret,
    # hvv_user der geofox-auth-user. Beide gelangen NUR in Header/Body des
    # signierten Geofox-Requests, NIE in Cache-Key/Response/Log. Der HVV-GTFS-
    # Batch (statische Stops) braucht weiterhin keinen Key, nur den ZIP-Pfad.
    hvv_api_key: SecretStr | None = None
    hvv_user: str | None = None
    # Toggle-Name == SourceId-Wert (hvv_geofox) == _KNOWN_SOURCES-Eintrag. Default
    # False; aktiv erst wenn Toggle AN und beide Credentials gesetzt sind.
    enable_hvv_geofox: bool = False
    # DATA-25: VGN/VAG-Nuernberg Live-Abfahrten. KEYLOS (offene Puls-API
    # start.vag.de, CC-BY 4.0) -> Default True analog der uebrigen keylosen
    # Quellen. Toggle-Name == SourceId-Wert (vgn) == _KNOWN_SOURCES-Eintrag.
    enable_vgn: bool = True
    # DATA-26: Hamburg-Verkehrslage (Echtzeit-Verkehrsfluss). KEYLOS (OAF/GeoJSON
    # api.hamburg.de, DL-DE/BY 2.0) -> Default True analog der uebrigen keylosen
    # Quellen. Toggle-Name == SourceId-Wert (hamburg_verkehrslage) ==
    # _KNOWN_SOURCES-Eintrag.
    enable_hamburg_verkehrslage: bool = True
    # DATA-30: Tankerkoenig-API-Key (SecretStr, nie im Klartext geloggt/serialisiert).
    # Geht NUR in den Query-Parameter ``apikey`` des Tankerkoenig-Requests, NIE in
    # Cache-Key/Response/Log. None = Quelle disabled (Graceful Degradation), die
    # Route liefert dann 200 source_status="disabled" (analog hvv_api_key). Per
    # INFRANODE_TANKERKOENIG_KEY in der gitignored .env gesetzt (Feldname
    # tankerkoenig_key -> Env INFRANODE_TANKERKOENIG_KEY ueber den env_prefix).
    tankerkoenig_key: SecretStr | None = None
    # DATA-34: DB-Timetables-Credentials (DB API Marketplace, Produkt "Timetables").
    # Beide SecretStr (nie im Klartext geloggt/serialisiert), gehen NUR in die
    # Request-Header DB-Client-Id/DB-Api-Key, NIE in Cache-Key/Response/Log. None ->
    # Route liefert 200 source_status="disabled". Per INFRANODE_DB_CLIENT_ID /
    # INFRANODE_DB_API_KEY in der gitignored .env gesetzt.
    db_client_id: SecretStr | None = None
    db_api_key: SecretStr | None = None
    # Lokale Pfade zu den vorverarbeiteten GTFS-ZIPs fuer den Batch-Ingest
    # (DATA-05). None = Batch nicht lauffaehig (kein Default-Pfad, damit der
    # CLI sauber mit Exit 2 abbricht). Per INFRANODE_DELFI_GTFS_PATH /
    # INFRANODE_HVV_GTFS_PATH ueberschreibbar. NICHT im Request-Pfad: der
    # Ingest laeuft ausschliesslich als manueller Batch (python -m).
    delfi_gtfs_path: str | None = None
    hvv_gtfs_path: str | None = None
    # Phase 19: SEPARATER Statik-Pfad fuer die GTFS-RT-Aufloesung. Der gtfs.de-
    # Free-Feed referenziert die gtfs.de-EIGENE Statik (numerische IDs, CC-BY-SA
    # Tier B, woechentlich via transit.refresh erneuert). Er darf NICHT auf das
    # DELFI-Zip zeigen (CC-BY 4.0 Tier A, Basis des /transit-Batch-Ingests),
    # sonst vermischen sich die Lizenzraeume beim Ueberschreiben. None =
    # Fallback auf delfi_gtfs_path (Tests/Mobilithek-Quelle mit DELFI-IDs).
    gtfs_rt_static_path: str | None = None

    # Phase 8: lokale Pfade zu den vorverarbeiteten Bulk-Dateien fuer den
    # Offline-Ingest (analog delfi_gtfs_path). None = Batch nicht lauffaehig
    # (kein Default-Pfad, CLI bricht sauber mit Exit 2 ab). Per
    # INFRANODE_MASTR_ZIP_PATH / INFRANODE_BKG_PATH / INFRANODE_BUNDESWAHL_CSV_PATH
    # / INFRANODE_DIVI_CSV_PATH ueberschreibbar. NICHT im Request-Pfad: der Ingest
    # laeuft ausschliesslich als manueller Batch (python -m).
    mastr_zip_path: str | None = None
    bkg_path: str | None = None
    bundeswahl_csv_path: str | None = None
    divi_csv_path: str | None = None
    # KBA-Bulk-Ingest (DATA-27): optionaler Pfad zu einer lokal vorgehaltenen
    # JSON-Datei im KBA-FeatureServer-Format ({"features":[{"attributes":{...}}]}).
    # None = der Batch holt den Datensatz direkt keylos vom KBA-Statistikportal.
    # Per INFRANODE_KBA_SOURCE_PATH ueberschreibbar. NICHT im Request-Pfad.
    kba_source_path: str | None = None
    # Unfallatlas-Bulk-Ingest (DATA-29): optionaler Pfad zu einer lokal
    # vorgehaltenen CSV-ZIP (Unfallorte<JAHR>_EPSG25832_CSV.zip). None = der Batch
    # holt das juengste Jahr keylos von opengeodata.nrw.de. NICHT im Request-Pfad.
    unfallatlas_source_path: str | None = None
    # INKAR-Bulk-Ingest (DATA-32): optionaler Pfad zu einer lokal vorgehaltenen
    # JSON-Datei (vorab geholte Indikator-Zeilenliste). None = der Batch holt die
    # Indikatoren live von www.inkar.de. NICHT im Request-Pfad.
    inkar_source_path: str | None = None
    # BORIS-Bulk-Ingest (DATA-35): optionaler Pfad zu einer lokal vorgehaltenen
    # JSON-Datei (vorab aggregierte Stadt-Zeilenliste). None = der Batch holt die
    # Bodenrichtwerte live von den Landes-WFS (BORIS_WFS). NICHT im Request-Pfad.
    boris_source_path: str | None = None

    # Optionaler Override des Upstream-User-Agents (RES-05). None = die
    # USER_AGENT-Konstante aus infra/http.py greift; per INFRANODE_HTTP_USER_AGENT
    # ueberschreibbar (z.B. fuer Staging-Kennzeichnung).
    http_user_agent: str | None = None

    # Wurzelpfad des lokalen Datenverzeichnisses. Per INFRANODE_ARCHIVE_DIR
    # ueberschreibbar, damit Tests nach tmp_path schreiben statt ins echte data/.
    # (Feld-/Env-Name aus Kompatibilitaetsgruenden unveraendert.)
    archive_dir: str = "data/archive"

    # Phase 16: Monitoring/Alarmierung/Selbstheilung (OPS-06/07/08). Notifier-Kanaele
    # (ntfy + E-Mail), Dead-Man-Ping und externer Liveness-Ping. Token und Passwort
    # sind SecretStr | None = None (fail-closed: ohne Wert kein Versand, kein Secret
    # im Code/Log). Alles uebrige als str/bool/int mit konservativen Defaults. Env-
    # Prefix INFRANODE_ greift automatisch ueber model_config.
    # ntfy: Push-Kanal. ntfy_topic ist faktisch ein Passwort (nur a-z/0-9/_/-).
    ntfy_url: str | None = None
    ntfy_topic: str | None = None
    ntfy_token: SecretStr | None = None
    # SMTP: E-Mail-Backup-Kanal. smtp_ssl=False = STARTTLS auf Port 587 (Default),
    # smtp_ssl=True = SMTP_SSL auf Port 465 (Decision SMTP-Transport-Modus).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    smtp_ssl: bool = False
    # Dead-Man-Ping (Kuma-Push bzw. Healthchecks.io) je Timer-Job; per systemd-Drop-in
    # ueberschreibbar. None = kein Ping.
    deadman_url: str | None = None
    # Dead-Man-Ping fuer den 08:00-Digest (CR-05): eigener Kuma-Push-Monitor
    # ("digest", ~26 h Heartbeat). run_digest pingt diese URL nach erfolgreichem
    # Versand; bleibt der Ping aus, alarmiert der Monitor. None = kein Ping (graceful).
    digest_deadman_url: str | None = None
    # Externer Box-Liveness-Ping (Finding 8): der Watchdog pingt diese URL am Ende
    # jedes erfolgreichen Laufs. Die URL traegt eine UUID und ist wie ein Secret zu
    # behandeln (nur via .env/systemd-Drop-in, nie ins Repo).
    healthchecks_url: str | None = None

    # Self-Heal-Reprobe (A, 2026-06-14): opt-in-Liste hart deaktivierter Quellen,
    # deren Upstream der Watchdog periodisch direkt anprobt, um beim Wiederaufleben
    # genau einen "X ist wieder reaktivierbar"-ntfy zu schicken. Format (komma-
    # separiert): ``source=https://probe.url,source2=https://probe.url2``. Nur fuer
    # Quellen, die man bei einer Stoerung BEWUSST per enable_*-Toggle abgeschaltet
    # hat (z.B. hamburg_verkehrslage); enabled gelassene Quellen heilen ohnehin ueber
    # den persistenten Breaker (Per-Source-Cooldown). Die Probe-URLs sind Owner-
    # kontrolliert (kein User-Input -> kein SSRF). Leer = Feature aus.
    selfheal_probes: str = ""


@lru_cache
def get_settings() -> Settings:
    """Singleton-Zugriff auf die Settings (gecached fuer den Prozess)."""
    return Settings()
