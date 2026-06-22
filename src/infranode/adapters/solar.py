"""Keyloser PVGIS-Solar-Adapter fetch_solar (DATA-38, Stufe 1).

Holt aus der keylosen PVGIS-Rechen-API (EU JRC, ``PVcalc``) das klimatologische
Jahres- und Monatsmittel der Globalstrahlung und des normierten PV-Ertrags am
Stadtzentrum und liefert ein flaches raw-dict, das der reine ``map_solar``-Mapper
erwartet. PVGIS rechnet jede Koordinate in Europa, daher sind alle Register-
Staedte ohne Stadt-Allowlist abgedeckt (passt zur keyless-hosted-USP).

Referenzkonfiguration (Owner-Entscheidung): peakpower=1 kWp, loss=14 %,
optimalangles=1 (PVGIS bestimmt den optimalen Neigungswinkel und das Azimut).
Damit ist ``E_y`` direkt der Jahresertrag in kWh je kWp und stadtuebergreifend
vergleichbar.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon stammen aus dem
validierten Register (``entry.geo``) und werden nur als Query-Parameter
uebergeben.
"""

from __future__ import annotations

import httpx

_BASE = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"


async def fetch_solar(
    http: httpx.AsyncClient, *, slug: str, lat: float, lon: float
) -> dict:
    """Holt PVGIS-Solar-Kennzahlen und liefert das flache raw-dict.

    Rueckgabe-Keys (exakt das, was ``map_solar`` erwartet): ``slug``/``lat``/
    ``lon``, ``annual_irradiation_kwh_m2`` (PVGIS ``H(i)_y``),
    ``annual_yield_kwh_kwp`` (``E_y``, da peakpower=1), ``system_loss_pct``
    (``l_total``), ``optimal_slope_deg``/``optimal_azimuth_deg`` (von PVGIS
    bestimmter optimaler Aufstaenderungswinkel bzw. Azimut, 0 = Sued),
    ``peakpower_kwp``, ``radiation_db``, ``period_start``/``period_end`` (Jahre
    des Strahlungs-Datensatzes) und ``monthly`` (12 dicts: ``month``/
    ``irradiation_kwh_m2``/``yield_kwh``). Der Host ist hartkodiert (SSRF-Schutz);
    lat/lon fliessen nur als Query-Parameter ein. Fehlende Felder bleiben robust
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
        "system_loss_pct": totals.get("l_total"),
        "optimal_slope_deg": (mounting.get("slope") or {}).get("value"),
        "optimal_azimuth_deg": (mounting.get("azimuth") or {}).get("value"),
        "peakpower_kwp": (inputs.get("pv_module") or {}).get("peak_power"),
        "radiation_db": meteo.get("radiation_db"),
        "period_start": meteo.get("year_min"),
        "period_end": meteo.get("year_max"),
        "monthly": monthly,
    }
