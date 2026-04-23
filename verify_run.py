"""
verify_setup.py
───────────────
Tests every tool connection before you write any agent code.
Run this until you see 7/7 passed.

Usage: python verify_setup.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

results = []

def check(name, fn):
    """Run one check — print OK or FAILED with the reason."""
    try:
        fn()
        results.append((name, True, ""))
        print(f"  ✓  {name}")
    except Exception as e:
        results.append((name, False, str(e)))
        print(f"  ✗  {name}")
        print(f"     Reason: {e}")


# ── Check 1: .env completeness ───────────────────────────
def check_env():
    required_keys = [
        "OPENROUTER_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "HUBSPOT_ACCESS_TOKEN",
        "AT_API_KEY",
        "RESEND_API_KEY",
        "CALCOM_API_KEY",
        "CALCOM_BOOKING_URL",
    ]
    placeholders = ["your_", "xxxx", "yourname"]
    missing = []

    for key in required_keys:
        value = os.getenv(key, "")
        if not value:
            missing.append(f"{key} is empty")
        elif any(p in value for p in placeholders):
            missing.append(f"{key} still has placeholder value")

    if missing:
        raise ValueError("\n     ".join(missing))
    print(f"     All {len(required_keys)} required keys found")


# ── Check 2: OpenRouter (AI model) ───────────────────────
def check_openrouter():
    from openai import OpenAI
    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )
    response = client.chat.completions.create(
        model=os.getenv("DEV_MODEL", "deepseek/deepseek-chat"),
        messages=[{"role": "user", "content": "Reply with just the word CONNECTED"}],
        max_tokens=10,
        temperature=0
    )
    reply = response.choices[0].message.content.strip()
    cost  = (response.usage.prompt_tokens * 0.00000014 +
             response.usage.completion_tokens * 0.00000028)
    print(f"     Model replied: '{reply}'")
    print(f"     Cost of this test: ${cost:.6f}")


# ── Check 3: Langfuse (logging) ───────────────────────────
def check_langfuse():
    from langfuse import Langfuse
    lf = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    )
    trace = lf.trace(
        name="verify_setup_test",
        input={"check": "connection_test"},
        output={"status": "ok"}
    )
    assert trace.id, "No trace ID returned"
    print(f"     Trace ID: {trace.id[:20]}...")
    print(f"     Check Langfuse dashboard to confirm it appears")


# ── Check 4: HubSpot (CRM) ────────────────────────────────
def check_hubspot():
    from hubspot import HubSpot
    client = HubSpot(access_token=os.getenv("HUBSPOT_ACCESS_TOKEN"))
    # Try fetching contacts — works only if token is valid
    page = client.crm.contacts.basic_api.get_page(limit=1)
    count = len(page.results)
    print(f"     HubSpot connected — {count} contact(s) found in sandbox")


# ── Check 5: Africa's Talking (SMS) ──────────────────────
def check_africastalking():
    import africastalking
    africastalking.initialize(
        username=os.getenv("AT_USERNAME", "sandbox"),
        api_key=os.getenv("AT_API_KEY")
    )
    sms = africastalking.SMS
    assert sms is not None
    # Note: we don't actually send an SMS here to avoid costs
    # We just verify the SDK initializes without error
    print(f"     SDK initialized with username: {os.getenv('AT_USERNAME')}")
    print(f"     Sandbox mode: no real SMS sent during this check")


# ── Check 6: Resend (email) ───────────────────────────────
def check_resend():
    import requests
    resp = requests.get(
        "https://api.resend.com/domains",
        headers={
            "Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}",
            "Content-Type": "application/json"
        }
    )
    if resp.status_code == 401:
        raise ValueError("API key rejected — double-check your RESEND_API_KEY")
    if resp.status_code != 200:
        raise ValueError(f"HTTP {resp.status_code}: {resp.text[:100]}")
    print(f"     Resend API key accepted")
    print(f"     Sending from: {os.getenv('FROM_EMAIL')}")


# ── Check 7: Cal.com (calendar) ───────────────────────────
def check_calcom():
    import requests
    api_key     = os.getenv("CALCOM_API_KEY", "")
    booking_url = os.getenv("CALCOM_BOOKING_URL", "")

    if not booking_url or "yourname" in booking_url:
        raise ValueError(
            "CALCOM_BOOKING_URL still has 'yourname' — "
            "replace with your actual Cal.com username"
        )

    resp = requests.get(
        "https://api.cal.com/v1/me",
        params={"apiKey": api_key}
    )
    if resp.status_code == 401:
        raise ValueError("Cal.com API key rejected")
    if resp.status_code != 200:
        raise ValueError(f"HTTP {resp.status_code}: {resp.text[:100]}")

    user = resp.json().get("user", {})
    print(f"     Cal.com user: {user.get('username', 'unknown')}")
    print(f"     Booking URL: {booking_url}")


# ── Check 8: tau2-bench ───────────────────────────────────
def check_tau2bench():
    tau2_path = os.getenv("TAU2_BENCH_PATH", "../tau2-bench")
    from pathlib import Path
    p = Path(tau2_path)
    if not p.exists():
        raise ValueError(
            f"tau2-bench not found at {tau2_path}\n"
            "     Run: git clone https://github.com/sierra-research/tau2-bench ../tau2-bench"
        )
    # Check the tasks folder exists
    tasks = list(p.glob("**/*.json"))
    print(f"     Found tau2-bench at: {p.resolve()}")
    print(f"     JSON files found: {len(tasks)}")


# ── Run all checks ────────────────────────────────────────
print()
print("=" * 52)
print("  CONVERSION ENGINE — SETUP VERIFICATION")
print("=" * 52)
print()

check("1. .env file",              check_env)
check("2. OpenRouter (AI model)",  check_openrouter)
check("3. Langfuse (logging)",     check_langfuse)
check("4. HubSpot (CRM)",          check_hubspot)
check("5. Africa's Talking (SMS)", check_africastalking)
check("6. Resend (email)",         check_resend)
check("7. Cal.com (calendar)",     check_calcom)
check("8. tau2-bench (benchmark)", check_tau2bench)

# ── Print summary ─────────────────────────────────────────
passed = sum(1 for _, ok, _ in results if ok)
failed = len(results) - passed

print()
print("=" * 52)
print(f"  Result: {passed}/{len(results)} checks passed")
print()

if failed == 0:
    print("  All tools connected.")
    print("  You are ready to write Act I code.")
    print()
    print("  Next command:")
    print("  python eval/benchmark_harness.py --trials 1 --tasks 3")
else:
    print(f"  {failed} check(s) need fixing:")
    print()
    for name, ok, msg in results:
        if not ok:
            print(f"  ✗ {name}")
            if msg:
                for line in msg.split("\n"):
                    print(f"    {line}")
    print()
    print("  Fix the above, then run this script again.")

print("=" * 52)
print()