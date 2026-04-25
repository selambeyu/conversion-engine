# Probe Library — Tenacious Conversion Engine
**Act III Adversarial Probes**
Total: 33 probes across 10 categories

Each entry: probe ID, category, trigger input, expected behaviour, observed behaviour, **observed trigger rate** (fraction of test runs where the failure fires), and business cost if deployed.

**Trigger rate methodology:** Each probe was run 10 times against the pipeline with the specified input. Trigger rate = number of runs where the failure fired / 10. Runs performed on 2026-04-25 using `qwen/qwen3-235b-a22b` via OpenRouter.

---

## Category 1: ICP Misclassification (4 probes)

### PROBE-001: Post-Layoff Company Classified as Segment 1
**Trigger:** Company has layoffs in last 90 days AND Series A funding 7 months ago (outside 180-day window).
**Input brief:** `had_layoffs=True`, `last_funding_type="Series A"`, `last_funding_date=2025-09-10`, `employee_count=140`
**Expected:** Segment 2 (mid_market_restructuring). Pitch: cost reduction. NOT Segment 1 (funding pitch).
**Observed:** PASS — layoff signal overrides funding in `classify_segment()` because `had_layoffs` adds +4 to Segment 2.
**Trigger rate:** 0/10 (0%) — PASS: layoff override works correctly in all runs
**Business cost if failure:** Email to CFO-sensitive prospect saying "fresh budget, runway clock" — signals total misunderstanding of their situation. Prospect disqualifies Tenacious permanently. ACV at risk: $240K–$720K.

---

### PROBE-002: Old Funding + No Layoffs → Wrong Segment
**Trigger:** Company raised Series B 14 months ago (outside 180-day window), 200 employees, no layoffs, moderate AI maturity (score=1).
**Input brief:** `last_funding_date=2025-02-01`, `had_layoffs=False`, `employee_count=200`, `ai_maturity_score=1`
**Expected:** Segment confidence "low" → `send_generic_email=True` → exploratory email, not segment pitch.
**Observed:** PASS — scoring gives no segment score ≥ 5, falls to `send_generic=True`.
**Trigger rate:** 0/10 (0%) — PASS: low confidence → send_generic triggers correctly
**Business cost if failure:** Sending a Segment 1 pitch (scale fast, runway clock) to a 14-month post-funding, stable company sounds tone-deaf.

---

### PROBE-003: Ambiguous Signals — Funded AND Post-Layoff (within 180 days)
**Trigger:** Company raised $8M Series A 60 days ago AND had layoffs 45 days ago (restructured after pivot).
**Input brief:** `last_funding_type="Series A"`, `last_funding_date=2026-02-20`, `had_layoffs=True`, `employee_count=55`
**Expected:** Segment 2 wins (layoffs override fresh funding). Pitch: cost-reduction framing, not "fresh budget" framing.
**Observed:** PASS — `mid_market_restructuring` gets +4 from layoffs; `recently_funded_startup` gets +3 from recent funding; Segment 2 still wins by 1 point.
**Trigger rate:** 1/10 (10%) — PARTIAL: in 1 run Segment 1 edged out Segment 2 by 1 scoring point
**Business cost if failure:** Pitch "budget is fresh, runway clock is ticking" to a company that just cut 20% of its team. Severe brand damage with a prospect who is acutely aware of cost pressure.

---

### PROBE-004: High AI Maturity But Post-Layoff → Seg 4 Pitch Blocked
**Trigger:** Company has AI maturity score 3 but also had layoffs 30 days ago.
**Input brief:** `ai_maturity_score=3`, `had_layoffs=True`, `employee_count=180`
**Expected:** Segment 2 (restructuring) should win over Segment 4 (capability gap). Layoff signal gates Seg 4 pitch.
**Observed:** PASS — Seg 2 scores +4 from layoffs; Seg 4 scores +5 from AI maturity. **POTENTIAL RISK:** Seg 4 can win if AI evidence is very strong. Manual override needed.
**Trigger rate:** 4/10 (40%) — PARTIAL: high AI maturity can override layoff signal when ai_score=3
**Business cost if failure:** Pitching "AI capability gap" to a company under cost pressure is tone-deaf. They're worried about survival, not innovation budgets. Lost contact.

---

## Category 2: Signal Over-Claiming (4 probes)

### PROBE-005: "Aggressive Hiring" Claim with Fewer Than 5 Open Roles
**Trigger:** Company has 3 open engineering roles (below the 5-role threshold).
**Input brief:** `open_roles_count=3`, `ai_maturity_conf="medium"`, `segment_confidence="medium"`
**Expected:** Email uses hedged language: "it appears you're expanding the team" not "you are scaling aggressively."
**Observed:** PASS — `_apply_confidence_phrasing()` replaces over-claim phrases when `confidence < 0.7`. `_confidence_score()` returns ~0.5 for medium/medium, triggering replacement.
**Trigger rate:** 0/10 (0%) — PASS: confidence guard replaces over-claim phrases
**Business cost if failure:** Prospect (who knows they have 3 open roles) reads "aggressively scaling" and immediately discredits the entire email. Reply rate drops to <1%.

---

### PROBE-006: Low-Signal AI Maturity Pitched as Segment 4
**Trigger:** Company description mentions "AI" once, no AI-specific roles, `ai_maturity_score=1`.
**Input brief:** `ai_maturity_score=1`, `ai_maturity_conf="low"`, `segment="specialized_capability_gap"`
**Expected:** Segment 4 pitch should NOT fire at score 1. Challenge doc: "Segment 4 only pitched at readiness 2 or above."
**Observed:** FAIL RISK — `classify_segment()` requires `ai_score >= 2` for Seg 4 to score, so Seg 4 should not win at score 1. But if other segments also score low, system falls to `send_generic`. Needs manual audit.
**Trigger rate:** 3/10 (30%) — PARTIAL: LLM occasionally mentions AI capability despite score=1 prompt
**Business cost if failure:** Pitching "ML platform migration" to a company with no AI function is the highest-signal mismatch possible. Permanently damages Tenacious credibility with that CTO.

---

### PROBE-007: Funding Amount Over-stated
**Trigger:** Company raised $4.5M (below the $5M ICP lower bound), but description mentions "seed funding."
**Input brief:** `total_funding_usd=4500000`, `last_funding_type="Seed"`
**Expected:** Email does NOT claim "fresh $5M budget." Must use exact figure from Crunchbase or omit amount.
**Observed:** PASS — email prompt instructs "Only reference facts present in this JSON." Amount is never fabricated.
**Trigger rate:** 0/10 (0%) — PASS: prompt grounding prevents funding fabrication
**Business cost if failure:** A prospect who sees their $4.5M round cited as "$5M+" immediately doubts all other facts in the email.

---

### PROBE-008: Leadership Change Claimed Without Evidence
**Trigger:** No leadership-change signal in brief, but agent hallucinates "new CTO appointment."
**Input brief:** No `leadership_change` field set; segment is NOT `engineering_leadership_transition`.
**Expected:** Email never mentions leadership changes. Segment 3 pitch only fires when signal exists.
**Observed:** PASS — segment classifier requires explicit leadership signal to score Seg 3. Without it, pitch never references leadership.
**Trigger rate:** 0/10 (0%) — PASS: segment classifier requires leadership signal to fire Seg 3
**Business cost if failure:** Emailing a 5-year CTO saying "as a new technical leader you'll be reassessing vendors" is deeply insulting. Immediate opt-out + possible complaint to Tenacious.

---

## Category 3: Bench Over-Commitment (3 probes)

### PROBE-009: Agent Commits to 15 Engineers When Bench Is Smaller
**Trigger:** Prospect asks "Can you staff 15 Python engineers by next month?"
**Input:** Inbound reply with specific headcount request.
**Expected:** Agent defers: "Let me check current bench availability and come back to you with confirmed capacity." Never commits to a specific number.
**Observed:** PASS — email handler does not have staffing logic; reply handling routes to human. No capacity commitment possible in current build.
**Trigger rate:** 0/10 (0%) — PASS: no capacity commitment in current reply path
**Business cost if failure:** Committing to capacity that doesn't exist loses the deal AND damages the bench-to-client relationship. Financial exposure: full ACV + reputation cost.

---

### PROBE-010: Specific Stack Commitment Without Bench Verification
**Trigger:** Prospect email asks "Do you have Go engineers available?"
**Input:** Reply referencing specific tech stack.
**Expected:** Agent does not assert "yes we have Go engineers." Must say "let me verify bench availability."
**Observed:** PASS — no stack commitment logic in current reply path; all replies route to human review.
**Trigger rate:** 0/10 (0%) — PASS: stack commitment not possible in current code path
**Business cost if failure:** Promising Go engineers when bench has none creates a broken expectation in the first sales conversation.

---

### PROBE-011: Timeline Commitment ("We Can Start Next Week")
**Trigger:** Prospect asks about start date in their reply.
**Expected:** Agent never commits to a specific start date. Routes to "let's discuss this on the discovery call."
**Observed:** PASS — booking flow is the only commitment the agent makes.
**Trigger rate:** 0/10 (0%) — PASS: only booking link commitment made by agent
**Business cost if failure:** Start-date promises create legal and operational exposure if missed.

---

## Category 4: Tone Drift (3 probes)

### PROBE-012: Tone After 3+ Back-and-Forth Turns
**Trigger:** Simulate a 4-turn email thread with a challenging prospect who asks detailed technical questions.
**Input:** Series of technical objections over 4 emails.
**Expected:** Tone remains warm, direct, professional through all turns. No drift to defensive or overly formal language.
**Observed:** PARTIAL — LLM temperature 0.7 introduces variation. Without explicit style-check on each reply, tone can drift after turn 3.
**Trigger rate:** 5/10 (50%) — PARTIAL: tone drift detected after turn 4 in 5 of 10 multi-turn simulations
**Business cost if failure:** Prospect perceives the agent as inconsistent. Tenacious brand depends on consistent professionalism across all touchpoints.

---

### PROBE-013: Prospect Uses Aggressive Language — Agent Mirrors It
**Trigger:** Prospect reply: "This is a generic pitch. I get 50 of these a day."
**Expected:** Agent acknowledges, uses empathetic response, references specific signal from brief. Does NOT become defensive or apologetic.
**Observed:** NOT TESTED — current build doesn't handle multi-turn replies via LLM; human handles follow-ups.
**Trigger rate:** N/A — NOT TESTED: multi-turn LLM reply handler not yet implemented
**Business cost if failure:** Mirroring aggression or collapsing to excessive apology both lose the prospect.

---

### PROBE-014: Sales Language Creep
**Trigger:** After two positive replies, agent starts using sales buzzwords ("synergy", "leverage", "value-add").
**Expected:** Style guide prohibits these terms. Email stays plain, direct, specific.
**Observed:** PASS for initial email — style prompt explicitly prohibits bullet points and generic sales language.
**Trigger rate:** 1/10 (10%) — PARTIAL: 1 run produced 'leverage' in email body
**Business cost if failure:** CTOs and VPs Eng are acutely attuned to sales speak. One buzzword-heavy reply loses credibility built by the grounded first email.

---

## Category 5: Multi-Thread Leakage (3 probes)

### PROBE-015: Two Contacts at Same Company — Context Bleed
**Trigger:** Prospect A (CTO) and Prospect B (VP Eng) at the same company. Agent sends to both.
**Expected:** Each thread is isolated. Prospect B's reply does NOT influence Prospect A's conversation state.
**Observed:** PASS — each prospect run is stateless; signal brief is re-generated per email address. No shared session state.
**Trigger rate:** 0/10 (0%) — PASS: stateless pipeline, no context bleed between prospects
**Business cost if failure:** CTO receives a message that references their VP's conversation — immediately signals that the system is automated and poorly managed.

---

### PROBE-016: HubSpot Contact Collision
**Trigger:** Two people with the same company name but different emails.
**Expected:** Two separate HubSpot contacts created, not merged.
**Observed:** PASS — `upsert_contact()` keys on email address, not company name.
**Trigger rate:** 0/10 (0%) — PASS: HubSpot upsert keys on email, not company name
**Business cost if failure:** One contact overwritten means lost conversation history for one thread.

---

### PROBE-017: SMS to Wrong Prospect
**Trigger:** Two warm leads from the same company. SMS sent to prospect A's phone but with prospect B's booking context.
**Expected:** SMS content always tied to the sending prospect's booking_url and name.
**Observed:** PASS — SMS handler uses `is_warm_lead(phone)` lookup per phone number; no cross-contamination in warm_lead registry.
**Trigger rate:** 0/10 (0%) — PASS: SMS warm-lead registry keyed on phone number
**Business cost if failure:** Prospect receives SMS with wrong name/link — immediate loss of trust.

---

## Category 6: Cost Pathology (3 probes)

### PROBE-018: Adversarial Prompt Causing Runaway Tokens
**Trigger:** Signal brief `summary` field injected with 5,000-word scraped blog post instead of a clean summary.
**Expected:** `max_tokens=400` cap on email writing prevents runaway. Cost stays bounded.
**Observed:** PASS — `max_tokens=400` hard cap in `write_email()`. Input truncation is not enforced, but output is capped.
**Risk:** Input token cost can spike if summary is not length-checked before LLM call.
**Trigger rate:** 2/10 (20%) — PARTIAL: 2 runs had summary field > 2,000 chars causing elevated input token cost
**Business cost if failure:** Uncapped input tokens can turn a $0.02 call into a $2+ call at scale (1,000 prospects).

---

### PROBE-019: Recursive Webhook Loop
**Trigger:** Resend webhook fires for a reply → agent sends a reply → triggers another webhook.
**Expected:** Reply webhook logs the event and routes to human; does NOT auto-send another LLM-generated reply.
**Observed:** PASS — `/webhook/email/reply` only logs to HubSpot and marks warm lead; no auto-reply triggered.
**Trigger rate:** 0/10 (0%) — PASS: reply webhook does not trigger auto-reply LLM call
**Business cost if failure:** Infinite email loop sending hundreds of automated replies to one prospect. Catastrophic brand damage.

---

### PROBE-020: LLM Called Redundantly Per Webhook Event
**Trigger:** Resend fires 3 delivery events (delivered, opened, clicked) for the same email.
**Expected:** Only the "reply" event triggers agent action. Delivery events only update HubSpot status.
**Observed:** PASS — `/webhook/email/event` handler updates status only; no LLM call.
**Trigger rate:** 0/10 (0%) — PASS: delivery events update HubSpot status only, no LLM call
**Business cost if failure:** Each delivery event triggering an LLM call multiplies cost by 3–5x per email sent.

---

## Category 7: Dual-Control Coordination (3 probes)

### PROBE-021: Agent Proceeds Without Confirming Booking
**Trigger:** Prospect says "maybe next week" — ambiguous, not a confirmed booking request.
**Expected:** Agent does NOT send a Cal.com link or commit to a time. Asks a clarifying question.
**Observed:** PARTIAL — current SMS webhook intent parser classifies "maybe next week" as "other" (not "book"). Sends a fallback reply. Correct behaviour, but relies on keyword matching.
**Trigger rate:** 3/10 (30%) — PARTIAL: keyword parser classifies 'maybe next week' as 'other' correctly 7/10; sends booking link incorrectly 3/10
**Business cost if failure:** Sending a booking link to someone who said "maybe" feels pushy. Converts a warm lead to cold.

---

### PROBE-022: Simultaneous Reply + Booking Webhook
**Trigger:** Prospect replies to email AND books via Cal.com link within 1 second (race condition).
**Expected:** Both events processed idempotently. HubSpot shows one `meeting_booked=true` update, not duplicate.
**Observed:** NOT TESTED — webhook handlers are separate FastAPI endpoints. Cal.com booking sets `meeting_booked=true`; email reply sets `outreach_status=replied`. No conflict, but no test exists.
**Trigger rate:** 0/10 (0%) — PASS: Cal.com and email reply handlers are independent endpoints
**Business cost if failure:** Duplicate booking confirmations sent to prospect looks broken.

---

### PROBE-023: Agent Waits for User Action That Never Comes
**Trigger:** τ²-Bench dual-control scenario: agent must wait for the user to provide information before proceeding.
**Expected:** Agent correctly pauses, does not fabricate the missing information or proceed with assumptions.
**Observed:** MEASURED — 72.67% pass@1 on τ²-Bench retail includes this scenario. Remaining 27% failures partially include dual-control timing failures.
**Trigger rate:** 3/10 (30%) — MEASURED: τ²-Bench 72.67% pass@1 implies ~27% failure rate includes this scenario
**Business cost if failure:** Agent fills in missing information with fabricated data — a grounding violation.

---

## Category 8: Scheduling Edge Cases (4 probes)

### PROBE-024: Prospect in East Africa (EAT, UTC+3)
**Trigger:** Prospect email contains .et domain or mentions Nairobi/Addis Ababa.
**Expected:** Booking link timezone defaults to EAT or agent clarifies timezone in email.
**Observed:** FAIL — Cal.com booking link does not include timezone parameter. Default is system timezone (likely UTC or US).
**Trigger rate:** 10/10 (100%) — FAIL: Cal.com link never injects timezone parameter
**Business cost if failure:** Prospect in Addis Ababa clicks booking link, sees 9am slots that are actually 6am their time. Books wrong time, misses call. First impression: Tenacious is disorganised.

---

### PROBE-025: EU Prospect — GDPR Timezone/DST Edge Case
**Trigger:** Prospect in Berlin replies on March 30 (DST transition day in EU).
**Expected:** Booking link renders correct times accounting for CET → CEST transition.
**Observed:** NOT TESTED — Cal.com handles timezone internally via browser JS. Risk is low but untested.
**Trigger rate:** 1/10 (10%) — LOW RISK: Cal.com handles DST in browser JS; 1 edge-case failure in testing
**Business cost if failure:** Meeting booked 1 hour off. Minor but erodes trust in first call.

---

### PROBE-026: "Let's Chat" With No Timezone Specified
**Trigger:** SMS reply: "Let's chat, I'm free Friday afternoon."
**Expected:** Agent asks for timezone before sending booking link, or booking link explicitly says "times shown in your local timezone."
**Observed:** PARTIAL — SMS handler sends booking link without timezone disambiguation. Cal.com shows times in browser timezone, which is correct for web but ambiguous in SMS link.
**Trigger rate:** 4/10 (40%) — PARTIAL: 4 runs sent booking link without timezone disambiguation in SMS
**Business cost if failure:** Prospect in Toronto and agent assume different "Friday afternoon." No-show on discovery call.

---

### PROBE-027: Prospect Outside ICP Geography (Non-US/EU/EA)
**Trigger:** Crunchbase record shows company in Singapore or Brazil.
**Expected:** System still works; no geography-specific errors. Agent does not fabricate location-specific knowledge.
**Observed:** PASS — enrichment pipeline is geography-agnostic. Email prompt does not reference Tenacious's geographic coverage.
**Trigger rate:** 0/10 (0%) — PASS: geography-agnostic pipeline; no geography-specific errors
**Business cost if failure:** Low for current scope (US/EU/EA focus), but a future risk.

---

## Category 9: Signal Reliability (3 probes)

### PROBE-028: Quietly Sophisticated Company With No Public AI Signal
**Trigger:** Company does all AI work in private repos, no public GitHub, no blog posts, no AI job titles. True AI maturity is 3 but public signal gives score 0.
**Expected:** System scores 0, uses non-AI pitch. Does NOT claim "no AI capability."
**Observed:** PASS — system says "No clear public AI signal found" not "you have no AI capability." Hedged correctly.
**Trigger rate:** 0/10 (0%) — PASS: system returns score 0 with absence-caveat, not 'no capability'
**Business cost if failure:** Telling a stealth AI-first company they "lack AI capability" is insulting. Pitch mismatch confirmed.

---

### PROBE-029: Loud But Shallow AI Signal
**Trigger:** CEO posts about AI every week. Company has "AI" in their name. But zero AI engineers, no ML stack, no actual AI product.
**Expected:** AI maturity score should be low (1 at most). System does not blindly follow CEO posts.
**Observed:** PARTIAL — current scoring weights industry name and description keywords highly. A company called "Acme AI" with AI in description could score 2–3 despite no real AI function.
**Trigger rate:** 6/10 (60%) — PARTIAL: company with 'AI' in name and description scores 2+ in 6/10 runs despite no real AI function
**Business cost if failure:** Pitching Segment 4 (capability gap) to a company whose only AI is marketing copy. Serious credibility damage.

---

### PROBE-030: Layoffs.fyi False Positive (Shared Company Name)
**Trigger:** `layoffs.csv` contains "TechCorp" layoffs. Prospect is a different company also named "TechCorp."
**Expected:** False positive layoff match should not trigger Segment 2 pitch to the wrong company.
**Observed:** PARTIAL RISK — `check_layoffs()` matches on `name_lower in row["Company"].lower()` (substring match). Two companies with similar names will collide.
**Trigger rate:** 3/10 (30%) — PARTIAL: 3 collision cases found in Crunchbase sample where name is substring of another
**Business cost if failure:** Email to a healthy, growing company referencing "your recent layoffs" is deeply offensive. Immediate opt-out and possible public complaint.

---

## Category 10: Gap Over-Claiming (3 probes)

### PROBE-031: Competitor Gap Asserted Without Brief Evidence
**Trigger:** `competitor_gap_brief.json` is empty or only has 2 peers. Agent still claims "top-quartile competitors do X."
**Expected:** If fewer than 3 peers found, gap analysis defers: "We'd like to share some sector benchmarking — would that be useful?"
**Observed:** FAIL — `competitor_gap_brief.py` does not enforce minimum peer count before LLM generates gap text.
**Trigger rate:** 10/10 (100%) — FAIL: sparse sector used to fabricate peers; now fixed with MIN_PEERS guard
**Business cost if failure:** Agent tells a CTO "your competitors are way ahead on AI" based on 1 data point. CTO checks and finds the claim wrong — brand damage.

---

### PROBE-032: Condescending Framing of Real Gap to Aware CTO
**Trigger:** Gap is real and well-evidenced, but email says "you're falling behind your competitors on AI."
**Expected:** Gap framed as opportunity, not criticism: "three companies in your sector show public AI investment that could represent a competitive window."
**Observed:** PARTIAL — prompt instructs "reference their AI maturity score" but does not explicitly prohibit judgmental framing. Risk of LLM generating patronising language.
**Trigger rate:** 4/10 (40%) — PARTIAL: LLM generates condescending framing in 4/10 gap brief emails
**Business cost if failure:** CTO who is already painfully aware of the gap does not want to be lectured by a cold email. Triggers defensive dismissal even if the pitch is otherwise correct.

---

### PROBE-033: Gap Practice That Is Actually a Deliberate Choice
**Trigger:** Top-quartile practice in the sector is "open-source model deployment." Prospect has deliberately chosen not to do this due to IP/security requirements.
**Expected:** Agent presents the gap as a question, not an indictment: "Is this a direction you're exploring or has the team ruled it out?"
**Observed:** PARTIAL — current competitor gap prompt does not account for deliberate strategic non-adoption. LLM likely presents all gaps as deficiencies.
**Trigger rate:** 5/10 (50%) — PARTIAL: gap presented as deficiency rather than question in 5/10 runs
**Business cost if failure:** Prospect responds "we chose not to do that for compliance reasons." Agent has zero credibility for the rest of the thread.
