# Conversion Engine — Decision Memo
**To:** Tenacious Consulting CEO and CFO
**From:** Engineering, 10 Academy Week 10
**Date:** April 25, 2026
**Re:** Deploy recommendation for automated lead generation system

---

## Page 1 — The Decision

### Executive Summary

We built an automated lead generation and conversion system that finds prospective Tenacious clients from public data, enriches each with a grounded hiring signal brief, sends personalised outbound emails, qualifies replies, and books discovery calls — all without human involvement until a call is confirmed. On the τ²-Bench retail conversational benchmark, the system scores 72.67% pass@1 (95% CI: 65.0%–79.2%), compared to the published 42% industry reference. We recommend a 30-day pilot against 100 prospects in the recently-funded startup segment, with a budget of $18/week in compute costs.

---

### τ²-Bench Performance

| Condition | pass@1 | 95% CI | Cost/task | p50 latency |
|---|---|---|---|---|
| Published reference (Feb 2026) | 42.0% | — | — | — |
| Day 1 baseline (dev tier, Qwen3) | 72.67% | [65.0%, 79.2%] | $0.0199 | 105.9s |
| Held-out baseline (no mechanism) | 72.00% | [63.2%, 80.8%] | $0.0199 | 109.4s |
| With mechanism (held-out) | 73.00% | [64.3%, 81.7%] | $0.0199 | 109.1s |

Source: `eval/score_log.json`, `eval/ablation_results.json`, `eval/held_out_traces.jsonl`

The mechanism (signal-confidence-aware phrasing) does not move the τ²-Bench score significantly (Delta A = +0.01, p = 0.87). This is expected: τ²-Bench measures retail task completion; the mechanism prevents email over-claiming — a failure mode τ²-Bench does not test. The honest value of the mechanism is documented in `method.md` and verified through email output audits.

---

### Cost Per Qualified Lead

| Cost component | Per prospect | Source |
|---|---|---|
| Enrichment (Crunchbase + layoffs CSV) | $0.002 | logs/prospect_runs.jsonl |
| LLM email writing (OpenRouter Qwen3) | $0.020 | eval/score_log.json avg_agent_cost |
| API overhead (Resend + HubSpot + Cal.com) | $0.001 | Free-tier APIs |
| **Total per prospect touched** | **$0.023** | |
| Reply rate (signal-grounded, top-quartile) | 7–12% | Clay / Smartlead benchmarks |
| **Cost per reply (qualified entry)** | **$0.19–$0.33** | |
| Discovery-call conversion from reply | 42% midpoint | Tenacious internal |
| **Cost per booked discovery call** | **$0.45–$0.78** | |

Tenacious target: under $5 per qualified lead. This system is **6–11× below that target.** Even at 10× cost inflation from live deployment overhead, cost remains under $5.

---

### Speed-to-Lead Delta

Manual process (Tenacious current state): 30–40% of qualified conversations stall in the first two weeks because the person who initiated the conversation must personally handle the thread while managing delivery work. System automated response time: 8–15 seconds from reply receipt to qualified response or booking link sent. Stalled-thread rate observed in system traces: 0% (every inbound reply is processed instantly). Source: `logs/prospect_runs.jsonl`, Tenacious CFO estimate (challenge document).

---

### Competitive-Gap Outbound Performance

In the 3 end-to-end prospect runs logged in `logs/prospect_runs.jsonl`, 100% led with a research finding (AI maturity score + hiring signal brief). Generic pitch fraction: 0%. The reply-rate delta between signal-grounded and generic outbound is documented as 7–12% vs. 1–3% in published benchmarks. System-specific delta measured against live Tenacious data: not yet available (requires pilot deployment). Source: `evidence_graph.json` → `reply_rate_signal_grounded`, `reply_rate_baseline_b2b`.

---

### Annualized Dollar Impact

All scenarios use: 60 outbound/week, 7% reply rate (signal-grounded low estimate), 42% discovery-call conversion, 32% proposal-to-close conversion, $480K ACV midpoint (talent outsourcing).

| Scenario | Annual outbound | Expected closes | Annual revenue impact |
|---|---|---|---|
| One segment (Seg 1: recently funded) | 3,120 | 29 | **$14.0M** |
| Two segments (Seg 1 + Seg 2) | 6,240 | 58 | **$27.8M** |
| All four segments | 12,480 | 116 | **$55.7M** |

These numbers are upper bounds assuming consistent signal quality. Conservative estimate at 50% model discount: $7M / $14M / $28M respectively.

---

### Pilot Recommendation

**Segment:** recently_funded_startup (Series A/B, last 180 days, $5M–$30M raise)
**Lead volume:** 100 prospects over 30 days (from Crunchbase ODM sample)
**Weekly compute budget:** $18 (LLM + API, well within free-tier limits for 30 days)
**Success criterion (trackable after 30 days):** At least 2 booked discovery calls from the 100-prospect cohort. This requires a 2% booking rate from initial outreach — well below the 7–12% expected reply rate × 42% booking conversion.

---

## Page 2 — The Skeptic's Appendix

### Four Failure Modes τ²-Bench Doesn't Capture

**1. Offshore-perception objection — Tenacious-specific**
Some prospects, particularly engineering-led companies with a public "build in-house" culture, react negatively to talent outsourcing pitches even when the signal brief is accurate. τ²-Bench retail scenarios do not include cultural/ideological objections to the product category itself. What would catch it: a set of adversarial probes using defensive personas ("we don't offshore") run against the reply handler. Cost to add: 4 hours of probe development + 20 synthetic dialogues. Current risk: ~10% of Segment 2 prospects in the Crunchbase sample are companies with public "in-house only" engineering culture signals (detectable from job post language).

**2. Bench mismatch — Tenacious-specific**
The system never checks current Tenacious bench availability before sending outreach. A prospect who replies "we need 8 Go engineers starting June 1" will receive a booking confirmation, and only on the discovery call will the human Tenacious lead discover whether Go engineers are available. τ²-Bench does not test inventory-gated commitments. What would catch it: integrate the bench summary CSV into the email handler; block or soften pitches for stacks with zero bench availability. Current risk: moderate; the bench summary shows Go as available but count is not validated per engagement.

**3. AI maturity false positive — signal reliability failure**
A company with "AI" in its name and an executive who posts about AI weekly can score 2–3 in the system despite having zero actual AI engineering function. The system pitches Segment 4 (ML platform migration) to a marketing-AI company. τ²-Bench doesn't test public-signal reliability. What would catch it: add a role-count floor (require ≥ 2 AI-adjacent open roles for score ≥ 2). Cost: 2 hours of scoring refinement. Current false-positive rate estimate: ~15% of AI maturity score ≥ 2 companies in the Crunchbase sample.

**4. Timezone scheduling failure — operational**
Prospects in East Africa (UTC+3) receive Cal.com booking links without timezone injection. The link renders in the prospect's browser timezone, which is correct for web browsers, but SMS links open in variable environments. A prospect who books via SMS link may see incorrect times. τ²-Bench does not test timezone handling. What would catch it: inject `?timezone={tz}` into booking links when prospect geography is detected. Fix time: 30 minutes. Current failure rate: 100% of East Africa prospects receive links without explicit timezone parameter.

---

### Public-Signal Lossiness

**Quietly sophisticated but publicly silent company:** A B2B infrastructure company that does all AI work in private repos, has no public AI blog, no "AI" in job titles (uses "software engineer" for ML roles), and whose CEO never posts publicly. Public AI maturity score: 0. System action: non-AI pitch (Segment 1 or 2). Business impact: correct generic pitch sent; no damage. But the prospect would have been a strong Segment 4 target. **False negative cost:** missed $80–300K consulting engagement opportunity.

**Loud but shallow company:** A startup with "AI" in its name, a CEO who keynotes about AI transformation, and a public GitHub with one LLM tutorial repo. No actual AI engineers, no data platform, no inference infrastructure. Public AI maturity score: 2–3. System action: Segment 4 pitch (ML platform migration). Business impact: CTO reads an email about "scaling your ML inference platform" and immediately identifies the pitch as uninformed. **False positive cost:** permanent disqualification, brand damage, ~$64K expected ACV at risk per PROBE-006 analysis.

---

### Gap-Analysis Risks

**Risk 1: Deliberate strategic non-adoption.** A top-quartile practice in a sector is "open-source model self-hosting." The prospect has made a deliberate compliance decision to use only vendor-hosted models (HIPAA, SOC2). The competitor gap brief presents this as a deficiency. The CTO responds: "We chose not to do this for regulatory reasons." The agent has zero credibility for the rest of the thread. Example from data: HealthAI (Crunchbase sample) — healthcare sector, self-hosting would violate HIPAA BAA requirements. The current `competitor_gap_brief.py` does not filter practices by regulatory context.

**Risk 2: Sector with insufficient peer data.** When fewer than 5 peers are found in the Crunchbase ODM sample for a given sector, the LLM generates gap text with very limited evidence. The result can reference a "top quartile" built from 2 companies, one of which may be the prospect's own parent company. Current code does not enforce a minimum peer count. PROBE-031 captures this failure. Fix: add `if len(peers) < 3: skip_gap_analysis()`.

---

### Brand-Reputation Comparison

If the system sends 1,000 emails and 5% (50) contain factually wrong signal data (wrong layoff flag, wrong funding amount, wrong AI maturity inference):

| Metric | Value |
|---|---|
| Wrong-signal emails | 50 |
| Fraction where prospect notices and is offended | ~40% (CTOs are detail-oriented) |
| Permanently disqualified prospects | ~20 |
| Expected ACV per disqualified prospect | $64,512 (using evidence_graph conversion math) |
| **Brand damage cost** | **~$1.29M** |
| Total reply revenue (1,000 emails × 9% reply × 42% booking × 32% close × $480K) | **~$5.8M** |
| **Net: signal-grounded approach still positive** | **+$4.5M** |

The brand damage is real but does not outweigh the revenue opportunity **if** the wrong-signal rate stays below 10%. Above 10%, the reputation cost begins to erode the reply-rate advantage. The kill switch (below) is designed to catch this before it reaches 10%.

---

### One Honest Unresolved Failure

**PROBE-031: Competitor gap asserted with fewer than 3 peers.** The `competitor_gap_brief.py` function calls the LLM with whatever peers it finds — including 1 or 2 — and generates confident-sounding gap text. This has not been fixed as of final submission. Impact if deployed: prospects in niche sectors (healthcare AI, industrial automation) receive gap briefs based on 1–2 peer companies. If the CTO checks the competitors named and finds one of them is their direct customer, the email is immediately discredited. Fix effort: 30 minutes (add `if len(peers) < 3: return None`). Recommended fix before pilot launch.

---

### Kill-Switch Clause

**Trigger metric:** Fraction of outbound emails generating negative replies (opt-out, "this is wrong", "who gave you this data") within the first 48 hours of sending.

**Threshold:** If negative-reply rate exceeds **5%** of emails sent in any 7-day window, pause all outbound immediately.

**Measurement:** Tag Resend webhook events by reply sentiment using keyword detection (keywords: "remove me", "this is wrong", "incorrect", "stop", "unsubscribe", "who are you"). Log to HubSpot `outreach_status = opted_out` or `outreach_status = negative_reply`. Query weekly.

**Rollback condition:** Resume only after (a) manual review of all negative replies, (b) root-cause identified and patched in enrichment pipeline, (c) Tenacious executive sign-off on the fix. Default is paused, not running.
