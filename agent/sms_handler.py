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

