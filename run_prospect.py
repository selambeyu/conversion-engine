"""
run_prospect.py
─────────────────────────────────────────────────────
End-to-end demo for Wednesday submission.

Runs the full pipeline for one synthetic prospect:
  1. Research company (signal_brief)
  2. Create HubSpot contact
  3. Write and send personalised email
  4. Generate Cal.com booking link
  5. Log everything to Langfuse

Take screenshots of HubSpot, Resend, Langfuse after running.
─────────────────────────────────────────────────────
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, ".")

from enrichment.signal_brief import build_signal_brief, download_data_files
from agent.email_handler     import run_outreach
from agent.hubspot_handler   import upsert_contact
from agent.sms_handler       import send_sms, mark_warm_lead, is_warm_lead


def get_booking_link(name: str, email: str) -> str:
    base = os.getenv("CALCOM_BOOKING_URL",
                     "https://cal.com/tenacious/discovery-call")
    name_enc = name.replace(" ", "+")
    return f"{base}?name={name_enc}&email={email}"


def run_end_to_end(
    company_name:   str,
    prospect_name:  str,
    prospect_email: str,
    open_roles:     int = 0,
    prospect_phone: str = "",   # E.164, e.g. "+251912345678"; leave blank to skip SMS
    careers_url:    str = "",
) -> dict:

    print()
    print("=" * 55)
    print("  CONVERSION ENGINE — END TO END")
    print("=" * 55)
    print(f"  Company:  {company_name}")
    print(f"  Prospect: {prospect_name} <{prospect_email}>")
    print(f"  Time:     {datetime.utcnow().strftime('%H:%M UTC')}")
    print("=" * 55)

    # ── 1. Research ───────────────────────────────────────
    print("\n[1/4] Building signal brief...")
    brief = build_signal_brief(company_name, open_roles=open_roles, careers_url=careers_url)

    # ── 2. HubSpot ────────────────────────────────────────
    print("\n[2/4] Creating HubSpot contact...")
    firm    = brief.get("firmographics", {})
    booking = get_booking_link(prospect_name, prospect_email)

    contact = upsert_contact(
        email             = prospect_email,
        company           = company_name,
        firstname         = prospect_name.split()[0],
        lastname          = " ".join(prospect_name.split()[1:]),
        segment           = brief.get("segment", ""),
        ai_maturity       = brief.get("ai_maturity_score", 0),
        ai_maturity_conf  = brief.get("ai_maturity_conf", ""),
        funding_usd       = firm.get("total_funding_usd", 0),
        employee_count    = firm.get("employee_count", 0),
        industry          = firm.get("industry", ""),
        city              = firm.get("city", ""),
        had_layoffs       = brief.get("layoff_signal", {})
                                  .get("had_layoffs", False),
        pitch_angle       = brief.get("pitch_angle", ""),
        signal_summary    = brief.get("summary", ""),
        outreach_status   = "email_sent",
        booking_url       = booking,
    )
    contact_id = contact["id"]
    print(f"  HubSpot contact: {contact_id} ({contact['status']})")

    # ── 3. Email ──────────────────────────────────────────
    print("\n[3/4] Writing and sending email...")
    outreach = run_outreach(
        prospect_email     = prospect_email,
        prospect_name      = prospect_name,
        signal_brief       = brief,
        hubspot_contact_id = contact_id,
    )

    # ── 4. SMS follow-up (warm leads only) ───────────────
    sms_status = "skipped"
    # Register phone ↔ email cross-link so the inbound webhook can resolve HubSpot ID
    if prospect_phone:
        mark_warm_lead(prospect_phone, email=prospect_email, phone=prospect_phone)

    if prospect_phone and is_warm_lead(prospect_phone):
        print("\n[4/5] Sending SMS follow-up (warm lead)...")
        booking = get_booking_link(prospect_name, prospect_email)
        try:
            send_sms(
                prospect_phone,
                f"Hi {prospect_name.split()[0]}, this is Maya from Tenacious. "
                f"Did you get my email? Happy to chat — book here: {booking}",
            )
            sms_status = "sent"
        except Exception as e:
            print(f"  SMS failed: {e}")
            sms_status = f"error: {e}"
    elif prospect_phone:
        print(f"\n[4/5] SMS skipped — {prospect_phone} is not yet a warm lead.")

    # ── 5. Save run record ────────────────────────────────
    print("\n[5/5] Saving to logs...")
    Path("logs").mkdir(exist_ok=True)
    record = {
        "timestamp":      datetime.utcnow().isoformat(),
        "company":        company_name,
        "prospect":       prospect_name,
        "email":          prospect_email,
        "phone":          prospect_phone,
        "segment":        brief.get("segment"),
        "ai_maturity":    brief.get("ai_maturity_score"),
        "pitch_angle":    brief.get("pitch_angle"),
        "hubspot_id":     contact_id,
        "email_subject":  outreach.get("subject"),
        "email_status":   outreach.get("send_status"),
        "sms_status":     sms_status,
        "trace_id":       outreach.get("trace_id"),
        "booking_link":   booking,
    }
    with open("logs/prospect_runs.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")

    # ── Summary ───────────────────────────────────────────
    print()
    print("=" * 55)
    print("  DONE")
    print("=" * 55)
    print(f"  Segment:     {brief.get('segment')}")
    print(f"  AI maturity: {brief.get('ai_maturity_score')}/3")
    print(f"  Email:       {outreach.get('send_status')}")
    print(f"  SMS:         {sms_status}")
    print(f"  HubSpot ID:  {contact_id}")
    print(f"  Trace ID:    {outreach.get('trace_id')}")
    print(f"  Booking:     {booking}")
    print()
    print("=" * 55)

    return record


if __name__ == "__main__":
    import argparse
    from run_batch import load_and_score_companies

    download_data_files()

    parser = argparse.ArgumentParser(description="Run pipeline for one auto-selected prospect from Crunchbase")
    parser.add_argument("--segment",   default="", help="ICP segment filter")
    parser.add_argument("--min-score", type=int, default=1, help="Min AI maturity score (default 1)")
    parser.add_argument("--company",   default="", help="Force a specific company name from the CSV")
    args = parser.parse_args()

    if args.company:
        # Forced company — look it up directly
        candidates = load_and_score_companies(limit=100)
        match = next((c for c in candidates if c["company_name"].lower() == args.company.lower()), None)
        if not match:
            print(f"[error] '{args.company}' not found in Crunchbase CSV ICP matches.")
            sys.exit(1)
        candidates = [match]
    else:
        # Auto-select the highest-scoring ICP match
        candidates = load_and_score_companies(
            segment_filter=args.segment,
            min_ai_score=args.min_score,
            limit=1,
        )

    if not candidates:
        print("[error] No ICP matches found. Try lowering --min-score.")
        sys.exit(1)

    best = candidates[0]
    company_name   = best["company_name"]
    contact_email  = best["contact_email"]

    # Use contact email from Crunchbase; fall back to a dev sink if redacted
    if not contact_email or "█" in contact_email:
        print(f"[warn] No usable contact email for {company_name} — using dev sink")
        contact_email = os.getenv("STAFF_SINK_EMAIL", "dev-sink@tenacious.com")

    prospect_name = f"Team at {company_name}"

    print(f"\nAuto-selected prospect from Crunchbase:")
    print(f"  Company : {company_name}")
    print(f"  Segment : {best['segment']}")
    print(f"  AI Score: {best['ai_score']}/3")
    print(f"  Industry: {best['industry']}")
    print(f"  Email   : {contact_email}\n")

    run_end_to_end(
        company_name   = company_name,
        prospect_name  = prospect_name,
        prospect_email = contact_email,
        open_roles     = 0,
    )