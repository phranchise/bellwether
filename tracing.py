"""Langfuse tracing — one switch, graceful when unconfigured or uninstalled.

Turn it on by setting LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (+ LANGFUSE_HOST
for your region). With no keys, the @observe decorator and the langfuse.openai
drop-in no-op, so tests and local runs need nothing. Call init() once at startup
to also stream the ADK/Gemini agent's generations in.

What gets traced:
  - OpenAI chat + embeddings  -> langfuse.openai drop-in in clients.py (tokens+cost)
  - Gemini/ADK agent runs     -> OpenInference instrumentor wired in init()
  - Each assistant question   -> one parent trace via @observe on run_agent_sync
"""
import os

ENABLED = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))

try:
    from langfuse import get_client, observe  # type: ignore
except ImportError:  # langfuse not installed -> no-op decorator, tracing stays off
    ENABLED = False

    def observe(*args, **kwargs):  # supports both @observe and @observe(name=...)
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda fn: fn

    def get_client():
        return None


def init() -> None:
    """Wire OpenInference ADK instrumentation and verify auth. No-op unless
    Langfuse is configured. Never raises — tracing must not break the app."""
    if not ENABLED:
        return
    try:
        client = get_client()
        from openinference.instrumentation.google_adk import GoogleADKInstrumentor
        GoogleADKInstrumentor().instrument()
        if client.auth_check():
            print("[tracing] Langfuse on — ADK + OpenAI traced.")
        else:
            print("[tracing] Langfuse keys set but auth_check failed; check keys/host.")
    except Exception as e:  # noqa: BLE001 — degrade to no tracing, never crash
        print(f"[tracing] setup skipped: {type(e).__name__}: {e}")


def set_trace(**io) -> None:
    """Set trace-level input/output if tracing is live (langfuse v4 API)."""
    if not ENABLED:
        return
    try:
        get_client().set_current_trace_io(**io)
    except Exception:  # noqa: BLE001 — never let tracing surface an error
        pass
