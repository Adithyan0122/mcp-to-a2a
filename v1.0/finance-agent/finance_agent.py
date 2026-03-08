"""
Finance Agent — v1.0
Runs on port 8003.
Manages monthly budget, approves/rejects order spend.
Uses LLM for mid-range approval decisions.
"""

import logging
import sys
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import (
    DB_CONFIG, MONTHLY_BUDGET, BUDGET_AUTO_APPROVE_PCT,
    BUDGET_ESCALATE_PCT, NOTIFICATION_AGENT_URL
)
from shared import llm
from shared.memory import MemoryClient
from shared.tracing import traced_a2a_call
from shared.circuit_breaker import get_breaker
from shared.health import build_health_response, check_db_connection

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("finance-agent")

load_dotenv()

memory = MemoryClient()
notify_cb = get_breaker("finance->notification-agent", failure_threshold=5, timeout=30)

started_at = time.time()

AGENT_CARD = {
    "name": "Finance Agent", "version": "1.0.0",
    "url": "http://localhost:8003",
    "capabilities": ["approve_spend", "get_budget_status", "reject_spend", "record_spend"],
    "skills": [
        {"name": "approve_spend", "description": "Request approval for a purchase order",
         "input_schema": {"type": "object",
            "properties": {"product": {"type": "string"}, "total_price": {"type": "number"},
            "supplier": {"type": "string"}, "quantity": {"type": "integer"}},
            "required": ["product", "total_price"]}},
        {"name": "get_budget_status", "description": "Get current month budget status"},
        {"name": "record_spend", "description": "Record confirmed spend against budget"},
    ]
}

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS budget (
            id           SERIAL PRIMARY KEY,
            month        TEXT        NOT NULL UNIQUE,
            total_budget NUMERIC(12,2) DEFAULT 50000.00,
            spent        NUMERIC(12,2) DEFAULT 0.00,
            updated_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS budget_transactions (
            id          SERIAL PRIMARY KEY,
            order_id    INTEGER,
            amount      NUMERIC(12,2),
            approved    BOOLEAN,
            reason      TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # Ensure current month budget exists
    current_month = datetime.utcnow().strftime("%Y-%m")
    cur.execute(
        "INSERT INTO budget (month, total_budget) VALUES (%s, %s) ON CONFLICT (month) DO NOTHING",
        (current_month, MONTHLY_BUDGET)
    )
    conn.commit()
    cur.close()
    conn.close()
    log.info("Finance tables initialized")

def get_budget_status() -> dict:
    """Get current month's budget."""
    current_month = datetime.utcnow().strftime("%Y-%m")
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM budget WHERE month = %s", (current_month,))
    row = cur.fetchone()
    if not row:
        # Create budget for current month
        cur.execute(
            "INSERT INTO budget (month, total_budget) VALUES (%s, %s) RETURNING *",
            (current_month, MONTHLY_BUDGET)
        )
        row = cur.fetchone()
        conn.commit()
    cur.close()
    conn.close()
    row = dict(row)
    total = float(row["total_budget"])
    spent = float(row["spent"])
    return {
        "month": row["month"],
        "total_budget": total,
        "spent": spent,
        "remaining": round(total - spent, 2),
        "utilization_pct": round(spent / total * 100, 1) if total > 0 else 0,
    }

def get_recent_transactions(limit: int = 10) -> list:
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM budget_transactions ORDER BY created_at DESC LIMIT %s", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        r["created_at"] = str(r["created_at"])
        r["amount"] = str(r["amount"])
    return rows

def record_transaction(order_id: int, amount: float, approved: bool, reason: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO budget_transactions (order_id, amount, approved, reason) VALUES (%s, %s, %s, %s)",
        (order_id, amount, approved, reason)
    )
    if approved:
        current_month = datetime.utcnow().strftime("%Y-%m")
        cur.execute(
            "UPDATE budget SET spent = spent + %s, updated_at = NOW() WHERE month = %s",
            (amount, current_month)
        )
    conn.commit()
    cur.close()
    conn.close()

# ── Approval Logic ───────────────────────────────────────────────────────────

def approve_spend(product: str, total_price: float, supplier: str = "",
                  quantity: int = 0, unit_price: float = 0,
                  delivery_days: int = 0) -> dict:
    """
    Three-tier approval:
    1. total_price <= remaining * 0.3 → auto-approve
    2. total_price <= remaining * 0.7 → LLM decides
    3. total_price > remaining * 0.7 → escalate to human
    """
    budget = get_budget_status()
    remaining = budget["remaining"]
    spend_pct = (total_price / remaining * 100) if remaining > 0 else 100

    log.info(f"Approval request: {product} ${total_price} "
             f"(remaining: ${remaining}, {spend_pct:.1f}% of remaining)")

    # Tier 1: Auto-approve
    if total_price <= remaining * BUDGET_AUTO_APPROVE_PCT:
        reason = f"Auto-approved: ${total_price} is ≤30% of remaining budget (${remaining})"
        log.info(f"✅ {reason}")
        memory.record_decision("finance-agent", {
            "type": "auto_approve", "product": product,
            "total_price": total_price, "remaining": remaining,
        })
        return {
            "status": "success", "approved": True,
            "reason": reason, "tier": "auto_approve",
            "remaining": remaining, "spend_pct": round(spend_pct, 1),
        }

    # Tier 3: Escalate (check this before LLM to avoid unnecessary API calls)
    if total_price > remaining * BUDGET_ESCALATE_PCT:
        reason = f"Escalated: ${total_price} exceeds 70% of remaining budget (${remaining})"
        log.warning(f"🚨 {reason}")

        # Send escalation email
        try:
            notify_cb.call(traced_a2a_call, NOTIFICATION_AGENT_URL, {
                "task": "send_alert",
                "event_type": "budget_escalation",
                "product": product,
                "details": {
                    "total_price": total_price,
                    "supplier": supplier,
                    "remaining_budget": remaining,
                    "spend_pct": round(spend_pct, 1),
                }
            })
        except Exception as e:
            log.warning(f"Escalation email failed: {e}")

        memory.record_decision("finance-agent", {
            "type": "escalation", "product": product,
            "total_price": total_price, "remaining": remaining,
        })
        return {
            "status": "success", "approved": False,
            "reason": reason, "tier": "escalated",
            "remaining": remaining, "spend_pct": round(spend_pct, 1),
        }

    # Tier 2: LLM decides
    recent_txns = get_recent_transactions(5)
    context = {
        "product": product,
        "total_price": total_price,
        "monthly_budget": budget["total_budget"],
        "spent": budget["spent"],
        "remaining": remaining,
        "spend_pct": spend_pct,
        "supplier": supplier,
        "current_stock": quantity,
        "recent_transactions": recent_txns,
    }
    decision = llm.decide_budget_approval(context)

    approved = decision.get("approved", True)
    reason = decision.get("reasoning", "LLM decision")

    memory.record_decision("finance-agent", {
        "type": "llm_decision", "product": product,
        "total_price": total_price, "remaining": remaining,
        "decision": decision,
    })

    log.info(f"{'✅' if approved else '❌'} LLM decision: {reason[:80]}")
    return {
        "status": "success", "approved": approved,
        "reason": reason, "tier": "llm_decision",
        "remaining": remaining, "spend_pct": round(spend_pct, 1),
        "llm_confidence": decision.get("confidence", 0),
    }

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Finance Agent v1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body = await request.json()
        task = body.get("task")

        if task == "approve_spend":
            result = approve_spend(
                product=body.get("product", ""),
                total_price=float(body.get("total_price", 0)),
                supplier=body.get("supplier", ""),
                quantity=int(body.get("quantity", 0)),
                unit_price=float(body.get("unit_price", 0)),
                delivery_days=int(body.get("delivery_days", 0)),
            )
            return JSONResponse(content=result)

        elif task == "get_budget_status":
            budget = get_budget_status()
            return JSONResponse(content={"status": "success", **budget})

        elif task == "record_spend":
            order_id = body.get("order_id", 0)
            amount = float(body.get("amount", 0))
            record_transaction(order_id, amount, True, "Confirmed order spend")
            return JSONResponse(content={"status": "success", "recorded": amount})

        elif task == "reject_spend":
            reason = body.get("reason", "Rejected")
            order_id = body.get("order_id", 0)
            amount = float(body.get("amount", 0))
            record_transaction(order_id, amount, False, reason)
            return JSONResponse(content={"status": "success", "rejected": True, "reason": reason})

        elif task == "get_transactions":
            limit = int(body.get("limit", 20))
            txns = get_recent_transactions(limit)
            return JSONResponse(content={"status": "success", "transactions": txns})

        else:
            return JSONResponse(status_code=400,
                content={"status": "error", "message": f"Unknown task: {task}"})

    except Exception as e:
        log.error(f"Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    db_ok = check_db_connection(DB_CONFIG)
    budget = get_budget_status() if db_ok else {}
    return JSONResponse(content=build_health_response(
        "Finance Agent", "1.0.0", db_connected=db_ok,
        dependencies={"notification-agent": notify_cb.get_status()},
        extra={"budget_remaining": budget.get("remaining", "unknown")}
    ))

if __name__ == "__main__":
    init_db()
    log.info("Finance Agent v1.0 starting on http://localhost:8003")
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="warning")
