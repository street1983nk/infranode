// Kurze, scanbare Nav-Labels für die API-Referenz (Docs.astro), DE + EN.
// Die OpenAPI-summary ist als Satz gut für Seiten-Titel und Suche, aber zu
// lang für die Sidebar. Hier steht je operationId eine knappe Nominalphrase;
// Quelle in Klammern nur, wo sie zur Unterscheidung nötig ist. Die volle
// summary bleibt im title-Attribut des Links (Tooltip) und auf der Seite.
// Fallback in Docs.astro: fehlt ein Eintrag, greift die summary.

export type NavLabel = { de: string; en: string };

export const NAV_LABEL: Record<string, NavLabel> = {
  // Vergleich & Meta
  getHealth: { de: "Health-Check", en: "Health check" },
  getPing: { de: "Ping", en: "Ping" },
  getEcho: { de: "Echo (Demo)", en: "Echo (demo)" },
  getBoom: { de: "Fehler-Demo", en: "Failure demo" },
  getSources: { de: "Quellen-Status", en: "Source status" },
  compareCities: { de: "Städte-Vergleich", en: "City comparison" },
  getOpenapiYaml: { de: "OpenAPI-Spec", en: "OpenAPI spec" },

  // Stadt & Stammdaten
  getCities: { de: "Städte-Liste", en: "City list" },
  getCity: { de: "Stadt-Eintrag", en: "City entry" },
  getCityBase: { de: "Stammdaten (Wikidata)", en: "Master data (Wikidata)" },
  getCityOverview: { de: "Stadt-Überblick", en: "City overview" },
  getCityGeo: { de: "Verwaltungsgrenze", en: "Administrative boundary" },
  getCityHeritage: { de: "Denkmäler", en: "Heritage monuments" },
  getCityHolidays: { de: "Feiertage & Ferien", en: "Holidays & vacations" },
  getCityCouncilPapers: { de: "Ratsinformationen (OParl)", en: "Council papers (OParl)" },

  // Umwelt & Wetter
  getCityAir: { de: "Luftqualität", en: "Air quality" },
  getCityAirUba: { de: "Luftqualität (UBA)", en: "Air quality (UBA)" },
  getCityWeather: { de: "Wetter (DWD)", en: "Weather (DWD)" },
  getCityWeatherWarnings: { de: "Wetterwarnungen", en: "Weather warnings" },
  getCityPollenUv: { de: "Pollen & UV-Index", en: "Pollen & UV index" },
  getCityFireDanger: { de: "Waldbrandindex", en: "Fire danger index" },
  getCityBathingWater: { de: "Badegewässer", en: "Bathing water" },
  getCityWaterLevel: { de: "Pegelstände", en: "Water levels" },
  getCityFlood: { de: "Hochwasser-Warnstufen", en: "Flood warnings" },
  getCitySolar: { de: "Solar-Ertrag (PVGIS)", en: "Solar yield (PVGIS)" },
  getCitySolarRoofs: { de: "Dach-Solarkataster", en: "Rooftop solar cadastre" },
  getLiveKoelnLowEmissionZone: { de: "Umweltzone Köln", en: "Low-emission zone Cologne" },
  getLiveKoelnUmweltzone: { de: "[Deprecated] Umweltzone Köln", en: "[Deprecated] Low-emission zone Cologne" },

  // Verkehr & Mobilität
  getCityTransit: { de: "ÖPNV-Haltestellen", en: "Transit stops" },
  getCityStations: { de: "Bahnhofs-Katalog", en: "Station catalog" },
  getCityStationDepartures: { de: "Abfahrten Hauptbahnhof", en: "Main-station departures" },
  getCityStationArrivals: { de: "Ankünfte Hauptbahnhof", en: "Main-station arrivals" },
  getStationDepartures: { de: "Abfahrten beliebiger Bahnhof", en: "Departures, any station" },
  getStationArrivals: { de: "Ankünfte beliebiger Bahnhof", en: "Arrivals, any station" },
  getCityStationFacilities: { de: "Aufzug-Status Bahnhöfe", en: "Station elevator status" },
  getCityTraffic: { de: "Verkehr & Baustellen (Autobahn)", en: "Traffic & roadworks (Autobahn)" },
  getCityRoadEvents: { de: "Baustellen innerstädtisch", en: "Inner-city roadworks" },
  getCitySharing: { de: "Bike- & Scooter-Sharing", en: "Bike & scooter sharing" },
  getCityParking: { de: "Parkhaus-Belegung", en: "Parking occupancy" },
  getCityFuelPrices: { de: "Spritpreise", en: "Fuel prices" },
  getCityBikeCounts: { de: "Radzählstellen", en: "Bicycle counters" },
  getLiveTrafficFlow: { de: "Verkehrslage (DATEX-II)", en: "Traffic flow (DATEX-II)" },
  getLiveRoadworks: { de: "Baustellen (DATEX-II)", en: "Roadworks (DATEX-II)" },
  getLiveIncidents: { de: "Verkehrsereignisse (DATEX-II)", en: "Traffic events (DATEX-II)" },
  getLiveBerlinTrafficReports: { de: "Verkehrsmeldungen Berlin", en: "Traffic messages Berlin" },
  getLiveHannoverTrafficReports: { de: "Verkehrsmeldungen Hannover", en: "Traffic messages Hanover" },
  getLiveHamburgTrafficSituation: { de: "Verkehrslage Hamburg", en: "Traffic situation Hamburg" },
  getLiveKielCountingStations: { de: "Zählstellen Kiel", en: "Traffic counters Kiel" },
  getLiveBaustellen: { de: "[Deprecated] Baustellen (DATEX-II)", en: "[Deprecated] Roadworks (DATEX-II)" },
  getLiveEreignisse: { de: "[Deprecated] Verkehrsereignisse (DATEX-II)", en: "[Deprecated] Traffic events (DATEX-II)" },
  getLiveBerlinVerkehrsmeldungen: { de: "[Deprecated] Verkehrsmeldungen Berlin", en: "[Deprecated] Traffic messages Berlin" },
  getLiveHannoverVerkehrsmeldungen: { de: "[Deprecated] Verkehrsmeldungen Hannover", en: "[Deprecated] Traffic messages Hanover" },
  getLiveHamburgVerkehrslage: { de: "[Deprecated] Verkehrslage Hamburg", en: "[Deprecated] Traffic situation Hamburg" },
  getLiveKielZaehlstellen: { de: "[Deprecated] Zählstellen Kiel", en: "[Deprecated] Traffic counters Kiel" },
  getLiveFrankfurtParking: { de: "Parken Frankfurt", en: "Parking Frankfurt" },
  getLiveMagdeburgParking: { de: "Parken Magdeburg", en: "Parking Magdeburg" },
  getLiveWuppertalParking: { de: "Parken Wuppertal", en: "Parking Wuppertal" },
  getLiveHamburgDepartures: { de: "ÖPNV-Abfahrten Hamburg", en: "Transit departures Hamburg" },
  getLiveFrankfurtDepartures: { de: "ÖPNV-Abfahrten Frankfurt", en: "Transit departures Frankfurt" },
  getLiveNuernbergDepartures: { de: "ÖPNV-Abfahrten Nürnberg", en: "Transit departures Nuremberg" },
  getLiveVrrDepartures: { de: "ÖPNV-Abfahrten VRR & VVS", en: "Transit departures VRR & VVS" },
  getLiveTransitDepartures: { de: "ÖPNV-Abfahrten (GTFS-RT)", en: "Transit departures (GTFS-RT)" },
  getLiveTransitTrip: { de: "ÖPNV-Fahrt-Detail (GTFS-RT)", en: "Transit trip detail (GTFS-RT)" },
  getLiveTransitRouteStatus: { de: "ÖPNV-Linienstatus (GTFS-RT)", en: "Transit route status (GTFS-RT)" },

  // Energie
  getCityCharging: { de: "Ladesäulen-Standorte", en: "Charging locations" },
  getCityChargingStatus: { de: "Ladesäulen-Belegung", en: "Charging occupancy" },
  getCityEnergy: { de: "Energie-Anlagen (MaStR)", en: "Energy installations (MaStR)" },
  getCityPowerLoad: { de: "Netzlast (SMARD)", en: "Grid load (SMARD)" },
  getCityPowerPrice: { de: "Börsenstrompreis", en: "Wholesale power price" },
  getCityDistrictHeating: { de: "Fernwärme", en: "District heating" },
  getLiveEroundCharging: { de: "Ladesäulen-Belegung (eRound)", en: "Charging occupancy (eRound)" },

  // Bevölkerung & Soziales
  getCityDemographics: { de: "Demografie-Zeitreihen", en: "Demographic time series" },
  getCityPopulationDensity: { de: "Einwohnerdichte", en: "Population density" },
  getCityIndicators: { de: "Sozialökonomische Indikatoren", en: "Socioeconomic indicators" },
  getCityUnemployment: { de: "Arbeitslosigkeit", en: "Unemployment" },
  getCityHealth: { de: "Krankenhaus-Stammdaten", en: "Hospital master data" },
  getCityHospitalsAtlas: { de: "Krankenhausstandorte", en: "Hospital locations" },
  getCityEducation: { de: "Bildungseinrichtungen", en: "Education facilities" },

  // Wirtschaft & Finanzen
  getCityBusinessRegistrations: { de: "Gewerbemeldungen", en: "Business registrations" },
  getCityInsolvencies: { de: "Insolvenzen", en: "Insolvencies" },
  getCityTaxRates: { de: "Hebesätze", en: "Local tax rates" },
  getCityLandValues: { de: "Bodenrichtwerte (BORIS)", en: "Land values (BORIS)" },
  getCityVehicleRegistrations: { de: "Pkw-Bestand (KBA)", en: "Car stock (KBA)" },
  getCityTourism: { de: "Tourismus", en: "Tourism" },
  getCityConstruction: { de: "Baugenehmigungen", en: "Building permits" },
  getCityPublicTenders: { de: "Ausschreibungen", en: "Public tenders" },
  getAllPublicTenders: { de: "Ausschreibungen bundesweit", en: "Public tenders nationwide" },

  // Sicherheit & Recht
  getCityCrimeStats: { de: "Kriminalstatistik", en: "Crime statistics" },
  getCityAccidents: { de: "Verkehrsunfälle", en: "Traffic accidents" },
  getCityElection: { de: "Wahlergebnisse", en: "Election results" },
  getCityCivilProtectionWarnings: { de: "Bevölkerungsschutz-Warnungen", en: "Civil protection warnings" },

  // Orte & Einrichtungen
  getCityPois: { de: "POIs (OSM)", en: "POIs (OSM)" },
  getCityPlaygrounds: { de: "Spielplätze", en: "Playgrounds" },
  getCityDrinkingWater: { de: "Trinkwasserbrunnen", en: "Drinking fountains" },
  getCityPublicToilets: { de: "Öffentliche Toiletten", en: "Public toilets" },
  getCityMarkets: { de: "Wochenmärkte", en: "Markets" },
  getCityParcelLockers: { de: "Paketstationen", en: "Parcel lockers" },
  getCityPostOffices: { de: "Postfilialen", en: "Post offices" },
  getCityPostBoxes: { de: "Briefkästen", en: "Post boxes" },
  getCityPublicWifi: { de: "Öffentliches WLAN", en: "Public Wi-Fi" },
  getCityRecyclingCentres: { de: "Wertstoffhöfe", en: "Recycling centres" },
  getCityGovernmentOffices: { de: "Behörden & Ämter", en: "Government offices" },
  getCityOfficeWaitTimes: { de: "Behörden-Wartezeiten", en: "Office wait times" },
  getCityTreeCadastre: { de: "Baumkataster", en: "Tree cadastre" },
  getCityEvents: { de: "Veranstaltungen", en: "Events" },
};

// LIVE-Badge = Echtzeitdaten, nicht Routenfamilie: Stadt-Endpunkte, die
// Belegungen, Messwerte oder Tafeln minütlich bis viertelstündlich aktuell
// liefern (on-demand oder Poller), tragen das Badge zusätzlich zu den
// /live/-Routen (OpenAPI-Tag "Live"). Bewusst NICHT dabei: stündliche
// Messwerte (Wetter, Luft) und Warnlagen (Hochwasser, Wetterwarnungen),
// sonst verliert das Badge seine Aussage.
export const NAV_LIVE = new Set<string>([
  "getCityFuelPrices",
  "getCityParking",
  "getCityChargingStatus",
  "getCityStationDepartures",
  "getCityStationArrivals",
  "getStationDepartures",
  "getStationArrivals",
  "getCityStationFacilities",
  "getCityOfficeWaitTimes",
  "getCitySharing",
  "getCityWaterLevel",
  "getCityTraffic",
]);

// Deprecation-Aliasse: Seiten existieren weiter (Suche, alte Links, openapi),
// erscheinen aber nicht in der Sidebar. Die Nachfolger stehen in der Nav.
export const NAV_HIDDEN = new Set<string>([
  "getLiveAir",
  "getLiveAirUba",
  "getLiveWaterLevel",
  "getLiveTraffic",
  "getLiveFlood",
  "getLiveDortmundParking",
]);
