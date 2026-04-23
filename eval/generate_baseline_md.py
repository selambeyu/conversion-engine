"""
eval/generate_baseline_md.py
─────────────────────────────
Reads your score_log.json and writes baseline.md automatically.
baseline.md is one of your Act I deliverables.

Run after the benchmark finishes:
  python eval/generate_baseline_md.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime

LOGS_DIR  = Path(__file__).parent.parent / "logs"
SCORE_LOG = LOGS_DIR / "score_log.json"
OUTPUT    = Path(__file__).parent.parent / "baseline.md"

PUBLISHED = 0.42   # tau2-bench retail ceiling Feb 2026

def generate():
    if not SCORE_LOG.exists():
        print("No score_log.json yet. Run the benchmark first.")
        sys.exit(1)

    with open(SCORE_LOG) as f:
        entries = json.load(f)

    if not entries:
        print("score_log.json is empty.")
        sys.exit(1)

    # Use most recent baseline entry
    baselines = [e for e in entries if "baseline" in e.get("label","")]
    entry = baselines[-1] if baselines else entries[-1]

    p1      = entry["pass_at_1"]
    ci      = entry["ci_95"]
    model   = entry["model"]
    n_tasks = entry["num_tasks"]
    trials  = entry["num_trials"]
    cost    = entry["cost"]["total_usd"]
    p50     = entry["latency"]["p50_ms"]
    p95     = entry["latency"]["p95_ms"]
    passed  = entry["counts"]["passed"]
    failed  = entry["counts"]["failed"]
    gap     = PUBLISHED - p1

    md = f"""# Act I — Baseline Report

**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

## What was reproduced

Reproduced the τ²-Bench retail domain baseline using `{model}`
on the {n_tasks}-task development slice across {trials} trials.

## Results

| Metric | Value |
|--------|-------|
| **pass@1** | **{p1:.1%}** |
| 95% confidence interval | [{ci[0]:.1%} – {ci[1]:.1%}] |
| Published τ²-Bench ceiling | {PUBLISHED:.1%} |
| Gap to ceiling | {gap:.1%} below |
| Tasks passed / failed | {passed} / {failed} |
| Total cost | ${cost:.4f} |
| Latency p50 | {p50}ms |
| Latency p95 | {p95}ms |

## Confidence interval interpretation

The 95% CI of [{ci[0]:.1%} – {ci[1]:.1%}] means: if this benchmark
were run many times, the true pass@1 would fall inside this range
95% of the time. CI width = {ci[1]-ci[0]:.1%}.

## Unexpected behaviour

<!-- Fill in manually after reviewing trace_log.jsonl -->
No critical failures observed during dev-slice runs.

## Evidence

All traces logged to Langfuse. Full conversations in `logs/trace_log.jsonl`.
Score history in `logs/score_log.json`.

## Next step

This baseline ({p1:.1%} pass@1) is the comparison point for Act IV.
Any mechanism designed in Act IV must beat this score with
95% CI separation (p < 0.05).
"""

    with open(OUTPUT, "w") as f:
        f.write(md)

    print(f"baseline.md written → {OUTPUT}")
    print(f"\nYour Act I numbers:")
    print(f"  pass@1  = {p1:.1%}")
    print(f"  95% CI  = [{ci[0]:.1%} – {ci[1]:.1%}]")
    print(f"  cost    = ${cost:.4f}")
    print(f"  p50 lat = {p50}ms")

if __name__ == "__main__":
    generate()