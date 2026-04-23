from fastapi import FastAPI, Request
from agent.sms_handler import send_sms

app = FastAPI()

# Simple in-memory store for now (replace with DB later)
conversations = {}

@app.post("/webhook/sms")
async def receive_sms(request: Request):
    """Africa's Talking calls this URL when someone replies to your SMS."""
    form = await request.form()
    
    phone = form.get("from")
    message = form.get("text", "").strip()
    
    print(f"Received SMS from {phone}: {message}")
    
    # Handle STOP command — non-negotiable
    if message.upper() in ["STOP", "UNSUBSCRIBE", "UNSUB", "QUIT", "END"]:
        conversations[phone] = {"opted_out": True}
        send_sms(phone, "You have been unsubscribed. Reply START to re-subscribe.")
        return {"status": "opted_out"}
    
    # Store the conversation turn
    if phone not in conversations:
        conversations[phone] = {"turns": [], "opted_out": False}
    
    conversations[phone]["turns"].append({
        "role": "user",
        "content": message
    })
    
    # TODO: Pass to AI agent (we build this in Act II)
    reply = "Thanks for your message. Our team will be in touch shortly."
    send_sms(phone, reply)
    
    return {"status": "ok"}

@app.get("/health")
def health():
    return {"status": "running"}


@app.get("/send-test")
def send_test(to: str, message: str = "Hello from Conversion Engine!"):
    """
    Quick test endpoint — send an SMS to any number.
    Usage: GET /send-test?to=%2B251XXXXXXXXX&message=Hello
    """
    result = send_sms(to, message)
    return {"status": "sent", "result": result}