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


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    }


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
