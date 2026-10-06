// Zentrales Abkündigungs-Register der InfraNode-API (Single Source).
//
// JEDE Abkündigung wird hier eingetragen, bevor sie irgendwo anders erwähnt
// wird: die Endpunkt-Banner (/api/<operationId> und /en/api/<operationId>)
// lesen FIELD_DEPRECATIONS, die OpenAPI-Beschreibung und der Changelog müssen
// mit den Daten hier übereinstimmen. Regeln:
//
//  1. Ein Eintrag bekommt IMMER ein konkretes Entfernungsdatum (removal),
//     mindestens 30 Tage nach der Ankündigung (announced).
//  2. Nach dem Vollzug wandert der Eintrag mit status: "removed" in die
//     REMOVED_DEPRECATIONS-Historie (Banner verschwindet), und der Changelog
//     bekommt einen "removed"-Eintrag. Einträge werden NICHT gelöscht: die
//     Historie ist der Nachweis, dass die Frist eingehalten wurde.
//  3. Pfad-Abkündigungen (Alias-Routen) stehen in PATH_DEPRECATIONS. Aliasse
//     ohne Entfernungszusage tragen removal: null; sie bleiben stehen, bis
//     eine bewusste Entscheidung ein Datum setzt (die OpenAPI verspricht für
//     die /cities-Altpfade ausdrücklich "kein Breaking Change").

/** Eine Feld-Umbenennung: alter Name -> kanonischer Name. */
export interface DeprecatedField {
  /** Alter Name, der während der Übergangsfrist denselben Wert trägt. */
  old: string;
  /** Kanonischer Name, auf den umgestellt werden soll. */
  now: string;
}

/** Ein Registereintrag für eine Operation. */
export interface DeprecationEntry {
  /** Betroffene Feldpaare dieser Operation. */
  fields: DeprecatedField[];
  /** Tag der Ankündigung (ISO-Datum). */
  announced: string;
  /** Frühester Entfernungstag (ISO-Datum), >= announced + 30 Tage. */
  removal: string;
}

/** Historien-Eintrag: vollzogene Abkündigung. */
export interface RemovedDeprecation extends DeprecationEntry {
  /** Tag, an dem die Felder tatsächlich aus der Ausgabe entfernt wurden. */
  removedOn: string;
}

/** Pfad-Alias mit Deprecation-Header. */
export interface PathDeprecation {
  /** Abgekündigter Pfad (OpenAPI-Notation). */
  path: string;
  /** Kanonischer Nachfolgepfad. */
  successor: string;
  announced: string;
  /**
   * Frühester Entfernungstag oder null. null = Alias ohne Entfernungszusage
   * (die OpenAPI verspricht "kein Breaking Change"); erst ein bewusster
   * Eintrag eines Datums macht daraus eine echte Abkündigung.
   */
  removal: string | null;
}

// ---------------------------------------------------------------------------
// AKTIVE Feld-Abkündigungen (Banner sichtbar).
// ---------------------------------------------------------------------------

/**
 * getCityEvents: die Umbenennung title->name war am 2026-08-01 angekündigt,
 * aber für die destination.one-Städte (Berlin/Hamburg/München u. a.) nie
 * umgesetzt: diese Quelle lieferte NUR title, das kanonische name erschien
 * dort nie. Ein Entfernen am 2026-08-31 hätte ein Feld ohne verfügbaren
 * Nachfolger gestrichen. Darum: name wird seit 2026-08-31 überall
 * ausgeliefert, und title bekommt eine NEUE Frist.
 */
export const FIELD_DEPRECATIONS: Record<string, DeprecationEntry> = {
  getCityEvents: {
    fields: [{ old: "title", now: "name" }],
    announced: "2026-08-31",
    removal: "2026-09-30",
  },
};

/** Anzeige-Datum des nächsten Entfernungstermins (für das Banner). */
export const REMOVAL_DATE = { de: "30. September 2026", en: "30 September 2026" };

// ---------------------------------------------------------------------------
// HISTORIE: vollzogene Abkündigungen (kein Banner mehr; Nachweis der Frist).
// Alle folgenden Felder waren am 2026-08-01 angekündigt und wurden am
// 2026-08-31 aus der Ausgabe entfernt. Persistierte Bestandsdaten werden
// beim Einlesen auf die kanonischen Namen umgeschrieben, alte Cache-Antworten
// bereinigen die Mapper.
// ---------------------------------------------------------------------------

const A = "2026-08-01";
const R = "2026-08-31";
const done = (fields: DeprecatedField[]): RemovedDeprecation => ({
  fields,
  announced: A,
  removal: R,
  removedOn: R,
});

export const REMOVED_DEPRECATIONS: Record<string, RemovedDeprecation> = {
  getCityCharging: done([
    { old: "plz", now: "post_code" },
    { old: "ort", now: "place" },
  ]),
  getCityEnergy: done([
    { old: "plz", now: "post_code" },
    { old: "leistung_kw", now: "power_kw" },
    { old: "einheit_typ", now: "asset_type" },
  ]),
  getCityStations: done([
    { old: "zip", now: "post_code" },
    { old: "category", now: "station_category" },
  ]),
  getCityHospitalsAtlas: done([
    { old: "zip", now: "post_code" },
    { old: "city", now: "place" },
  ]),
  getCityEvents: done([
    { old: "strasse", now: "street" },
    { old: "hausnummer", now: "house_number" },
    { old: "plz", now: "post_code" },
  ]),
  getCityRoadEvents: done([
    // Köln (Stufe 1) + Stadtquellen München/Rostock/Dortmund/Sachsen/Hamburg
    // (Stufe 3); je Quelle trugen die Events nur die dort vorhandenen Felder.
    { old: "bezeichnung", now: "name" },
    { old: "beginn", now: "start" },
    { old: "ende", now: "end" },
    { old: "art", now: "event_type" },
    { old: "beschreibung", now: "description" },
    { old: "von", now: "start" },
    { old: "bis", now: "end" },
    { old: "strasse", now: "street" },
    { old: "strasse_hausnr", now: "street" },
    { old: "betroffene_bereiche", now: "affected_areas" },
    { old: "sparte", now: "sector" },
    { old: "einschraenkung", now: "restriction" },
    { old: "abschnitt_von", now: "section_from" },
    { old: "abschnitt_nach", now: "section_to" },
    { old: "baubeginn", now: "start" },
    { old: "bauende", now: "end" },
    { old: "typ", now: "closure_type" },
    { old: "grund", now: "reason" },
    { old: "strassenklasse", now: "road_class" },
    { old: "ortslage", now: "location" },
    { old: "umleitung_ueber", now: "diversion_via" },
    { old: "auftraggeber", now: "client" },
    { old: "zeitraum", now: "period" },
    { old: "stadtbezirk", now: "district" },
    { old: "titel", now: "name" },
    { old: "anlass", now: "reason" },
  ]),
  getCityFuelPrices: done([{ old: "dist_km", now: "distance_km" }]),
  getCityTraffic: done([
    { old: "isBlocked", now: "is_blocked" },
    { old: "startTimestamp", now: "start_timestamp" },
    { old: "delayTimeValue", now: "delay_minutes" },
    { old: "averageSpeed", now: "average_speed_kmh" },
    { old: "abnormalTrafficType", now: "abnormal_traffic_type" },
    { old: "extent", now: "bbox" },
  ]),
  getCityStationDepartures: done([{ old: "stop_id", now: "trip_stop_id" }]),
  getCityStationArrivals: done([{ old: "stop_id", now: "trip_stop_id" }]),
  getStationDepartures: done([{ old: "stop_id", now: "trip_stop_id" }]),
  getStationArrivals: done([{ old: "stop_id", now: "trip_stop_id" }]),
  getCityFlood: done([{ old: "stand", now: "as_of" }]),
  getCityFireDanger: done([{ old: "bundesland", now: "federal_state" }]),
  getCityElection: done([{ old: "granularity", now: "coverage_granularity" }]),
  getCityTreeCadastre: done([
    // Rohe WFS-Feldnamen je Stadt (Berlin/Hamburg/Kiel).
    { old: "art_dtsch", now: "species" },
    { old: "art_deutsch", now: "species" },
    { old: "Baumart", now: "species" },
    { old: "art_bot", now: "species_botanical" },
    { old: "Baumart__bot._", now: "species_botanical" },
    { old: "gattung_deutsch", now: "genus" },
    { old: "pflanzjahr", now: "planting_year" },
    { old: "Kronendurchmesser__m_", now: "crown_diameter_m" },
  ]),
  getCityHeritage: done([
    // Rohe WFS-Feldnamen je Land (Berlin/Hamburg/Hessen).
    { old: "typ", now: "type" },
    { old: "bezeichnung", now: "name" },
    { old: "bautyp", now: "building_type" },
    { old: "baujahr", now: "build_year" },
    { old: "siteName", now: "site_name" },
    { old: "siteDesignation", now: "site_designation" },
    { old: "publicationSource", now: "publication_source" },
  ]),
  getCityLandValues: done([{ old: "stichtag", now: "reference_date" }]),
  getCityTaxRates: done([
    { old: "gewerbesteuer_hebesatz", now: "trade_tax_rate" },
    { old: "grundsteuer_a", now: "property_tax_a" },
    { old: "grundsteuer_b", now: "property_tax_b" },
    { old: "grundsteuer_c", now: "property_tax_c" },
    { old: "stichtag", now: "reference_date" },
  ]),
  getCityBusinessRegistrations: done([
    { old: "anmeldungen", now: "registrations" },
    { old: "abmeldungen", now: "deregistrations" },
    { old: "saldo", now: "balance" },
    { old: "jahr", now: "year" },
  ]),
  getCityInsolvencies: done([
    { old: "unternehmensinsolvenzen", now: "corporate_insolvencies" },
    { old: "uebrige_schuldner_insolvenzen", now: "other_debtor_insolvencies" },
    { old: "jahr", now: "year" },
  ]),
};

// ---------------------------------------------------------------------------
// Pfad-Abkündigungen (Alias-Routen mit Deprecation-/Link-Header).
// ---------------------------------------------------------------------------

export const PATH_DEPRECATIONS: PathDeprecation[] = [
  // Deutsche Live-Slugs, abgelöst von den kanonischen englischen Pfaden.
  // BEWUSST ohne Entfernungsdatum: die OpenAPI sagt "der alte Pfad bleibt als
  // Alias erhalten"; derselbe Handler, keine Betriebskosten. Ein Datum wird
  // erst gesetzt, wenn der Owner die Entfernung entscheidet.
  { path: "/api/v1/live/{city}/baustellen", successor: "/api/v1/live/{city}/roadworks", announced: "2026-07-25", removal: null },
  { path: "/api/v1/live/{city}/ereignisse", successor: "/api/v1/live/{city}/incidents", announced: "2026-07-25", removal: null },
  { path: "/api/v1/live/berlin/verkehrsmeldungen", successor: "/api/v1/live/berlin/traffic-reports", announced: "2026-07-25", removal: null },
  { path: "/api/v1/live/hannover/verkehrsmeldungen", successor: "/api/v1/live/hannover/traffic-reports", announced: "2026-07-25", removal: null },
  { path: "/api/v1/live/koeln/umweltzone", successor: "/api/v1/live/koeln/low-emission-zone", announced: "2026-07-25", removal: null },
  { path: "/api/v1/live/hamburg/verkehrslage", successor: "/api/v1/live/hamburg/traffic-situation", announced: "2026-07-25", removal: null },
  { path: "/api/v1/live/kiel/zaehlstellen", successor: "/api/v1/live/kiel/counting-stations", announced: "2026-07-25", removal: null },
  { path: "/api/v1/live/dortmund/parking", successor: "/api/v1/cities/dortmund/parking", announced: "2026-08-25", removal: null },
];
