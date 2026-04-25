"""
agent/channel_policy.py
─────────────────────────────────────────────────────
Centralized channel handoff policy for the Conversion Engine.

Single source of truth for: which channel to use next, when to
escalate from email → SMS → voice, and when to route to a human.

ALL channel routing decisions in the system must go through
decide_next_action(). Handlers (email_handler, sms_handler,
main.py webhook) call this — they do not make routing decisions
themselves.

Channel priority (per challenge spec):
  1. Email  — primary, all cold outreach
  2. SMS    — secondary, warm leads only (post email-reply)
  3. Voice  — final, discovery call booked by agent, delivered by human

State machine:
  new_lead → email_sent → replied → [sms_scheduling | booking_sent]
           → booked → human_handoff
           → opted_out (terminal)
           → stalled → [re_engage | archive]
─────────────────────────────────────────────────────
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────────────────
# State definitions
# ─────────────────────────────────────────────────────────

class ProspectState(str, Enum):
    NEW_LEAD        = "new_lead"
    EMAIL_SENT      = "email_sent"
    REPLIED         = "replied"
    SMS_SCHEDULING  = "sms_scheduling"
    BOOKING_SENT    = "booking_sent"
    BOOKED          = "booked"
    HUMAN_HANDOFF   = "human_handoff"
    OPTED_OUT       = "opted_out"
    STALLED         = "stalled"
    ARCHIVED        = "archived"


class Channel(str, Enum):
    EMAIL  = "email"
    SMS    = "sms"
    VOICE  = "voice"  # discovery call — human delivers
    NONE   = "none"   # no outreach — wait or archive


class Action(str, Enum):
    SEND_EMAIL          = "send_email"
    SEND_SMS            = "send_sms"
    SEND_BOOKING_LINK   = "send_booking_link"
    ROUTE_TO_HUMAN      = "route_to_human"
    WAIT                = "wait"
    ARCHIVE             = "archive"
    RE_ENGAGE_EMAIL     = "re_engage_email"


# ─────────────────────────────────────────────────────────
# Policy configuration
# ─────────────────────────────────────────────────────────

# Days after email_sent before a prospect is considered stalled
EMAIL_STALL_DAYS = 7

# Days after stalled before archiving
STALL_ARCHIVE_DAYS = 14

# After reply: if prospect mentions scheduling within this many hours,
# offer SMS scheduling instead of a second email
SMS_SCHEDULING_TRIGGER_HOURS = 48

# Keywords in prospect reply that trigger SMS scheduling offer
SMS_SCHEDULING_KEYWORDS = {
    "call", "chat", "schedule", "book", "calendar", "available",
    "when", "time", "meeting", "talk", "connect", "catch up",
}

# Keywords that trigger immediate human handoff (pricing, contracts, legal)
HUMAN_HANDOFF_KEYWORDS = {
    "pricing", "contract", "proposal", "legal", "sow", "nda",
    "capacity", "how many engineers", "start date", "pricing sheet",
    "specific staffing", "cost", "rate", "invoice",
}

# Keywords that are definitive opt-outs
OPT_OUT_KEYWORDS = {
    "unsubscribe", "remove me", "stop", "do not contact", "not interested",
    "please remove", "opt out", "opt-out",
}


# ─────────────────────────────────────────────────────────
# Decision record returned by decide_next_action()
# ─────────────────────────────────────────────────────────

@dataclass
class ChannelDecision:
    action:          Action
    channel:         Channel
    reason:          str
    new_state:       ProspectState
    metadata:        dict = field(default_factory=dict)
    requires_human:  bool = False


# ─────────────────────────────────────────────────────────
# Core policy function — ALL routing goes through here
# ─────────────────────────────────────────────────────────

def decide_next_action(
    current_state:    ProspectState,
    prospect:         dict,
    event:            str = "",
    reply_text:       str = "",
    days_since_email: Optional[int] = None,
) -> ChannelDecision:
    """
    Decide what action to take next for a prospect given their current state
    and the triggering event.

    Args:
        current_state:    Current ProspectState enum value
        prospect:         Dict with keys: email, phone, segment, ai_maturity_score,
                          has_replied, booking_url, hubspot_id
        event:            Triggering event string: "email_reply", "sms_inbound",
                          "booking_confirmed", "no_reply_timeout", "new_prospect"
        reply_text:       Full text of prospect reply (used for intent parsing)
        days_since_email: Days elapsed since last email sent (for stall detection)

    Returns:
        ChannelDecision with action, channel, reason, new_state
    """

    reply_lower = reply_text.lower()

    # ── Terminal states — never route out ───────────────────────────────
    if current_state == ProspectState.OPTED_OUT:
        return ChannelDecision(
            action=Action.ARCHIVE, channel=Channel.NONE,
            reason="Prospect has opted out — no further contact",
            new_state=ProspectState.OPTED_OUT,
        )

    if current_state == ProspectState.ARCHIVED:
        return ChannelDecision(
            action=Action.ARCHIVE, channel=Channel.NONE,
            reason="Prospect is archived",
            new_state=ProspectState.ARCHIVED,
        )

    # ── Opt-out detection — check reply text first regardless of state ──
    if reply_text and any(kw in reply_lower for kw in OPT_OUT_KEYWORDS):
        return ChannelDecision(
            action=Action.ARCHIVE, channel=Channel.NONE,
            reason=f"Opt-out keyword detected in reply: '{reply_text[:80]}'",
            new_state=ProspectState.OPTED_OUT,
        )

    # ── Human handoff triggers — pricing, capacity, contracts ───────────
    if reply_text and any(kw in reply_lower for kw in HUMAN_HANDOFF_KEYWORDS):
        return ChannelDecision(
            action=Action.ROUTE_TO_HUMAN, channel=Channel.NONE,
            reason=f"Human-handoff keyword in reply: prospect asking about {[kw for kw in HUMAN_HANDOFF_KEYWORDS if kw in reply_lower][:2]}",
            new_state=ProspectState.HUMAN_HANDOFF,
            requires_human=True,
            metadata={"reply_text": reply_text, "trigger": "pricing_or_capacity"},
        )

    # ── Booking confirmed ────────────────────────────────────────────────
    if event == "booking_confirmed" or current_state == ProspectState.BOOKED:
        return ChannelDecision(
            action=Action.ROUTE_TO_HUMAN, channel=Channel.VOICE,
            reason="Discovery call booked — route context brief to Tenacious delivery lead",
            new_state=ProspectState.HUMAN_HANDOFF,
            requires_human=True,
            metadata={"handoff_type": "discovery_call_booked"},
        )

    # ── New lead — always start with email ──────────────────────────────
    if current_state == ProspectState.NEW_LEAD or event == "new_prospect":
        return ChannelDecision(
            action=Action.SEND_EMAIL, channel=Channel.EMAIL,
            reason="New lead — email is primary cold outreach channel for Tenacious prospects",
            new_state=ProspectState.EMAIL_SENT,
            metadata={"pitch_angle": prospect.get("pitch_angle", "exploratory_discovery")},
        )

    # ── Email sent, no reply yet — check for stall ──────────────────────
    if current_state == ProspectState.EMAIL_SENT and event == "no_reply_timeout":
        days = days_since_email or 0
        if days >= EMAIL_STALL_DAYS + STALL_ARCHIVE_DAYS:
            return ChannelDecision(
                action=Action.ARCHIVE, channel=Channel.NONE,
                reason=f"No reply after {days} days — archiving",
                new_state=ProspectState.ARCHIVED,
            )
        if days >= EMAIL_STALL_DAYS:
            return ChannelDecision(
                action=Action.RE_ENGAGE_EMAIL, channel=Channel.EMAIL,
                reason=f"No reply for {days} days — send re-engagement email",
                new_state=ProspectState.STALLED,
            )
        return ChannelDecision(
            action=Action.WAIT, channel=Channel.NONE,
            reason=f"Email sent {days} days ago — within normal response window, wait",
            new_state=ProspectState.EMAIL_SENT,
        )

    # ── Prospect replied to email ────────────────────────────────────────
    if event == "email_reply" or current_state == ProspectState.REPLIED:
        # Check if reply contains scheduling intent → offer SMS for fast coordination
        has_scheduling_intent = any(kw in reply_lower for kw in SMS_SCHEDULING_KEYWORDS)
        has_phone = bool(prospect.get("phone"))

        if has_scheduling_intent and has_phone:
            # Only switch to SMS if prospect has provided a phone number
            return ChannelDecision(
                action=Action.SEND_SMS, channel=Channel.SMS,
                reason="Reply contains scheduling intent + phone available — SMS handoff for fast coordination",
                new_state=ProspectState.SMS_SCHEDULING,
                metadata={"scheduling_keywords_found": [kw for kw in SMS_SCHEDULING_KEYWORDS if kw in reply_lower]},
            )

        # No scheduling keywords or no phone — send booking link via email
        return ChannelDecision(
            action=Action.SEND_BOOKING_LINK, channel=Channel.EMAIL,
            reason="Prospect replied — send Cal.com booking link via email",
            new_state=ProspectState.BOOKING_SENT,
            metadata={"booking_url": prospect.get("booking_url", "")},
        )

    # ── SMS scheduling flow ──────────────────────────────────────────────
    if current_state == ProspectState.SMS_SCHEDULING and event == "sms_inbound":
        has_scheduling_intent = any(kw in reply_lower for kw in SMS_SCHEDULING_KEYWORDS)
        if has_scheduling_intent:
            return ChannelDecision(
                action=Action.SEND_BOOKING_LINK, channel=Channel.SMS,
                reason="SMS scheduling conversation — send booking link via SMS",
                new_state=ProspectState.BOOKING_SENT,
                metadata={"booking_url": prospect.get("booking_url", "")},
            )
        return ChannelDecision(
            action=Action.SEND_SMS, channel=Channel.SMS,
            reason="SMS reply received — continue SMS scheduling conversation",
            new_state=ProspectState.SMS_SCHEDULING,
        )

    # ── Booking sent, awaiting confirmation ─────────────────────────────
    if current_state == ProspectState.BOOKING_SENT:
        return ChannelDecision(
            action=Action.WAIT, channel=Channel.NONE,
            reason="Booking link sent — waiting for Cal.com confirmation webhook",
            new_state=ProspectState.BOOKING_SENT,
        )

    # ── Stalled re-engagement ────────────────────────────────────────────
    if current_state == ProspectState.STALLED:
        if event == "email_reply":
            return ChannelDecision(
                action=Action.SEND_BOOKING_LINK, channel=Channel.EMAIL,
                reason="Stalled prospect replied to re-engagement email — move to booking",
                new_state=ProspectState.BOOKING_SENT,
            )
        days = days_since_email or 0
        if days >= EMAIL_STALL_DAYS + STALL_ARCHIVE_DAYS:
            return ChannelDecision(
                action=Action.ARCHIVE, channel=Channel.NONE,
                reason=f"Stalled for {days} days with no reply — archive",
                new_state=ProspectState.ARCHIVED,
            )
        return ChannelDecision(
            action=Action.WAIT, channel=Channel.NONE,
            reason="Stalled — waiting for re-engagement reply",
            new_state=ProspectState.STALLED,
        )

    # ── Fallback — should not reach here in normal flow ─────────────────
    return ChannelDecision(
        action=Action.WAIT, channel=Channel.NONE,
        reason=f"No policy matched for state={current_state} event={event} — wait",
        new_state=current_state,
        metadata={"warning": "unmatched_policy_case"},
    )


# ─────────────────────────────────────────────────────────
# Convenience: parse inbound message to event string
# ─────────────────────────────────────────────────────────

def classify_inbound_event(text: str, source: str = "email") -> str:
    """
    Map raw inbound message text to a normalized event string.
    Used by webhook handlers before calling decide_next_action().
    """
    t = text.lower()
    if any(kw in t for kw in OPT_OUT_KEYWORDS):
        return "opt_out"
    if any(kw in t for kw in HUMAN_HANDOFF_KEYWORDS):
        return "human_handoff_trigger"
    if source == "calcom":
        return "booking_confirmed"
    if source == "sms":
        return "sms_inbound"
    return "email_reply"
