"""
Notification Agent — v0.6 MCP + A2A
Runs on port 8002.
Sends email alerts via Gmail SMTP.
Identical to v0.5 — just connected to pipeline_db.
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

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("notification-agent")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

SMTP_HOST       = os.getenv("SMTP_HOST",       "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT",   587))
SMTP_USER       = os.getenv("SMTP_USER")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD")
ALERT_RECIPIENT = os.getenv("ALERT_RECIPIENT")

# ── Agent Card ────────────────────────────────────────────────────────────────

AGENT_CARD = {
    "name":        "Notification Agent",
    "description": "Sends email alerts for inventory and order events",
    "version":     "0.6.0",
    "url":         "http://localhost:8002",
    "capabilities": ["send_alert"],
    "skills": [
        {
            "name":        "send_alert",
            "description": "Send an email alert about an inventory or order event",
            "input_schema": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type":        "string",
                        "enum":        ["low_stock", "order_placed", "restock_complete"],
                        "description": "Type of event triggering the alert"
                    },
                    "product": {
                        "type":        "string",
                        "description": "Product name related to the event"
                    },
                    "details": {
                        "type":        "object",
                        "description": "Additional event details"
                    }
                },
                "required": ["event_type", "product"]
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "status":  {"type": "string"},
                    "message": {"type": "string"}
                }
            }
        }
    ],
    "authentication": {
        "type":        "none",
        "description": "No auth required for internal agent communication"
    },
    "contact": "pipeline-system"
}

# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(subject: str, body: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = ALERT_RECIPIENT
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, ALERT_RECIPIENT, msg.as_string())

        log.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        log.error(f"Failed to send email: {e}")
        return False

def build_email(event_type: str, product: str, details: dict) -> tuple[str, str]:
    if event_type == "low_stock":
        quantity  = details.get("quantity",  "unknown")
        threshold = details.get("threshold", "unknown")
        subject   = f"⚠️ Low Stock Alert: {product}"
        body      = f"""
        <h2>⚠️ Low Stock Alert</h2>
        <p><strong>Product:</strong> {product}</p>
        <p><strong>Current Stock:</strong> {quantity} units</p>
        <p><strong>Threshold:</strong> {threshold} units</p>
        <p>The MCP Inventory Server detected low stock and triggered a restock via A2A.</p>
        """
    elif event_type == "order_placed":
        order_id = details.get("order_id", "unknown")
        quantity = details.get("quantity", "unknown")
        subject  = f"✅ Restock Order Placed: {product}"
        body     = f"""
        <h2>✅ Restock Order Placed</h2>
        <p><strong>Product:</strong> {product}</p>
        <p><strong>Order ID:</strong> {order_id}</p>
        <p><strong>Quantity Ordered:</strong> {quantity} units</p>
        <p>The Order Agent has successfully placed a restock order.</p>
        """
    else:
        subject = f"📢 Pipeline Event: {product}"
        body    = f"<h2>📢 Event: {event_type}</h2><p>{product}</p><p>{details}</p>"

    return subject, body

# ── FastAPI App ───────────────────────────────────────────────────────────────

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

        log.info(f"A2A request: task={task} event={event_type} product={product}")

        if task != "send_alert":
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Unknown task: {task}"})
        if not product or not event_type:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Missing product or event_type"})

        subject, html_body = build_email(event_type, product, details)
        success = send_email(subject, html_body)

        if success:
            return JSONResponse(content={"status": "success", "message": f"Alert sent: {event_type} — {product}"})
        else:
            return JSONResponse(status_code=500, content={"status": "error", "message": "Failed to send email"})

    except Exception as e:
        log.error(f"Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok", "recipient": ALERT_RECIPIENT})

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not SMTP_USER or not SMTP_PASSWORD:
        log.error("SMTP_USER and SMTP_PASSWORD must be set in .env")
        sys.exit(1)
    log.info(f"Notification Agent starting on http://localhost:8002")
    log.info(f"Alerts will be sent to: {ALERT_RECIPIENT}")
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="warning")