"""
agent/email_handler.py
─────────────────────────────────────────────────────
Sends personalised outbound emails and handles replies.

Flow:
  1. Receive a signal_brief from enrichment pipeline
  2. Use AI to write a grounded, personalised email
  3. Send via Resend API
  4. Log to HubSpot and Langfuse
  5. When prospect replies, webhook calls handle_reply()

The email must:
  - Reference something real about the company
  - Match the tone in Tenacious's style guide
  - Never over-claim weak signals
  - End with a booking link
─────────────────────────────────────────────────────
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))
from logger import log_trace

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL     = os.getenv("FROM_EMAIL", "onboarding@resend.dev")
DEV_MODEL      = os.getenv("DEV_MODEL", "deepseek/deepseek-chat")

# ─────────────────────────────────────────────────────────
# MECHANISM: Signal-Confidence-Aware Phrasing
# ─────────────────────────────────────────────────────────
# Maps confidence level + signal type to assertion vs hedge vocabulary.
# This is the Act IV mechanism: agent language automatically adjusts
# based on per-signal confidence so we never over-claim weak signals.

_CONFIDENCE_THRESHOLDS = {"high": 0.7, "medium": 0.4, "low": 0.0}

# Strong assertion words that must be replaced when confidence is low/medium
_OVERCLAIM_PHRASES = [
    ("you are scaling aggressively", "public signals suggest rapid hiring"),
    ("you are aggressively hiring", "it appears you are expanding the team"),
    ("your team is growing fast", "based on public job postings, your team appears to be growing"),
    ("you have a dedicated AI team", "public signals suggest AI investment"),
    ("you recently raised", "according to public records, you raised"),
    ("your engineers tripled", "open roles appear to have increased significantly"),
    ("you are building", "it appears you are building"),
]


def _confidence_score(signal_brief: dict) -> float:
    """Compute a 0–1 numeric confidence from the brief's qualitative fields."""
    ai_conf = signal_brief.get("ai_maturity_conf", "low")
    seg_conf = signal_brief.get("segment_confidence", "low")
    send_generic = signal_brief.get("send_generic_email", False)

    conf_map = {"high": 1.0, "medium": 0.55, "low": 0.2}
    ai_score = conf_map.get(ai_conf, 0.2)
    seg_score = conf_map.get(seg_conf, 0.2)

    if send_generic:
        return 0.15

    # Evidence count boosts confidence
    evidence = signal_brief.get("ai_evidence", [])
    evidence_boost = min(len(evidence) * 0.05, 0.2)

    return min((ai_score + seg_score) / 2 + evidence_boost, 1.0)


def _apply_confidence_phrasing(body: str, confidence: float) -> str:
    """
    Post-generation guard: replace over-claiming phrases when confidence
    is below threshold. This is the core Act IV mechanism.

    High confidence (>= 0.7): keep original assertive language
    Medium confidence (0.4–0.69): soften claims to hedged language
    Low confidence (< 0.4): replace assertions with questions/exploration
    """
    if confidence >= _CONFIDENCE_THRESHOLDS["high"]:
        return body  # high confidence: assertive language is appropriate

    result = body
    for assertive, hedged in _OVERCLAIM_PHRASES:
        if assertive.lower() in result.lower():
            # Case-insensitive replace
            import re
            result = re.sub(re.escape(assertive), hedged, result, flags=re.IGNORECASE)

    if confidence < _CONFIDENCE_THRESHOLDS["medium"]:
        # Very low confidence: prepend a disclaimer phrase to the first sentence
        if not any(p in result.lower() for p in ["it appears", "based on public", "public signals"]):
            result = "Based on public signals — " + result[0].lower() + result[1:]

    return result


# ─────────────────────────────────────────────────────────
# PART 1 — Write the email using AI
# ─────────────────────────────────────────────────────────

def write_email(signal_brief: dict) -> dict:
    """
    Use the AI to write a personalised outbound email
    based on the signal brief from the enrichment pipeline.

    The AI reads the signal summary and writes an email
    that feels researched — not generic.

    Returns: {"subject": "...", "body": "..."}
    """
    segment    = signal_brief.get("segment", "unknown")
    summary    = signal_brief.get("summary", "")
    company    = signal_brief.get("company_name", "your company")
    ai_score   = signal_brief.get("ai_maturity_score", 0)
    ai_conf    = signal_brief.get("ai_maturity_conf", "low")
    pitch      = signal_brief.get("pitch_angle", "exploratory_discovery")
    send_generic = signal_brief.get("send_generic_email", False)
    booking_url  = os.getenv("CALCOM_BOOKING_URL", "https://cal.com/tenacious/discovery-call")

    # Act IV mechanism: compute numeric confidence before writing
    confidence = _confidence_score(signal_brief)

    # Build the writing instructions based on segment and confidence
    segment_instructions = {
        "recently_funded_startup": (
            "They recently raised funding and are growing fast. "
            "The angle is: you need to scale engineering output faster "
            "than in-house hiring can support. Budget is fresh, "
            "runway clock is ticking. Be energetic but not pushy."
        ),
        "mid_market_restructuring": (
            "They have had layoffs and are under cost pressure. "
            "The angle is: replace higher-cost roles with offshore equivalents "
            "while keeping delivery capacity. Be empathetic, not salesy."
        ),
        "engineering_leadership_transition": (
            "They have a new technical leader. "
            "The angle is: new leaders reassess vendor contracts in their first 6 months. "
            "This is a narrow but high-value window. Be direct and respectful."
        ),
        "specialized_capability_gap": (
            "They are building something AI/ML specific but lack the in-house skills. "
            "The angle is: specific project consulting, not generic outsourcing. "
            "Reference their AI maturity score — they will recognise themselves."
        ),
        "unknown": (
            "We do not have a strong signal for this company. "
            "Write an exploratory email — ask rather than assert. "
            "Do NOT claim facts you cannot verify."
        ),
    }

    angle_desc = segment_instructions.get(segment, segment_instructions["unknown"])

    # Confidence guard — soften language for low confidence signals
    if send_generic or ai_conf == "low":
        confidence_instruction = (
            "IMPORTANT: Our signal confidence for this company is LOW. "
            "Use exploratory language throughout. "
            "Say 'it appears' or 'based on public signals' not 'you are' or 'you have'. "
            "Ask questions rather than making statements about their situation."
        )
    else:
        confidence_instruction = (
            "Signal confidence is HIGH. You can reference the company's "
            "specific situation directly but always stay factual. "
            "Never exaggerate or fabricate details."
        )

    prompt = f"""You are writing a cold outreach email for Tenacious Consulting and Outsourcing.
Tenacious provides engineering teams and AI consulting to tech companies.

COMPANY RESEARCH SUMMARY:
{summary}

SEGMENT: {segment}
PITCH ANGLE: {pitch}
AI MATURITY SCORE: {ai_score}/3 (confidence: {ai_conf})

WRITING INSTRUCTIONS:
{angle_desc}

{confidence_instruction}

TENACIOUS STYLE GUIDE:
- Warm, direct, professional — never salesy or robotic
- Under 200 words total
- One specific reference to something real about their company
- One clear question or call to action
- End with a booking link: {booking_url}
- Never use phrases like "I hope this email finds you well"
- Never use bullet points in cold emails
- Sign off as: Maya — Tenacious Consulting

Write the subject line first on its own line starting with "Subject: "
Then write the email body.
Do NOT add any other labels or formatting."""

    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )

    start = time.time()
    response = client.chat.completions.create(
        model=DEV_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,   # slight creativity for email writing
        max_tokens=400
    )
    latency_ms = int((time.time() - start) * 1000)
    content    = response.choices[0].message.content.strip()

    # Parse subject and body
    lines   = content.split("\n")
    subject = ""
    body    = ""

    for i, line in enumerate(lines):
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
            body    = "\n".join(lines[i+1:]).strip()
            break

    if not subject:
        subject = f"Engineering capacity for {company}"
        body    = content

    # Act IV mechanism: post-generation confidence phrasing guard
    body = _apply_confidence_phrasing(body, confidence)

    # Calculate cost
    tokens_in  = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens
    cost_usd   = (tokens_in * 0.00000014) + (tokens_out * 0.00000028)

    return {
        "subject":          subject,
        "body":             body,
        "cost_usd":         round(cost_usd, 7),
        "latency_ms":       latency_ms,
        "confidence_score": round(confidence, 3),
        "mechanism":        "signal_confidence_aware_phrasing",
    }


# ─────────────────────────────────────────────────────────
# PART 2 — Send the email via Resend
# ─────────────────────────────────────────────────────────

def send_email(
    to_email:   str,
    subject:    str,
    body:       str,
    company:    str = "",
) -> dict:
    """
    Send an email via Resend API.
    Returns: {"id": "...", "status": "sent"} or error dict
    """
    import requests

    if not RESEND_API_KEY or RESEND_API_KEY == "re_xxxx":
        print("  Email: RESEND_API_KEY not set — printing instead")
        print(f"\n  TO: {to_email}")
        print(f"  SUBJECT: {subject}")
        print(f"  BODY:\n{body}\n")
        return {"id": "mock-email-001", "status": "mock_sent"}

    # Kill switch: route all outbound to staff sink unless PRODUCTION_MODE=true
    STAFF_SINK = os.getenv("STAFF_SINK_EMAIL", "dev-sink@tenacious.com")
    if os.getenv("PRODUCTION_MODE", "false").lower() != "true":
        print(f"  [kill-switch] PRODUCTION_MODE != true — redirecting {to_email} → {STAFF_SINK}")
        to_email = STAFF_SINK

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type":  "application/json"
        },
        json={
            "from":    FROM_EMAIL,
            "to":      [to_email],
            "subject": subject,
            "text":    body,
        }
    )

    if resp.status_code == 200:
        email_id = resp.json().get("id", "unknown")
        print(f"  Email sent → {to_email} (id: {email_id})")
        return {"id": email_id, "status": "sent"}
    else:
        print(f"  Email error: {resp.status_code} — {resp.text[:200]}")
        return {"id": None, "status": "failed", "error": resp.text}


# ─────────────────────────────────────────────────────────
# PART 3 — Full outreach flow (research → write → send → log)
# ─────────────────────────────────────────────────────────

def run_outreach(
    prospect_email: str,
    prospect_name:  str,
    signal_brief:   dict,
    hubspot_contact_id: str = None,
) -> dict:
    """
    Run the complete outreach flow for one prospect.

    Steps:
    1. Write personalised email using signal brief
    2. Send via Resend
    3. Log to Langfuse with trace_id
    4. Update HubSpot contact status
    5. Return full result including trace_id

    This is the function you call once per prospect.
    """
    company = signal_brief.get("company_name", "")
    print(f"\nRunning outreach for {prospect_name} at {company}")
    print("-" * 45)

    # Step 1 — Write the email
    print("  Writing email...")
    email = write_email(signal_brief)
    print(f"  Subject: {email['subject']}")

    # Step 2 — Send the email
    print("  Sending email...")
    send_result = send_email(
        to_email = prospect_email,
        subject  = email["subject"],
        body     = email["body"],
        company  = company,
    )

    # Step 3 — Log to Langfuse
    trace_id = log_trace(
        name="outbound_email",
        input_data={
            "prospect":  prospect_email,
            "company":   company,
            "segment":   signal_brief.get("segment"),
            "ai_score":  signal_brief.get("ai_maturity_score"),
        },
        output_data={
            "subject":     email["subject"],
            "body_preview":email["body"][:300],
            "send_status": send_result["status"],
            "email_id":    send_result.get("id"),
        },
        cost_usd   = email["cost_usd"],
        latency_ms = email["latency_ms"],
        tags       = ["outbound", "email", signal_brief.get("segment", "unknown")]
    )

    # Step 4 — Update HubSpot if we have a contact ID
    if hubspot_contact_id:
        from agent.hubspot_handler import update_status, log_email_activity
        update_status(hubspot_contact_id, "email_sent")
        log_email_activity(
            contact_id = hubspot_contact_id,
            subject    = email["subject"],
            body       = email["body"],
            direction  = "outbound"
        )

    result = {
        "prospect_email": prospect_email,
        "prospect_name":  prospect_name,
        "company":        company,
        "subject":        email["subject"],
        "body":           email["body"],
        "send_status":    send_result["status"],
        "email_id":       send_result.get("id"),
        "trace_id":       trace_id,
        "cost_usd":       email["cost_usd"],
        "timestamp":      datetime.utcnow().isoformat(),
    }

    print(f"  Done. trace_id: {trace_id}")
    return result