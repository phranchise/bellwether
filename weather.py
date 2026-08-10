"""Weather-driven demand: turn the local forecast into department-level demand
signals, dollar impact, and actions a farm-and-home manager can take today.

Why this belongs in Bellwether: this store's categories are weather-elastic —
cold snaps pull winter feed, heaters, and insulated apparel; warm dry spells
move lawn & garden; rain suppresses foot traffic. The manager knows this in
their gut; this makes it a ranked, dollar-quantified signal like every other
alert.

The model (transparent, stdlib only, same spirit as analytics.py):
  demand_index = 100 + sum(coefficient * weather_driver)
where drivers are the temperature anomaly vs the seasonal normal, rain inches,
and snow inches. Coefficients are expert priors per department.

  python weather.py     # self-check on the synthetic forecast

Forecast source: a deterministic synthetic forecast by default (an early-season
cold front), so the demo always shows the feature's value and stays consistent
with the rest of the store's synthetic, pinned data. Set WEATHER_LIVE=1 to pull
the real Open-Meteo forecast (free, no API key) for the store's location instead
— same live-or-sample pattern as /api/ticker.
"""
import os
import time

import retail_data as rd

# Store location (Marshall, MN — the synthetic store's home).
LAT, LON = 44.4469, -95.7883

# Average daily high (°F) by month for the location — the climatological normal
# we measure the forecast against. A "temperature anomaly" is forecast minus this.
NORMAL_HIGH_F = {1: 23, 2: 28, 3: 41, 4: 58, 5: 71, 6: 80,
                 7: 84, 8: 82, 9: 73, 10: 58, 11: 40, 12: 27}

# Per-department weather sensitivity, in demand-index points.
#   temp  : points per +10°F above the seasonal normal (warm-driven positive,
#           cold-driven negative)
#   precip: points per inch of rain (foot-traffic effect / storm-prep pull)
#   snow  : points per inch of snow (winter-prep pull)
# ponytail: expert-prior coefficients — a real deployment fits these from POS x
# weather history. Tune here; this is the knob a minimal model can't see.
WEATHER_MODEL = {
    "Lawn & Garden":  {"temp":  4.0, "precip": -6.0, "snow":  0.0},
    "Ranch & Farm":   {"temp": -3.0, "precip":  1.0, "snow":  5.0},
    "Apparel":        {"temp": -5.0, "precip": -1.0, "snow":  4.0},
    "Hardware":       {"temp": -1.0, "precip":  2.0, "snow":  4.0},
    "Automotive":     {"temp": -3.0, "precip":  1.0, "snow":  3.0},
    "Sporting Goods": {"temp": -3.0, "precip": -2.0, "snow":  2.0},
    "Pet":            {"temp": -0.5, "precip": -1.0, "snow":  1.0},
}

# WMO weather code -> (short label, emoji). Coarse buckets are enough for the UI.
_WMO = [
    ({0}, "Clear", "☀️"), ({1, 2}, "Partly cloudy", "🌤️"), ({3}, "Overcast", "☁️"),
    ({45, 48}, "Fog", "🌫️"), ({51, 53, 55, 56, 57}, "Drizzle", "🌦️"),
    ({61, 63, 65, 66, 67, 80, 81, 82}, "Rain", "🌧️"),
    ({71, 73, 75, 77, 85, 86}, "Snow", "🌨️"), ({95, 96, 99}, "Storm", "⛈️"),
]


def _wmo(code):
    for codes, label, icon in _WMO:
        if code in codes:
            return label, icon
    return "Mixed", "🌥️"


# --- Forecast source: live Open-Meteo, synthetic fallback. Cached 1h. ----------
_cache = {"at": 0.0, "data": None}


def _synthetic_forecast():
    """A deterministic 7-day forecast for the demo: an early-season cold front
    moving through mid-week, so the weather signal has real story to tell."""
    import datetime
    start = datetime.date.fromisoformat(rd.TODAY_ISO)
    # highs dip Wed-Fri (a cold snap), rain Thu, first flurries Fri.
    highs = [79, 76, 63, 58, 55, 68, 74]
    lows = [61, 58, 47, 41, 39, 50, 57]
    precip = [0.0, 0.1, 0.3, 0.9, 0.2, 0.0, 0.0]
    snow = [0.0, 0.0, 0.0, 0.0, 0.4, 0.0, 0.0]
    codes = [0, 2, 3, 65, 71, 1, 0]
    days = []
    for i in range(7):
        label, icon = _wmo(codes[i])
        days.append({"date": (start + datetime.timedelta(days=i)).isoformat(),
                     "tmax": highs[i], "tmin": lows[i], "precip": precip[i],
                     "snow": snow[i], "label": label, "icon": icon})
    return {"source": "sample", "days": days}


def fetch_forecast():
    """7-day daily forecast for the store. Synthetic story forecast by default;
    real Open-Meteo when WEATHER_LIVE is set (falls back to synthetic on any
    error). Cached for an hour."""
    if _cache["data"] and time.time() - _cache["at"] < 3600:
        return _cache["data"]
    if not os.getenv("WEATHER_LIVE"):
        data = _synthetic_forecast()
        _cache.update(at=time.time(), data=data)
        return data
    data = None
    try:
        import httpx
        r = httpx.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum,weathercode",
            "temperature_unit": "fahrenheit", "precipitation_unit": "inch",
            "timezone": "America/Chicago", "forecast_days": 7}, timeout=4)
        r.raise_for_status()
        d = r.json()["daily"]
        days = []
        for i in range(len(d["time"])):
            label, icon = _wmo(d["weathercode"][i])
            days.append({"date": d["time"][i], "tmax": round(d["temperature_2m_max"][i]),
                         "tmin": round(d["temperature_2m_min"][i]),
                         "precip": round(d["precipitation_sum"][i], 2),
                         "snow": round(d["snowfall_sum"][i], 2), "label": label, "icon": icon})
        if days:
            data = {"source": "live", "days": days}
    except Exception:  # noqa: BLE001 — fall back to the synthetic forecast
        data = None
    if not data:
        data = _synthetic_forecast()
    _cache.update(at=time.time(), data=data)
    return data


def _daily_index(dept, day, month):
    """Demand-index contribution for one department on one day (100 = normal)."""
    c = WEATHER_MODEL[dept]
    temp_anom = day["tmax"] - NORMAL_HIGH_F[month]
    return 100 + c["temp"] * temp_anom / 10 + c["precip"] * day["precip"] + c["snow"] * day["snow"]


def department_impact(forecast=None):
    """Per-department 7-day demand outlook: mean index vs normal, direction, the
    dominant weather driver, and the dollar swing against this week's sales."""
    forecast = forecast or fetch_forecast()
    month = int(forecast["days"][0]["date"][5:7])
    rows = []
    for dept in WEATHER_MODEL:
        idxs = [_daily_index(dept, d, month) for d in forecast["days"]]
        idx = sum(idxs) / len(idxs)
        weekly_sales = rd.current_week(dept)["sales_actual"]
        impact = round((idx / 100 - 1) * weekly_sales)
        # dominant driver over the week
        c = WEATHER_MODEL[dept]
        mean_anom = sum(d["tmax"] - NORMAL_HIGH_F[month] for d in forecast["days"]) / 7
        tot_precip = sum(d["precip"] for d in forecast["days"])
        tot_snow = sum(d["snow"] for d in forecast["days"])
        drivers = {"temperature": abs(c["temp"] * mean_anom / 10),
                   "rain": abs(c["precip"] * tot_precip / 7),
                   "snow": abs(c["snow"] * tot_snow / 7)}
        driver = max(drivers, key=drivers.get)
        rows.append({
            "department": dept, "index": round(idx, 1),
            "direction": "up" if idx >= 100.5 else "down" if idx <= 99.5 else "flat",
            "impact_usd": impact, "driver": driver,
        })
    return sorted(rows, key=lambda r: abs(r["impact_usd"]), reverse=True)


# Action templates: how a manager acts on a weather-driven demand swing per dept.
_ACTIONS = {
    "Ranch & Farm":  ("Move winter feed & heaters to the power aisle; add an associate to Ranch & Farm.",
                      "Trim Ranch & Farm seasonal facings; hold winter-prep freight."),
    "Lawn & Garden": ("Extend the lawn & garden set and feature grass seed/mums while it's dry.",
                      "Accelerate the fall markdown on summer seasonal — rain and cold end the season."),
    "Apparel":       ("Front insulated bibs, gloves, and base layers; build a cold-weather endcap.",
                      "Hold the apparel cold-weather reset — the warm-up softens demand."),
    "Hardware":      ("Stage ice-melt, generators, and storm-prep on the front aisle.",
                      "No storm pull needed; keep hardware freight on the normal cadence."),
    "Automotive":    ("Feature batteries, wiper fluid, and oil ahead of the cold.",
                      "Automotive winter demand is quiet this week."),
    "Sporting Goods": ("Feature cold-weather hunting gear ahead of the front.",
                       "Keep sporting goods on plan."),
    "Pet":           ("Feature heated bowls and cold-weather pet gear.",
                      "Pet demand is weather-neutral this week."),
}


def _featured(dept):
    """The department's current top seller, for a concrete action."""
    prods = [p for p in rd.PRODUCTS if p["department"] == dept]
    return max(prods, key=lambda p: p["units"])["name"] if prods else None


def recommended_actions(forecast=None, top_n=3):
    """The few biggest actionable weather swings, as manager-ready actions."""
    impact = department_impact(forecast)
    actions = []
    for r in impact[:top_n]:
        if abs(r["impact_usd"]) < 400:
            continue
        up = r["direction"] == "up"
        text = _ACTIONS.get(r["department"], ("Adjust staffing and facings.", "Hold."))[0 if up else 1]
        feat = _featured(r["department"])
        actions.append({
            "department": r["department"], "direction": r["direction"],
            "impact_usd": r["impact_usd"], "driver": r["driver"],
            "featured": feat, "action": text,
        })
    return actions


def weather_alerts(forecast=None):
    """Weather-driven demand swings large enough to rank alongside the other
    alerts. Positive = capture the upside; negative = a demand risk to plan for.
    Returns alert dicts shaped like analytics.generate_alerts()'s."""
    forecast = forecast or fetch_forecast()
    out = []
    for r in department_impact(forecast):
        if abs(r["impact_usd"]) < 1200 or r["direction"] == "flat":
            continue
        up = r["direction"] == "up"
        text = _ACTIONS.get(r["department"], ("Adjust staffing and facings.", "Hold."))[0 if up else 1]
        verb = "upside" if up else "risk"
        out.append({
            "id": f"A-WX-{r['department'][:3].upper()}",
            "type": "Weather-driven demand", "dept": r["department"], "metric": "weather",
            "title": (f"{r['department']} demand {'+' if up else ''}{r['index'] - 100:.0f}% "
                      f"on the {r['driver']} outlook"),
            "detail": (f"7-day forecast shifts {r['department']} demand to index {r['index']} "
                       f"(100 = normal) — an estimated {'+' if up else ''}${r['impact_usd']:,} "
                       f"{verb} vs a normal week."),
            "recommendation": text,
            "z": None, "financial_impact_usd": abs(r["impact_usd"]),
            "priority": min(85, 45 + round(abs(r["impact_usd"]) / 800)),
        })
    return out


def weather_outlook():
    """Everything the dashboard's Weather view needs, in one payload."""
    forecast = fetch_forecast()
    return {
        "location": rd.STORE["location"], "source": forecast["source"],
        "days": forecast["days"], "department_impact": department_impact(forecast),
        "actions": recommended_actions(forecast),
    }


def demo():
    fc = _synthetic_forecast()
    impact = department_impact(fc)
    by = {r["department"]: r for r in impact}

    # The engineered cold front should push cold-driven departments up and Lawn &
    # Garden down — the whole point of the feature.
    assert by["Ranch & Farm"]["direction"] == "up", by["Ranch & Farm"]
    assert by["Apparel"]["direction"] == "up", by["Apparel"]
    assert by["Lawn & Garden"]["direction"] == "down", by["Lawn & Garden"]

    # A normal week (forecast == seasonal normal, no precip) must read ~flat.
    month = int(fc["days"][0]["date"][5:7])
    flat = [dict(tmax=NORMAL_HIGH_F[month], tmin=50, precip=0.0, snow=0.0, label="", icon="", date=fc["days"][0]["date"])] * 7
    for r in department_impact({"source": "sample", "days": flat}):
        assert r["direction"] == "flat", f"expected flat on a normal week, got {r}"

    alerts = weather_alerts(fc)
    assert alerts, "expected at least one weather alert on the cold-front forecast"
    assert all(a["type"] == "Weather-driven demand" for a in alerts)

    print(f"forecast source: {fc['source']}, {len(fc['days'])} days")
    print(f"{len(impact)} departments ranked by weather impact:")
    for r in impact:
        print(f"  {r['department']:<16} index {r['index']:>5}  "
              f"{'+' if r['impact_usd'] >= 0 else ''}{r['impact_usd']:>6} USD  ({r['driver']})")
    print(f"\n{len(alerts)} weather alert(s), {len(recommended_actions(fc))} action(s)")
    print("self-check passed")


if __name__ == "__main__":
    demo()
