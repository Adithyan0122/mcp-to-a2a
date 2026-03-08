"""
Notification Agent — v1.0
Runs on port 8002. Sends HTML emails via Gmail SMTP.
Supports budget_escalation event type and async via Celery.
"""

import logging
import sys
import os
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_RECIPIENT
from shared.health import build_health_response

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("notification-agent")

load_dotenv()
# Override from env if set
_smtp_user = os.getenv("SMTP_USER", SMTP_USER)
_smtp_pass = os.getenv("SMTP_PASSWORD", SMTP_PASSWORD)
_recipient = os.getenv("ALERT_RECIPIENT", ALERT_RECIPIENT)

started_at = time.time()
emails_sent = 0
emails_failed = 0

AGENT_CARD = {
    "name": "Notification Agent", "version": "1.0.0",
    "url": "http://localhost:8002",
    "capabilities": ["send_alert"],
    "skills": [{
        "name": "send_alert",
        "input_schema": {"type": "object",
            "properties": {"event_type": {"type": "string"}, "product": {"type": "string"},
            "details": {"type": "object"}},
            "required": ["event_type", "product"]}
    }]
}

def send_email(subject: str, body: str) -> bool:
    global emails_sent, emails_failed
    if not _smtp_user or not _smtp_pass:
        log.warning(f"SMTP not configured — would have sent: {subject}")
        emails_sent += 1
        return True
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = _smtp_user
        msg["To"]      = _recipient
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(_smtp_user, _smtp_pass)
            server.sendmail(_smtp_user, _recipient, msg.as_string())
        log.info(f"Email sent: {subject}")
        emails_sent += 1
        return True
    except Exception as e:
        log.error(f"Email failed: {e}")
        emails_failed += 1
        return False

def build_email(event_type: str, product: str, details: dict) -> tuple[str, str]:
    if event_type == "low_stock":
        return (f"⚠️ Low Stock: {product}",
            f"<h2>⚠️ Low Stock Alert</h2><p><b>Product:</b> {product}</p>"
            f"<p><b>Stock:</b> {details.get('quantity')} units (threshold: {details.get('threshold')})</p>"
            f"<p>Supplier bidding has been triggered automatically.</p>")
    elif event_type == "order_placed":
        return (f"✅ Order Placed: {product}",
            f"<h2>✅ Restock Order Confirmed</h2><p><b>Product:</b> {product}</p>"
            f"<p><b>Supplier:</b> {details.get('supplier')}</p>"
            f"<p><b>Quantity:</b> {details.get('quantity')} units @ ${details.get('unit_price')}</p>"
            f"<p><b>Total:</b> ${details.get('total_price')}</p>"
            f"<p><b>Delivery:</b> {details.get('delivery_days')} days</p>"
            f"<p><b>Order ID:</b> {details.get('order_id')}</p>"
            f"<p><b>AI Reasoning:</b> {details.get('llm_reasoning', 'N/A')}</p>")
    elif event_type == "budget_escalation":
        return (f"🚨 Budget Escalation: {product}",
            f"<h2>🚨 Budget Escalation Required</h2><p><b>Product:</b> {product}</p>"
            f"<p><b>Order Total:</b> ${details.get('total_price')}</p>"
            f"<p><b>Supplier:</b> {details.get('supplier')}</p>"
            f"<p><b>Remaining Budget:</b> ${details.get('remaining_budget')}</p>"
            f"<p><b>Spend % of Remaining:</b> {details.get('spend_pct', 0):.1f}%</p>"
            f"<p><b>Reason:</b> Order exceeds budget threshold. Manual approval required.</p>"
            f"<p>Please respond to approve or reject this order.</p>")
    elif event_type == "price_updated":
        return (f"📈 Price Updated: {product}",
            f"<h2>📈 Price Update</h2><p><b>Product:</b> {product}</p>"
            f"<p><b>Old Price:</b> ${details.get('old_price')}</p>"
            f"<p><b>New Price:</b> ${details.get('new_price')}</p>"
            f"<p><b>Change:</b> {details.get('pct_change', 0):+.1f}%</p>")
    else:
        return (f"📢 Pipeline Event: {product}",
            f"<h2>📢 {event_type}</h2><p>{product}</p><p>{details}</p>")

app = FastAPI(title="Notification Agent v1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body       = await request.json()
        task       = body.get("task")
        product    = body.get("product")
        event_type = body.get("event_type")
        details    = body.get("details", {})
        if task != "send_alert" or not product or not event_type:
            return JSONResponse(status_code=400,
                content={"status": "error", "message": "Invalid request"})
        subject, html = build_email(event_type, product, details)
        success = send_email(subject, html)
        return JSONResponse(content={
            "status": "success" if success else "error",
            "message": f"Alert {'sent' if success else 'failed'}: {event_type} — {product}"
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    smtp_ok = bool(_smtp_user and _smtp_pass)
    return JSONResponse(content=build_health_response(
        "Notification Agent", "1.0.0", db_connected=True,
        extra={
            "smtp_configured": smtp_ok,
            "recipient": _recipient,
            "emails_sent": emails_sent,
            "emails_failed": emails_failed,
        }
    ))

if __name__ == "__main__":
    if not _smtp_user or not _smtp_pass:
        log.warning("SMTP credentials missing — emails will be logged only")
    log.info("Notification Agent v1.0 starting on http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="warning")
