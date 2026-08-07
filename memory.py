"""Durable, Pinecone-backed memory (Session 5).

Four memory types, one durable store (the "memory" namespace in Pinecone, which
survives server restarts and redeploys — that's what satisfies "data persists
across sessions"):

  working    - the current request/session context (held in-process, not here)
  semantic   - facts about the store & manager (the profile)        [persisted]
  episodic   - past interactions + acknowledged alerts              [persisted]
  procedural - how to act = the agent's tools (see agent_retail.py)

Persisted memories are embedded so they're semantically recallable; acknowledged
alerts also use a deterministic id so we can fetch them back exactly.
"""
import time

import clients

NS = "memory"


def _upsert(vec_id: str, text: str, meta: dict):
    vec, _ = clients.embed([text])
    clients.get_index().upsert(
        vectors=[{"id": vec_id, "values": vec[0], "metadata": {"text": text, **meta}}],
        namespace=NS,
    )


def _fetched(res):
    """Normalise a Pinecone fetch response to a {id: vector} dict across versions."""
    return getattr(res, "vectors", None) or (res.get("vectors", {}) if isinstance(res, dict) else {})


def remember(text: str, kind: str = "episodic", vec_id: str = None):
    _upsert(vec_id or f"{kind}::{int(time.time() * 1000)}", text, {"kind": kind, "ts": time.time()})


def recall(query: str, top_k: int = 3):
    """Semantically recall past memories relevant to the query."""
    matches, _ = clients.retrieve(query, top_k=top_k, namespace=NS)
    return [m.metadata.get("text", "") for m in matches if m.score >= 0.30]


def acknowledge_alert(alert_id: str, title: str = ""):
    _upsert(f"ack::{alert_id}", f"Manager acknowledged alert: {title} ({alert_id})",
            {"kind": "episodic", "alert_id": alert_id})


def acknowledged_ids(alert_ids):
    """Which of these alert ids has the manager already acknowledged (durably)?"""
    if not alert_ids:
        return set()
    res = clients.get_index().fetch(ids=[f"ack::{a}" for a in alert_ids], namespace=NS)
    got = _fetched(res)
    return {aid for aid in alert_ids if f"ack::{aid}" in got}


def seed_profile():
    """Semantic memory: who this store is and what it optimises for. Idempotent."""
    from retail_data import STORE
    _upsert(
        "profile::store",
        f"Store profile: {STORE['name']} in {STORE['location']}, managed by {STORE['manager']}. "
        "Priorities: hit the weekly sales plan, keep in-stock above 95 percent, hold labor to "
        "budget, and clear compliance tasks (recalls, pricing, planograms) on time.",
        {"kind": "semantic"},
    )


def profile_text() -> str:
    res = clients.get_index().fetch(ids=["profile::store"], namespace=NS)
    v = _fetched(res).get("profile::store")
    if not v:
        return ""
    md = v["metadata"] if isinstance(v, dict) else v.metadata
    return md.get("text", "")
