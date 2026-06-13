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
    # Whitelist statt "*" (REST-Regel 5). Phase 12: additiv um den Astro-Dev-
    # Port (4321) ergaenzt, damit die "Try it"-Konsole der Doku-Seite die Live-
    # API rein client-seitig aufrufen kann, ohne von der CORS-Policy still
    # blockiert zu werden (T-12-TRYIT-CORS). Doku + API liegen beide auf
    # infranode.dev. Nie "*"; per INFRANODE_CORS_ORIGINS ueberschreibbar.
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:4321",
        "https://infranode.dev",
    ]

    # Rate-Limit (API-06), limits/slowapi-Format ("<zahl>/<einheit>"). Die API ist
    # keylos/offen; limit_anon ist das IP-Budget fuer ALLE Clients (DoS-Schutz).
    limit_anon: str = "60/minute"
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
    enable_zensus: bool = False
    enable_divi: bool = False
    enable_mastr: bool = True
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
    enable_dortmund_parking: bool = False
    enable_kiel_zaehlstellen: bool = False
    enable_eround_charging: bool = False
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


@lru_cache
def get_settings() -> Settings:
    """Singleton-Zugriff auf die Settings (gecached fuer den Prozess)."""
    return Settings()
