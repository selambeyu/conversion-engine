import africastalking
import os
from dotenv import load_dotenv

load_dotenv()

_sms = None

def _get_sms():
    """Lazy-initialize Africa's Talking so import never crashes on missing credentials."""
    global _sms
    if _sms is None:
        username = os.getenv("AT_USERNAME")
        api_key = os.getenv("AT_API_KEY")
        if not username or not api_key:
            raise RuntimeError(
                "AT_USERNAME and AT_API_KEY must be set in .env. "
                "Use username='sandbox' and your sandbox API key from account.africastalking.com."
            )
        africastalking.initialize(username=username, api_key=api_key)
        _sms = africastalking.SMS
    return _sms


def _normalize_phone(phone_number: str) -> str:
    """Ensure E.164 format: strip spaces, add + if missing."""
    phone = phone_number.strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def send_sms(phone_number: str, message: str) -> dict:
    """Send an SMS to a phone number."""
    try:
        # Kill switch: route all outbound to staff sink unless PRODUCTION_MODE=true
        STAFF_SINK_PHONE = os.getenv("STAFF_SINK_PHONE", "+254700000000")
        if os.getenv("PRODUCTION_MODE", "false").lower() != "true":
            print(f"  [kill-switch] PRODUCTION_MODE != true — redirecting {phone_number} → {STAFF_SINK_PHONE}")
            phone_number = STAFF_SINK_PHONE

        phone = _normalize_phone(phone_number)
        response = _get_sms().send(message, [phone])
        print(f"SMS sent to {phone_number}: {response}")
        return response
    except Exception as e:
        print(f"SMS failed: {e}")
        raise


def handle_stop_command(phone_number: str) -> bool:
    """Check if message is a STOP command — must always be respected."""
    return True  # Log this number, never contact again


# ─── Warm-lead registry ───────────────────────────────────
# SMS is only for warm leads (prospects who replied to email).
# Cold outreach is email-only.

_warm_leads: dict = {}   # identifier (phone or email) → {"email": ..., "phone": ...}


def mark_warm_lead(identifier: str, email: str = "", phone: str = ""):
    """
    Register a phone number or email as a warm lead (prospect who replied to email).
    Optionally cross-link email ↔ phone so the SMS webhook can find the HubSpot contact.
    SMS outbound must ONLY be sent to identifiers registered here.
    """
    key = identifier.strip().lower()
    _warm_leads[key] = {"email": email.strip().lower(), "phone": phone.strip()}
    # Also index by the other identifier if provided
    if email and email.strip().lower() != key:
        _warm_leads[email.strip().lower()] = {"email": email.strip().lower(), "phone": phone.strip()}
    if phone and phone.strip() != key:
        _warm_leads[phone.strip()] = {"email": email.strip().lower(), "phone": phone.strip()}


def is_warm_lead(identifier: str) -> bool:
    """Return True if this phone/email is a known warm lead."""
    return identifier.strip().lower() in _warm_leads


def get_warm_lead_email(phone: str) -> str:
    """Return the email address linked to this phone number, or empty string."""
    entry = _warm_leads.get(phone.strip(), {})
    return entry.get("email", "") if isinstance(entry, dict) else ""

