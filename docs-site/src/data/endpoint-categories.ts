// Thematische Kategorien für die Endpunkt-Navigation (Docs.astro).
// Gliedert die OpenAPI-Endpunkte innerhalb von "Endpunkte" und "Live Endpunkte"
// in sinnvolle Themengruppen (statt der groben OpenAPI-Tags). Reihenfolge der
// CATEGORIES bestimmt die Anzeigereihenfolge; leere Kategorien werden je Sektion
// ausgeblendet. Endpunkte ohne Eintrag fallen in "sonstige".

export type Category = { id: string; de: string; en: string };

export const CATEGORIES: Category[] = [
  { id: "umwelt", de: "Umwelt & Wetter", en: "Environment & weather" },
  { id: "verkehr", de: "Verkehr & Mobilität", en: "Transport & mobility" },
  { id: "energie", de: "Energie", en: "Energy" },
  { id: "bevoelkerung", de: "Bevölkerung & Soziales", en: "Population & society" },
  { id: "wirtschaft", de: "Wirtschaft & Finanzen", en: "Economy & finance" },
  { id: "sicherheit", de: "Sicherheit & Recht", en: "Safety & law" },
  { id: "orte", de: "Orte & Einrichtungen", en: "Places & facilities" },
  { id: "stadt", de: "Stadt & Stammdaten", en: "City & base data" },
  { id: "meta", de: "Vergleich & Meta", en: "Compare & meta" },
  { id: "sonstige", de: "Sonstige", en: "Other" },
];

// Kategorie -> Endpunkt-IDs (operationId). Eine ID gehört genau zu einer Kategorie.
const MEMBERS: Record<string, string[]> = {
  umwelt: [
    "getCityAir", "getCityAirUba", "getCityWeather", "getCityWeatherWarnings",
    "getCityPollenUv", "getCityFireDanger", "getCityBathingWater",
    "getCityWaterLevel", "getCityFlood", "getCitySolar",
    "getCitySolarRoofs",
    // Wegweiser Kommune (CC0): SDG-/Nachhaltigkeits-Zeitreihe.
    "getCitySustainability", "getLiveAir", "getLiveAirUba", "getLiveFlood",
    "getLiveWaterLevel", "getLiveKoelnLowEmissionZone",
    "getLiveKoelnUmweltzone",
  ],
  verkehr: [
    "getCityTransit", "getCityStationDepartures", "getCityStationArrivals",
    "getCityStations", "getCityStationFacilities", "getCityTraffic",
    "getCityRoadEvents",
    "getCitySharing", "getCityParking", "getCityFuelPrices", "getCityBikeCounts",
    "getCityParkingOnstreet", "getCityParkAndRide", "getCityMobilityPoints",
    "getCityBikeParking",
    "getStationArrivals", "getStationDepartures", "getLiveTransitDepartures",
    "getLiveTransitRouteStatus", "getLiveTransitTrip", "getLiveHamburgDepartures",
    "getLiveNuernbergDepartures", "getLiveTraffic", "getLiveTrafficFlow",
    "getLiveRoadworks", "getLiveBerlinTrafficReports",
    "getLiveHannoverTrafficReports", "getLiveHamburgTrafficSituation",
    "getLiveIncidents", "getLiveDortmundParking",
    "getLiveFrankfurtParking", "getLiveWuppertalParking", "getLiveMagdeburgParking",
    "getLiveKielCountingStations", "getLiveFrankfurtDepartures", "getLiveVrrDepartures",
    "getLiveBaustellen", "getLiveEreignisse", "getLiveBerlinVerkehrsmeldungen",
    "getLiveHannoverVerkehrsmeldungen", "getLiveHamburgVerkehrslage",
    "getLiveKielZaehlstellen",
  ],
  energie: [
    "getCityCharging", "getCityChargingStatus", "getCityEnergy", "getCityPowerLoad",
    "getCityPowerPrice", "getCityDistrictHeating", "getLiveEroundCharging",
  ],
  bevoelkerung: [
    "getCityDemographics", "getCityPopulationDensity", "getCityIndicators",
    // Wegweiser Kommune (CC0), Indikator-Zeitreihen je Gemeinde.
    "getCityPopulationStructure", "getCityPopulationTrend",
    "getCityIntegration", "getCityChildcare", "getCityEducationStats",
    "getCitySocialSituation", "getCityCare",
    "getCityUnemployment", "getCityHealth", "getCityHospitalsAtlas",
    "getCityEducation",
  ],
  wirtschaft: [
    "getCityBusinessRegistrations", "getCityInsolvencies", "getCityTaxRates",
    // Wegweiser Kommune (CC0): Finanz- und Arbeitsmarkt-Zeitreihen.
    "getCityMunicipalFinance", "getCityLabourMarket",
    "getCityLandValues", "getCityVehicleRegistrations", "getCityTourism",
    "getCityConstruction", "getCityPublicTenders", "getAllPublicTenders",
  ],
  sicherheit: [
    "getCityCrimeStats", "getCityAccidents", "getCityElection",
    "getCityCivilProtectionWarnings",
  ],
  orte: [
    "getCityPlaygrounds", "getCityDrinkingWater", "getCityPublicToilets",
    "getCityMarkets",
    "getCityParcelLockers", "getCityPostOffices", "getCityPostBoxes",
    "getCityPublicWifi", "getCityRecyclingCentres", "getCityGovernmentOffices",
    "getCityOfficeWaitTimes", "getCityTreeCadastre", "getCityPois", "getCityEvents",
  ],
  stadt: [
    "getCities", "getCity", "getCityBase", "getCityGeo", "getCityHeritage",
    "getCityHolidays", "getCityOverview", "getCityCouncilPapers",
  ],
  meta: [
    "compareCities", "getBoom", "getEcho", "getHealth", "getOpenapiYaml",
    "getPing", "getSources",
  ],
};

export const CATEGORY_OF: Record<string, string> = {};
for (const [cat, ids] of Object.entries(MEMBERS)) {
  for (const id of ids) CATEGORY_OF[id] = cat;
}
