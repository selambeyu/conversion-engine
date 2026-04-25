"""
run_batch.py
─────────────────────────────────────────────────────
Batch prospect runner — reads companies directly from
the Crunchbase CSV, filters by ICP signals, and runs
the full pipeline for each match.

Usage:
    uv run python run_batch.py                        # default: top 10 ICP matches
    uv run python run_batch.py --limit 25             # process up to 25 companies
    uv run python run_batch.py --segment recently_funded_startup
    uv run python run_batch.py --dry-run              # score + print, no email sent
    uv run python run_batch.py --min-score 2          # only AI maturity >= 2

Output:
    logs/batch_runs.jsonl  — one record per prospect processed
─────────────────────────────────────────────────────
"""

import os
import sys
import csv
import json
import argparse
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, ".")

from enrichment.signal_brief import (
    lookup_crunchbase,
    check_layoffs,
    score_ai_maturity,
    classify_segment,
    _parse_employee_count,
    _parse_funding_rounds,
    _parse_industries,
)

DATA_DIR       = Path("data")
CRUNCHBASE_CSV = DATA_DIR / "crunchbase-companies-information.csv"
LOGS_DIR       = Path("logs")
BATCH_LOG      = LOGS_DIR / "batch_runs.jsonl"

# ICP filter: minimum funding to be considered a real prospect
MIN_FUNDING_USD = 1_000_000   # $1M+

# ICP segments supported by the system
ALL_SEGMENTS = {
    "recently_funded_startup",
    "mid_market_restructuring",
    "engineering_leadership_transition",
    "specialized_capability_gap",
}


# ─────────────────────────────────────────────────────────
# STEP 1 — Scan Crunchbase CSV and score every company
# ─────────────────────────────────────────────────────────

def load_and_score_companies(
    segment_filter: str = "",
    min_ai_score: int = 0,
    limit: int = 10,
) -> list[dict]:
    """
    Scan the Crunchbase CSV, compute ICP segment and AI maturity for each row,
    and return the top `limit` matches sorted by AI maturity score descending.

    Args:
        segment_filter: if set, only return companies in this ICP segment
        min_ai_score:   only return companies with AI maturity >= this value
        limit:          max companies to return
    """
    if not CRUNCHBASE_CSV.exists():
        print(f"[error] Crunchbase CSV not found at {CRUNCHBASE_CSV}")
        print("  Run: uv run python run_prospect.py  (calls download_data_files first)")
        sys.exit(1)

    print(f"Scanning {CRUNCHBASE_CSV.name} for ICP matches...")
    candidates = []

    with CRUNCHBASE_CSV.open(encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            name = row.get("name", "").strip()
            if not name:
                continue

            # Quick funding filter — funds_total is JSON: {"value_usd": 90000000}
            funding = 0
            funds_raw = row.get("funds_total", "") or ""
            if funds_raw and funds_raw not in ("null", "{}", ""):
                try:
                    funding = json.loads(funds_raw).get("value_usd", 0) or 0
                except Exception:
                    pass
            # Also accept companies with any funding_rounds_list even if funds_total is null
            has_rounds = bool(
                row.get("funding_rounds_list", "") not in ("", "null", "[]")
            )
            if funding < MIN_FUNDING_USD and not has_rounds:
                continue

            # Parse fields needed for segmentation
            _, latest_round_date, _ = _parse_funding_rounds(
                row.get("funding_rounds_list", "") or row.get("funding_rounds", "")
            )
            employee_count = _parse_employee_count(row.get("num_employees", ""))
            industry       = _parse_industries(
                row.get("industries", "") or row.get("industry", "")
            )

            # Build minimal crunchbase dict for classifiers
            crunchbase = {
                "name":               name,
                "industry":           industry,
                "num_employees":      str(employee_count),
                "employee_count":     employee_count,
                "total_funding_usd":  funding,
                "last_funding_date":  latest_round_date,
                "latest_round_date":  latest_round_date,
                "description":        row.get("about", "") or row.get("full_description", ""),
                "full_description":   row.get("full_description", ""),
                "builtwith_tech":     row.get("builtwith_tech", ""),
                "leadership_hire":    row.get("leadership_hire", ""),
                "current_employees":  row.get("current_employees", ""),
                "overview_highlights": row.get("overview_highlights", ""),
                "news":               row.get("news", ""),
                "website":            row.get("website", ""),
                "contact_email":      row.get("contact_email", ""),
                "country_code":       row.get("country_code", ""),
            }

            # Score AI maturity
            maturity = score_ai_maturity(crunchbase, open_roles=0)
            ai_score = maturity.get("score", 0)

            if ai_score < min_ai_score:
                continue

            # Classify ICP segment
            layoffs = check_layoffs(name)
            segment_result = classify_segment(crunchbase, layoffs, maturity)
            segment = segment_result.get("segment", "specialized_capability_gap")

            if segment_filter and segment != segment_filter:
                continue

            candidates.append({
                "company_name":   name,
                "industry":       industry,
                "funding_usd":    funding,
                "employee_count": employee_count,
                "ai_score":       ai_score,
                "segment":        segment,
                "contact_email":  crunchbase["contact_email"],
                "website":        crunchbase["website"],
                "country_code":   crunchbase["country_code"],
                "_row":           row,   # keep original row for full enrichment
            })

    # Sort by AI maturity descending — highest signal prospects first
    candidates.sort(key=lambda x: x["ai_score"], reverse=True)
    top = candidates[:limit]

    print(f"  Scanned companies → {len(candidates)} ICP matches → returning top {len(top)}")
    return top


# ─────────────────────────────────────────────────────────
# STEP 2 — Run pipeline for each candidate
# ─────────────────────────────────────────────────────────

def run_batch(
    candidates: list[dict],
    dry_run: bool = False,
    delay_seconds: int = 5,
) -> list[dict]:
    """
    Run the full prospect pipeline for each candidate.

    dry_run=True: print enrichment results only, skip email/SMS/HubSpot.
    delay_seconds: wait between prospects to avoid rate limits.
    """
    from enrichment.signal_brief  import build_signal_brief
    from agent.email_handler      import run_outreach
    from agent.hubspot_handler    import upsert_contact
    from agent.sms_handler        import mark_warm_lead

    LOGS_DIR.mkdir(exist_ok=True)
    results = []

    for idx, candidate in enumerate(candidates, 1):
        company = candidate["company_name"]
        print(f"\n{'─'*55}")
        print(f"[{idx}/{len(candidates)}] {company}")
        print(f"  Segment : {candidate['segment']}")
        print(f"  AI Score: {candidate['ai_score']}/3")
        print(f"  Industry: {candidate['industry']}")
        print(f"  Funding : ${candidate['funding_usd']:,.0f}")

        if dry_run:
            print("  [dry-run] Skipping email/HubSpot/SMS")
            record = {**candidate, "status": "dry_run", "_row": None}
            record.pop("_row", None)
            results.append(record)
            continue

        # Derive prospect contact from Crunchbase contact_email
        # Fall back to a placeholder if no contact email exists
        prospect_email = candidate["contact_email"]
        if not prospect_email or "█" in prospect_email:
            print(f"  [skip] No usable contact email for {company}")
            record = {**candidate, "status": "skipped_no_email", "_row": None}
            record.pop("_row", None)
            results.append(record)
            _append_log(record)
            continue

        # Use company name as prospect name when no individual is known
        prospect_name = f"Team at {company}"

        try:
            # Full enrichment
            print("  Building signal brief...")
            brief = build_signal_brief(company, open_roles=0)

            # HubSpot
            print("  Upserting HubSpot contact...")
            booking_url = _booking_link(prospect_name, prospect_email)
            firm        = brief.get("firmographics", {})
            contact     = upsert_contact(
                email            = prospect_email,
                company          = company,
                firstname        = "Team",
                lastname         = company,
                segment          = brief.get("segment", ""),
                ai_maturity      = brief.get("ai_maturity_score", 0),
                ai_maturity_conf = brief.get("ai_maturity_conf", ""),
                funding_usd      = firm.get("total_funding_usd", 0),
                employee_count   = firm.get("employee_count", 0),
                industry         = firm.get("industry", ""),
                city             = firm.get("city", ""),
                had_layoffs      = brief.get("layoff_signal", {}).get("had_layoffs", False),
                pitch_angle      = brief.get("pitch_angle", ""),
                signal_summary   = brief.get("summary", ""),
                outreach_status  = "email_sent",
                booking_url      = booking_url,
            )

            # Email
            print("  Sending outreach email...")
            outreach = run_outreach(
                prospect_email     = prospect_email,
                prospect_name      = prospect_name,
                signal_brief       = brief,
                hubspot_contact_id = contact["id"],
            )

            record = {
                "timestamp":     datetime.now(timezone.utc).isoformat(),
                "company":       company,
                "prospect_email": prospect_email,
                "segment":       brief.get("segment"),
                "ai_maturity":   brief.get("ai_maturity_score"),
                "email_status":  outreach.get("send_status"),
                "hubspot_id":    contact["id"],
                "trace_id":      outreach.get("trace_id"),
                "booking_url":   booking_url,
                "status":        "sent",
            }
            print(f"  ✓ Email {outreach.get('send_status')} | HubSpot {contact['id']}")

        except Exception as e:
            print(f"  [error] {company}: {e}")
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "company":   company,
                "status":    f"error: {e}",
            }

        results.append(record)
        _append_log(record)

        if idx < len(candidates):
            print(f"  Waiting {delay_seconds}s before next prospect...")
            time.sleep(delay_seconds)

    return results


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _booking_link(name: str, email: str) -> str:
    base = os.getenv("CALCOM_BOOKING_URL", "https://cal.com/tenacious/discovery-call")
    return f"{base}?name={name.replace(' ', '+')}&email={email}"


def _append_log(record: dict):
    LOGS_DIR.mkdir(exist_ok=True)
    with BATCH_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _print_summary(results: list[dict]):
    sent    = sum(1 for r in results if r.get("status") == "sent")
    skipped = sum(1 for r in results if "skip" in r.get("status", ""))
    errors  = sum(1 for r in results if "error" in r.get("status", ""))
    dry     = sum(1 for r in results if r.get("status") == "dry_run")

    print(f"\n{'='*55}")
    print(f"  BATCH COMPLETE — {len(results)} prospects processed")
    print(f"{'='*55}")
    print(f"  Sent:       {sent}")
    print(f"  Skipped:    {skipped}  (no contact email in Crunchbase)")
    print(f"  Errors:     {errors}")
    if dry:
        print(f"  Dry-run:    {dry}")
    print(f"  Log:        {BATCH_LOG}")
    print(f"{'='*55}\n")


# ─────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Batch prospect runner from Crunchbase CSV")
    p.add_argument("--limit",     type=int, default=10,
                   help="Max number of companies to process (default: 10)")
    p.add_argument("--segment",   type=str, default="",
                   choices=list(ALL_SEGMENTS) + [""],
                   help="Filter by ICP segment (default: all segments)")
    p.add_argument("--min-score", type=int, default=0,
                   help="Minimum AI maturity score 0-3 (default: 0)")
    p.add_argument("--dry-run",   action="store_true",
                   help="Score and print prospects only — no email/HubSpot/SMS")
    p.add_argument("--delay",     type=int, default=5,
                   help="Seconds to wait between prospects (default: 5)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    print(f"\nConversion Engine — Batch Mode")
    print(f"  Limit    : {args.limit} prospects")
    print(f"  Segment  : {args.segment or 'all'}")
    print(f"  Min score: {args.min_score}/3")
    print(f"  Dry run  : {args.dry_run}\n")

    candidates = load_and_score_companies(
        segment_filter = args.segment,
        min_ai_score   = args.min_score,
        limit          = args.limit,
    )

    if not candidates:
        print("No ICP matches found with the given filters.")
        sys.exit(0)

    print(f"\nTop {len(candidates)} prospects:")
    for i, c in enumerate(candidates, 1):
        print(f"  {i:2}. {c['company_name']:<35} score={c['ai_score']}/3  segment={c['segment']}")

    if not args.dry_run:
        confirm = input(f"\nProceed with sending to {len(candidates)} prospects? [y/N] ")
        if confirm.lower() != "y":
            print("Aborted.")
            sys.exit(0)

    results = run_batch(candidates, dry_run=args.dry_run, delay_seconds=args.delay)
    _print_summary(results)
