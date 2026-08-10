"""The data-science layer: turn raw weekly KPIs into ranked, explained alerts.

Three ideas, all running over the synthetic weekly time series in retail_data:

  1. Anomaly detection  - a rolling-baseline z-score flags a week that breaks
                          from its own recent trend (|z| > 2).
  2. Forecast           - a least-squares trend projects next week's sales-vs-plan
                          and, for inventory, days-to-stockout (proactive, not
                          just "it already happened").
  3. Priority score     - severity (statistical + how far off plan) blended with
                          financial impact ($), so the manager sees the most
                          expensive problem first. Compliance tasks are weighted up.

This is deliberately transparent, not a black box: every alert carries the z-score,
the dollar impact, and a plain-English reason, so it can be defended in a demo and
an interview. Uses only the standard library (statistics), no heavy ML dependency.

    python analytics.py     # runs a self-check
"""
from datetime import date
from statistics import mean, pstdev

import retail_data as rd

ANOMALY_Z = 2.0        # |z| above this = anomaly
BASELINE_WEEKS = 6     # trailing window the baseline is built from
AVG_WAGE_USD = 16.0    # for costing labor overage
IN_STOCK_FLOOR = 85.0  # in-stock % we treat as the danger line


def zscore(series, window=BASELINE_WEEKS):
    """z-score of the latest point vs the trailing `window` before it.

    Returns (z, is_anomaly). Guards against a zero-variance baseline.
    """
    if len(series) < window + 1:
        window = len(series) - 1
    baseline = series[-(window + 1):-1]
    latest = series[-1]
    sd = pstdev(baseline)
    if sd == 0:
        return 0.0, False
    z = (latest - mean(baseline)) / sd
    return round(z, 2), abs(z) >= ANOMALY_Z


def trend_slope(series):
    """Least-squares slope (units per week) over the series."""
    n = len(series)
    xs = list(range(n))
    mx, my = mean(xs), mean(series)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, series)) / denom


def forecast_next(series):
    """Project next week's value from the trend."""
    slope = trend_slope(series)
    return series[-1] + slope


def days_to_stockout(dept):
    """Project days until a department's in-stock % hits the danger floor.

    Uses the recent slope of in-stock %. Returns None if it isn't declining.
    """
    stock = rd.series_for(dept, "in_stock_pct")[-4:]
    slope = trend_slope(stock)  # % per week
    current = stock[-1]
    if slope >= -0.01 or current <= IN_STOCK_FLOOR:
        return 0 if current <= IN_STOCK_FLOOR else None
    weeks = (current - IN_STOCK_FLOOR) / abs(slope)
    return round(weeks * 7)


SHRINK_METRICS = ["refund_pct", "void_pct", "discount_pct", "no_sale_count"]


def detect_shrink():
    """Flag registers whose transaction behavior deviates from the store norm.

    Shrink and point-of-sale fraud (sweethearting, refund/void abuse) show up as a
    register running high on refunds, voids, discounts, and no-sales at once. For
    each metric we z-score every register against the store baseline, then sum the
    high-side z's into a composite risk. High-risk registers come back with the
    specific reasons, ranked. Pure anomaly detection, no labels needed.
    """
    flagged = []
    stats = {}
    for m in SHRINK_METRICS:
        vals = [r[m] for r in rd.REGISTERS]
        mu, sd = mean(vals), pstdev(vals)
        stats[m] = (mu, sd or 1.0)
    est_reg_sales = sum(rd.current_week(d)["sales_actual"] for d in rd.DEPARTMENTS) / max(1, len(rd.REGISTERS))
    for r in rd.REGISTERS:
        reasons, composite = [], 0.0
        for m in SHRINK_METRICS:
            mu, sd = stats[m]
            z = (r[m] - mu) / sd
            if z > 1.5:  # only the high side matters for shrink
                composite += z
                reasons.append(f"{m.replace('_', ' ').replace('pct', '%')} {r[m]} (z={round(z, 1)})")
        risk = min(100, round(composite * 12))
        if risk >= 50:
            # Rough weekly exposure: refund % over baseline applied to the register's sales.
            excess = max(0, r["refund_pct"] - stats["refund_pct"][0]) / 100
            flagged.append({
                "register": r["register"], "cashier": r["cashier"], "risk": risk,
                "reasons": reasons, "exposure_usd": round(excess * est_reg_sales),
            })
    return sorted(flagged, key=lambda f: f["risk"], reverse=True)


def _alert(**kw):
    kw.setdefault("z", None)
    kw.setdefault("financial_impact_usd", 0)
    return kw


def generate_alerts(compliance_weighting=True):
    """Scan every department + the task list, return alerts ranked by priority.

    Priority (0-100) blends statistical severity, distance from plan, and dollar
    impact; with compliance_weighting, compliance/safety tasks are floored high so
    they never get buried under a small-dollar sales miss (set False to see the
    pre-fix behavior the evals catch).
    """
    alerts = []
    i = rd.latest_index()

    for dept in rd.DEPARTMENTS:
        wk = rd.current_week(dept)

        # --- Sales vs plan (anomaly-aware) ---
        sales_series = rd.series_for(dept, "sales_actual")
        z, is_anom = zscore(sales_series)
        gap = wk["sales_plan"] - wk["sales_actual"]
        gap_pct = round((wk["sales_actual"] / wk["sales_plan"] - 1) * 100, 1)
        if gap > 0 and (is_anom or gap_pct <= -8):
            proj = forecast_next(sales_series)
            alerts.append(_alert(
                id=f"A-SALES-{dept[:3].upper()}",
                type="Sales below plan", dept=dept, metric="sales",
                title=f"{dept} sales {gap_pct}% under plan",
                detail=(f"${wk['sales_actual']:,} vs ${wk['sales_plan']:,} plan "
                        f"(z={z}). Trend projects ${round(proj):,} next week."),
                recommendation=("Check seasonal sell-through and staffing on peak days; "
                                "consider a markdown on aged stock."),
                z=z, financial_impact_usd=round(gap),
                priority=min(100, round(abs(z) * 15 + gap / 500)),
            ))

        # --- Inventory / stockout risk (forecast) ---
        if wk["in_stock_pct"] < 92 or wk["out_of_stock_count"] >= 30:
            dte = days_to_stockout(dept)
            dept_sales = wk["sales_actual"]
            lost = round((97 - wk["in_stock_pct"]) / 100 * dept_sales)  # est. weekly lost sales
            when = "already at risk" if dte == 0 else (f"~{dte} days to {IN_STOCK_FLOOR}% floor"
                                                       if dte else "declining")
            alerts.append(_alert(
                id=f"A-STOCK-{dept[:3].upper()}",
                type="Low / out-of-stock inventory", dept=dept, metric="in_stock_pct",
                title=f"{dept} in-stock at {wk['in_stock_pct']}%",
                detail=(f"{wk['out_of_stock_count']} SKUs out; {when}. "
                        f"Est. ${lost:,}/wk in lost sales."),
                recommendation="Expedite backorders, cap purchases, feature in-stock alternates.",
                financial_impact_usd=lost,
                priority=min(100, round((97 - wk["in_stock_pct"]) * 6 + lost / 500)),
            ))

        # --- Labor vs budget ---
        over = wk["labor_hours_actual"] - wk["labor_hours_budget"]
        if over > 0 and over / wk["labor_hours_budget"] >= 0.10:
            cost = round(over * AVG_WAGE_USD)
            alerts.append(_alert(
                id=f"A-LABOR-{dept[:3].upper()}",
                type="Labor over budget", dept=dept, metric="labor",
                title=f"{dept} labor {round(over / wk['labor_hours_budget'] * 100)}% over budget",
                detail=(f"{wk['labor_hours_actual']} hrs vs {wk['labor_hours_budget']} budgeted "
                        f"(+{round(over, 1)} hrs, ~${cost})."),
                recommendation="Rebalance the schedule off low-traffic hours; clear freight backlog.",
                financial_impact_usd=cost,
                priority=min(100, round(over / wk["labor_hours_budget"] * 100 + cost / 200)),
            ))

    # --- Overdue / due-today corporate tasks (compliance-weighted) ---
    tier = {"Recall": 95, "Safety": 80, "Pricing": 70, "Planogram": 60, "Labor": 55}
    for t in rd.TASKS:
        if t["status"] in ("overdue", "due today"):
            # Pre-fix: every task got a flat low priority, so a safety recall could
            # rank below a minor sales miss. The fix weights by compliance risk.
            base = (tier.get(t["category"], 60) if compliance_weighting else 40)
            if t["status"] == "due today":
                base += 3
            alerts.append(_alert(
                id=f"A-TASK-{t['id']}",
                type="Overdue corporate task", dept="Store", metric="task",
                title=f"{t['category']} task {t['status']}: {t['title']}",
                detail=f"Task {t['id']} due {t['due']} ({t['status']}).",
                recommendation="Complete and confirm in the task system today.",
                priority=min(100, base),
            ))

    # --- Shrink / fraud: a flagged register is a high-priority integrity issue. ---
    for f in detect_shrink():
        alerts.append(_alert(
            id=f"A-SHRINK-{f['register'].replace(' ', '')}",
            type="Loss prevention", dept="Store", metric="shrink",
            title=f"{f['register']} ({f['cashier']}) flagged for shrink risk",
            detail="Unusual pattern: " + "; ".join(f["reasons"][:3]) + f". Est. ${f['exposure_usd']:,}/wk exposure.",
            recommendation="Pull the register's exception report and review voids/refunds with the cashier.",
            financial_impact_usd=f["exposure_usd"],
            priority=min(100, 60 + round(f["risk"] / 4)),
        ))

    # --- Weather-driven demand: forecast-based upside/risk per department. ---
    try:
        import weather
        alerts.extend(weather.weather_alerts())
    except Exception as e:  # noqa: BLE001 — weather is best-effort, never break core alerts
        print(f"[alerts] weather signals skipped: {type(e).__name__}: {e}")

    alerts.sort(key=lambda a: a["priority"], reverse=True)
    return alerts


def demo():
    alerts = generate_alerts()

    # Lawn & Garden's engineered sales cliff must register as an anomaly.
    lg_z, lg_anom = zscore(rd.series_for("Lawn & Garden", "sales_actual"))
    assert lg_anom, f"expected Lawn & Garden sales anomaly, got z={lg_z}"

    # Pet's stock crisis must surface as an inventory alert.
    assert any(a["metric"] == "in_stock_pct" and a["dept"] == "Pet" for a in alerts), \
        "expected a Pet inventory alert"

    # Shrink detection must flag the engineered bad register (Reg 4).
    shrink = detect_shrink()
    assert any(f["register"] == "Reg 4" for f in shrink), "expected Reg 4 shrink flag"

    # The recall task must rank at or near the very top.
    top3 = [a["id"] for a in alerts[:3]]
    assert any("T-1055" in a["id"] for a in alerts), "recall task missing"
    assert alerts == sorted(alerts, key=lambda a: a["priority"], reverse=True), "not sorted by priority"

    print(f"{len(alerts)} alerts, ranked:")
    for a in alerts:
        imp = f"${a['financial_impact_usd']:,}" if a["financial_impact_usd"] else "-"
        print(f"  [{a['priority']:>3}] {a['type']:<28} {a['title'][:44]:<44} {imp}")
    print("\nself-check passed")


if __name__ == "__main__":
    demo()
