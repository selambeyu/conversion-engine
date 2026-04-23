"""
Partition tau2-bench retail tasks into:
  - dev_slice.jsonl      (30 tasks  — yours to iterate on)
  - held_out_slice.jsonl (20 tasks  — sealed until Act IV scoring)

Usage:
    uv run python eval/partition.py
    uv run python eval/partition.py --seed 99
"""

import json
import random
import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

ROOT = Path(__file__).parent.parent
EVAL_DIR = ROOT / "eval"
TAU2_PATH = Path(os.environ.get("TAU2_BENCH_PATH", ROOT.parent / "tau2-bench"))
TAU2_SRC = TAU2_PATH / "src"

DEV_SIZE = int(os.environ.get("DEV_SLICE_SIZE", 30))
HELD_OUT_SIZE = int(os.environ.get("HELD_OUT_SLICE_SIZE", 20))

if str(TAU2_SRC) not in sys.path:
    sys.path.insert(0, str(TAU2_SRC))


def load_all_tasks(domain: str) -> list:
    """Load all tasks for a domain using the tau2 API."""
    from tau2.run import get_tasks
    tasks = get_tasks(domain)
    print(f"Loaded {len(tasks)} tasks from tau2-bench ({domain} domain)")
    return tasks


def write_jsonl(tasks: list, path: Path):
    with path.open("w") as f:
        for t in tasks:
            # Task objects are pydantic models — serialize via .model_dump()
            f.write(json.dumps(t.model_dump()) + "\n")
    print(f"  Wrote {len(tasks)} tasks → {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="retail")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dev-size", type=int, default=DEV_SIZE)
    parser.add_argument("--held-out-size", type=int, default=HELD_OUT_SIZE)
    args = parser.parse_args()

    tasks = load_all_tasks(args.domain)

    total_needed = args.dev_size + args.held_out_size
    if len(tasks) < total_needed:
        print(f"[warn] Only {len(tasks)} tasks available, need {total_needed}. Adjusting split.")
        args.dev_size = int(len(tasks) * 0.6)
        args.held_out_size = len(tasks) - args.dev_size

    rng = random.Random(args.seed)
    shuffled = tasks.copy()
    rng.shuffle(shuffled)

    dev_tasks = shuffled[: args.dev_size]
    held_out_tasks = shuffled[args.dev_size : args.dev_size + args.held_out_size]

    print(f"\nSplit (seed={args.seed}):")
    write_jsonl(dev_tasks, EVAL_DIR / "dev_slice.jsonl")
    write_jsonl(held_out_tasks, EVAL_DIR / "held_out_slice.jsonl")

    manifest = {
        "seed": args.seed,
        "domain": args.domain,
        "total_available": len(tasks),
        "dev_size": len(dev_tasks),
        "held_out_size": len(held_out_tasks),
        "dev_task_ids": [str(t.id) for t in dev_tasks],
        "held_out_task_ids": [str(t.id) for t in held_out_tasks],
    }
    manifest_path = EVAL_DIR / "partition_manifest.json"
    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Manifest  → {manifest_path}")
    print("\nDone. Run the baseline with:")
    print("  uv run python eval/run_eval.py --slice dev --label dev_tier_baseline")


if __name__ == "__main__":
    main()
