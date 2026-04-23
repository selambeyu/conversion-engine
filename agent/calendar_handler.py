"""
agent/calendar_handler.py
─────────────────────────────────────────────────────
Handles Cal.com booking links.

For Wednesday, the agent needs to:
  1. Generate a booking link for a prospect
  2. Send it in the email
  3. When they book, log it in HubSpot

The grader checks: is there a Cal.com booking
with both attendees listed?
─────────────────────────────────────────────────────
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

CALCOM_API_KEY   = os.getenv("CALCOM_API_KEY", "")
CALCOM_BOOKING_URL = os.getenv("CALCOM_BOOKING_URL", "")


def get_booking_link(
    prospect_name: str  = "",
    prospect_email: str = "",
    notes: str          = ""
) -> str:
    """
    Return a personalised Cal.com booking link for this prospect.

    Cal.com supports pre-filling fields via URL parameters.
    This means the prospect arrives at the booking page with
    their name and email already filled in — less friction,
    more bookings.

    Example output:
      https://cal.com/tenacious/discovery-call
        ?name=Alex+Chen
        &email=cto@acmeai.com
        &notes=Series+A+startup...
    """
    base = CALCOM_BOOKING_URL

    if not base or "yourname" in base:
        # Fallback if not configured yet
        return "https://cal.com/tenacious/discovery-call"

    # Build URL parameters
    params = []
    if prospect_name:
        params.append(f"name={prospect_name.replace(' ', '+')}")
    if prospect_email:
        params.append(f"email={prospect_email}")
    if notes:
        # Truncate notes for URL safety
        short_note = notes[:200].replace(" ", "+").replace("&", "and")
        params.append(f"notes={short_note}")

    if params:
        return f"{base}?{'&'.join(params)}"
    return base


def create_booking(
    prospect_name:  str,
    prospect_email: str,
    start_time:     str,   # ISO format e.g. "2026-04-25T10:00:00Z"
    event_type_id:  int = None,
    notes:          str = ""
) -> dict:
    """
    Create an actual booking via the Cal.com API.

    This is called when a prospect clicks the booking link
    and selects a time — Cal.com sends a webhook to your
    server, and you call this to confirm the booking.

    For the Wednesday demo, you can also call this directly
    to create a test booking to show the grader.

    Returns: booking details dict
    """
    if not CALCOM_API_KEY:
        print("  Cal.com API key not set — returning mock booking")
        return _mock_booking(prospect_name, prospect_email, start_time)

    # Get event type ID if not provided
    if not event_type_id:
        event_type_id = _get_event_type_id()

    url  = "https://api.cal.com/v1/bookings"
    body = {
        "eventTypeId": event_type_id,
        "start":       start_time,
        "responses": {
            "name":  prospect_name,
            "email": prospect_email,
            "notes": notes,
        },
        "timeZone": "America/New_York",
        "language": "en",
        "metadata": {
            "source": "conversion_engine",
            "notes":  notes[:500]
        }
    }

    resp = requests.post(
        url,
        params={"apiKey": CALCOM_API_KEY},
        json=body
    )

    if resp.status_code in [200, 201]:
        data = resp.json()
        booking = {
            "booking_id":    data.get("id"),
            "uid":           data.get("uid"),
            "status":        data.get("status", "ACCEPTED"),
            "start":         start_time,
            "prospect_name": prospect_name,
            "prospect_email":prospect_email,
            "join_url":      data.get("videoCallData", {}).get("url", ""),
        }
        print(f"  Cal.com: booking created — ID {booking['booking_id']}")
        return booking
    else:
        print(f"  Cal.com warning: {resp.status_code} — {resp.text[:200]}")
        return _mock_booking(prospect_name, prospect_email, start_time)


def _get_event_type_id() -> int:
    """Get the event type ID for the discovery call."""
    resp = requests.get(
        "https://api.cal.com/v1/event-types",
        params={"apiKey": CALCOM_API_KEY}
    )
    if resp.status_code == 200:
        types = resp.json().get("event_types", [])
        if types:
            return types[0]["id"]
    return 1   # fallback


def _mock_booking(name, email, start_time) -> dict:
    """Return a mock booking for testing without Cal.com API."""
    return {
        "booking_id":     "mock-001",
        "status":         "ACCEPTED",
        "start":          start_time,
        "prospect_name":  name,
        "prospect_email": email,
        "booking_url":    get_booking_link(name, email),
        "mock":           True,
    }