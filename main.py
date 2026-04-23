"""
main.py — FastAPI webhook server for the Conversion Engine.

Handles:
  POST /webhook/sms          Africa's Talking inbound SMS
  POST /webhook/email/reply  Resend inbound reply
  POST /webhook/email/event  Resend delivery events (bounce, failed, etc.)
  POST /webhook/calcom       Cal.com booking confirmation
  GET  /health
  GET  /send-test            Quick SMS send for testing
"""

import json
import hmac
import hashlib
import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from agent.sms_handler import send_sms, is_warm_lead, mark_warm_lead, get_warm_lead_email
from agent.hubspot_handler import (
    update_status,
    log_email_activity,
    find_contact_by_email,
    mark_meeting_booked,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("conversion_engine")

app = FastAPI(title="Conversion Engine", version="0.1.0")

# In-memory state (replace with Redis/DB for production)
conversations: dict = {}     # phone → {turns, opted_out, warm}
email_threads: dict = {}     # email → {hubspot_id, turns}


# ─────────────────────────────────────────────────────────
# SMS — INBOUND WEBHOOK (Africa's Talking)
# ─────────────────────────────────────────────────────────

# Intent labels returned by _parse_sms_intent()
SMS_INTENT_BOOK     = "book"        # prospect wants to schedule a call
SMS_INTENT_POSITIVE = "positive"    # interested, asking questions
SMS_INTENT_NEGATIVE = "negative"    # not interested / go away
SMS_INTENT_OTHER    = "other"       # unclear / general chat


def _parse_sms_intent(message: str) -> str:
    """
    Classify inbound SMS intent without an LLM call.
    Fast keyword-based triage; used to route to the right downstream handler.
    """
    txt = message.lower().strip()

    book_kw = {"book", "schedule", "cal.com", "calendar", "call", "meeting",
               "link", "send link", "yes", "sure", "sounds good", "interested",
               "let's do it", "let's talk", "when"}
    neg_kw  = {"no", "not interested", "remove", "unsubscribe", "stop",
               "don't contact", "do not contact", "leave me alone", "wrong number"}

    if any(kw in txt for kw in neg_kw):
        return SMS_INTENT_NEGATIVE
    if any(kw in txt for kw in book_kw):
        return SMS_INTENT_BOOK
    # Ends with "?" → question → positive engagement
    if txt.endswith("?") or any(w in txt for w in ["what", "how", "who", "tell me", "more info"]):
        return SMS_INTENT_POSITIVE
    return SMS_INTENT_OTHER


def _downstream_sms(phone: str, intent: str, message: str, state: dict):
    """
    Route the parsed intent to the appropriate downstream action:
      book     → send Cal.com booking link, update HubSpot to 'booking_link_sent'
      negative → record opt-out, update HubSpot to 'opted_out_sms'
      positive → AI reply, log note to HubSpot
      other    → AI reply only
    Returns the reply string to send back.
    """
    import os
    booking_url = os.getenv("CALCOM_BOOKING_URL", "https://cal.com/tenacious/discovery-call")
    hubspot_id  = state.get("hubspot_id")

    if intent == SMS_INTENT_BOOK:
        reply = f"Great! Book your 30-min call here: {booking_url} — looking forward to it."
        if hubspot_id:
            update_status(hubspot_id, "booking_link_sent",
                          notes=f"Prospect requested booking link via SMS: {message[:200]}")
        log.info(f"SMS booking intent | {phone} | HubSpot={hubspot_id}")
        return reply

    if intent == SMS_INTENT_NEGATIVE:
        # Mark opted-out in conversation state
        state["opted_out"] = True
        if hubspot_id:
            update_status(hubspot_id, "opted_out_sms",
                          notes=f"Prospect asked to stop SMS contact: {message[:200]}")
        log.info(f"SMS opt-out (negative intent) | {phone}")
        return "Understood — I won't reach out again. Have a great day!"

    # positive or other → AI-generated reply
    return _ai_sms_reply(phone, message, state.get("turns", []))


def _ai_sms_reply(phone: str, message: str, history: list) -> str:
    """
    Generate an AI reply for warm-lead SMS conversation.
    160-char limit; falls back to a booking link nudge on error.
    """
    import os
    from openai import OpenAI

    booking_url = os.getenv("CALCOM_BOOKING_URL", "https://cal.com/tenacious/discovery-call")
    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )
    messages = [
        {"role": "system", "content": (
            "You are Maya from Tenacious Consulting, following up via SMS after a prospect "
            "replied positively to your email. "
            "Your only goal is to get them to book a 30-minute discovery call. "
            "Keep every reply under 160 characters. Be warm, direct, human. "
            f"If they seem ready, send: {booking_url} "
            "If they ask about pricing, say a team member will confirm details on the call. "
            "Never fabricate facts or make commitments."
        )},
        *[
            {"role": "user" if t["role"] == "user" else "assistant", "content": t["content"]}
            for t in history[-6:]
        ],
    ]
    try:
        resp = client.chat.completions.create(
            model=os.getenv("DEV_MODEL", "deepseek/deepseek-chat"),
            messages=messages,
            max_tokens=80,
            temperature=0.4,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"SMS AI reply error for {phone}: {e}")
        return f"Thanks for the reply! Book a quick call: {booking_url}"


@app.post("/webhook/sms")
async def receive_sms(request: Request):
    """
    Africa's Talking calls this endpoint when a prospect replies to an SMS.
    Form fields: from, to, text, date, id, linkId

    Guard: SMS is warm-lead only. Cold numbers are silently dropped —
    they should never be receiving outbound SMS in the first place.
    """
    try:
        form = await request.form()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed form payload")

    phone   = form.get("from", "").strip()
    message = form.get("text", "").strip()
    msg_id  = form.get("id", "")

    if not phone or not message:
        raise HTTPException(status_code=400, detail="Missing 'from' or 'text' fields")

    log.info(f"SMS inbound | from={phone} | text={message[:80]}")

    # ── STOP / opt-out commands — must always be honoured immediately ──────
    if message.upper() in {"STOP", "UNSUBSCRIBE", "UNSUB", "QUIT", "END", "CANCEL"}:
        conversations[phone] = {"opted_out": True, "turns": [], "warm": False}
        send_sms(phone, "You've been unsubscribed. Reply START to re-subscribe.")
        log.info(f"SMS opt-out (command) | {phone}")
        return {"status": "opted_out"}

    # ── Re-subscribe ───────────────────────────────────────────────────────
    if message.upper() in {"START", "SUBSCRIBE"}:
        conversations.setdefault(phone, {})["opted_out"] = False
        send_sms(phone, "You're re-subscribed. Reply STOP at any time to opt out.")
        return {"status": "resubscribed"}

    # ── Warm-lead guard — drop cold inbound, log for audit ────────────────
    # SMS outbound is only sent to warm leads (prospects who replied to email).
    # If we receive SMS from an unknown number it means a routing error occurred;
    # we do NOT respond so as not to initiate unsolicited contact.
    if not is_warm_lead(phone):
        log.warning(f"SMS from non-warm-lead {phone} — dropped (cold contact guard)")
        return {"status": "ignored", "reason": "not_warm_lead"}

    # ── Retrieve or initialise conversation state ──────────────────────────
    state = conversations.setdefault(phone, {"turns": [], "opted_out": False, "warm": True})
    if state.get("opted_out"):
        log.info(f"SMS from opted-out number {phone} — silently dropped")
        return {"status": "opted_out"}

    # ── Attach HubSpot ID if not already cached ────────────────────────────
    # Resolve phone → email via warm-lead registry, then look up HubSpot
    if not state.get("hubspot_id"):
        email = state.get("email") or get_warm_lead_email(phone)
        if email:
            state["email"] = email
            result = find_contact_by_email(email)
            if result:
                state["hubspot_id"] = result["id"]

    # ── Record inbound turn ────────────────────────────────────────────────
    state["turns"].append({
        "role": "user",
        "content": message,
        "ts": datetime.utcnow().isoformat(),
    })

    # ── Parse intent and route to downstream handler ───────────────────────
    intent = _parse_sms_intent(message)
    log.info(f"SMS intent={intent} | {phone}")

    reply = _downstream_sms(phone, intent, message, state)

    # ── If opted out via negative intent, honour immediately ──────────────
    if state.get("opted_out"):
        send_sms(phone, reply)
        return {"status": "opted_out_via_intent", "msg_id": msg_id}

    # ── Record agent turn and send reply ──────────────────────────────────
    state["turns"].append({
        "role": "agent",
        "content": reply,
        "ts": datetime.utcnow().isoformat(),
    })
    send_sms(phone, reply)

    return {"status": "ok", "intent": intent, "msg_id": msg_id}


# ─────────────────────────────────────────────────────────
# EMAIL — INBOUND REPLY WEBHOOK (Resend)
# ─────────────────────────────────────────────────────────

@app.post("/webhook/email/reply")
async def receive_email_reply(request: Request):
    """
    Resend calls this endpoint when a prospect replies to an outbound email.
    Payload is JSON with fields: from, to, subject, text, html, headers.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed JSON payload")

    sender_email = body.get("from", "")
    subject      = body.get("subject", "")
    text_body    = body.get("text", body.get("html", ""))
    message_id   = body.get("headers", {}).get("message-id", "")

    if not sender_email:
        raise HTTPException(status_code=400, detail="Missing 'from' field in reply payload")

    log.info(f"Email reply | from={sender_email} | subject={subject[:60]}")

    # Store the turn
    thread = email_threads.setdefault(sender_email, {"turns": [], "hubspot_id": None})
    thread["turns"].append({
        "role": "prospect",
        "subject": subject,
        "body": text_body[:2000],
        "ts": datetime.utcnow().isoformat(),
        "message_id": message_id,
    })

    # Mark as warm lead for SMS escalation — cross-link email so SMS webhook can resolve HubSpot ID
    mark_warm_lead(sender_email, email=sender_email)

    # Log to HubSpot if we have a contact
    hubspot_id = thread.get("hubspot_id") or _lookup_hubspot_id(sender_email)
    if hubspot_id:
        thread["hubspot_id"] = hubspot_id
        log_email_activity(
            contact_id=hubspot_id,
            subject=subject,
            body=text_body[:2000],
            direction="inbound",
        )
        update_status(hubspot_id, "replied")

    return {"status": "received", "from": sender_email}


# ─────────────────────────────────────────────────────────
# EMAIL — DELIVERY EVENT WEBHOOK (Resend)
# ─────────────────────────────────────────────────────────

@app.post("/webhook/email/event")
async def receive_email_event(request: Request):
    """
    Resend delivery events: delivered, bounced, complained, failed, opened, clicked.
    Payload: {"type": "email.bounced", "data": {"email_id": "...", "to": ["..."], ...}}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed JSON payload")

    event_type = body.get("type", "")
    data       = body.get("data", {})
    to_list    = data.get("to", [])
    email_id   = data.get("email_id", "")
    to_email   = to_list[0] if to_list else ""

    log.info(f"Email event | type={event_type} | to={to_email} | id={email_id}")

    if event_type in {"email.bounced", "email.failed", "email.complained"}:
        log.warning(f"Delivery failure: {event_type} for {to_email}")
        # Update HubSpot so the SDR knows this address is bad
        hubspot_id = _lookup_hubspot_id(to_email)
        if hubspot_id:
            status_map = {
                "email.bounced":    "bounced",
                "email.failed":     "delivery_failed",
                "email.complained": "spam_complaint",
            }
            update_status(hubspot_id, status_map.get(event_type, "delivery_failed"))

    elif event_type == "email.delivered":
        log.info(f"Delivered: {to_email}")

    elif event_type in {"email.opened", "email.clicked"}:
        log.info(f"Engagement: {event_type} by {to_email}")
        # Mark as engaged — potentially upgrade to warm lead for SMS
        hubspot_id = _lookup_hubspot_id(to_email)
        if hubspot_id:
            update_status(hubspot_id, "email_opened" if event_type == "email.opened" else "email_clicked")

    return {"status": "ok", "event": event_type}


# ─────────────────────────────────────────────────────────
# CALCOM — BOOKING CONFIRMATION WEBHOOK
# ─────────────────────────────────────────────────────────

@app.post("/webhook/calcom")
async def receive_calcom_booking(request: Request):
    """
    Cal.com calls this when a prospect completes a booking.
    Payload: {"triggerEvent": "BOOKING_CREATED", "payload": {...}}

    On confirmation:
      - Sets meeting_booked = true on the HubSpot contact
      - Updates last_booking_at and booking_url
      - Updates outreach_status to 'booked'
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed JSON payload")

    event   = body.get("triggerEvent", "")
    payload = body.get("payload", {})

    log.info(f"Cal.com event | trigger={event}")

    if event not in {"BOOKING_CREATED", "BOOKING_CONFIRMED"}:
        return {"status": "ignored", "event": event}

    # Extract attendee info
    attendees     = payload.get("attendees", [])
    organizer     = payload.get("organizer", {})
    booking_id    = payload.get("id", "")
    booking_uid   = payload.get("uid", "")
    start_time    = payload.get("startTime", "")
    meeting_url   = payload.get("videoCallData", {}).get("url", "")

    # Find the prospect (non-organizer attendee)
    prospect = next(
        (a for a in attendees if a.get("email") != organizer.get("email")),
        attendees[0] if attendees else {}
    )
    prospect_email = prospect.get("email", "")
    prospect_name  = prospect.get("name", "")
    booking_url    = f"https://app.cal.com/booking/{booking_uid}" if booking_uid else ""

    log.info(f"Booking confirmed | prospect={prospect_email} | start={start_time}")

    # Sync to HubSpot
    if prospect_email:
        hubspot_id = _lookup_hubspot_id(prospect_email)
        if hubspot_id:
            mark_meeting_booked(
                contact_id=hubspot_id,
                booking_url=booking_url or meeting_url,
                booked_at=start_time,
            )
            log.info(f"HubSpot updated | contact={hubspot_id} | meeting_booked=true")
        else:
            log.warning(f"No HubSpot contact found for {prospect_email} — booking not synced")

    return {
        "status": "ok",
        "booking_id": booking_id,
        "prospect_email": prospect_email,
        "start_time": start_time,
    }


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def _lookup_hubspot_id(email: str) -> str | None:
    """Find a HubSpot contact ID by email, with cache."""
    # Check email thread cache first
    if email in email_threads and email_threads[email].get("hubspot_id"):
        return email_threads[email]["hubspot_id"]
    try:
        result = find_contact_by_email(email)
        if result:
            hid = result.get("id")
            email_threads.setdefault(email, {})["hubspot_id"] = hid
            return hid
    except Exception as e:
        log.warning(f"HubSpot lookup failed for {email}: {e}")
    return None


# ─────────────────────────────────────────────────────────
# UTILITY ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "running", "version": "0.1.0", "timestamp": datetime.utcnow().isoformat()}


@app.get("/send-test")
def send_test(to: str, message: str = "Hello from Conversion Engine!"):
    """Quick SMS test. Usage: GET /send-test?to=%2B251XXXXXXXXX"""
    result = send_sms(to, message)
    return {"status": "sent", "result": result}
