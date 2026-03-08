"""
Notification Agent — v0.9 Full Pipeline
Runs on port 8002. Sends HTML emails via Gmail SMTP.
"""

import logging
import sys
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("notification-agent")

load_dotenv()
SMTP_HOST       = os.getenv("SMTP_HOST",       "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT",   587))
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD")
ALERT_RECIPIENT = os.getenv("ALERT_RECIPIENT")

AGENT_CARD = {
    "name": "Notification Agent", "version": "0.9.0",
    "url": "http://localhost:8002", "capabilities": ["send_alert"],
    "skills": [{"name": "send_alert", "input_schema": {"type": "object",
        "properties": {"event_type": {"type": "string"}, "product": {"type": "string"},
        "details": {"type": "object"}}, "required": ["event_type", "product"]}}]
}

def send_email(subject: str, body: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = ALERT_RECIPIENT
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo(); server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, ALERT_RECIPIENT, msg.as_string())
        log.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        log.error(f"Email failed: {e}")
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
            f"<p><b>Order ID:</b> {details.get('order_id')}</p>")
    elif event_type == "price_updated":
        return (f"📈 Price Updated: {product}",
            f"<h2>📈 Price Update</h2><p><b>Product:</b> {product}</p>"
            f"<p><b>Old Price:</b> ${details.get('old_price')}</p>"
            f"<p><b>New Price:</b> ${details.get('new_price')}</p>"
            f"<p><b>Change:</b> {details.get('pct_change'):+.1f}%</p>")
    else:
        return (f"📢 Pipeline Event: {product}",
            f"<h2>📢 {event_type}</h2><p>{product}</p><p>{details}</p>")

app = FastAPI(title="Notification Agent")

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
            return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid request"})
        subject, html = build_email(event_type, product, details)
        success = send_email(subject, html)
        return JSONResponse(content={"status": "success" if success else "error",
            "message": f"Alert {'sent' if success else 'failed'}: {event_type} — {product}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok", "recipient": ALERT_RECIPIENT})

if __name__ == "__main__":
    if not SMTP_USER or not SMTP_PASSWORD:
        log.error("SMTP credentials missing"); sys.exit(1)
    log.info(f"Notification Agent starting on http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="warning")