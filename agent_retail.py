"""The Retail AIOS assistant as a Google ADK agent (Session 3, re-pointed).

A store manager asks a plain-language question; the agent PLANS which tools to
use, ACTS, OBSERVES, and only then answers — it never invents numbers, and it
grounds policy answers in the store's ops docs (RAG) with citations.

Tools (procedural memory):
  get_store_kpis   - current-week sales/plan, transactions, in-stock, labor
  get_alerts       - the data-science-ranked "what needs attention" list
  get_tasks        - corporate directives and their status
  search_ops_docs  - RAG over the ops-doc corpus; returns cited passages

Because the answer depends on tool results that can't be hard-coded (which alerts
exist, whether a policy is in the docs), this is an agent, not a fixed workflow.

    python agent_retail.py     # prints a Think/Act/Observe trace
Needs GOOGLE_API_KEY (agent) plus OPENAI_API_KEY + PINECONE_API_KEY (RAG tool).
"""
import asyncio
import concurrent.futures

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()

import analytics
import clients
import retail_data as rd
import tracing

MODEL = "gemini-2.5-flash"
MAX_TOOL_CALLS = 8


def get_store_kpis() -> dict:
    """Current-week store KPIs: sales vs plan, transactions, avg ticket, in-stock
    percent, and labor vs budget. Call this for any question about store numbers,
    performance, or how the store is tracking."""
    return rd.store_kpis()


def get_alerts() -> dict:
    """The ranked 'what needs attention' list: anomalies, stock risks, labor
    overages, and overdue compliance tasks, each with a dollar impact and a
    priority score. Call this for 'what should I focus on / what's wrong today'."""
    return {"alerts": analytics.generate_alerts()}


def get_tasks() -> dict:
    """The corporate tasks pushed to this store and their status (overdue, due
    today, open). Call this for questions about tasks, directives, or deadlines."""
    return {"tasks": rd.TASKS}


def search_ops_docs(query: str) -> dict:
    """Search the store's operations documents (memos, vendor notices, policies,
    the weekly Horizon report) for a policy or procedure. Call this BEFORE
    answering any 'what's the policy / how do I / are we allowed to' question.
    Returns matching passages with ids and scores; grounded_ids are the passages
    relevant enough to cite; found_in_docs is false when nothing covers it."""
    matches, _ = clients.retrieve(query, namespace="ops")
    results = [
        {"id": m.id, "score": round(m.score, 4), "text": m.metadata.get("text", "")[:500]}
        for m in matches
    ]
    grounded = [r["id"] for r in results if r["score"] >= clients.SCORE_THRESHOLD]
    return {"query": query, "matches": results, "grounded_ids": grounded,
            "found_in_docs": bool(grounded)}


def get_loss_prevention() -> dict:
    """Registers flagged for shrink or fraud risk (unusual refunds, voids, discounts,
    no-sales), each with a risk score, the reasons, and estimated weekly exposure.
    Call this for questions about shrink, fraud, theft, or register/cashier issues."""
    return {"flagged": analytics.detect_shrink()}


def get_comms() -> dict:
    """The manager's unread emails, team messages, and today's calendar/schedule
    (freight, huddles, visits). Call this for questions about email, messages,
    schedule, or what's on today."""
    return {"emails": rd.EMAILS, "messages": rd.MESSAGES, "calendar": rd.CALENDAR}


def get_weather_outlook() -> dict:
    """The 7-day weather forecast for the store and its demand impact by
    department: which categories the weather will push up or down, the estimated
    dollar swing, and recommended actions (staffing, facings, what to feature).
    Call this for any question about weather, temperature, rain, snow, or how the
    forecast affects sales, demand, or what to stock and staff for this week."""
    import weather
    return weather.weather_outlook()


INSTRUCTION = (
    "You are the Retail AIOS assistant for a busy store manager. Be concise, "
    "direct, and practical. Follow these rules:\n"
    "- For any question about numbers or performance, call get_store_kpis (and "
    "get_alerts if it's about problems). NEVER state a number you did not get "
    "from a tool. If a figure isn't available, say so.\n"
    "- For 'what needs my attention' style questions, call get_alerts and, if "
    "relevant, get_tasks; summarize the top few by priority with their dollar "
    "impact and a next step.\n"
    "- For any policy/procedure/how-to question, you MUST call search_ops_docs "
    "first. If found_in_docs is true, answer only from those passages and cite "
    "the grounded_ids. If it is false, say the ops docs don't cover it rather "
    "than guessing.\n"
    "Keep answers short enough to read on a phone."
)

root_agent = Agent(
    name="retail_aios_agent",
    model=MODEL,
    description="Store-manager assistant grounded in the store's own KPIs, tasks, and ops docs.",
    instruction=INSTRUCTION,
    tools=[get_store_kpis, get_alerts, get_tasks, search_ops_docs, get_loss_prevention,
           get_comms, get_weather_outlook],
)


def _run_gemini_sync(message: str, timeout: int = 120):
    """Run the ADK/Gemini agent, returning (final_answer, trace, citations).

    trace is a list of THINK/ACT/OBSERVE/ANSWER step dicts; citations are the
    grounded ops-doc ids the agent actually retrieved (for the UI to show).
    """
    async def _run():
        service = InMemorySessionService()
        runner = Runner(agent=root_agent, app_name="retail-aios", session_service=service)
        session = await service.create_session(app_name="retail-aios", user_id="manager")
        content = types.Content(role="user", parts=[types.Part(text=message)])
        trace, final, citations, tool_calls = [], "(no response)", [], 0
        async for event in runner.run_async(user_id="manager", session_id=session.id, new_message=content):
            if not (event.content and event.content.parts):
                continue
            for part in event.content.parts:
                fc = getattr(part, "function_call", None)
                fr = getattr(part, "function_response", None)
                text = getattr(part, "text", None)
                if fc:
                    tool_calls += 1
                    trace.append({"step": "ACT", "tool": fc.name, "args": dict(fc.args) if fc.args else {}})
                elif fr:
                    resp = fr.response or {}
                    if isinstance(resp, dict) and resp.get("grounded_ids"):
                        citations.extend(resp["grounded_ids"])
                    trace.append({"step": "OBSERVE", "tool": fr.name, "result": str(resp)[:800]})
                elif text and text.strip():
                    is_final = event.is_final_response()
                    trace.append({"step": "ANSWER" if is_final else "THINK", "text": text})
                    if is_final:
                        final = text
            if tool_calls > MAX_TOOL_CALLS:
                final = f"Stopped: exceeded {MAX_TOOL_CALLS} tool calls without finishing."
                trace.append({"step": "ANSWER", "text": final})
                break
        return final, trace, sorted(set(citations))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _run()).result(timeout=timeout)


# --- OpenAI fallback (model routing) -------------------------------------------
# Gemini's free tier caps at 20 requests/day; a live demo can't die on that. This
# is the same agent loop over the same tools on OpenAI (ample quota), and it tracks
# real tokens + cost (the Session 1 reliability angle). run_agent_sync tries Gemini
# first and routes here on any failure.
import json  # noqa: E402

_OAI_TOOLS = [
    {"type": "function", "function": {"name": "get_store_kpis",
        "description": get_store_kpis.__doc__, "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_alerts",
        "description": get_alerts.__doc__, "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_tasks",
        "description": get_tasks.__doc__, "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "search_ops_docs",
        "description": search_ops_docs.__doc__,
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_loss_prevention",
        "description": get_loss_prevention.__doc__, "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_comms",
        "description": get_comms.__doc__, "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_weather_outlook",
        "description": get_weather_outlook.__doc__, "parameters": {"type": "object", "properties": {}}}},
]
_TOOL_FNS = {"get_store_kpis": get_store_kpis, "get_alerts": get_alerts,
             "get_tasks": get_tasks, "search_ops_docs": search_ops_docs,
             "get_loss_prevention": get_loss_prevention, "get_comms": get_comms,
             "get_weather_outlook": get_weather_outlook}


def run_openai_agent(message: str, note: str = None):
    """OpenAI function-calling version of the agent. Returns (answer, trace, citations)."""
    import clients
    msgs = [{"role": "system", "content": INSTRUCTION}, {"role": "user", "content": message}]
    trace, citations, ptok, ctok = [], [], 0, 0
    if note:
        trace.append({"step": "THINK", "text": note})
    for _ in range(MAX_TOOL_CALLS):
        resp = clients.get_openai().chat.completions.create(
            model=clients.CHAT_MODEL, messages=msgs, tools=_OAI_TOOLS)
        u = resp.usage
        ptok += u.prompt_tokens; ctok += u.completion_tokens
        m = resp.choices[0].message
        if not m.tool_calls:
            trace.append({"step": "ANSWER", "text": m.content or ""})
            trace.append({"step": "THINK",
                          "text": f"[openai] {ptok + ctok} tokens, ${clients.cost_usd(clients.CHAT_MODEL, ptok, ctok)}"})
            return (m.content or ""), trace, sorted(set(citations))
        msgs.append({"role": "assistant", "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in m.tool_calls]})
        for tc in m.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            trace.append({"step": "ACT", "tool": tc.function.name, "args": args})
            result = _TOOL_FNS[tc.function.name](**args)
            if isinstance(result, dict) and result.get("grounded_ids"):
                citations.extend(result["grounded_ids"])
            trace.append({"step": "OBSERVE", "tool": tc.function.name, "result": str(result)[:800]})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
    return "Stopped: exceeded the tool-call budget.", trace, sorted(set(citations))


@tracing.observe(name="retail-assistant")
def run_agent_sync(message: str, timeout: int = 120):
    """Run the agent: ADK/Gemini first, OpenAI fallback on any failure (rate limits).

    Observed as one Langfuse trace per question; the OpenAI/Gemini generations and
    RAG embeddings nest under it. ponytail: ADK runs in a worker thread, so on the
    Gemini path its spans may land as a sibling trace (OTel context is thread-local)
    — propagate the context here if that nesting matters for the demo.
    """
    tracing.set_trace(input={"question": message})
    try:
        answer, trace, citations = _run_gemini_sync(message, timeout)
    except Exception as e:  # noqa: BLE001 — any Gemini failure routes to OpenAI
        answer, trace, citations = run_openai_agent(
            message, note=f"Gemini unavailable ({type(e).__name__}); routed to OpenAI.")
    tracing.set_trace(output={"answer": answer, "citations": citations})
    return answer, trace, citations


if __name__ == "__main__":
    for q in ["What needs my attention today?",
              "What's our policy on markdowns above 15 percent?",
              "How are Pet sales tracking?"]:
        print(f"\n=== {q} ===")
        answer, trace, cites = run_agent_sync(q)
        for s in trace:
            print(s["step"], "-", s.get("tool") or (s.get("text", "")[:90]))
        print("CITATIONS:", cites)
        print("ANSWER:", answer[:400])
