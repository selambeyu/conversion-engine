# Act I — Baseline Report

**Generated:** 2026-04-23 13:38 UTC

## What was reproduced

Reproduced the τ²-Bench retail domain baseline using `deepseek/deepseek-chat`
on the 30-task development slice across 5 trials.

## Results

| Metric | Value |
|--------|-------|
| **pass@1** | **91.3%** |
| 95% confidence interval | [86.7% – 96.0%] |
| Published τ²-Bench ceiling | 42.0% |
| Gap to ceiling | -49.3% below |
| Tasks passed / failed | 137 / 13 |
| Total cost | $0.0100 |
| Latency p50 | 7234ms |
| Latency p95 | 21277ms |

## Confidence interval interpretation

The 95% CI of [86.7% – 96.0%] means: if this benchmark
were run many times, the true pass@1 would fall inside this range
95% of the time. CI width = 9.3%.

## Unexpected behaviour

<!-- Fill in manually after reviewing trace_log.jsonl -->
No critical failures observed during dev-slice runs.

## Evidence

All traces logged to Langfuse. Full conversations in `logs/trace_log.jsonl`.
Score history in `logs/score_log.json`.

## Next step

This baseline (91.3% pass@1) is the comparison point for Act IV.
Any mechanism designed in Act IV must beat this score with
95% CI separation (p < 0.05).
