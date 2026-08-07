"""TRACE eval suite for the Retail AIOS (Session 4).

Trace -> Read -> Analyze -> Codify -> Enforce. Code-based assertions grouped into
a retail failure taxonomy, run against the real system:

  INPUT_VALIDATED          blank questions are rejected, not answered
  SCHEMA_VALID             API responses carry all required fields
  ANOMALY_DETECTION        a real KPI break registers as an anomaly
  ALERT_PRIORITIZATION     a safety recall outranks minor sales misses   <- the fix
  CITATION_GROUNDING       policy answers cite the ops docs they used
  CORRECT_REFUSAL          uncovered questions don't get a made-up citation
  NO_HALLUCINATED_NUMBERS  store figures in answers match the data

The demonstrated before/after fix: without compliance weighting the priority score
buried a due-today safety recall below a small-dollar sales miss. Weighting it fixes
ALERT_PRIORITIZATION (0% -> 100%). Deterministic checks make the before/after
reproducible; a few agent calls exercise grounding/refusal/number-fidelity.

    python eval_suite.py            # full run (needs API keys)
    python eval_suite.py --no-agent # deterministic only (offline, fast)
Writes eval_results.json + eval_results_before.json (read by eval_app.py).
"""
import json
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient

import analytics
import retail_data as rd
from main import app

client = TestClient(app, raise_server_exceptions=False)

CATEGORIES = {
    "INPUT_VALIDATED": "Empty or blank questions are rejected, not answered",
    "SCHEMA_VALID": "API responses contain all required fields",
    "ANOMALY_DETECTION": "A real KPI break is flagged as an anomaly",
    "ALERT_PRIORITIZATION": "A safety recall is ranked above minor sales misses",
    "CITATION_GROUNDING": "Policy answers cite the ops docs they used",
    "CORRECT_REFUSAL": "Questions the ops docs don't cover get no made-up citation",
    "NO_HALLUCINATED_NUMBERS": "Store figures in answers match the data",
}

RECALL_ID = "A-TASK-T-1055"


def deterministic_checks(weighting: bool):
    """Fast, no-API assertions. `weighting` toggles the prioritization fix."""
    traces = []

    # INPUT_VALIDATED — blank input must 422 before reaching the model.
    for q in ["", "   "]:
        st = client.post("/api/assistant", json={"question": q}).status_code
        traces.append(_t("input-" + (q or "empty"), "/api/assistant", repr(q), st,
                         [("INPUT_VALIDATED", st == 422, f"status={st}")]))

    # SCHEMA_VALID — summary payload + alert shape.
    r = client.get("/api/summary"); d = r.json()
    keys_ok = all(k in d for k in ("store", "kpis", "alerts", "tasks", "trends"))
    alert_ok = all(all(f in a for f in ("id", "title", "priority", "type")) for a in d["alerts"])
    traces.append(_t("schema-summary", "/api/summary", "-", r.status_code,
                     [("SCHEMA_VALID", keys_ok and alert_ok,
                       "" if keys_ok and alert_ok else "missing fields")]))

    # ANOMALY_DETECTION — engineered Lawn & Garden cliff must flag.
    z, is_anom = analytics.zscore(rd.series_for("Lawn & Garden", "sales_actual"))
    traces.append(_t("anomaly-lg", "analytics", "Lawn & Garden sales", 200,
                     [("ANOMALY_DETECTION", is_anom, f"z={z}")]))

    # ALERT_PRIORITIZATION — the recall must land in the top 2 (the before/after).
    alerts = analytics.generate_alerts(compliance_weighting=weighting)
    top_ids = [a["id"] for a in alerts[:2]]
    recall_rank = next((i for i, a in enumerate(alerts) if a["id"] == RECALL_ID), 99)
    passed = RECALL_ID in top_ids
    traces.append(_t("prio-recall", "analytics", "rank of due-today recall", 200,
                     [("ALERT_PRIORITIZATION", passed, f"recall at rank {recall_rank + 1}")]))
    return traces


def agent_checks():
    """A few real agent calls for grounding / refusal / number fidelity."""
    traces = []
    k = rd.store_kpis()

    # CITATION_GROUNDING — a policy that IS in the ops docs.
    d = client.post("/api/assistant", json={"question": "policy on markdowns above 15 percent"}).json()
    traces.append(_t("ground-markdown", "/api/assistant", "markdown policy", 200,
                     [("CITATION_GROUNDING", len(d.get("citations", [])) > 0,
                       f"citations={d.get('citations')}")], out=d.get("answer", "")))

    # CORRECT_REFUSAL — a policy NOT in the ops docs. Grade the ANSWER TEXT, not the
    # captured citation: the agent may search, see the docs don't cover it, and refuse
    # (an earlier version of this check false-flagged that correct refusal).
    d = client.post("/api/assistant", json={"question": "what is the employee discount percentage"}).json()
    ans = (d.get("answer") or "").lower()
    # Refusal heuristic: a negation plus a pointer to the source it's not in (docs) or
    # elsewhere (HR/resources). Keyword matching is brittle here — a validated
    # LLM-as-judge is the documented next step (Session 4 Path B) for semantic checks.
    negation = "not" in ans or "n't" in ans or "unable" in ans
    pointer = any(p in ans for p in ("document", "ops doc", "hr", "resource", "policy", "available", "find", "specify"))
    refused = negation and pointer
    traces.append(_t("refuse-discount", "/api/assistant", "employee discount %", 200,
                     [("CORRECT_REFUSAL", refused, f"answer='{(d.get('answer') or '')[:80]}'")], out=d.get("answer", "")))

    # NO_HALLUCINATED_NUMBERS — the figure must match the data (exact $ or the vs-plan
    # magnitude, phrased "down 4.2%" or "-4.2%").
    d = client.post("/api/assistant", json={"question": "what are total store sales versus plan this week"}).json()
    ans = d.get("answer") or ""
    sales, vp = k["sales_actual"], abs(k["sales_vs_plan_pct"])
    ok = (str(sales) in ans.replace(",", "") or f"{sales:,}" in ans or str(vp) in ans)
    traces.append(_t("numbers-sales", "/api/assistant", "total sales vs plan", 200,
                     [("NO_HALLUCINATED_NUMBERS", ok, f"expected {sales:,} or {vp}%")], out=ans))
    return traces


def _t(cid, endpoint, inp, status, checks, out=None):
    return {"id": cid, "endpoint": endpoint, "input": inp, "status": status,
            "output": out, "checks": [{"category": c, "passed": p, "detail": d} for c, p, d in checks]}


def _assemble(traces):
    checked = {c: 0 for c in CATEGORIES}
    failed = {c: 0 for c in CATEGORIES}
    for t in traces:
        for c in t["checks"]:
            checked[c["category"]] += 1
            if not c["passed"]:
                failed[c["category"]] += 1
    total = sum(checked.values()); fails = sum(failed.values())
    categories = [{"id": c, "description": CATEGORIES[c], "checked": checked[c], "failed": failed[c],
                   "pass_rate": round(1 - failed[c] / checked[c], 3) if checked[c] else None} for c in CATEGORIES]
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {"cases": len(traces), "assertions": total, "passed": total - fails,
                    "failed": fails, "pass_rate": round((total - fails) / total, 3) if total else 0.0},
        "categories": categories, "traces": traces,
    }


def run(with_agent=True):
    agent = agent_checks() if with_agent else []
    after = _assemble(deterministic_checks(weighting=True) + agent)
    before = _assemble(deterministic_checks(weighting=False) + agent)
    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump(after, f, indent=2)
    with open("eval_results_before.json", "w", encoding="utf-8") as f:
        json.dump(before, f, indent=2)
    return before, after


def _print(before, after):
    s = after["summary"]
    print(f"\nRetail TRACE eval — {s['passed']}/{s['assertions']} assertions passed "
          f"({s['pass_rate']:.0%})\n")
    b = {c["id"]: c for c in before["categories"]}
    print(f"{'category':<26} {'before':>7} {'after':>7}")
    print("-" * 42)
    for c in after["categories"]:
        fmt = lambda r: "n/a" if r is None else f"{r:.0%}"
        move = " <-- fixed" if (b[c["id"]]["pass_rate"] is not None and c["pass_rate"] is not None
                                and c["pass_rate"] > b[c["id"]]["pass_rate"]) else ""
        print(f"{c['id']:<26} {fmt(b[c['id']]['pass_rate']):>7} {fmt(c['pass_rate']):>7}{move}")
    print(f"\noverall: {before['summary']['pass_rate']:.0%} -> {after['summary']['pass_rate']:.0%}")


if __name__ == "__main__":
    _print(*run(with_agent="--no-agent" not in sys.argv))
