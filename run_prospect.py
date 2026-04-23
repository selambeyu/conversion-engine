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
    brief = build_signal_brief(company_name, open_roles=open_roles)

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

    # ── 4. Save run record ────────────────────────────────
    print("\n[4/4] Saving to logs...")
    Path("logs").mkdir(exist_ok=True)
    record = {
        "timestamp":      datetime.utcnow().isoformat(),
        "company":        company_name,
        "prospect":       prospect_name,
        "email":          prospect_email,
        "segment":        brief.get("segment"),
        "ai_maturity":    brief.get("ai_maturity_score"),
        "pitch_angle":    brief.get("pitch_angle"),
        "hubspot_id":     contact_id,
        "email_subject":  outreach.get("subject"),
        "email_status":   outreach.get("send_status"),
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
    print(f"  HubSpot ID:  {contact_id}")
    print(f"  Trace ID:    {outreach.get('trace_id')}")
    print(f"  Booking:     {booking}")
    print()
    print("  Take these screenshots for Wednesday PDF:")
    print("  [ ] HubSpot contact — all custom fields filled")
    print("  [ ] Resend dashboard — email delivered")
    print("  [ ] Langfuse — trace visible")
    print("=" * 55)

    return record


if __name__ == "__main__":
    download_data_files()

    run_end_to_end(
        company_name   = "Acme AI",
        prospect_name  = "Alex Chen",
        prospect_email = "melkambeyu@gmail.com",
        open_roles     = 8,
    )