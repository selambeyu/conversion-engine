"""
tau2-bench evaluation wrapper.

Runs the retail domain using the real tau2 API, logs every task trajectory
to Langfuse, writes trace_log.jsonl, and updates score_log.json.

Usage:
    uv run python eval/run_eval.py --slice dev --label dev_tier_baseline
"""

import json
import os
import sys
import time
import uuid
import argparse
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
EVAL_DIR = ROOT / "eval"
TRACE_LOG = EVAL_DIR / "trace_log.jsonl"
SCORE_LOG = EVAL_DIR / "score_log.json"
TAU2_PATH = Path(os.environ.get("TAU2_BENCH_PATH", ROOT.parent / "tau2-bench"))

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------
MODEL = os.environ.get("TAU2_MODEL", "qwen/qwen3-235b-a22b")
TEMPERATURE = float(os.environ.get("TAU2_TEMPERATURE", "0.0"))
DOMAIN = os.environ.get("EVAL_DOMAIN", "retail")
TRIALS = int(os.environ.get("EVAL_TRIALS", "5"))

# ---------------------------------------------------------------------------
# tau2-bench on sys.path
# ---------------------------------------------------------------------------
TAU2_SRC = TAU2_PATH / "src"
if str(TAU2_SRC) not in sys.path:
    sys.path.insert(0, str(TAU2_SRC))

# ---------------------------------------------------------------------------
# Langfuse client (lazy init so missing keys only fail at runtime)
# ---------------------------------------------------------------------------
_langfuse = None

def get_langfuse():
    global _langfuse
    if _langfuse is None:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=os.environ.get(
                "LANGFUSE_BASE_URL",
                os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            ),
        )
    return _langfuse


# ---------------------------------------------------------------------------
# tau2-bench helpers
# ---------------------------------------------------------------------------

def load_tau2():
    try:
        from tau2.run import run_single_task, get_tasks  # noqa: F401
        return True
    except ImportError as e:
        print(f"[ERROR] Cannot import tau2 from {TAU2_SRC}: {e}")
        print(f"  Make sure TAU2_BENCH_PATH={TAU2_PATH} points to your clone.")
        return False


def make_config():
    """Build a TextRunConfig for the pinned dev-tier model.
    Both agent and user simulator use the same OpenRouter model to avoid
    requiring a separate OPENAI_API_KEY (tau2 default is gpt-4.1).
    """
    from tau2.data_model.simulation import TextRunConfig
    USER_MODEL = os.environ.get("TAU2_USER_MODEL", MODEL)
    return TextRunConfig(
        domain=DOMAIN,
        agent="llm_agent",
        llm_agent=MODEL,
        llm_args_agent={"temperature": TEMPERATURE},
        llm_user=USER_MODEL,
        llm_args_user={"temperature": 0.0},
    )


def run_one_task(config, task, seed: int):
    """
    Run a single tau2 task and return a flat result dict.
    tau2.run.run_single_task returns a SimulationRun object.
    """
    from tau2.run import run_single_task

    start = time.perf_counter()
    sim = run_single_task(config, task, seed=seed)
    latency = time.perf_counter() - start

    reward = sim.reward_info.reward if sim.reward_info else 0.0
    passed = reward >= 1.0  # tau2 uses reward=1.0 for full pass

    # Extract turn-by-turn messages for the trajectory
    trajectory = []
    for msg in (sim.messages or []):
        trajectory.append({
            "role": getattr(msg, "role", str(type(msg))),
            "content": str(getattr(msg, "content", msg))[:500],  # truncate long tool outputs
        })

    return {
        "passed": passed,
        "reward": reward,
        "trajectory": trajectory,
        "latency_seconds": round(latency, 3),
    }


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def append_trace(record: dict):
    with TRACE_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")


def send_to_langfuse(record: dict):
    lf = get_langfuse()
    from langfuse.types import TraceContext

    trace_context = TraceContext(trace_id=record["trace_id"])

    with lf.start_as_current_observation(
        trace_context=trace_context,
        as_type="span",
        name=f"tau2-{DOMAIN}-{record['task_id']}-trial{record['trial']}",
        input={"task_id": record["task_id"]},
        output={"trajectory": record["trajectory"]},
        metadata={
            "task_id": record["task_id"],
            "trial": record["trial"],
            "run_label": record["run_label"],
            "domain": DOMAIN,
            "model": MODEL,
            "temperature": TEMPERATURE,
        },
    ):
        lf.set_current_trace_io(
            input={"task_id": record["task_id"]},
            output={"passed": record["passed"], "reward": record["reward"]},
        )
        lf.score_current_trace(
            name="pass@1",
            value=1.0 if record["passed"] else 0.0,
        )
        lf.score_current_trace(
            name="reward",
            value=record["reward"],
        )


# ---------------------------------------------------------------------------
# Score log
# ---------------------------------------------------------------------------

def compute_ci95(values: list) -> tuple:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    se = ((mean * (1 - mean)) / n) ** 0.5
    margin = 1.96 * se
    return round(mean - margin, 4), round(mean + margin, 4)


def update_score_log(results: list, run_label: str) -> dict:
    passes = [float(r["passed"]) for r in results]
    latencies = sorted(r["latency_seconds"] for r in results)
    n = len(passes)
    mean = sum(passes) / n
    ci_lo, ci_hi = compute_ci95(passes)

    entry = {
        "run_label": run_label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "temperature": TEMPERATURE,
        "domain": DOMAIN,
        "n_total_runs": n,
        "n_trials": TRIALS,
        "pass_at_1_mean": round(mean, 4),
        "ci_95_lower": ci_lo,
        "ci_95_upper": ci_hi,
        "latency_p50_seconds": latencies[int(n * 0.50)],
        "latency_p95_seconds": latencies[min(int(n * 0.95), n - 1)],
        "trace_ids": [r["trace_id"] for r in results],
    }

    if SCORE_LOG.exists():
        with SCORE_LOG.open() as f:
            log = json.load(f)
    else:
        log = []

    log.append(entry)
    with SCORE_LOG.open("w") as f:
        json.dump(log, f, indent=2)

    print("\n=== Score Log Entry ===")
    display = {k: v for k, v in entry.items() if k != "trace_ids"}
    print(json.dumps(display, indent=2))
    return entry


# ---------------------------------------------------------------------------
# Main eval loop
# ---------------------------------------------------------------------------

def run_eval(tasks: list, run_label: str = "dev_tier_baseline"):
    config = make_config()
    all_results = []
    total = len(tasks) * TRIALS

    print(f"\nRunning {TRIALS} trials × {len(tasks)} tasks = {total} runs")
    print(f"Model       : {MODEL}")
    print(f"Temperature : {TEMPERATURE}")
    print(f"Label       : {run_label}\n")

    for trial in range(TRIALS):
        for task in tasks:
            task_id = str(task.id)
            trace_id = uuid.uuid4().hex  # Langfuse v4 requires 32 hex chars, no hyphens
            seed = trial * 1000 + hash(task_id) % 1000

            print(f"  trial={trial}  task={task_id}  ", end="", flush=True)

            try:
                result = run_one_task(config, task, seed=seed)
            except Exception as e:
                print(f"ERROR: {e}")
                result = {
                    "passed": False,
                    "reward": 0.0,
                    "trajectory": [],
                    "latency_seconds": 0.0,
                    "error": str(e),
                }

            record = {
                "trace_id": trace_id,
                "task_id": task_id,
                "trial": trial,
                "run_label": run_label,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **result,
            }

            append_trace(record)
            all_results.append(record)

            try:
                send_to_langfuse(record)
            except Exception as e:
                print(f"[Langfuse warn] {e}")

            status = "PASS" if record["passed"] else "FAIL"
            print(f"{status}  reward={record['reward']:.2f}  latency={record['latency_seconds']:.2f}s")

    get_langfuse().flush()
    return update_score_log(all_results, run_label)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_task_slice(slice_name: str) -> list:
    """Load tasks from tau2-bench directly using the split_tasks.json manifest."""
    from tau2.run import get_tasks, load_task_splits

    slice_file = EVAL_DIR / f"{slice_name}_slice.jsonl"
    if slice_file.exists():
        # Load task IDs from our partition file, then fetch from tau2
        task_ids = []
        with slice_file.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    task_ids.append(str(obj.get("id", obj.get("task_id", ""))))
        tasks = get_tasks(DOMAIN, task_ids=task_ids)
        print(f"Loaded {len(tasks)} tasks from {slice_file.name}")
        return tasks

    raise FileNotFoundError(
        f"{slice_file} not found. Run: uv run python eval/partition.py"
    )


def main():
    parser = argparse.ArgumentParser(description="Run tau2-bench eval with Langfuse tracing")
    parser.add_argument("--slice", choices=["dev", "held_out"], default="dev")
    parser.add_argument("--label", default="dev_tier_baseline")
    parser.add_argument("--trials", type=int, default=None)
    args = parser.parse_args()

    if args.trials:
        global TRIALS
        TRIALS = args.trials

    if not load_tau2():
        sys.exit(1)

    tasks = load_task_slice(args.slice)
    run_eval(tasks, run_label=args.label)


if __name__ == "__main__":
    main()
