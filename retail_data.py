"""Synthetic store data for the Retail AIOS demo.

100% fabricated, modeled on the *structure* of a farm-and-home retail store (the
kind of chain Runnings runs), never real company data. Deterministic (seeded) so
the analytics, alerts, and evals are reproducible.

Shape:
  STORE          store profile
  DEPARTMENTS    the merchandising departments
  WEEKS          12 week-ending dates, oldest -> newest
  SERIES[dept]   list of 12 weekly dicts aligned to WEEKS (one per department)
  TASKS          corporate directives pushed to the store
  OPS_DOCS       free-text ops docs for the RAG corpus

A few deliberate anomalies are baked into the latest week so the data-science
layer (analytics.py) has real signal to catch: Lawn & Garden sales fall off a
cliff, Pet stock is running out, and Hardware labor blows past budget.
"""
import random
from datetime import date, timedelta

random.seed(47)  # 1947 = year the real chain was founded; keeps output stable

STORE = {
    "id": "STORE-142",
    "name": "Store #142 (synthetic)",
    "location": "Marshall, MN",
    "manager": "Alex",
    "note": "Synthetic demo data — not real company data.",
}

# (department, base weekly sales $, weekly seasonal drift, avg ticket $)
_DEPTS = [
    ("Ranch & Farm", 86000, -600, 62),
    ("Lawn & Garden", 61000, -1400, 48),   # late-season wind-down
    ("Pet", 39000, 150, 34),
    ("Sporting Goods", 54000, 300, 71),
    ("Apparel", 33000, -200, 45),
    ("Hardware", 46000, 120, 28),
    ("Automotive", 29000, 80, 39),
]
DEPARTMENTS = [d[0] for d in _DEPTS]

_N_WEEKS = 12
_today = date(2026, 8, 6)
# Week-ending Sundays, oldest first.
_last_sun = _today - timedelta(days=(_today.weekday() + 1) % 7)
WEEKS = [(_last_sun - timedelta(weeks=(_N_WEEKS - 1 - i))).isoformat() for i in range(_N_WEEKS)]


def _weekly(base, drift, ticket):
    """Build one department's 12-week series with trend + noise, plan near base."""
    rows = []
    for w in range(_N_WEEKS):
        trend = base + drift * w
        sales = max(5000, round(trend * random.uniform(0.94, 1.06)))
        plan = round(base + drift * w * 0.5)  # plan assumes a gentler slope
        txns = round(sales / (ticket * random.uniform(0.95, 1.05)))
        units = round(txns * random.uniform(1.6, 2.4))
        in_stock = round(random.uniform(93.5, 98.5), 1)
        oos = random.randint(2, 18)
        labor_budget = round(sales / 1000 * random.uniform(3.2, 3.6), 1)  # ~hrs
        labor_actual = round(labor_budget * random.uniform(0.95, 1.05), 1)
        rows.append({
            "sales_actual": sales, "sales_plan": plan,
            "transactions": txns, "units": units,
            "in_stock_pct": in_stock, "out_of_stock_count": oos,
            "labor_hours_actual": labor_actual, "labor_hours_budget": labor_budget,
        })
    return rows


SERIES = {name: _weekly(base, drift, ticket) for name, base, drift, ticket in _DEPTS}

# --- Baked-in anomalies in the latest week, so alerts have real signal. ---
_last = -1
# Lawn & Garden: sharp sales miss vs plan (weather + season end).
SERIES["Lawn & Garden"][_last]["sales_actual"] = round(SERIES["Lawn & Garden"][_last]["sales_plan"] * 0.72)
# Pet: stock crisis — low in-stock, many outages.
SERIES["Pet"][_last]["in_stock_pct"] = 88.9
SERIES["Pet"][_last]["out_of_stock_count"] = 41
# Hardware: labor well over budget.
SERIES["Hardware"][_last]["labor_hours_actual"] = round(SERIES["Hardware"][_last]["labor_hours_budget"] * 1.19, 1)

TASKS = [
    {"id": "T-1042", "title": "Reset Lawn & Garden endcap to fall planogram", "category": "Planogram",
     "due": (_today - timedelta(days=2)).isoformat(), "status": "overdue"},
    {"id": "T-1050", "title": "Apply October price changes (batch 3)", "category": "Pricing",
     "due": (_today - timedelta(days=1)).isoformat(), "status": "overdue"},
    {"id": "T-1055", "title": "Pull recalled propane heater SKU 88231", "category": "Recall",
     "due": _today.isoformat(), "status": "due today"},
    {"id": "T-1061", "title": "Complete Q3 safety walk checklist", "category": "Safety",
     "due": (_today + timedelta(days=3)).isoformat(), "status": "open"},
    {"id": "T-1067", "title": "Submit holiday seasonal labor plan", "category": "Labor",
     "due": (_today + timedelta(days=6)).isoformat(), "status": "open"},
]

OPS_DOCS = {
    "ops-memo-fall-reset": (
        "Fall Reset Memo. All stores must complete the Lawn & Garden fall planogram "
        "reset by the second Friday of the period. Move remaining summer seasonal to "
        "the clearance racks at 30 percent off. Ranch & Farm winter feed displays move "
        "to the front power aisle. District managers audit resets the following week."
    ),
    "vendor-notice-pet": (
        "Vendor Notice: Pet Nutrition. Our primary dog food supplier reported a "
        "distribution delay of 7 to 10 days on 40-pound bags. Stores should cap "
        "customer purchases at two bags, feature the in-stock alternate brand, and "
        "backorder rather than zero out the planogram. Expected recovery by end of month."
    ),
    "policy-markdowns": (
        "Markdown Policy. Managers may take up to 15 percent markdowns on aged seasonal "
        "inventory without district approval. Markdowns above 15 percent, or on regular "
        "non-seasonal stock, require district manager sign-off. All markdowns must be "
        "logged the same day in the pricing system."
    ),
    "policy-recall": (
        "Product Recall Procedure. On any recall notice, immediately remove affected "
        "SKUs from the sales floor and stockroom, quarantine them in the returns cage, "
        "and confirm completion in the task system within 24 hours. Do not sell recalled "
        "product under any circumstance."
    ),
    "horizon-report-summary": (
        "Weekly Horizon Report Summary. Store 142 comp sales are tracking slightly below "
        "plan driven by Lawn and Garden seasonality. Shrink is within tolerance. Labor "
        "hours ran over in Hardware due to a freight backlog. In-stock percentage dipped "
        "in Pet due to the supplier delay. Transactions are flat week over week."
    ),
}


# --- Product-level data for the "selling right now" board (units this vs last week). ---
# (name, department, unit_price, units_this_week, units_last_week)
_PRODUCTS = [
    ("Fall Grass Seed 20 lb", "Lawn & Garden", 49.99, 420, 240),
    ("Trail Camera (cellular)", "Sporting Goods", 129.99, 310, 150),
    ("Insulated Work Bibs", "Apparel", 89.99, 260, 140),
    ("Potted Mums 8 in", "Lawn & Garden", 8.99, 1900, 1100),
    ("40 lb Premium Dog Food", "Pet", 54.99, 180, 520),      # supplier delay -> falling
    ("Leaf Blower (cordless)", "Lawn & Garden", 159.99, 240, 160),
    ("12 ga Field Loads (box)", "Sporting Goods", 12.99, 880, 520),
    ("Galvanized Stock Tank 100 gal", "Ranch & Farm", 199.99, 95, 88),
    ("Leather Work Gloves", "Apparel", 24.99, 610, 470),
    ("Cordless Drill Kit", "Hardware", 149.99, 205, 190),
    ("Full-Synthetic Oil 5 qt", "Automotive", 34.99, 430, 405),
    ("Garden Hose 50 ft", "Lawn & Garden", 29.99, 120, 300),  # season end -> falling
    ("Cat Litter 40 lb", "Pet", 19.99, 340, 360),
    ("LED Shop Light", "Hardware", 39.99, 280, 175),
    ("Patio Heater (propane)", "Lawn & Garden", 179.99, 20, 210),  # recalled -> collapsing
    ("Heated Dog Bowl", "Pet", 34.99, 190, 90),
]

PRODUCTS = [
    {
        "name": n, "department": d, "price": p,
        "units": u, "sales": round(u * p),
        "momentum_pct": round((u / lu - 1) * 100) if lu else 0,
    }
    for n, d, p, u, lu in _PRODUCTS
]

# The systems a production deployment would unify. Synthetic here; each would connect
# via an MCP or API. Surfaced in the "Connected sources" strip on the dashboard.
DATA_SOURCES = [
    {"name": "Horizon POS", "kind": "Sales & transactions", "via": "API", "status": "sample"},
    {"name": "Microsoft 365", "kind": "Tasks, email, files", "via": "MCP", "status": "sample"},
    {"name": "Inventory Service", "kind": "On-hand & stockouts", "via": "API", "status": "sample"},
    {"name": "Vendor EDI", "kind": "Supply & recalls", "via": "API", "status": "sample"},
]


# ---- accessors used by analytics.py, the agent tools, and the endpoints ----

def latest_index():
    return _N_WEEKS - 1


def series_for(dept, metric):
    """The 12-week list of one metric for one department."""
    return [wk[metric] for wk in SERIES[dept]]


def totals_by_week(metric):
    """That metric summed across all departments, per week."""
    return [sum(SERIES[d][w][metric] for d in DEPARTMENTS) for w in range(_N_WEEKS)]


def current_week(dept):
    """The latest weekly row for a department."""
    return SERIES[dept][latest_index()]


def department_breakdown():
    """Per-department current-week sales vs plan, for the performance chart."""
    i = latest_index()
    rows = []
    for d in DEPARTMENTS:
        wk = SERIES[d][i]
        rows.append({
            "department": d, "sales": wk["sales_actual"], "plan": wk["sales_plan"],
            "vs_plan_pct": round((wk["sales_actual"] / wk["sales_plan"] - 1) * 100, 1),
        })
    return sorted(rows, key=lambda r: r["vs_plan_pct"])


def store_kpis():
    """Store-level current-week KPIs vs plan / budget, for the dashboard cards."""
    i = latest_index()
    sales = sum(SERIES[d][i]["sales_actual"] for d in DEPARTMENTS)
    plan = sum(SERIES[d][i]["sales_plan"] for d in DEPARTMENTS)
    txns = sum(SERIES[d][i]["transactions"] for d in DEPARTMENTS)
    units = sum(SERIES[d][i]["units"] for d in DEPARTMENTS)
    in_stock = round(sum(SERIES[d][i]["in_stock_pct"] for d in DEPARTMENTS) / len(DEPARTMENTS), 1)
    labor_a = sum(SERIES[d][i]["labor_hours_actual"] for d in DEPARTMENTS)
    labor_b = sum(SERIES[d][i]["labor_hours_budget"] for d in DEPARTMENTS)
    return {
        "week_ending": WEEKS[i],
        "sales_actual": sales, "sales_plan": plan,
        "sales_vs_plan_pct": round((sales / plan - 1) * 100, 1),
        "transactions": txns,
        "avg_ticket": round(sales / txns, 2),
        "units_per_txn": round(units / txns, 2),
        "in_stock_pct": in_stock,
        "labor_hours_actual": round(labor_a, 1),
        "labor_hours_budget": round(labor_b, 1),
        "labor_vs_budget_pct": round((labor_a / labor_b - 1) * 100, 1),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(store_kpis(), indent=2))
    print(f"\n{len(WEEKS)} weeks, {len(DEPARTMENTS)} departments, "
          f"{len(TASKS)} tasks, {len(OPS_DOCS)} ops docs")
