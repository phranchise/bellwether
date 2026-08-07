"""Shared OpenAI + Pinecone clients and the RAG helpers built on them.

One home for the retrieval infrastructure so main.py, memory.py, and
agent_retail.py all reuse it (and don't import-cycle through each other).
Clients are lazy-initialised, so importing this module for tests needs no keys.

Ported from the tested everyday-genius-endpoint reliability/RAG stack, re-pointed
at a retail index with namespaces: "ops" for the ops-doc corpus, "memory" for
durable memory.
"""
import os

from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

CHAT_MODEL = "gpt-4o-mini"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536

INDEX_NAME = "retail-aios"
TOP_K = 4
# Cosine floor for a chunk to count as relevant. ponytail: calibration knob —
# raise if answers drift off-source, lower if valid topics get refused.
SCORE_THRESHOLD = 0.35
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

# USD per 1M tokens. VERIFY against current OpenAI pricing before trusting cost.
PRICES = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}

_openai = None
_index = None


def get_openai() -> OpenAI:
    global _openai
    if _openai is None:
        _openai = OpenAI()
    return _openai


def get_index():
    global _index
    if _index is None:
        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        if not pc.has_index(INDEX_NAME):
            pc.create_index(
                name=INDEX_NAME, dimension=EMBED_DIM, metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
        _index = pc.Index(INDEX_NAME)
    return _index


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = PRICES[model]
    return round(prompt_tokens / 1e6 * p["input"] + completion_tokens / 1e6 * p["output"], 6)


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """Split text into overlapping chunks so context isn't cut mid-idea."""
    text = text.strip()
    if not text:
        return []
    step = max(1, size - overlap)
    return [text[i:i + size] for i in range(0, len(text), step) if text[i:i + size].strip()]


def embed(texts):
    """Embed a list of texts with the single locked embedding model."""
    resp = get_openai().embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data], resp.usage.total_tokens


def ingest(document_id: str, text: str, namespace: str = "ops") -> int:
    """Chunk, embed, and upsert a document. Returns the chunk count."""
    chunks = chunk_text(text)
    if not chunks:
        return 0
    vectors, _ = embed(chunks)
    items = [
        {"id": f"{document_id}#{i}", "values": v,
         "metadata": {"document_id": document_id, "chunk_index": i, "text": chunks[i]}}
        for i, v in enumerate(vectors)
    ]
    get_index().upsert(vectors=items, namespace=namespace)
    return len(items)


def retrieve(query: str, top_k: int = TOP_K, namespace: str = "ops"):
    """Embed the query and return (matches, embed_tokens) from one namespace."""
    qvec, tokens = embed([query])
    res = get_index().query(vector=qvec[0], top_k=top_k, include_metadata=True, namespace=namespace)
    return res.matches, tokens
