"""
logger.py
─────────────────────────────────────────────────────
Every single thing your AI does gets logged here.

When your AI sends an email → log it → get a trace_id
When your AI runs a benchmark task → log it → get a trace_id
When your AI qualifies a lead → log it → get a trace_id

That trace_id is your PROOF it happened.
─────────────────────────────────────────────────────
"""

import uuid
import os
from datetime import datetime
from dotenv import load_dotenv
from langfuse import Langfuse
from langfuse.types import TraceContext

load_dotenv()

_langfuse = None


def get_langfuse():
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        )
    return _langfuse


def log_trace(name, input_data, output_data,
              metadata=None, cost_usd=0.0,
              latency_ms=0, passed=None, tags=None):
    """
    Log any action and return a trace_id string.

    name        = what happened e.g. "email_sent", "benchmark_task"
    input_data  = what went IN  (dictionary)
    output_data = what came OUT (dictionary)
    cost_usd    = how much this AI call cost
    latency_ms  = how long it took in milliseconds
    passed      = True/False for benchmark tasks, None for other actions
    tags        = list of labels e.g. ["benchmark", "retail"]

    Returns: trace_id  ← save this string, it is your evidence
    """
    lf = get_langfuse()

    # Langfuse v4 requires 32 lowercase hex chars, no hyphens
    trace_id = uuid.uuid4().hex
    trace_context = TraceContext(trace_id=trace_id)

    full_metadata = {
        **(metadata or {}),
        "cost_usd":   cost_usd,
        "latency_ms": latency_ms,
        "passed":     passed,
        "logged_at":  datetime.utcnow().isoformat(),
    }

    with lf.start_as_current_observation(
        trace_context=trace_context,
        as_type="span",
        name=name,
        input=input_data,
        output=output_data,
        metadata=full_metadata,
    ):
        lf.set_current_trace_io(input=input_data, output=output_data)

        if passed is not None:
            lf.score_current_trace(name="pass@1", value=1.0 if passed else 0.0)

        if cost_usd:
            lf.score_current_trace(name="cost_usd", value=cost_usd)

    lf.flush()
    return trace_id


def log_benchmark_task(task_id, domain, model,
                       conversation, passed,
                       cost_usd, latency_ms, trial_num):
    """
    Specific logger for one tau2-bench task run.
    Called once per task per trial during Act I.
    """
    return log_trace(
        name=f"benchmark_{domain}_trial{trial_num}",
        input_data={
            "task_id": task_id,
            "domain":  domain,
            "model":   model,
            "trial":   trial_num,
        },
        output_data={
            "conversation": conversation,
            "passed":       passed,
        },
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        passed=passed,
        tags=["benchmark", domain, f"trial-{trial_num}"],
    )
