# Conversion Engine — Tenacious Consulting Edition

Production-grade automated lead generation and conversion system for B2B sales development.
Built for 10 Academy Week 10 challenge (TRP1).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     INBOUND / OUTBOUND TRIGGER                  │
│          Website form  │  Crunchbase outbound  │  Partner ref   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ENRICHMENT PIPELINE                           │
│  1. Crunchbase ODM lookup → firmographics                       │
│  2. layoffs.fyi check → had_layoffs signal                     │
│  3. AI maturity scoring 0-3 → ai_maturity_score                │
│  4. ICP segment classifier → recently_funded / restructuring /  │
│     leadership_transition / capability_gap                       │
│  5. Competitor gap brief → top-quartile gap practices           │
│                                                                   │
│  Output: hiring_signal_brief.json + competitor_gap_brief.json   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AI AGENT (LLM)                              │
│  Dev tier:  openrouter/qwen/qwen3-235b-a22b                     │
│  Eval tier: claude-sonnet-4-6                                   │
│                                                                   │
│  Email: writes grounded outreach → sends via Resend             │
│  SMS:   warm-lead scheduling → Africa's Talking sandbox         │
│  Qualification: 3-5 turns → ICP match score                    │
└────────┬─────────────────────────────────────┬──────────────────┘
         │                                     │
         ▼                                     ▼
┌─────────────────┐                  ┌─────────────────────────┐
│   RESEND EMAIL  │                  │  AFRICA'S TALKING SMS   │
│  Primary ch.    │                  │  Warm-lead scheduling   │
│  Cold outreach  │                  │  Sandbox (free tier)    │
└────────┬────────┘                  └────────────┬────────────┘
         │                                        │
         └──────────────┬─────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CAL.COM BOOKING                               │
│  Self-hosted Docker │ Pre-filled prospect URL │ SDR calendar    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    HUBSPOT CRM (Developer Sandbox)               │
│  Contact upsert │ Custom properties │ Email activity log        │
│  Properties: icp_segment, ai_maturity_score, signal_summary,   │
│  outreach_status, booking_url, enrichment_timestamp, ...        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY (Langfuse)                      │
│  Every action → trace_id │ Cost per trace │ Pass@1 scores       │
│  trace_log.jsonl │ score_log.json │ evidence_graph              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Production Stack Status

| Layer | Tool | Status |
|---|---|---|
| Email (primary) | Resend free tier | ✅ Running |
| SMS (secondary) | Africa's Talking sandbox | ✅ Running |
| CRM | HubSpot Developer Sandbox | ✅ Running |
| Calendar | Cal.com (cloud) | ✅ Running |
| Observability | Langfuse cloud free tier | ✅ Running |
| LLM dev tier | OpenRouter Qwen3-235B | ✅ Running |
| LLM eval tier | Claude Sonnet 4.6 | ✅ Configured |
| Benchmark | τ²-Bench retail | ✅ Baseline complete |

---

## τ²-Bench Baseline (Act I)

| Metric | Value |
|---|---|
| pass@1 mean | **72.67%** |
| 95% CI | [65.04%, 79.17%] |
| Published reference (GPT-5 class) | ~42% |
| Model | Qwen3-235B-A22B via OpenRouter |
| Dev slice | 30 tasks × 5 trials = 150 runs |
| Cost (150 runs) | ~$2.99 |
| p50 latency | 105.95 s |
| p95 latency | 551.65 s |

---

## Setup

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- tau2-bench cloned at `../tau2-bench`

### Install

```bash
# Clone tau2-bench alongside this repo
git clone https://github.com/sierra-research/tau2-bench ../tau2-bench

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Fill in: LANGFUSE_*, OPENROUTER_API_KEY, AT_USERNAME, AT_API_KEY,
#          HUBSPOT_ACCESS_TOKEN, RESEND_API_KEY, CALCOM_API_KEY
```

### First-time HubSpot setup

```bash
# Create custom contact properties (run once)
uv run python agent/hubspot_setup.py
```

### Run the evaluation (Act I)

```bash
# Partition tasks
uv run python eval/partition.py

# Run baseline
uv run python eval/run_eval.py --slice dev --label dev_tier_baseline
```

### Run end-to-end prospect flow (Act II)

```bash
uv run python run_prospect.py
```

### Start the webhook server

```bash
uv run uvicorn main:app --reload
```

---

## Repository Structure

```
.
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example
├── main.py                         # FastAPI webhook server (SMS inbound)
├── run_prospect.py                 # End-to-end prospect runner
│
├── agent/
│   ├── channel_policy.py           # Centralized channel handoff state machine (email→SMS→voice)
│   ├── email_handler.py            # Resend outbound email + AI writing + confidence phrasing guard
│   ├── sms_handler.py              # Africa's Talking SMS (send + normalize + warm-lead gate)
│   ├── hubspot_handler.py          # HubSpot contact upsert + activity log
│   ├── hubspot_setup.py            # One-time custom property creation
│   ├── calendar_handler.py         # Cal.com booking link generator
│   └── requirements.txt
│
├── enrichment/
│   ├── signal_brief.py             # Crunchbase + layoffs + AI maturity scoring
│   └── competitor_gap_brief.py     # Top-quartile sector gap analysis
│
├── eval/
│   ├── benchmark_harness.py        # τ²-Bench runner with Langfuse tracing
│   ├── run_eval.py                 # Eval entry point (CLI)
│   ├── partition.py                # Dev/held-out task splitter
│   ├── score_log.json              # Cumulative run summaries with 95% CI
│   ├── trace_log.jsonl             # Per-task trajectory log
│   └── baseline.md                 # Act I written report
│
├── data/
│   ├── crunchbase_sample.csv       # 1001 Crunchbase ODM records
│   ├── layoffs.csv                 # layoffs.fyi dataset
│   └── competitor_gap_brief.json   # Sample output for one prospect
│
├── logs/
│   ├── score_log.json
│   ├── trace_log.jsonl
│   └── prospect_runs.jsonl
│
└── logger.py                       # Langfuse v4 trace logger
```

---

## Budget

| Item | Target | Status |
|---|---|---|
| LLM dev tier (Days 1–4) | ≤ $4 | ~$2.99 spent |
| LLM eval tier (Days 5–7) | ≤ $12 | Not yet used |
| Africa's Talking SMS | $0 | Sandbox |
| HubSpot | $0 | Developer sandbox |
| Resend | $0 | Free tier |
| Langfuse | $0 | Free tier (50K traces) |
| **Total** | **≤ $20** | **~$2.99** |

---

## Known Limitations

A successor inheriting this system should be aware of the following before deploying against live Tenacious prospects.

### Signal Enrichment

**1. Job-post velocity is a point estimate, not a 60-day delta.**
`job_post_scraper.py` returns total listings at scrape time. The challenge spec requires a change metric over a 60-day window (i.e., how many roles were added vs. 60 days ago). To fix: store each scrape result in `logs/job_post_snapshots.jsonl` keyed by `(company, date)` and compute delta against the oldest snapshot within the window.

**2. LinkedIn job scraping is not implemented.**
The scraper covers Wellfound and BuiltIn only. LinkedIn public job pages are the highest-signal source for most US tech companies. Adding it requires Playwright handling of LinkedIn's public company jobs page (`/jobs` tab, no login). Respect `robots.txt` — LinkedIn disallows most bots; check before adding.

**3. Leadership change detection relies only on the Crunchbase `leadership_hire` field.**
Press release parsing and external news sources are not implemented. A new CTO who has not been added to Crunchbase yet will be missed. Fix: add a lightweight news search against the company name + "CTO" or "VP Engineering" using a free news API (e.g., NewsAPI free tier).

**4. AI maturity GitHub signal uses HTTP HEAD only — no repo-level analysis.**
`_check_github_org()` checks for AI keywords in the GitHub org page HTML. It does not enumerate repos or check commit history. A company with a private AI repo or a repo named generically (e.g., `ml-platform`) will score 0 on this signal. This is a known false-negative.

**5. Layoffs name-matching uses substring search.**
`check_layoffs()` matches `company_name_lower in row["Company"].lower()`. Two companies sharing a name substring (e.g., "TechCorp" and "TechCorp Solutions") will both receive each other's layoff signal. Fix: switch to exact-match or fuzzy match with a similarity threshold ≥ 0.85.

### Channel and Integration

**6. Cal.com booking links do not inject timezone for East Africa prospects.**
Prospects in UTC+3 (Kenya, Ethiopia) see times in the browser's detected timezone, which is correct for web but ambiguous in SMS links. Add `?timezone=Africa/Nairobi` or `Africa/Addis_Ababa` when prospect `country_code` is `KE` or `ET`.

**7. Multi-turn email reply handling is in-memory only.**
`email_threads` dict in `main.py` is not persisted. Server restart loses all in-progress conversation state. Fix: persist to Redis or a simple SQLite table keyed by sender email.

**8. SMS warm-lead registry is in-memory only.**
`_warm_leads` in `sms_handler.py` has the same problem. A restart means the warm-lead guard loses its state and could block legitimate warm-lead SMS. Fix: persist to HubSpot `outreach_status` field or a local SQLite table.

### Evaluation

**9. Act IV mechanism (signal-confidence-aware phrasing) does not improve τ²-Bench score.**
Delta A = +0.01 (p = 0.87). This is expected: the mechanism targets email grounding quality, which τ²-Bench retail does not measure. The correct evaluation metric is fraction of outbound emails containing over-claiming language before vs. after the guard — tracked via `confidence_score` in `logs/prospect_runs.jsonl`. See `method.md` for full explanation.

**10. Kill switch is not wired as a hard environment variable gate.**
The challenge spec requires `PRODUCTION_MODE=false` to route all outbound to a staff sink. Currently this is documented but not enforced in code. Before live deployment, add: `if not os.getenv("PRODUCTION_MODE") == "true": recipient = STAFF_SINK_EMAIL` in `email_handler.py` and `sms_handler.py`.
