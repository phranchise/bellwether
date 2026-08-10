"""Retail AIOS — FastAPI backend + dashboard host.

One service:
  GET  /                 the responsive store-manager dashboard
  GET  /health           liveness (uptime-pinger target)
  GET  /api/summary      KPIs + data-science-ranked alerts + tasks (+ ack state)
  POST /api/assistant    natural-language question -> agent answer + citations + trace
  POST /api/ack          acknowledge an alert (durable memory)

The AI pillars: reliable reasoning (structured tool outputs, bounded agent loop,
cost-aware retrieval), RAG (ops docs, cited), an ADK agent (agent_retail.py),
TRACE evals (eval_suite.py), and durable memory (memory.py).

All data is synthetic (retail_data.py) — not real company data.
"""
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

load_dotenv()

import analytics
import memory
import retail_data as rd
import tracing


@asynccontextmanager
async def lifespan(app: FastAPI):
    tracing.init()  # wire ADK instrumentation before any request runs (no-op if off)
    # Seed the ops-doc corpus (RAG) and the store profile (semantic memory) once,
    # idempotently. Non-fatal: the dashboard still loads if Pinecone is slow.
    try:
        import clients
        for doc_id, text in rd.OPS_DOCS.items():
            clients.ingest(doc_id, text, namespace="ops")
        memory.seed_profile()
    except Exception as e:  # noqa: BLE001 — best-effort seeding
        print(f"[startup] seeding skipped: {type(e).__name__}: {e}")
    yield


app = FastAPI(title="Retail AIOS", version="1.0.0", lifespan=lifespan)


class Question(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be empty")
        return v


class Ack(BaseModel):
    alert_id: str
    title: str = ""


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse("dashboard.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/summary")
def summary():
    """Everything the dashboard needs on load: profile, KPIs, ranked alerts, tasks."""
    alerts = analytics.generate_alerts()
    try:
        acked = memory.acknowledged_ids([a["id"] for a in alerts])
    except Exception:  # noqa: BLE001 — degrade gracefully if memory store is unreachable
        acked = set()
    for a in alerts:
        a["acknowledged"] = a["id"] in acked
    n = len(rd.WEEKS)
    trends = {
        "weeks": rd.WEEKS,
        "sales": rd.totals_by_week("sales_actual"),
        "transactions": rd.totals_by_week("transactions"),
        "in_stock": [round(sum(rd.SERIES[d][w]["in_stock_pct"] for d in rd.DEPARTMENTS) / len(rd.DEPARTMENTS), 1)
                     for w in range(n)],
        "labor": rd.totals_by_week("labor_hours_actual"),
    }
    movers = sorted(rd.PRODUCTS, key=lambda p: p["momentum_pct"], reverse=True)
    return {
        "store": rd.STORE,
        "kpis": rd.store_kpis(),
        "alerts": alerts,
        "tasks": rd.TASKS,
        "departments": rd.department_breakdown(),
        "trends": trends,
        "top_movers": movers[:5],
        "slow_movers": [m for m in movers if m["momentum_pct"] < 0][-4:][::-1],
        "data_sources": rd.DATA_SOURCES,
        "comms": {"emails": rd.EMAILS, "messages": rd.MESSAGES, "calendar": rd.CALENDAR},
        "loss_prevention": analytics.detect_shrink(),
        "calendar_events": rd.CALENDAR_EVENTS,
        "today": rd.TODAY_ISO,
        "weather": _weather_safe(),
    }


def _weather_safe():
    """Weather outlook for the dashboard; None if the forecast layer errors so the
    rest of the summary still loads."""
    try:
        import weather
        return weather.weather_outlook()
    except Exception:  # noqa: BLE001 — degrade gracefully
        return None


@app.get("/api/weather")
def weather_view():
    """7-day forecast + per-department demand impact + recommended actions."""
    return _weather_safe() or {"location": rd.STORE["location"], "source": "unavailable",
                               "days": [], "department_impact": [], "actions": []}


# --- Live market watch (external data via API, with a graceful fallback). ---
_ticker_cache = {"at": 0.0, "data": None}


@app.get("/api/ticker")
def ticker():
    """Quotes for retail/ag tickers. Pulls live from a public API when reachable;
    falls back to sample values so the demo never shows a dead widget. Cached 30s."""
    import random
    import time

    if _ticker_cache["data"] and time.time() - _ticker_cache["at"] < 30:
        return _ticker_cache["data"]

    symbols = [t["symbol"] for t in rd.TICKERS]
    names = {t["symbol"]: t["name"] for t in rd.TICKERS}
    out, source = [], "sample"
    try:
        import httpx
        r = httpx.get("https://query1.finance.yahoo.com/v7/finance/quote",
                      params={"symbols": ",".join(symbols)},
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        r.raise_for_status()
        for q in r.json()["quoteResponse"]["result"]:
            out.append({"symbol": q["symbol"], "name": names.get(q["symbol"], q["symbol"]),
                        "price": round(q["regularMarketPrice"], 2),
                        "change_pct": round(q.get("regularMarketChangePercent", 0), 2)})
        if out:
            source = "live"
    except Exception:  # noqa: BLE001 — fall back to sample quotes
        out = []
    if not out:
        base = {"TSCO": 271.0, "DE": 412.0, "WMT": 82.0, "TGT": 148.0, "COST": 905.0}
        for s in symbols:
            drift = random.uniform(-1.8, 1.8)
            out.append({"symbol": s, "name": names[s],
                        "price": round(base[s] * (1 + drift / 100), 2), "change_pct": round(drift, 2)})
    data = {"source": source, "quotes": out}
    _ticker_cache.update(at=time.time(), data=data)
    return data


@app.post("/api/assistant")
def assistant(q: Question):
    """Run the agent on a manager's question; return answer, citations, and the
    Think/Act/Observe trace so the reasoning is visible."""
    from agent_retail import run_agent_sync  # lazy: keeps ADK/Gemini off the summary path
    try:
        answer, trace, citations = run_agent_sync(q.question)
    except Exception as e:  # noqa: BLE001 — never 500 the UI; return a readable message
        return {"answer": f"The assistant is temporarily unavailable ({type(e).__name__}). "
                          "Please try again in a moment.", "citations": [], "trace": [], "tool_calls": 0}
    return {"answer": answer, "citations": citations, "trace": trace,
            "tool_calls": sum(1 for s in trace if s["step"] == "ACT")}


@app.post("/api/ack")
def ack(body: Ack):
    """Acknowledge an alert. Persists to durable memory so it stays acknowledged
    across sessions and restarts."""
    memory.acknowledge_alert(body.alert_id, body.title)
    return {"ok": True, "alert_id": body.alert_id}
