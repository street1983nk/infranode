"""Keyloser PVGIS-Solar-Adapter fetch_solar (DATA-38, Stufe 1).

Holt aus der keylosen PVGIS-Rechen-API (EU JRC, ``PVcalc``) das klimatologische
Jahres- und Monatsmittel der Globalstrahlung und des normierten PV-Ertrags am
Stadtzentrum und liefert ein flaches raw-dict, das der reine ``map_solar``-Mapper
erwartet. PVGIS rechnet jede Koordinate in Europa, daher sind alle Register-
Städte ohne Stadt-Allowlist abgedeckt (passt zur keyless-hosted-USP).

Referenzkonfiguration (Owner-Entscheidung): peakpower=1 kWp, loss=14 %,
optimalangles=1 (PVGIS bestimmt den optimalen Neigungswinkel und das Azimut).
Damit ist ``E_y`` direkt der Jahresertrag in kWh je kWp und stadtübergreifend
vergleichbar.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon stammen aus dem
validierten Register (``entry.geo``) und werden nur als Query-Parameter
übergeben.
"""

from __future__ import annotations

import httpx

_BASE = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"


async def fetch_solar(
    http: httpx.AsyncClient, *, slug: str, lat: float, lon: float
) -> dict:
    """Holt PVGIS-Solar-Kennzahlen und liefert das flache raw-dict.

    Rückgabe-Keys (exakt das, was ``map_solar`` erwartet): ``slug``/``lat``/
    ``lon``, ``annual_irradiation_kwh_m2`` (PVGIS ``H(i)_y``),
    ``annual_yield_kwh_kwp`` (``E_y``, da peakpower=1), ``system_loss_pct`` (der
    konfigurierte Systemverlust ``inputs.pv_module.system_loss``, i.d.R. 14 %, =
    der gewollte Verlust aus Verkabelung/Wechselrichter/Verschmutzung),
    ``total_performance_delta_pct`` (PVGIS ``l_total``, die GESAMTE
    Performance-Differenz inkl. Temperatur-/Einstrahlungs-/Winkel-Effekten;
    negativ = Gesamtminderung, kann durch Spektral-/AOI-Gewinne abweichen und ist
    NICHT der Systemverlust), ``optimal_slope_deg``/``optimal_azimuth_deg`` (von
    PVGIS bestimmter optimaler Aufständerungswinkel bzw. Azimut, 0 = Süd),
    ``peakpower_kwp``, ``radiation_db``, ``period_start``/``period_end`` (Jahre
    des Strahlungs-Datensatzes) und ``monthly`` (12 dicts: ``month``/
    ``irradiation_kwh_m2``/``yield_kwh``). Der Host ist hartkodiert (SSRF-Schutz);
    lat/lon fließen nur als Query-Parameter ein. Fehlende Felder bleiben robust
    ``None`` (keine KeyError), damit ein leicht abweichendes PVGIS-Schema die Route
    nicht in einen 500 kippt.
    """
    resp = await http.get(
        _BASE,
        params={
            "lat": lat,
            "lon": lon,
            "peakpower": 1,
            "loss": 14,
            "optimalangles": 1,
            "outputformat": "json",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    outputs = body.get("outputs") or {}
    inputs = body.get("inputs") or {}
    totals = (outputs.get("totals") or {}).get("fixed") or {}
    mounting = (inputs.get("mounting_system") or {}).get("fixed") or {}
    meteo = inputs.get("meteo_data") or {}
    pv_module = inputs.get("pv_module") or {}

    monthly = [
        {
            "month": m.get("month"),
            "irradiation_kwh_m2": m.get("H(i)_m"),
            "yield_kwh": m.get("E_m"),
        }
        for m in ((outputs.get("monthly") or {}).get("fixed") or [])
    ]

    return {
        "slug": slug,
        "lat": lat,
        "lon": lon,
        "annual_irradiation_kwh_m2": totals.get("H(i)_y"),
        "annual_yield_kwh_kwp": totals.get("E_y"),
        # Tatsächlicher (konfigurierter) Systemverlust = der an PVGIS übergebene
        # loss-Parameter, gespiegelt in inputs.pv_module.system_loss (i.d.R. 14 %).
        # NICHT l_total: l_total ist die Gesamt-Performance-Differenz und wird
        # separat als total_performance_delta_pct geführt.
        "system_loss_pct": pv_module.get("system_loss"),
        "total_performance_delta_pct": totals.get("l_total"),
        "optimal_slope_deg": (mounting.get("slope") or {}).get("value"),
        "optimal_azimuth_deg": (mounting.get("azimuth") or {}).get("value"),
        "peakpower_kwp": pv_module.get("peak_power"),
        "radiation_db": meteo.get("radiation_db"),
        "period_start": meteo.get("year_min"),
        "period_end": meteo.get("year_max"),
        "monthly": monthly,
    }
