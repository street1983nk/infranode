"""Diskriminierte Payload-Union der Normalisierungs-Library (CORE-01).

Die domänenspezifischen Nutzdaten variieren je Quelle. Ein ``kind``-Literal
diskriminiert die Union; pydantic wählt damit effizient das korrekte Modell und
erzeugt einen sauberen OpenAPI-Discriminator. Neue Quellen (Phase 7 bis 9)
ergänzen nur ein weiteres Payload-Modell mit eigenem ``kind`` und ein
Union-Mitglied, ohne Breaking Change am Envelope.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class CityBaseDataPayload(BaseModel):
    """Stammdaten je Stadt (Einwohner, Fläche)."""

    kind: Literal["city_base"] = "city_base"
    population: int | None = None
    area_km2: float | None = None


class AirQualityPayload(BaseModel):
    """Luftqualitaets-Messwerte je Stadt (UBA, Tier A).

    Erweitert um die real von UBA gelieferten Schadstoff-Parameter. Alle
    Felder optional, da nicht jede Messstation jeden Parameter liefert.
    ``station_id`` trägt die stabile Mess-/Detektor-ID je Messpunkt (ARCH-02)
    und dient als fachlicher Schlüssel für die deterministische ``record_id``.
    """

    kind: Literal["air_quality"] = "air_quality"
    station_id: str | None = None
    pm10: float | None = None
    no2: float | None = None
    pm25: float | None = None
    o3: float | None = None
    so2: float | None = None


class WeatherPayload(BaseModel):
    """Wetter-Messwerte je Stadt (DWD/Bright Sky, Tier A).

    Erweitert um Luftfeuchte, Windgeschwindigkeit und Wetterlage. Alle Felder
    optional, da Bright Sky je Station unterschiedlich vollständig liefert.
    ``station_id`` trägt die stabile Mess-/Detektor-ID je Messpunkt (ARCH-02)
    und dient als fachlicher Schlüssel für die deterministische ``record_id``.

    Einheiten: ``temperature_c`` in Grad Celsius, ``humidity`` in Prozent,
    ``wind_speed`` in km/h (Bright Sky liefert die Windgeschwindigkeit in km/h;
    Quelle ist das aktuellste Mittelungs-Fenster ``wind_speed_10``, siehe Audit K3).
    """

    kind: Literal["weather"] = "weather"
    station_id: str | None = None
    temperature_c: float | None = None
    humidity: float | None = None
    # Windgeschwindigkeit in km/h (Bright-Sky-Einheit), aus wind_speed_10/30/60.
    wind_speed: float | None = None
    condition: str | None = None


class PoiPayload(BaseModel):
    """POIs je Stadt, gefiltert nach Typ (OSM/Overpass, Tier B copyleft).

    ``items`` trägt je POI ein schlankes dict (z.B. name, lat, lon). Mutable
    Default über ``Field(default_factory=list)`` (kein ``=[]``, ruff B006).

    Ehrlichkeit bei Truncation (Audit K9): ``count`` ist IMMER die Anzahl der
    tatsächlich ausgelieferten ``items`` (die ggf. gedeckelte Stichprobe).
    ``total_available`` ist der ECHTE Gesamtbestand laut Quelle (Overpass
    ``out count;``); ``truncated`` ist True, wenn die Stichprobe gedeckelt wurde
    (``total_available`` > ``count``). Liefert die Quelle keinen Gesamtbestand,
    bleibt ``total_available`` ``None`` und ``truncated`` ``False``.
    """

    kind: Literal["poi"] = "poi"
    poi_type: str
    count: int
    total_available: int | None = None
    truncated: bool = False
    items: list[dict] = Field(default_factory=list)


class TrafficEventPayload(BaseModel):
    """Verkehrsereignisse je Stadt/Region (Autobahn-API, Tier A).

    Trennt Baustellen (``roadworks``) von Verkehrswarnungen (``warnings``).
    Mutable Defaults über ``Field(default_factory=list)`` (ruff B006).
    ``station_id`` trägt die stabile Detektor-/Abschnitts-ID je Messpunkt
    (ARCH-02) und dient als fachlicher Schlüssel für die deterministische
    ``record_id``; die feingranularen Einzel-Event-IDs liegen weiterhin je Event
    als ``identifier`` in ``roadworks``/``warnings``.
    """

    kind: Literal["traffic_event"] = "traffic_event"
    station_id: str | None = None
    roadworks: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    # DATA-08: Stau-/Verkehrslage-Verdichtung aus den ``warnings`` (Autobahn-
    # warning-Feed, INRIX). Jede congestion-relevante Warnung trägt zusätzlich ein
    # ``congestion``-Feld (level stau/stockend/dicht/unspezifisch, delay_minutes,
    # blocked); ``congestion_summary`` fasst sie je Stadt zusammen (count/stau/
    # stockend/blocked/max_delay_minutes). ``None`` = keine Stau-relevante Meldung.
    congestion_summary: dict | None = None


class TransitStopPayload(BaseModel):
    """ÖPNV-Haltestelle (DELFI/HVV GTFS). Geo liegt im CanonicalRecord.geo.

    Bildet eine GTFS-``stops.txt``-Zeile auf das kanonische Schema ab. Die
    Koordinaten wandern in ``CanonicalRecord.geo``; hier verbleiben die
    haltestellen-spezifischen GTFS-Felder. Alle Felder außer ``stop_id`` und
    ``stop_name`` sind optional, da GTFS-Feeds sie nicht durchgängig füllen.
    Keine mutable Listen-Felder (kein B006-Risiko).
    """

    kind: Literal["transit_stop"] = "transit_stop"
    stop_id: str
    stop_name: str
    location_type: int | None = None
    parent_station: str | None = None
    platform_code: str | None = None
    wheelchair_boarding: int | None = None


class ChargingStationPayload(BaseModel):
    """E-Ladesäulen-Standorte je Stadt (BNetzA, Tier A, nur Stammdaten).

    Bildet die stadt-gefilterte Teilmenge des CSV-Bulk-Downloads ab (Batch-
    Ingest ``ingest.bnetza``). ``stations`` trägt je Standort ein schlankes
    dict (operator, power_kw, lat, lon; additiv station_id/status/charging_type/
    points/plz/ort/connectors). Keine Belegung/Auslastung (bundesweit keine
    freie Tier-A-Echtzeitquelle). Mutable Default über
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["charging_station"] = "charging_station"
    count: int
    stations: list[dict] = Field(default_factory=list)


class WaterLevelPayload(BaseModel):
    """Pegelstand je Stadt (PEGELONLINE, Tier A, Teilabdeckung).

    Nur Städte an Bundeswasserstraßen liefern eine nahe Station. Binnenstädte
    ohne nahe Station tragen ``station=None`` (ehrliche Teilabdeckung, kein
    Fehler). Alle Felder optional.
    """

    kind: Literal["water_level"] = "water_level"
    station: str | None = None
    water: str | None = None
    value: float | None = None
    unit: str | None = None


class PowerPayload(BaseModel):
    """Strommarkt-Tageswert (SMARD, Tier A): Verbrauch (Netzlast) oder Day-ahead-Preis.

    Regionale Aufloesung: ``load`` liegt je Regelzone vor (``region`` =
    50Hertz/Amprion/TenneT/TransnetBW), ``price`` bundesweit (``region`` = DE).
    ``series_date`` ist der Tag des Werts (YYYY-MM-DD). Quelle ist die keylose
    SMARD-API der Bundesnetzagentur.
    """

    kind: Literal["power"] = "power"
    measure: Literal["load", "price"]
    value: float | None = None
    unit: str | None = None
    region: str | None = None
    series_date: str | None = None


class WeatherWarningPayload(BaseModel):
    """Amtliche DWD-Wetterwarnungen je Stadt (GeoNutzV, Tier A).

    ``max_level`` ist die höchste aktive REGULÄRE Warnstufe (0 = keine reguläre
    Warnung, 1-4 = DWD-Warnstufe); ``count`` die Anzahl aller aktiven Warnungen;
    ``warnings`` je Warnung ein dict (event/level/headline/start/end).

    KRITISCH (Audit K5): Der DWD führt Hitze-/UV-/Sonderwarnungen auf einer
    EIGENEN Skala (Code >= 50, z.B. 51 = starke Wärmebelastung). Diese fließen
    NICHT in ``max_level`` ein (sonst überstrahlt eine Hitzewarnung jede echte
    Sturm-Stufe), sondern werden separat in ``special_warnings`` mit ihrem echten
    Code geführt (Teilmenge von ``warnings``). Mutable Default via
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["weather_warning"] = "weather_warning"
    count: int = 0
    # Höchste reguläre Warnstufe 0-4; Sondercodes >= 50 sind hier ausgeschlossen.
    max_level: int | None = None
    warnings: list[dict] = Field(default_factory=list)
    special_warnings: list[dict] = Field(default_factory=list)


class FloodWarningPayload(BaseModel):
    """Hochwasser-Warnungen je Stadt (LHP, Tier A, Event-Layer).

    ``warnings`` trägt je kuratiertem Pegel ein dict (z.B. Warnstufe, Pegel).
    ``stand`` hält den Stand-Zeitstempel-Text der LHP-Antwort (Attributions-
    Pflicht, siehe Mapper). Mutable Default über ``Field(default_factory=list)``
    (ruff B006).
    """

    kind: Literal["flood_warning"] = "flood_warning"
    warnings: list[dict] = Field(default_factory=list)
    stand: str | None = None


class PollenUvPayload(BaseModel):
    """Pollenflug + UV-Index je Stadt (DWD opendata, Tier A, täglich).

    Daten sind nach DWD-Großregionen gegliedert, NICHT stadtgenau:
    ``region_id``/``region_name`` weisen die Großregion ehrlich aus. ``pollen``
    trägt je Pollenart die Belastungsstufen (today/tomorrow/dayafter). Mutable
    Default über ``Field(default_factory=dict)`` (ruff B006).
    """

    kind: Literal["pollen_uv"] = "pollen_uv"
    region_id: int | None = None
    region_name: str | None = None
    pollen: dict = Field(default_factory=dict)
    uv_index: float | None = None


class FireDangerPayload(BaseModel):
    """Waldbrand-/Graslandfeuerindex je Stadt (DWD, Tier A, taeglich).

    Daten sind STATIONS-genau, NICHT stadtgenau: ``station_name``/``distance_km``
    weisen die naechste DWD-Station ehrlich aus (Pitfall 4). ``wbi_level`` ist die
    Waldbrandgefahrenstufe 1..5 (1=sehr gering ... 5=sehr hoch), ``wbi_label`` das
    deutsche Klartext-Label. ``glfi_level``/``glfi_label`` tragen den
    Graslandfeuerindex (best-effort, kann ``None`` sein). ``forecast_date`` ist das
    Vorhersagedatum (ISO), ``updated_at`` der DWD-Aktualisierungszeitpunkt.
    """

    kind: Literal["fire_danger"] = "fire_danger"
    wbi_level: int | None = None
    wbi_label: str | None = None
    glfi_level: int | None = None
    glfi_label: str | None = None
    station_name: str | None = None
    station_id: str | None = None
    bundesland: str | None = None
    distance_km: float | None = None
    forecast_date: str | None = None
    updated_at: str | None = None


class BathingWaterPayload(BaseModel):
    """Badegewaesserqualitaet im Umkreis einer Stadt (EEA, Tier A, jaehrlich).

    Daten je Badestelle aus der EU-Badegewaesserrichtlinie 2006/7/EG (EEA
    DiscoMap), gefiltert auf einen Umkreis um die Stadt (Pitfall 4: ortsnah, nicht
    stadtgenau, ``distance_km`` je Stelle). ``season_year`` ist die bewertete
    Badesaison. ``counts`` zaehlt die Qualitaetsklassen (Excellent/Good/
    Sufficient/Poor/not_classified). ``sites`` listet je Stelle Name, Klasse,
    Gewaessertyp, Koordinaten, Distanz und Profil-Link. Mutable Defaults ueber
    ``Field(default_factory=...)`` (ruff B006).
    """

    kind: Literal["bathing_water"] = "bathing_water"
    season_year: int | None = None
    count: int = 0
    counts: dict = Field(default_factory=dict)
    sites: list[dict] = Field(default_factory=list)
    truncated: bool = False


class HospitalAtlasPayload(BaseModel):
    """Krankenhausstandorte im Umkreis einer Stadt (Bundes-Klinik-Atlas).

    Standortgenaue Liste (Name, Adresse, Betten, Kontakt, Koordinaten) aus dem
    Bundes-Klinik-Atlas (BMG/IQTIG). FAIL-CLOSED: Lizenz nicht ausgewiesen ->
    license_id UNKNOWN, Tier C (live-only, kein Archiv) und Quelle per Default
    deaktiviert, bis die Lizenz bestaetigt ist. Daten ortsnah gefiltert (Pitfall 4,
    ``distance_km`` je Standort). Mutable Defaults via ``Field(default_factory=...)``.
    """

    kind: Literal["hospital_atlas"] = "hospital_atlas"
    count: int = 0
    total_beds: int | None = None
    truncated: bool = False
    hospitals: list[dict] = Field(default_factory=list)


class StationFacilityPayload(BaseModel):
    """Aufzug-/Rolltreppen-Status an Bahnhoefen einer Stadt (DB FaSta, Tier A).

    Echtzeit-Barrierefreiheit: je Anlage Typ (ELEVATOR/ESCALATOR), Status
    (ACTIVE/INACTIVE/UNKNOWN) + Begruendung, Bahnhofsnummer, Koordinaten und
    Distanz. ``counts`` zaehlt je Status. Anlagen liegen an Bahnhoefen im
    Stadtgebiet (Bbox-Filter, Pitfall 4: ``distance_km`` je Anlage). Mutable
    Defaults via ``Field(default_factory=...)``.
    """

    kind: Literal["station_facilities"] = "station_facilities"
    count: int = 0
    counts: dict = Field(default_factory=dict)
    facilities: list[dict] = Field(default_factory=list)
    truncated: bool = False


class DemographicsPayload(BaseModel):
    """Demografie-Zeitreihen je Stadt (GENESIS/Zensus, Tier A, DATA-17).

    Stammwerte (Einwohner, Haushalte, Gebäude, Durchschnittsmiete) plus eine
    optionale Zeitreihe je Stichjahr in ``series``. Mutable Liste IMMER via
    ``Field(default_factory=list)`` (ruff B006). ``reference_year`` trägt das
    Stichjahr der Stammwerte, die Punkte in ``series`` ihre eigenen Jahre.
    """

    kind: Literal["demographics"] = "demographics"
    population: int | None = None
    households: int | None = None
    buildings: int | None = None
    rent_avg: float | None = None
    reference_year: int | None = None
    series: list[dict] = Field(default_factory=list)


class EnergyAssetPayload(BaseModel):
    """Energie-Anlagen je Stadt (MaStR, Tier A, DATA-18).

    Aggregierte Anlagenzahl plus Aufschlüsselung je Typ (pv/wind/speicher/
    biogas) und die schlanken Einzel-Anlagen-dicts in ``assets``. Mutable
    Defaults IMMER via ``Field(default_factory=...)`` (ruff B006).
    """

    kind: Literal["energy_asset"] = "energy_asset"
    count: int
    by_type: dict = Field(default_factory=dict)
    # Aggregierte installierte Nettonennleistung in kW (Summe ``leistung_kw`` über
    # alle Anlagen) plus Aufschlüsselung je Typ. ``None``/leer, wenn keine Anlage
    # eine Leistung trägt (ehrliche Null statt 0.0). Wichtigste MaStR-Kennzahl.
    total_power_kw: float | None = None
    power_by_type: dict = Field(default_factory=dict)
    assets: list[dict] = Field(default_factory=list)


class AccidentPayload(BaseModel):
    """Strassenverkehrsunfaelle je Kreis (Unfallatlas, Tier A, DATA-29).

    Jahres-Aggregat der amtlichen Unfallstatistik mit Personenschaden je Kreis/
    kreisfreie Stadt (``district_key`` = 5-stelliger Kreisschlüssel). ``total``
    = Unfälle gesamt; ``fatal``/``serious``/``light`` = nach Unfallkategorie
    (1=mit Getöteten, 2=mit Schwerverletzten, 3=mit Leichtverletzten);
    ``with_bicycle``/``with_pedestrian``/``with_car``/``with_motorcycle`` =
    Anzahl Unfälle mit Beteiligung der jeweiligen Verkehrsart. ``reference_year``
    trägt das Berichtsjahr (Unfallatlas ist jährlich).
    """

    kind: Literal["accident"] = "accident"
    reference_year: int | None = None
    total: int | None = None
    fatal: int | None = None
    serious: int | None = None
    light: int | None = None
    with_bicycle: int | None = None
    with_pedestrian: int | None = None
    with_car: int | None = None
    with_motorcycle: int | None = None
    district_key: str | None = None


class RegionalStatPayload(BaseModel):
    """Regionalstatistik-Kennzahl je Kreis (GENESIS, Tier A, DATA-28).

    Generischer Träger für das GENESIS-Trio (Arbeitslosenquote, Tourismus/
    Übernachtungen, Bautaetigkeit/Baugenehmigungen). ``dataset`` benennt den
    Datensatz (unemployment/tourism/construction), ``values`` hält je Kennzahl
    einen Wert (z.B. arbeitslose/arbeitslosenquote). Regionale Auflösung ist der
    Kreis/die kreisfreie Stadt; ``region_name`` weist ihn ehrlich aus. Die
    Regionalstatistik führt diese Tabellen je Kreis als Jahreswert ->
    ``reference_year`` trägt das Berichtsjahr. Mutable Default via
    ``Field(default_factory=dict)`` (ruff B006).
    """

    kind: Literal["regional_stat"] = "regional_stat"
    dataset: str
    reference_year: int | None = None
    region_name: str | None = None
    values: dict = Field(default_factory=dict)


class VehicleRegistrationPayload(BaseModel):
    """Pkw-Bestand + Elektro-Anteil je Stadt (KBA, Tier A, DATA-27).

    Quelle ist das Kraftfahrt-Bundesamt (FZ Pkw mit Elektroantrieb je
    Zulassungsbezirk). Regionale Auflösung ist der Zulassungsbezirk, der sich mit
    dem Kreis/der kreisfreien Stadt deckt (``district``/``district_key`` weisen
    ihn ehrlich aus): für kreisfreie Städte stadtgenau, für übrige Städte der
    umgebende Kreis. ``electric_share``/``bev_share``/``plugin_hybrid_share`` sind
    Anteile in Prozent; ``bev_estimated`` ist die aus ``pkw_total`` und
    ``bev_share`` abgeleitete absolute BEV-Zahl (das KBA führt im Datensatz nur
    Anteile, keine Absolutwerte). ``reference_period`` ist der Berichtszeitpunkt
    (Format JJJJ.MM).
    """

    kind: Literal["vehicle_registration"] = "vehicle_registration"
    pkw_total: int | None = None
    electric_share: float | None = None
    bev_share: float | None = None
    plugin_hybrid_share: float | None = None
    bev_estimated: int | None = None
    district: str | None = None
    district_key: str | None = None
    reference_period: str | None = None


class AdminBoundaryPayload(BaseModel):
    """Verwaltungsgrenze je Stadt (BKG VG250, Tier A, DATA-19).

    Attributtabellen-Auszug (AGS, Gemeindename, Fläche) ohne Geometrie-Body
    (kein GDAL/geopandas, RESEARCH Pitfall 3). Alle Felder optional.
    """

    kind: Literal["admin_boundary"] = "admin_boundary"
    ags: str | None = None
    gen_name: str | None = None
    area_km2: float | None = None
    reference_year: int | None = None


class ElectionResultPayload(BaseModel):
    """Wahlergebnis je Stadt/Kreis (Bundeswahlleiterin, Tier A, DATA-20).

    ``granularity`` weist die Abdeckung ehrlich aus: "stadt" = stadtgenau aus den
    Wahlkreisen der Stadt aggregiert (saubere Wahlkreis-Vereinigung, Audit-Finding
    47); "teilweise" (Default) = Wahlkreis/Kreis-Ebene, Stadt nur teilweise
    (RESEARCH Pitfall 7). Mutable Liste IMMER via ``Field(default_factory=list)``
    (ruff B006).
    """

    kind: Literal["election_result"] = "election_result"
    election: str | None = None
    granularity: str = "teilweise"
    area_name: str | None = None
    # [VERIFIED 2026-06-10] Wahlbeteiligung aus der kerg2-Zeile
    # Gruppenname=="Wählende", Spalte Prozent (String mit Dezimal-KOMMA,
    # z.B. "82,5122"); additiv ergänzt, nicht brechend.
    turnout: str | None = None
    results: list[dict] = Field(default_factory=list)


class HolidayPayload(BaseModel):
    """Feiertage und Schulferien je Bundesland (Seed, gemeinfrei, DATA-21).

    Aus dem eingebetteten Seed je ``state`` aufgelöst, NICHT permissiv lizenziert
    (Gratis-Reichweiten-Feature). Mutable Listen IMMER via
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["holiday"] = "holiday"
    state: str | None = None
    year: int | None = None
    holidays: list[dict] = Field(default_factory=list)
    school_holidays: list[dict] = Field(default_factory=list)


class HospitalPayload(BaseModel):
    """Krankenhaus-Stammdaten je Stadt (Destatis-Verzeichnis, Tier A, DATA-25a).

    Aggregierte Anzahl plus schlanke Einzel-Krankenhaus-dicts. Custom-Lizenz-
    Wortlaut im Mapper (RESEARCH Pitfall 6). Mutable Liste IMMER via
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["hospital"] = "hospital"
    count: int
    hospitals: list[dict] = Field(default_factory=list)
    reference_date: str | None = None


class IcuCapacityPayload(BaseModel):
    """Intensivbetten-Kapazität je Kreis (DIVI, Tier C live-only, DATA-25b).

    Klinikscharfes DB-Schutzrecht -> Tier C, nur Live-Anzeige (RESEARCH Pitfall 4).
    Alle Felder optional. ``beds_free``/``beds_occupied`` trägt nur noch das
    Tier-A-Kreis-Aggregat (RKI-DIVI-CSV, mappers/divi.py); die Live-API liefert
    [VERIFIED 2026-06-10] KEINE numerische Belegung mehr, sondern qualitative
    Status-Einschätzungen je Klinik in ``hospitals`` (bezeichnung, ort,
    letzte_meldung, status_high_care, status_ecmo). Additiv erweitert (nicht
    brechend); mutable Liste IMMER via ``Field(default_factory=list)``
    (ruff B006).
    """

    kind: Literal["icu_capacity"] = "icu_capacity"
    kreis_id: str | None = None
    kreis_name: str | None = None
    beds_free: int | None = None
    beds_occupied: int | None = None
    hospitals: list[dict] = Field(default_factory=list)
    datum: str | None = None


class RoadEventPayload(BaseModel):
    """Innerstaedtische Baustellen + Sperrungen je Stadt (DATA-15, Tier A).

    Bündelt die Pro-Stadt-Verkehrsereignisse (Berlin VIZ, Hamburg, Köln,
    München, MobiData BW) zu einer einheitlichen Liste schlanker Event-dicts.
    ``city_source`` weist die konkrete Quelle aus (berlin_viz/hamburg_baustellen/
    koeln_verkehr/muenchen_baustellen/mobidata_bw). Keine strikte Geometry-
    Validierung im Schema (Berlin liefert GeometryCollection, RESEARCH Pitfall 6):
    je Event ein schlankes dict. Mutable Liste IMMER via
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["road_event"] = "road_event"
    city_source: str | None = None
    events: list[dict] = Field(default_factory=list)


class WebcamPayload(BaseModel):
    """Autobahn-Webcams je Stadt (DATA-22, Tier A).

    Erweitert den keylosen Autobahn-Adapter um den webcam-Sub-Service:
    Koordinaten + Bild-URLs der Webcams im BBox um die Stadt. ``count`` trägt die
    Anzahl, ``webcams`` je Cam ein schlankes dict (imageurl/coordinate/title).
    Mutable Liste IMMER via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["webcam"] = "webcam"
    count: int
    webcams: list[dict] = Field(default_factory=list)


class EventPayload(BaseModel):
    """Stadt-Events und Veranstaltungen je Stadt (DATA-16, Tier A/B gemischt).

    Bündelt die Pro-Stadt-Veranstaltungen (destination.one/eT4.META,
    Köln-Events-Feed) zu einer einheitlichen Liste schlanker Event-dicts.
    ``city_source`` weist die konkrete Quelle aus (destination_one/koeln_events).
    Das Lizenz-Tier wird je Record aus ``map_license`` abgeleitet (GOV-04), nicht
    im Payload getragen: ein CC-BY-SA-Event trägt damit Tier B, ein
    CC0/CC-BY-Event Tier A. Je Event ein schlankes dict (title/date_from/
    date_to/location/...). Mutable Liste IMMER via ``Field(default_factory=list)``
    (ruff B006).
    """

    kind: Literal["event"] = "event"
    city_source: str | None = None
    events: list[dict] = Field(default_factory=list)


class TrafficFlowPayload(BaseModel):
    """Live-Verkehrslage je Streckenabschnitt (Mobilithek DATEX-II V2, Phase 20).

    Quelle: Köln MeasuredDataPublication (minutenfrisch). ``station_id`` trägt
    die measurementSiteReference-ID; ``measurements`` je Messpunkt ein schlankes
    dict (z.B. speed/flow/observed_at). Reine Live-Daten (Tier C, kein Archiv).
    Mutable Liste IMMER via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["traffic_flow"] = "traffic_flow"
    station_id: str | None = None
    measurements: list[dict] = Field(default_factory=list)
    # Additiv (Phase 26): optionale Netz-Zusammenfassung für flächige Quellen wie
    # Hamburg-Verkehrslage (``total`` + ``by_state``-Zählung je Zustandsklasse).
    # Default None -> die station-basierten Quellen (Köln) bleiben unverändert.
    summary: dict | None = None


class ParkingPayload(BaseModel):
    """Live-Parkhaus-Belegung je Stadt (Mobilithek DATEX-II V2, Phase 20).

    Quelle: Dortmund Parkleitsystem dynamisch (ParkingStatusPublication).
    ``facilities`` je Parkhaus ein schlankes dict (z.B. name, free, capacity,
    occupancy, observed_at). Reine Live-Daten (kein Archiv). Mutable Liste IMMER
    via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["parking"] = "parking"
    facilities: list[dict] = Field(default_factory=list)


class CountStationPayload(BaseModel):
    """Live-Zählstellen-Daten je Stadt (Mobilithek DATEX-II V2, Phase 20).

    Quelle: Kiel MIV-Dauerzählstellen + Radzähler (stündlich). ``counts`` je
    Zählstelle ein schlankes dict (z.B. station, value, vehicle_type,
    observed_at). Reine Live-Daten (kein Archiv). Mutable Liste IMMER via
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["count_station"] = "count_station"
    counts: list[dict] = Field(default_factory=list)


class ChargingStatusPayload(BaseModel):
    """Live-Ladesäulen-Belegung je Stadt (Mobilithek DATEX-II V3, Phase 20).

    Quelle: eRound AFIR-Recharging dynamisch (EnergyInfrastructureStatus-
    Publication, V3). Schließt die bekannte Lücke DATA-09 (bisher keine freie
    Echtzeit-Ladesäulenbelegung). ``points`` je Ladepunkt ein schlankes dict
    (z.B. refill_point_id, status, observed_at). Lizenz VOR Einbau verifizieren
    (Plan 07). Mutable Liste IMMER via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["charging_status"] = "charging_status"
    points: list[dict] = Field(default_factory=list)


class TransitDeparturePayload(BaseModel):
    """Live-Abfahrten je Halt mit Verspätung (GTFS-RT, Phase 19).

    Quelle: gtfs.de bzw. Mobilithek-DELFI Trip Updates (protobuf). Tier B
    (CC-BY-SA), reine Live-Daten, KEIN Archiv (T-20-ARCHIVE). ``stop_id`` trägt
    die GTFS-Halt-ID; ``departures`` je Abfahrt ein schlankes dict (z.B. route,
    trip_id, delay_s, planned, expected). Mutable Liste IMMER via
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["transit_departure"] = "transit_departure"
    stop_id: str | None = None
    departures: list[dict] = Field(default_factory=list)


class TransitTripPayload(BaseModel):
    """Live-Fahrt-Detail inkl. geschätzter Position (GTFS-RT, Phase 19).

    Quelle: gtfs.de bzw. Mobilithek-DELFI Trip Updates (protobuf). Tier B
    (CC-BY-SA), reine Live-Daten, KEIN Archiv. ``delay_s`` ist die aktuelle
    Verspätung in Sekunden (positiv = verspätet); ``estimated_position`` ist die
    linear interpolierte Schätzung ({lat, lon, estimated=True, between}).
    ``unresolved`` ist True, wenn die trip_id nicht gegen das statische GTFS
    auflösbar war (ehrlich statt 500, RESEARCH Pitfall 4). Mutable Liste IMMER
    via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["transit_trip"] = "transit_trip"
    trip_id: str
    route_id: str | None = None
    delay_s: int | None = None
    estimated_position: dict | None = None
    stop_time_updates: list[dict] = Field(default_factory=list)
    unresolved: bool = False


class TransitRouteStatusPayload(BaseModel):
    """Live-Verspätungslage einer Linie (GTFS-RT, Phase 19).

    Quelle: gtfs.de bzw. Mobilithek-DELFI Trip Updates (protobuf). Tier B
    (CC-BY-SA), reine Live-Daten, KEIN Archiv. Aggregiert die aktiven Fahrten
    einer Linie: ``active_trips`` Anzahl, ``avg_delay_s``/``max_delay_s`` die
    Verspätungs-Kennzahlen, ``trips`` je Fahrt ein schlankes dict. Mutable Liste
    IMMER via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["transit_route_status"] = "transit_route_status"
    route_id: str | None = None
    active_trips: int = 0
    avg_delay_s: float | None = None
    max_delay_s: int | None = None
    trips: list[dict] = Field(default_factory=list)


class FuelPricePayload(BaseModel):
    """Aggregierte Spritpreise je Stadt (Tankerkoenig/MTS-K, Tier A, DATA-30).

    Verdichtet die einzelnen Tankstellen im Umkreis (``radius_km``) der
    Stadtkoordinate zu einer Stadt-Kennzahl: ``avg_*``/``min_*`` sind Durchschnitt
    bzw. Minimum je Sorte (e5/e10/diesel, EUR/Liter) über die geöffneten
    Tankstellen mit gültigem Preis. ``station_count`` = Tankstellen im Radius,
    ``open_count`` = davon geöffnet. ``stations`` trägt je Tankstelle ein
    schlankes dict (station_id/name/brand/e5/e10/diesel/is_open/dist_km). Quelle:
    Markttransparenzstelle für Kraftstoffe (MTS-K) via Tankerkönig. Mutable
    Default via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["fuel_price"] = "fuel_price"
    radius_km: float | None = None
    station_count: int = 0
    open_count: int = 0
    avg_e5: float | None = None
    avg_e10: float | None = None
    avg_diesel: float | None = None
    min_e5: float | None = None
    min_e10: float | None = None
    min_diesel: float | None = None
    stations: list[dict] = Field(default_factory=list)


class SharingPayload(BaseModel):
    """Bike-/Scooter-Sharing-Snapshot je Stadt (GBFS, Tier A, DATA-33).

    Verdichtet die offenen GBFS-Feeds der kuratierten Tier-A-Anbieter (Primär
    Nextbike, CC0) im Stadtgebiet zu einer Live-Kennzahl. ``vehicles_available`` =
    insgesamt verfügbare Fahrzeuge (``free_floating_available`` frei abgestellt +
    ``docked_available`` an Stationen). ``station_count`` = Stationen im Stadtgebiet.
    ``providers`` trägt je akzeptiertem GBFS-System ein schlankes dict (provider/
    operator/system_id/license_id/free_floating_available/docked_available/
    station_count/stations) - inkl. der pro System fail-closed verifizierten
    Tier-A-``license_id`` (GOV-02/04). Mutable Default via
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["sharing"] = "sharing"
    radius_km: float | None = None
    vehicles_available: int = 0
    free_floating_available: int = 0
    docked_available: int = 0
    station_count: int = 0
    providers: list[dict] = Field(default_factory=list)


class IndicatorsPayload(BaseModel):
    """Kuratierte sozialökonomische Indikatoren je Stadt (INKAR/BBSR, Tier A, DATA-32).

    Bündelt ein breites Set INKAR-Kennzahlen (Arbeitsmarkt, Wirtschaft, Einkommen,
    Demografie, Wohnen, Erreichbarkeit, Verkehr, Bildung, Gesundheit, Fläche) je
    Kreis/kreisfreie Stadt zu einer Liste schlanker dicts. ``indicators`` trägt je
    Indikator ``gruppe`` (INKAR-Variablen-ID), ``name`` (inkl. Einheit, z.B. "...
    in %"), ``value`` (jüngster Jahreswert), ``year`` und ``category``.
    ``indicator_count`` = Anzahl gelieferter Indikatoren. Regionale Auflösung ist
    der Kreis (kreisfreie Städte stadtgenau, sonst der umgebende Kreis). Mutable
    Default via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["indicators"] = "indicators"
    indicator_count: int = 0
    indicators: list[dict] = Field(default_factory=list)


class CrimeStatsPayload(BaseModel):
    """Polizeiliche Kriminalstatistik je Kreis (BKA PKS, Tier A, PKS-01).

    Bündelt je Hauptstraftatengruppe die amtlichen Kennzahlen der Kreis-
    Falltabelle des Bundeskriminalamts zu einer Liste schlanker dicts. ``groups``
    trägt je Gruppe ``key`` (Straftatenschlüssel, z.B. "------" =
    "Straftaten insgesamt"), ``label`` (Klartext), ``cases`` (erfasste Fälle),
    ``frequency_per_100k`` (Häufigkeitszahl HZ je 100.000 Einwohner) und
    ``clearance_rate_pct`` (Aufklärungsquote in Prozent). Regionale Auflösung
    ist der Kreis (kreisfreie Städte stadtgenau, sonst der umgebende Kreis).
    ``reference_year`` (Berichtsjahr) und ``version`` (PKS-Stand) sind
    Attributionspflicht-Felder: das BKA verlangt die Angabe von Berichtsjahr und
    Version. Sperr-/Leerwerte werden zu ``null`` (nie 0 erfunden). Mutable
    Default via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["crime_stats"] = "crime_stats"
    reference_year: int | None = None
    version: str | None = None
    groups: list[dict] = Field(default_factory=list)


class StationDeparturesPayload(BaseModel):
    """Live-Abfahrtstafel des Stadt-Hauptbahnhofs (DB Timetables, Tier A, DATA-34).

    Bündelt die nächsten Zugabfahrten am Haupt-Bahnhof einer Stadt (alle
    Gattungen inkl. Echtzeit-Verspätung) zu einer Liste schlanker dicts.
    ``departures`` trägt je
    Abfahrt ``line`` (z.B. "ICE 73"/"RB22"), ``category`` (ICE/IC/RE/RB/S),
    ``train_number``, ``long_distance`` (Fernverkehr-Flag), ``destination``,
    ``planned_time`` (ISO), ``platform``, ``delay_minutes`` (None = keine Echtzeit),
    ``cancelled`` und ``messages`` (Stoerungen/Hinweise je Abfahrt: Liste aus
    ``{type, code, category, timestamp}``). ``departure_count`` = Anzahl,
    ``long_distance_count`` =
    davon Fernverkehr. Quelle: DB Timetables (CC BY 4.0). Mutable Default via
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["station_departures"] = "station_departures"
    departure_count: int = 0
    long_distance_count: int = 0
    departures: list[dict] = Field(default_factory=list)


class StationArrivalsPayload(BaseModel):
    """Live-Ankunftstafel des Stadt-Hauptbahnhofs (DB Timetables, Tier A, DATA-34).

    Spiegelbild zu ``StationDeparturesPayload`` für ankommende Züge. ``arrivals``
    trägt je Ankunft ``line``, ``category``, ``train_number``, ``long_distance``,
    ``origin`` (Startbahnhof = erstes ppth-Glied), ``planned_time`` (ISO),
    ``platform``, ``delay_minutes`` (None = keine Echtzeit), ``cancelled`` und
    ``messages`` (Stoerungen/Hinweise je Ankunft: Liste aus
    ``{type, code, category, timestamp}``).
    ``arrival_count`` = Anzahl, ``long_distance_count`` = davon Fernverkehr. Quelle:
    DB Timetables (CC BY 4.0). Mutable Default via ``Field(default_factory=list)``.
    """

    kind: Literal["station_arrivals"] = "station_arrivals"
    arrival_count: int = 0
    long_distance_count: int = 0
    arrivals: list[dict] = Field(default_factory=list)


class StationCatalogPayload(BaseModel):
    """Bahnhofs-Katalog einer Stadt (StaDa Station Data, Tier A, DATA-36).

    Listet ALLE DB-Bahnhöfe im Stadtgebiet (Zuordnung über den amtlichen
    Gemeindeschluessel: StaDa ``municipalityCode`` == Stadt-``ags``), nicht nur
    den Fernverkehrs-Hbf. Je Bahnhof trägt ``stations`` ein schlankes dict mit
    ``eva`` (Haupt-EVA-Nummer, für die Per-Bahnhof-Boards
    ``/stations/{eva}/departures``), ``evas`` (ALLE EVA-Nummern des Bahnhofs;
    Großbahnhöfe haben mehrere Ebenen, deren Abfahrtstafel teils an einer
    Ebenen-EVA hängt statt an der Haupt-EVA -> Fallback für Split-Bahnhöfe),
    ``name``, ``category`` (1-7, je kleiner desto
    groesser/wichtiger der Bahnhof), ``lat``/``lon`` (aus der EVA-Geokoordinate)
    und ``zip`` (PLZ). ``station_count`` = Anzahl. Quelle: DB StaDa (CC BY 4.0).
    Mutable Default via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["station_catalog"] = "station_catalog"
    station_count: int = 0
    stations: list[dict] = Field(default_factory=list)


class LandValuesPayload(BaseModel):
    """Aggregierte Bodenrichtwerte je Stadt (BORIS, Tier A, DATA-35).

    Verdichtet die amtlichen Bodenrichtwert-Bauland-Zonen (BORIS, Bodenrichtwert-
    Informationssystem der Gutachterausschüsse; Bauland = Wohnen/Misch/Gewerbe,
    ohne Wald/Wasser/Landwirtschaft) im Stadtgebiet zu einer
    Kennzahl: ``brw_median_eur_m2`` (Median des Bodenrichtwerts in EUR/m2),
    ``brw_min_eur_m2``/``brw_max_eur_m2`` (Spanne) und ``zone_count`` (Anzahl der
    berücksichtigten Zonen). ``stichtag`` ist der Bewertungsstichtag des
    Landes-WFS (ISO-Datum, z.B. "2026-01-01"). ``bbox_radius_deg`` dokumentiert
    den Umkreis um das Stadtzentrum, über den aggregiert wurde (ehrliche
    Methoden-Transparenz: kein amtlicher Stadtgrenzen-Schnitt, sondern eine
    Bounding-Box). Regionale Auflösung ist das Stadtgebiet; BORIS ist pro
    Bundesland föderiert (ein Landes-WFS deckt alle Städte des Landes ab).
    """

    kind: Literal["land_values"] = "land_values"
    brw_median_eur_m2: float | None = None
    brw_min_eur_m2: float | None = None
    brw_max_eur_m2: float | None = None
    zone_count: int = 0
    stichtag: str | None = None
    bbox_radius_deg: float | None = None
    # True, wenn die Werte NORMIERTE Bodenrichtwerte sind (auf 1000 m2/GFZ 1.0
    # normiert, z.B. Hamburg): grober Indikator, NICHT cross-city-vergleichbar und
    # nicht zur Wertermittlung geeignet (Methoden-Transparenz, Audit 2026-06-29).
    normalized: bool = False
    # True, wenn der WFS-Seiten-Cap erreicht wurde und die Aggregation NICHT alle
    # Bauland-Zonen umfasst (nur Live-Pfad; Archiv-/Ingest-Zeilen führen das Feld
    # nicht -> Default False). Methoden-Transparenz, Audit 2026-06-29.
    truncated: bool = False


class PopulationDensityPayload(BaseModel):
    """Einwohnerdichte je Stadt aus dem Zensus-2022-100m-Gitter (Tier A).

    Aggregiert EXAKT über die Gitterzellen mit der Stadt-AGS (kein Bounding-Box-
    Schnitt): ``population`` (Summe der Einwohner über alle bewohnten Zellen),
    ``populated_cells`` (Zahl der bewohnten 100m-Zellen), ``populated_area_km2``
    (= ``populated_cells`` * 0.01) und ``density_per_km2`` (Einwohner je km2 über
    die BEWOHNTE Fläche, nicht die Gesamtfläche der Stadt; ehrliche Methoden-
    Transparenz, da Wald/Wasser/unbewohnte Zellen ausgeklammert sind). ``grid``
    nennt die Auflösung, ``reference_year`` das Zensus-Jahr.
    """

    kind: Literal["population_density"] = "population_density"
    population: int | None = None
    populated_cells: int = 0
    populated_area_km2: float | None = None
    density_per_km2: float | None = None
    grid: str = "100m"
    reference_year: int = 2022


class TaxRatesPayload(BaseModel):
    """Realsteuer-Hebesätze einer Gemeinde (Regionalstatistik 71231, Tier A, DATA-37).

    Die amtlichen Hebesätze der Realsteuern GEMEINDE-genau (Realsteuervergleich
    der Statistischen Ämter, Tabelle 71231): ``gewerbesteuer_hebesatz`` (Hebesatz
    der Gewerbesteuer in %), ``grundsteuer_a`` (land-/forstwirtschaftliche
    Betriebe), ``grundsteuer_b`` (Grundstücke) und ``grundsteuer_c`` (baureife,
    unbebaute Grundstücke; erst seit 2025 möglich, daher oft ``None``). Alle
    Werte sind ganze Prozentpunkte; ein nicht festgesetzter Satz ist ``None``
    (Quelle-Sperrwert "-"). ``stichtag`` ist der Bewertungsstichtag (ISO-Datum,
    Stand 31.12., neuester verfügbarer Jahrgang). Standort-/immobilienrelevante
    Kennzahl, die kaum anderswo als API gemeindegenau vorliegt.
    """

    kind: Literal["tax_rates"] = "tax_rates"
    gewerbesteuer_hebesatz: int | None = None
    grundsteuer_a: int | None = None
    grundsteuer_b: int | None = None
    grundsteuer_c: int | None = None
    stichtag: str | None = None


class BusinessRegistrationsPayload(BaseModel):
    """Gewerbean-/-abmeldungen je Kreis (Regionalstatistik 52311, Tier A, DATA-37).

    Die Gründungsdynamik aus der Gewerbeanzeigenstatistik (Tabelle 52311,
    Jahressumme, KREIS-genau, ohne Automatenaufsteller): ``anmeldungen``
    (Gewerbeanmeldungen), ``abmeldungen`` (Gewerbeabmeldungen) und ``saldo``
    (anmeldungen - abmeldungen; positiv = Netto-Gründungsplus). ``jahr`` ist das
    Berichtsjahr (neuester Jahrgang, für den beide Kennzahlen vorliegen).
    Regionale Auflösung ist der Kreis/die kreisfreie Stadt (kreisfreie Städte
    stadtgenau, sonst der umgebende Kreis).
    """

    kind: Literal["business_registrations"] = "business_registrations"
    anmeldungen: int | None = None
    abmeldungen: int | None = None
    saldo: int | None = None
    jahr: int | None = None


class InsolvenciesPayload(BaseModel):
    """Beantragte Insolvenzen je Kreis (Regionalstatistik 52411, Tier A, INSO-01).

    Aus der Insolvenzstatistik der Statistischen Ämter (Tabelle 52411,
    Jahressumme, KREIS-genau): ``unternehmensinsolvenzen`` (beantragte
    Unternehmensinsolvenzen, Tabelle 52411-02, Measure ISV006) und
    ``uebrige_schuldner_insolvenzen`` (beantragte Insolvenzen übriger Schuldner,
    Tabelle 52411-03, Measure ISV007). ``jahr`` ist das Berichtsjahr (neuester
    Jahrgang, für den BEIDE Kennzahlen vorliegen).

    Ehrliche Benennung (RESEARCH Pitfall 2): die übrigen Schuldner sind NICHT
    deckungsgleich mit Verbrauchern. Sie umfassen Verbraucher, ehemalige
    Selbstständige und sonstige natürliche Personen; reine Verbraucher
    (ISV004) sind nur eine Teilmenge und auf Kreisebene nicht durchgängig
    verfügbar. Daher trägt der Payload bewusst ``uebrige_schuldner_insolvenzen``
    statt eines irreführenden ``verbraucherinsolvenzen``. Regionale Auflösung ist
    der Kreis/die kreisfreie Stadt (kreisfreie Städte stadtgenau, sonst der
    umgebende Kreis).
    """

    kind: Literal["insolvencies"] = "insolvencies"
    unternehmensinsolvenzen: int | None = None
    uebrige_schuldner_insolvenzen: int | None = None
    jahr: int | None = None


class SolarRoofsPayload(BaseModel):
    """Dach-Solarkataster je Stadt: installiertes + Potenzial Dach-PV (DATA-39).

    Aus dem amtlichen Gemeinde-Aggregat (NRW-Pilot: Solarkataster NRW,
    MaStR/LANUK/Geobasis NRW, DL-DE/Zero 2.0 = Tier A; föderiert je Bundesland wie
    BORIS). ``potential_kwp``/``potential_yield_mwh`` = gesamtes installierbares
    Dach-PV-Potenzial (Leistung kWp bzw. Jahresertrag MWh);
    ``installed_kwp``/``installed_yield_mwh`` = bereits installierte Dach-PV
    (Bestand, jüngstes Jahr, kumuliert). ``exploitation_pct`` =
    installed_kwp/potential_kwp*100 (Ausschöpfungsgrad). ``potential_by_category``
    = Potenzial-Leistung kWp je Gebäudekategorie (wohngebaeude/gewerbe_industrie/
    oeffentliche/landwirtschaft/sonstige/nicht_zuordbar). ``reference_date`` = Stand
    des Datensatzes. Anders als ``SolarPayload`` (PVGIS-Einstrahlung je kWp) trägt
    dieser Payload das Dach-Kataster (Mengen je Stadt). Mutable Default via
    ``Field(default_factory=dict)`` (ruff B006).
    """

    kind: Literal["solar_roofs"] = "solar_roofs"
    potential_kwp: float | None = None
    potential_yield_mwh: float | None = None
    installed_kwp: float | None = None
    installed_yield_mwh: float | None = None
    exploitation_pct: float | None = None
    potential_by_category: dict = Field(default_factory=dict)
    reference_date: str | None = None


class DistrictHeatingPayload(BaseModel):
    """Fernwärme-/Wärmenetz-Versorgung je Stadt (föderiert je Stadt-WFS, DATA-41).

    Aggregat aus den amtlichen, offen lizenzierten Wärmenetz-/Fernwärme-Geodaten
    der kommunalen Wärmeplanung (föderiert je Stadt wie ``solar-roofs``/BORIS, je
    Ursprung lizenzverifiziert). Berlin: Energienetze-WFS, Netzgebiet Fernwärme
    einschließlich 250 m Puffer (DL-DE/Zero 2.0); Hamburg: WFS "Gebiete mit
    Wärmenetz" der kommunalen Wärmeplanung (DL-DE/BY 2.0). Der Batch-Ingest holt
    den WFS, verdichtet die Flächen zu einem schlanken Stadt-Aggregat (KEINE
    Geometrien im Payload) und schreibt EINEN Record je Stadt; die Route liest
    read-only.

    ``network_area_count`` = Anzahl der Wärmenetz-/Versorgungs-Flächen im Quell-
    datensatz (Berlin: je Netzbetreiber ein Versorgungsgebiet; Hamburg: einzelne
    Netzteilflächen). ``supplied_area_km2`` = Summe der Versorgungsflächen in km²
    (planar aus den projizierten WFS-Koordinaten, EPSG:258xx, via Shoelace; bei
    Berlin inkl. des 250-m-Puffers, siehe ``area_basis``). ``operators`` = sortierte
    Liste der distinct Netzbetreiber, ``operator_count`` deren Anzahl.
    ``house_connections`` = Summe der Hausanschlüsse (sofern der Quelldatensatz sie
    führt, sonst None). ``network_length_km`` = Summe der Trassenlänge in km (dito).
    ``networks`` = je Netzbetreiber ein schlankes dict (``operator`` plus, soweit
    vorhanden, ``area_count``/``supplied_area_km2``/``house_connections``/
    ``network_length_km``/``info_url``). ``area_basis`` beschreibt die Flächen-
    Semantik wortgenau (z.B. "Versorgungsgebiet inkl. 250 m Puffer"). Mutable
    Default via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["district_heating"] = "district_heating"
    network_area_count: int | None = None
    supplied_area_km2: float | None = None
    operator_count: int | None = None
    operators: list[str] = Field(default_factory=list)
    house_connections: int | None = None
    network_length_km: float | None = None
    networks: list[dict] = Field(default_factory=list)
    area_basis: str | None = None
    reference_date: str | None = None


class SolarPayload(BaseModel):
    """Solar-Einstrahlung + normierter PV-Ertrag je Stadt (PVGIS/JRC, Tier A, DATA-38).

    Klimatologisches Mehrjahresmittel aus der keylosen PVGIS-Rechen-API (PVcalc)
    am Stadtzentrum, normiert auf eine 1-kWp-Anlage bei optimalem Neigungswinkel
    (``optimalangles``). KEIN Tageswert -> ``CanonicalRecord.observed_at`` bleibt
    None; der Bezugszeitraum steht als ``period_start``/``period_end`` (Jahre des
    PVGIS-Strahlungs-Datensatzes). ``annual_yield_kwh_kwp`` ist der Jahresertrag in
    kWh je kWp (PVGIS ``E_y``, da peakpower=1), ``annual_irradiation_kwh_m2`` die
    Globalstrahlung auf die geneigte Fläche (``H(i)_y``). ``optimal_slope_deg``/
    ``optimal_azimuth_deg`` der von PVGIS bestimmte optimale Aufständerungswinkel
    bzw. Azimut (0 = Süd). ``system_loss_pct`` = der konfigurierte (gewollte)
    Systemverlust aus Verkabelung/Wechselrichter/Verschmutzung (an PVGIS übergebener
    ``loss``-Parameter, i.d.R. 14 %); ``total_performance_delta_pct`` = PVGIS
    ``l_total``, die GESAMTE Performance-Differenz inkl. Temperatur-/Einstrahlungs-/
    Winkel-Effekten (negativ = Gesamtminderung, kann durch Spektral-/AOI-Gewinne
    abweichen und ist ausdrücklich NICHT der Systemverlust). ``radiation_db``
    benennt den Strahlungs-Datensatz (z.B. "PVGIS-SARAH3"). ``monthly`` trägt je
    Monat ein schlankes dict (``month`` 1-12, ``irradiation_kwh_m2``, ``yield_kwh``).
    Mutable Default IMMER via ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["solar"] = "solar"
    annual_irradiation_kwh_m2: float | None = None
    annual_yield_kwh_kwp: float | None = None
    optimal_slope_deg: float | None = None
    optimal_azimuth_deg: float | None = None
    peakpower_kwp: float | None = None
    system_loss_pct: float | None = None
    total_performance_delta_pct: float | None = None
    radiation_db: str | None = None
    period_start: int | None = None
    period_end: int | None = None
    monthly: list[dict] = Field(default_factory=list)


class PublicTenderPayload(BaseModel):
    """Oeffentliche Auftragsvergabe je Stadt (OCDS, Tier A, DATA-21).

    Bildet eine OCDS-1.1-Bekanntmachung (Notice) auf das kanonische Schema ab.
    ``notice_id`` + ``notice_version`` bilden den fachlichen Dedup-Schlüssel
    (jüngste Version gewinnt). ``match`` weist aus, über welchen Pfad die
    Bekanntmachung der Stadt zugeordnet wurde ("buyer_city" = Auftraggeber-Sitz,
    "place_of_performance" = Erfüllungsort): eine Bekanntmachung kann beide
    Pfade tragen. ``buyer_city`` trägt den (slugifizierten) Stadt-Bezug, ``nuts``
    den NUTS-3-Code des Auftraggebers/Erfuellungsorts. Mutable Liste IMMER via
    ``Field(default_factory=list)`` (ruff B006).
    """

    kind: Literal["public_tender"] = "public_tender"
    notice_id: str
    notice_version: str
    notice_type: str | None = None
    status: str | None = None
    title: str | None = None
    buyer_name: str | None = None
    buyer_city: str | None = None
    buyer_postal_code: str | None = None
    nuts: str | None = None
    cpv: str | None = None
    value: float | None = None
    currency: str | None = None
    publication_date: str | None = None
    deadline: str | None = None
    award_date: str | None = None
    match: list[str] = Field(default_factory=list)
    source_url: str | None = None


PayloadUnion = Annotated[
    CityBaseDataPayload
    | AirQualityPayload
    | WeatherPayload
    | PoiPayload
    | TrafficEventPayload
    | TransitStopPayload
    | ChargingStationPayload
    | WaterLevelPayload
    | FloodWarningPayload
    | PowerPayload
    | WeatherWarningPayload
    | PollenUvPayload
    | FireDangerPayload
    | BathingWaterPayload
    | HospitalAtlasPayload
    | StationFacilityPayload
    | DemographicsPayload
    | EnergyAssetPayload
    | VehicleRegistrationPayload
    | RegionalStatPayload
    | AccidentPayload
    | FuelPricePayload
    | SharingPayload
    | SolarPayload
    | SolarRoofsPayload
    | DistrictHeatingPayload
    | IndicatorsPayload
    | CrimeStatsPayload
    | LandValuesPayload
    | PopulationDensityPayload
    | TaxRatesPayload
    | BusinessRegistrationsPayload
    | InsolvenciesPayload
    | StationCatalogPayload
    | StationDeparturesPayload
    | StationArrivalsPayload
    | AdminBoundaryPayload
    | ElectionResultPayload
    | HolidayPayload
    | HospitalPayload
    | IcuCapacityPayload
    | RoadEventPayload
    | WebcamPayload
    | EventPayload
    | TrafficFlowPayload
    | ParkingPayload
    | CountStationPayload
    | ChargingStatusPayload
    | TransitDeparturePayload
    | TransitTripPayload
    | TransitRouteStatusPayload
    | PublicTenderPayload,
    Field(discriminator="kind"),
]
