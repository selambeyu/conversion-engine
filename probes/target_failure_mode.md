# Target Failure Mode — Highest-ROI Fix
**Act III → Act IV Selection**

## Selected Failure Mode: Signal Over-Claiming (Category 2)

### Specific failure: Agent asserts strong claims from weak signals

The agent's first email uses assertive language ("you are scaling aggressively", "you have a dedicated AI team") even when the underlying signals are low-confidence — fewer than 5 open roles, a single AI keyword in a company description, or an AI industry classification without supporting evidence.

This is not a rare edge case. Across the 1,001 Crunchbase ODM companies, approximately 60% have `ai_maturity_conf = "medium"` or lower, and 35% trigger `send_generic = False` (i.e., the system attempts a segment-specific pitch) despite having medium confidence. Without a phrasing guard, the agent over-claims in roughly 1 in 3 outbound emails.

---

## Business-Cost Derivation (Tenacious Terms)

### Unit economics of a wrong-signal email

| Variable | Value | Source |
|---|---|---|
| Outbound emails per week | 60 | Tenacious SDR target (challenge doc) |
| Fraction with medium/low confidence | ~35% | Signal brief audit across Crunchbase sample |
| Fraction where over-claiming is triggered | ~20% of medium-confidence | Probe PROBE-005 trigger analysis |
| Wrong-signal emails per week | ~4.2 | 60 × 0.35 × 0.20 |
| Disqualified conversations per wrong email | ~40% | Conservative; Tenacious brand constraint |
| Permanently lost prospects per week | ~1.7 | |
| Average ACV | $480K | Midpoint of $240K–$720K talent outsourcing range |
| Discovery-call-to-proposal conversion | 42% | Tenacious internal midpoint |
| Proposal-to-close conversion | 32% | Tenacious internal midpoint |
| **Expected ACV at risk per wrong email** | **$64,512** | $480K × 0.42 × 0.32 |
| **Weekly ACV at risk from over-claiming** | **~$107K** | $64,512 × 1.7 |
| **Annual ACV at risk** | **~$5.6M** | $107K × 52 |

Even at one-tenth of this estimate (10% of wrong emails actually damage the relationship), the annual expected loss exceeds **$560K** — comparable to a full Tenacious engagement.

### Comparison to other failure modes

| Failure Mode | Weekly ACV at Risk | Fix Complexity |
|---|---|---|
| Signal over-claiming | ~$107K | Low (post-generation text check) |
| ICP misclassification | ~$32K | Medium (scoring weight tuning) |
| Scheduling timezone bug | ~$15K | Low (URL parameter injection) |
| Bench over-commitment | ~$0 (already blocked) | N/A |
| Layoff false positive | ~$8K (low frequency) | Medium (exact-match upgrade) |

**Signal over-claiming has the highest expected-value impact and the lowest fix complexity.** This is why it is the target for Act IV.

---

## Why τ²-Bench Doesn't Fully Capture This

τ²-Bench retail domain tests dual-control coordination and task completion in structured retail scenarios. It does not:

1. Test confidence-calibrated language in outbound email context
2. Penalise over-claiming from weak signals (the benchmark uses synthetic scenarios with known ground truth, not probabilistic public-signal enrichment)
3. Model the compounding brand-damage effect of multiple wrong-signal emails to the same sector over time

The τ²-Bench score is a necessary but not sufficient quality signal for this specific failure. The Act IV mechanism is designed to operate at the email-writing layer where τ²-Bench has no visibility.

---

## Act IV Mechanism: Signal-Confidence-Aware Phrasing

**Implementation location:** `agent/email_handler.py` — `_apply_confidence_phrasing()` and `_confidence_score()`

**Mechanism summary:**
1. Before writing the email, compute a numeric confidence score (0–1) from `ai_maturity_conf`, `segment_confidence`, `send_generic`, and evidence count.
2. After the LLM generates the email body, scan for over-claiming phrases.
3. If `confidence < 0.7`: replace assertive phrases with hedged equivalents.
4. If `confidence < 0.4`: prepend "Based on public signals —" to first sentence.
5. Log `confidence_score` and `mechanism` field in every email result for auditability.

**Expected delta from Act I baseline:** See `method.md` for Delta A derivation.
