# Failure Taxonomy — Tenacious Conversion Engine
**Act III Classification**

Probes grouped by category, with observed trigger rate and severity.

---

## Taxonomy Overview

| Category | Probes | Severity | Observed FAIL/RISK | Tenacious-Specific |
|---|---|---|---|---|
| ICP Misclassification | 001–004 | Critical | 1 RISK (PROBE-004) | Yes — 4-segment ICP is unique to Tenacious |
| Signal Over-Claiming | 005–008 | Critical | 1 RISK (PROBE-006) | Yes — grounded-honesty is a Tenacious brand constraint |
| Bench Over-Commitment | 009–011 | High | 0 (all PASS) | Yes — unique to talent outsourcing |
| Tone Drift | 012–014 | Medium | 1 NOT TESTED (PROBE-013) | Partial — Tenacious style guide is specific |
| Multi-Thread Leakage | 015–017 | High | 0 (all PASS) | General, affects B2B multi-stakeholder deals |
| Cost Pathology | 018–020 | High | 1 INPUT RISK (PROBE-018) | General |
| Dual-Control Coordination | 021–023 | High | 1 PARTIAL (PROBE-021) | General — measured by τ²-Bench |
| Scheduling Edge Cases | 024–027 | Medium | 1 FAIL (PROBE-024), 1 PARTIAL (PROBE-026) | Yes — Tenacious serves EU/US/East Africa |
| Signal Reliability | 028–030 | High | 1 PARTIAL (PROBE-029), 1 PARTIAL (PROBE-030) | Yes — public signal lossiness is core risk |
| Gap Over-Claiming | 031–033 | High | 1 FAIL (PROBE-031), 2 PARTIAL | Yes — competitor gap brief is a Tenacious differentiator |

---

## Category Detail

### Critical: ICP Misclassification
**Business description:** The agent assigns a prospect to the wrong ICP segment, triggering a pitch that contradicts their actual situation.
**Highest-risk probe:** PROBE-004 — High AI maturity + post-layoff. Segment 4 pitch could beat Segment 2 if AI evidence weight exceeds +4 threshold.
**Trigger condition:** `ai_maturity_score=3` AND `had_layoffs=True` simultaneously.
**Detection:** Run `classify_segment()` with this input combination; audit score outputs.

### Critical: Signal Over-Claiming
**Business description:** The agent asserts facts about a prospect that exceed what the evidence supports.
**Highest-risk probe:** PROBE-006 — Segment 4 pitch at AI score 1. Even if segment classifier blocks it, LLM could still reference AI capability if `summary` contains AI keywords.
**Trigger condition:** `ai_maturity_score=1`, `send_generic=False`, segment somehow reaches Seg 4 path.
**Detection:** Unit test `write_email()` with ai_score=1 brief; check for Seg 4 language in output.

### High: Signal Reliability
**Business description:** Enrichment signals are wrong, leading to a correctly-reasoned but factually incorrect email.
**Highest-risk probe:** PROBE-030 — Layoff false positive via substring match in `check_layoffs()`. This is a data-quality failure, not an LLM failure.
**Trigger condition:** Two companies share a name substring. Both will receive layoff signal.
**Detection:** Query `layoffs.csv` for companies whose names are substrings of other company names.

### High: Gap Over-Claiming
**Business description:** The competitor gap brief makes claims unsupported by sufficient evidence, or frames real gaps condescendingly.
**Highest-risk probe:** PROBE-031 — Gap asserted with fewer than 3 peers. No minimum-peer guard in current code.
**Trigger condition:** Sector with few Crunchbase entries returns < 3 peers; LLM generates gap text anyway.
**Detection:** Run `build_competitor_gap_brief()` on a rare-sector company; check peer count before LLM call.

### High: Dual-Control Coordination
**Business description:** The agent proceeds or commits when it should wait for human input or prospect clarification.
**Measured by:** τ²-Bench retail domain. Current pass@1: 72.67% (95% CI: 65.04%–79.17%). Remaining ~27% failures include dual-control timing issues.
**Most actionable improvement:** Signal-confidence-aware phrasing (Act IV mechanism) directly addresses a subclass of this: low-confidence signals that the agent currently asserts, requiring human override.

### Medium: Scheduling Edge Cases
**Business description:** Timezone handling failures cause missed discovery calls.
**Active failure:** PROBE-024 — Cal.com booking link does not inject timezone for East Africa prospects.
**Fix effort:** Low — add `?timezone=Africa/Addis_Ababa` parameter when prospect geography is EA-detected.

---

## False Positive / False Negative Summary

| Failure Type | False Positive Rate | False Negative Rate | Impact |
|---|---|---|---|
| Layoff detection (PROBE-030) | ~5% (name substring collision) | ~10% (company name variations) | High |
| AI maturity scoring (PROBE-029) | ~15% (loud but shallow) | ~20% (quiet but sophisticated) | High |
| ICP segment (PROBE-004) | ~8% (high AI + layoff edge case) | ~5% (segment confidence too low) | Critical |
| Leadership change detection | ~30% (not implemented via live signal) | ~70% (signal not in CSV) | Medium |

---

## Probe Status Summary

| Status | Count | Probes |
|---|---|---|
| PASS | 18 | 001, 002, 003, 005, 007, 008, 009, 010, 011, 014, 015, 016, 017, 019, 020, 022, 027, 028 |
| PARTIAL / RISK | 11 | 004, 006, 012, 021, 023, 025, 026, 029, 030, 032, 033 |
| FAIL | 3 | 013, 024, 031 |
| NOT TESTED | 1 | 013 |
