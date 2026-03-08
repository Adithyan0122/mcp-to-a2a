"""
Notification Agent — v0.5 Agent Cards
Runs on port 8002.
Sends email alerts via Gmail SMTP when triggered by other agents.
Exposes a proper A2A Agent Card with full skill schema.
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
    "version":     "0.5.0",
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
                        "description": "Additional event details (quantity, order_id, etc.)"
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
    "contact": "supply-chain-system"
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

        log.info(f"Email sent to {ALERT_RECIPIENT}: {subject}")
        return True

    except Exception as e:
        log.error(f"Failed to send email: {e}")
        return False

def build_email(event_type: str, product: str, details: dict) -> tuple[str, str]:
    """Build subject + HTML body based on event type."""

    if event_type == "low_stock":
        quantity = details.get("quantity", "unknown")
        threshold = details.get("threshold", "unknown")
        subject = f"⚠️ Low Stock Alert: {product}"
        body = f"""
        <h2>⚠️ Low Stock Alert</h2>
        <p><strong>Product:</strong> {product}</p>
        <p><strong>Current Stock:</strong> {quantity} units</p>
        <p><strong>Threshold:</strong> {threshold} units</p>
        <p>The Inventory Agent has detected low stock and is placing a restock order.</p>
        """

    elif event_type == "order_placed":
        order_id = details.get("order_id", "unknown")
        quantity = details.get("quantity", "unknown")
        subject = f"✅ Restock Order Placed: {product}"
        body = f"""
        <h2>✅ Restock Order Placed</h2>
        <p><strong>Product:</strong> {product}</p>
        <p><strong>Order ID:</strong> {order_id}</p>
        <p><strong>Quantity Ordered:</strong> {quantity} units</p>
        <p>The Order Agent has successfully placed a restock order.</p>
        """

    elif event_type == "restock_complete":
        new_quantity = details.get("new_quantity", "unknown")
        subject = f"📦 Restock Complete: {product}"
        body = f"""
        <h2>📦 Restock Complete</h2>
        <p><strong>Product:</strong> {product}</p>
        <p><strong>New Stock Level:</strong> {new_quantity} units</p>
        <p>Inventory has been updated successfully.</p>
        """

    else:
        subject = f"📢 Inventory Event: {product}"
        body = f"""
        <h2>📢 Inventory Event</h2>
        <p><strong>Product:</strong> {product}</p>
        <p><strong>Event:</strong> {event_type}</p>
        <p><strong>Details:</strong> {details}</p>
        """

    return subject, body

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Notification Agent")

@app.get("/.well-known/agent.json")
async def agent_card():
    """A2A Agent Card — full skill schema with input/output definitions."""
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body       = await request.json()
        task       = body.get("task")
        product    = body.get("product")
        event_type = body.get("event_type")
        details    = body.get("details", {})

        log.info(f"Received A2A request: task={task} product={product} event={event_type}")

        if task != "send_alert":
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"Unknown task: {task}"}
            )

        if not product or not event_type:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Missing product or event_type"}
            )

        subject, html_body = build_email(event_type, product, details)
        success = send_email(subject, html_body)

        if success:
            return JSONResponse(content={
                "status":  "success",
                "message": f"Alert sent for {event_type} — {product}"
            })
        else:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Failed to send email"}
            )

    except Exception as e:
        log.error(f"Error handling A2A request: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

@app.get("/health")
async def health():
    return JSONResponse(content={
        "status": "ok",
        "smtp":   SMTP_HOST,
        "recipient": ALERT_RECIPIENT
    })

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not SMTP_USER or not SMTP_PASSWORD:
        log.error("SMTP_USER and SMTP_PASSWORD must be set in .env")
        sys.exit(1)
    log.info(f"Notification Agent starting on http://localhost:8002")
    log.info(f"Alerts will be sent to: {ALERT_RECIPIENT}")
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="warning")