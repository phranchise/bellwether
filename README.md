# Bellwether — the leading indicator for every store

An AI operating system for retail operations. It opens to one screen that shows what
actually needs attention today, ranked by dollar impact, surfaces what's selling
right now, and answers plain questions about the store's numbers, tasks, and
policies. Built as the capstone for the TAI Agentic AI Engineering Bootcamp.

**Brand & design system:** see [BRAND.md](BRAND.md). Bellwether is a fictional
retail-technology company; the identity is its own, separate from any personal brand.

> **Prototype with 100% synthetic data.** Inspired by a real problem I saw working
> at a retail support center: store data scattered across Microsoft tools and a
> legacy retail system, and managers with no single place to see it. It is not
> affiliated with, or connected to, any company's real systems or data.

**Live demo:** _add your Render URL here after deploy_
**Demo video:** _add the 60-second recording link here_

## Problem

A store manager runs a high-SKU, seasonal, multi-department store and reports up to
a district manager. The data they need lives in different places: sales in one
report, tasks pushed from corporate somewhere else, inventory in a legacy system,
policies in email. So the important signal, a department missing plan, a safety
recall due today, stock about to run out, gets buried. This tool pulls it into one
surface and puts an assistant in front of it.

## Architecture

```
Responsive dashboard (served by FastAPI)
   GET /api/summary     -> KPI cards + ranked alerts + tasks
   POST /api/assistant  -> natural-language answer + citations + reasoning trace
        |
FastAPI backend
   analytics.py    data-science layer: anomaly detection, forecast, priority score
   retail_data.py  synthetic store: 12-week KPI series, tasks, ops docs
   agent_retail.py ADK/Gemini agent (OpenAI fallback) over 4 tools
   memory.py       durable Pinecone memory (survives restarts)
   Pinecone (ops-doc RAG + memory) · OpenAI (embeddings, fallback agent) · Gemini (agent)
```

## Stack

- **Backend:** FastAPI, Python
- **RAG:** OpenAI `text-embedding-3-small` + Pinecone (cosine), chunked with overlap,
  cited retrieval with a relevance floor
- **Agent:** Google ADK on `gemini-2.5-flash`, four tools, a bounded Think/Act/Observe
  loop, with an OpenAI `gpt-4o-mini` function-calling fallback for rate limits
- **Data science:** rolling-baseline z-score anomaly detection, least-squares
  forecast (days-to-stockout, next-week sales), a priority score blending statistical
  severity with financial impact
- **Evals:** a TRACE suite (`eval_suite.py`) with a code-based failure taxonomy and a
  Streamlit viewer (`eval_app.py`)
- **Memory:** Pinecone-backed durable store (semantic profile, episodic acknowledged
  alerts, recall)
- **Frontend:** one responsive, accessible, mobile-first page, no build step
- **Hosting:** Render (single web service)

## Evals

TRACE (Trace, Read, Analyze, Codify, Enforce). The suite runs a failure taxonomy of
code-based assertions against the real system:

| Category | What it checks |
|---|---|
| INPUT_VALIDATED | Blank questions are rejected, not answered |
| SCHEMA_VALID | API responses carry all required fields |
| ANOMALY_DETECTION | A real KPI break registers as an anomaly |
| ALERT_PRIORITIZATION | A safety recall outranks minor sales misses |
| CITATION_GROUNDING | Policy answers cite the ops docs they used |
| CORRECT_REFUSAL | Uncovered questions get no made-up answer |
| NO_HALLUCINATED_NUMBERS | Store figures in answers match the data |

**Demonstrated fix (before -> after):** the priority score originally gave every task
a flat weight, so a due-today safety **recall** ranked below a small-dollar sales
miss. Weighting priority by compliance risk fixed it. `ALERT_PRIORITIZATION` went
**0% -> 100%**, overall **88% -> 100%**. Reading the traces also caught three
miscalibrated assertions of my own (false negatives on a correct refusal and a
correctly-phrased number), which is the point of TRACE: the checks get calibrated
against real output, not vibes.

## Memory

- **What's kept:** the store profile and priorities (semantic), and acknowledged
  alerts plus interactions (episodic).
- **When it's written:** the profile is seeded on startup; an alert is written the
  moment the manager acknowledges it.
- **Where it lives:** a dedicated namespace in Pinecone, so it survives server
  restarts and redeploys.
- **How it's retrieved:** semantic recall by embedding similarity; acknowledged
  alerts are fetched by exact id so the dashboard shows them as handled.
- **Forgetting:** memory is scoped by namespace and id; acknowledgements are the
  durable record, transient session chatter is not written.

## Three architecture decisions (interview-ready)

1. **Re-point a proven engine instead of rebuilding.** The reliability layer, RAG,
   agent loop, and eval harness came from a prior working project. Why: the risk on
   a deadline is integration, not novelty. Evidence: the whole domain swap shipped
   fast because the tested parts didn't change.
2. **A data-science layer drives the alerts, the dashboard doesn't just display
   numbers.** Why: "sales are down" is not actionable; "this is a statistical break
   costing an estimated $14,900, here's the next step" is. Evidence: alerts are
   computed from z-scores and financial impact, ranked, and eval-checked.
3. **Model routing with an OpenAI fallback.** Why: the primary agent model has a
   hard daily free-tier cap; a live demo can't depend on it. Evidence: when Gemini
   returns 429, the same agent runs on OpenAI and the request still succeeds.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env    # add OPENAI_API_KEY, PINECONE_API_KEY, GOOGLE_API_KEY
uvicorn main:app --reload            # http://localhost:8000
python analytics.py                  # data-science self-check
python eval_suite.py                 # TRACE eval (add --no-agent to skip live calls)
python -m streamlit run eval_app.py  # eval results UI
```

## Note on data

Everything in `retail_data.py` is fabricated for demonstration. No real company
data, systems, or credentials are used or included.
