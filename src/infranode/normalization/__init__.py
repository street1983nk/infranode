"""Normalisierungs-Library: kanonisches Schema als einzige Quelle der Wahrheit.

Re-exportiert die oeffentliche API der Library (CORE-01): den
``CanonicalRecord``-Envelope, die Wert-Objekte, die Lizenz-/Quellen-Enums sowie
die diskriminierte Payload-Union und ihre Mitglieder. Jede Quelle ab Phase 4
bildet ihre Daten auf diese Modelle ab.
"""

from __future__ import annotations

from infranode.normalization.enums import LicenseId, LicenseTier, SourceId
from infranode.normalization.models import (
    SCHEMA_VERSION,
    Attribution,
    CanonicalRecord,
    GeoPoint,
)
from infranode.normalization.payloads import (
    AdminBoundaryPayload,
    AirQualityPayload,
    ChargingStationPayload,
    ChargingStatusPayload,
    CityBaseDataPayload,
    CountStationPayload,
    DemographicsPayload,
    ElectionResultPayload,
    EnergyAssetPayload,
    EventPayload,
    FloodWarningPayload,
    HolidayPayload,
    HospitalPayload,
    IcuCapacityPayload,
    ParkingPayload,
    PayloadUnion,
    PoiPayload,
    PollenUvPayload,
    RoadEventPayload,
    TrafficEventPayload,
    TrafficFlowPayload,
    TransitStopPayload,
    WaterLevelPayload,
    WeatherPayload,
    WebcamPayload,
)

__all__ = [
    "SCHEMA_VERSION",
    "AdminBoundaryPayload",
    "AirQualityPayload",
    "Attribution",
    "CanonicalRecord",
    "ChargingStationPayload",
    "ChargingStatusPayload",
    "CityBaseDataPayload",
    "CountStationPayload",
    "DemographicsPayload",
    "ElectionResultPayload",
    "EnergyAssetPayload",
    "EventPayload",
    "FloodWarningPayload",
    "GeoPoint",
    "HolidayPayload",
    "HospitalPayload",
    "IcuCapacityPayload",
    "LicenseId",
    "LicenseTier",
    "ParkingPayload",
    "PayloadUnion",
    "PoiPayload",
    "PollenUvPayload",
    "RoadEventPayload",
    "SourceId",
    "TrafficEventPayload",
    "TrafficFlowPayload",
    "TransitStopPayload",
    "WaterLevelPayload",
    "WebcamPayload",
    "WeatherPayload",
]
