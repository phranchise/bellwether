"""Streamlit UI for the Retail AIOS TRACE eval suite (Session 4, the Enforce step).

Shows the failure taxonomy, per-category pass rates, the before -> after of the
demonstrated fix, and every graded trace. Re-run on demand.

    python -m streamlit run eval_app.py
Reads eval_results.json (+ eval_results_before.json). Running needs API keys in .env.
"""
import json
import os

import streamlit as st

st.set_page_config(page_title="Retail AIOS — TRACE Evals", page_icon="🧪", layout="centered")


def load(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


st.title("🧪 Retail AIOS — TRACE Evals")
st.caption("Trace → Read → Analyze → Codify → Enforce. Code-based assertions run "
           "against the system's real outputs, grouped into a retail failure taxonomy.")

col_a, col_b = st.columns(2)
if col_a.button("▶️ Run full suite", type="primary"):
    with st.spinner("Running traces (incl. live agent calls) and grading..."):
        import eval_suite
        eval_suite.run(with_agent=True)
    st.success("Done — refreshed below.")
if col_b.button("⚡ Deterministic only"):
    with st.spinner("Running offline checks..."):
        import eval_suite
        eval_suite.run(with_agent=False)
    st.success("Done — refreshed below.")

results = load("eval_results.json")
before = load("eval_results_before.json")

if not results:
    st.info("No results yet. Click **Run full suite** above.")
    st.stop()

s = results["summary"]
c1, c2, c3 = st.columns(3)
c1.metric("Overall pass rate", f"{s['pass_rate']:.0%}")
c2.metric("Assertions passed", f"{s['passed']}/{s['assertions']}")
c3.metric("Traces", s["cases"])
st.caption(f"Generated {results['generated_at']}")

if before:
    st.subheader("Before → after the fix")
    b_by = {c["id"]: c for c in before["categories"]}
    rows = []
    for c in results["categories"]:
        b = b_by.get(c["id"], {})
        fmt = lambda r: "n/a" if r is None else f"{r:.0%}"
        moved = "  ⬆️" if (b.get("pass_rate") is not None and c["pass_rate"] is not None
                          and c["pass_rate"] > b["pass_rate"]) else ""
        rows.append({"failure category": c["id"], "before": fmt(b.get("pass_rate")),
                     "after": fmt(c["pass_rate"]) + moved})
    st.table(rows)
    st.caption(f"Overall: {before['summary']['pass_rate']:.0%} → **{s['pass_rate']:.0%}**. "
               "The fix: weight the priority score by compliance risk so a due-today safety "
               "**recall** is no longer buried under a small-dollar sales miss.")

st.subheader("Failure taxonomy")
for c in results["categories"]:
    rate = "n/a" if c["pass_rate"] is None else f"{c['pass_rate']:.0%}"
    ok = c["failed"] == 0
    st.markdown(f"{'✅' if ok else '❌'} **{c['id']}** — {rate} "
                f"({c['failed']}/{c['checked']} failed)  \n<small>{c['description']}</small>",
                unsafe_allow_html=True)

st.subheader("Traces")
for t in results["traces"]:
    failed = [c for c in t["checks"] if not c["passed"]]
    icon = "❌" if failed else "✅"
    with st.expander(f"{icon} {t['id']} — {t['endpoint']} · {str(t['input'])[:50]}"):
        st.write(f"**status** `{t['status']}`")
        if isinstance(t["output"], str) and t["output"]:
            st.caption(t["output"][:400])
        for c in t["checks"]:
            st.write(f"{'✅' if c['passed'] else '❌'} {c['category']}"
                     + (f" — {c['detail']}" if c["detail"] else ""))
