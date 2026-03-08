"""
Inventory Agent — v1.0
Runs on port 8000.
LLM-powered supplier selection + restock quantity decisions.
Integrated with Finance Agent for budget approval.
Memory-backed context for LLM decisions.
Circuit breakers + tracing on all inter-agent calls.
"""

import logging
import sys
import os
import time
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
import uvicorn
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import (
    DB_CONFIG, RESTOCK_THRESHOLD, DEADLINE_DAYS,
    ORDER_AGENT_URL, NOTIFICATION_AGENT_URL, FINANCE_AGENT_URL,
)
from shared import llm
from shared.memory import MemoryClient
from shared.tracing import traced_a2a_call
from shared.circuit_breaker import get_breaker, CircuitOpenError
from shared.health import build_health_response, check_db_connection

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("inventory-agent")

load_dotenv()
SUPPLIER_URLS = [
    os.getenv("SUPPLIER_A_URL", "http://localhost:8011"),
    os.getenv("SUPPLIER_B_URL", "http://localhost:8012"),
    os.getenv("SUPPLIER_C_URL", "http://localhost:8013"),
]

memory = MemoryClient()
order_cb     = get_breaker("inventory->order-agent", failure_threshold=3, timeout=60)
notify_cb    = get_breaker("inventory->notification-agent", failure_threshold=5, timeout=30)
finance_cb   = get_breaker("inventory->finance-agent", failure_threshold=3, timeout=60)
supplier_cbs = {
    url: get_breaker(f"inventory->supplier-{url.split(':')[-1]}", failure_threshold=3, timeout=60)
    for url in SUPPLIER_URLS
}

started_at = time.time()

AGENT_CARD = {
    "name": "Inventory Agent", "version": "1.0.0",
    "url": "http://localhost:8000",
    "capabilities": ["update_price", "get_inventory", "check_and_restock"],
    "skills": [
        {"name": "update_price", "input_schema": {"type": "object",
            "properties": {"product": {"type": "string"}, "new_price": {"type": "number"},
            "old_price": {"type": "number"}, "pct_change": {"type": "number"}},
            "required": ["product", "new_price"]}},
        {"name": "get_inventory", "input_schema": {"type": "object", "properties": {}}},
        {"name": "check_and_restock", "input_schema": {"type": "object", "properties": {}}}
    ]
}

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id         SERIAL PRIMARY KEY,
            product    TEXT           NOT NULL UNIQUE,
            quantity   INTEGER        DEFAULT 0,
            price      NUMERIC(10,2)  DEFAULT 0.00,
            updated_at TIMESTAMPTZ    DEFAULT NOW()
        )
    """)
    cur.execute("SELECT COUNT(*) FROM inventory")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO inventory (product, quantity, price) VALUES (%s, %s, %s)", [
            ("Laptop",   10, 999.99), ("Mouse",    50,  29.99),
            ("Keyboard", 30,  79.99), ("Monitor",   8, 349.99), ("Webcam",   20,  89.99),
        ])
        log.info("Inventory seeded with 5 products")
    conn.commit()
    cur.close()
    conn.close()
    log.info("Inventory initialized")

def get_all_products() -> list:
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM inventory ORDER BY quantity ASC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def get_low_stock() -> list:
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM inventory WHERE quantity < %s ORDER BY quantity ASC", (RESTOCK_THRESHOLD,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def do_update_price(product: str, new_price: float) -> dict | None:
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("UPDATE inventory SET price=%s, updated_at=NOW() WHERE LOWER(product)=LOWER(%s) RETURNING *",
        (new_price, product))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return dict(row) if row else None

# ── Bidding ───────────────────────────────────────────────────────────────────

_card_cache = {}

def discover(url: str) -> dict | None:
    if url in _card_cache:
        return _card_cache[url]
    try:
        import httpx
        card = httpx.get(f"{url}/.well-known/agent.json", timeout=5).json()
        _card_cache[url] = card
        return card
    except:
        return None

def bid_request(url: str, product: str, quantity: int, base_price: float) -> dict:
    """Send bid request through circuit breaker + tracing."""
    start = time.time()
    cb = supplier_cbs.get(url)
    try:
        discover(url)
        if cb:
            result, latency = cb.call(
                traced_a2a_call, url,
                {"task": "submit_bid", "product": product,
                 "quantity": quantity, "base_price": base_price,
                 "deadline_days": DEADLINE_DAYS},
                timeout=5
            )
        else:
            result, latency = traced_a2a_call(
                url,
                {"task": "submit_bid", "product": product,
                 "quantity": quantity, "base_price": base_price,
                 "deadline_days": DEADLINE_DAYS},
                timeout=5
            )
        result["latency_ms"] = latency
        return result
    except CircuitOpenError as e:
        return {"status": "error", "supplier": url, "message": str(e),
            "circuit_breaker": "open", "latency_ms": round((time.time() - start) * 1000, 2)}
    except Exception as e:
        return {"status": "error", "supplier": url, "message": str(e),
            "latency_ms": round((time.time() - start) * 1000, 2)}

def run_bidding(product: str, quantity: int, base_price: float) -> tuple[dict | None, list]:
    """Run parallel supplier bidding with LLM-powered winner selection."""
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(bid_request, url, product, quantity, base_price): url for url in SUPPLIER_URLS}
        bids = [f.result() for f in as_completed(futures)]

    accepted = [b for b in bids if b.get("status") == "accepted"]
    if not accepted:
        return None, bids

    # Get supplier history from memory for LLM context
    supplier_history = {}
    for bid in accepted:
        supplier = bid.get("supplier", "")
        history = memory.get_supplier_history(supplier, product)
        supplier_history[supplier] = history

    # Get budget info from Finance Agent
    budget_remaining = "unknown"
    try:
        budget_result, _ = finance_cb.call(
            traced_a2a_call, FINANCE_AGENT_URL,
            {"task": "get_budget_status"}
        )
        if budget_result.get("status") == "success":
            budget_remaining = budget_result.get("remaining", "unknown")
    except Exception as e:
        log.warning(f"Could not get budget status: {e}")

    # LLM decides the best supplier
    context = {
        "product": product,
        "current_stock": quantity,
        "threshold": RESTOCK_THRESHOLD,
        "budget_remaining": budget_remaining,
        "bids": accepted,
        "supplier_history": supplier_history,
    }
    decision = llm.decide_supplier(context)

    # Record LLM decision
    memory.record_decision("inventory-agent", {
        "type": "supplier_selection",
        "product": product,
        "decision": decision,
        "bids_received": len(accepted),
    })

    winner_name = decision.get("winner")
    winner = next((b for b in accepted if b.get("supplier") == winner_name), None)

    if not winner:
        # Fallback: if LLM picked an invalid supplier, use lowest score
        winner = min(accepted, key=lambda b: b.get("score", 999))
        log.warning(f"LLM picked invalid supplier '{winner_name}', falling back to {winner.get('supplier')}")

    winner["llm_reasoning"] = decision.get("reasoning", "")
    winner["llm_confidence"] = decision.get("confidence", 0)

    log.info(f"Winner for {product}: {winner['supplier']} "
             f"score={winner.get('score')} ${winner.get('unit_price')} "
             f"(LLM confidence: {decision.get('confidence', 'N/A')})")

    return winner, bids

def get_restock_quantity(product: str, current_stock: int, price: float) -> int:
    """LLM-decided restock quantity."""
    price_history = memory.get_price_history(product, days=14)

    try:
        budget_result, _ = finance_cb.call(
            traced_a2a_call, FINANCE_AGENT_URL,
            {"task": "get_budget_status"}
        )
        budget_remaining = budget_result.get("remaining", "unknown")
    except:
        budget_remaining = "unknown"

    context = {
        "product": product,
        "current_stock": current_stock,
        "threshold": RESTOCK_THRESHOLD,
        "unit_price": price,
        "budget_remaining": budget_remaining,
        "delivery_days": DEADLINE_DAYS,
        "price_history": price_history[:10],
    }
    decision = llm.decide_restock_quantity(context)

    memory.record_decision("inventory-agent", {
        "type": "restock_quantity",
        "product": product,
        "decision": decision,
    })

    qty = decision.get("quantity", 20)
    log.info(f"Restock qty for {product}: {qty} (reasoning: {decision.get('reasoning', '')[:60]})")
    return qty

def notify_low_stock(product: str, quantity: int):
    try:
        notify_cb.call(traced_a2a_call, NOTIFICATION_AGENT_URL,
            {"task": "send_alert", "event_type": "low_stock", "product": product,
             "details": {"quantity": quantity, "threshold": RESTOCK_THRESHOLD}})
    except Exception as e:
        log.warning(f"Low stock notify failed: {e}")

def request_finance_approval(winner: dict, product: str, quantity: int) -> dict:
    """Request Finance Agent approval before confirming order."""
    try:
        result, latency = finance_cb.call(
            traced_a2a_call, FINANCE_AGENT_URL,
            {"task": "approve_spend", "product": product, "quantity": quantity,
             "supplier": winner.get("supplier"), "unit_price": winner.get("unit_price"),
             "total_price": winner.get("total_price"), "delivery_days": winner.get("delivery_days")}
        )
        result["latency_ms"] = latency
        return result
    except Exception as e:
        log.warning(f"Finance approval failed: {e}")
        # If finance agent is down, auto-approve (degrade gracefully)
        return {"status": "success", "approved": True, "reason": "Finance agent unavailable — auto-approved"}

def confirm_order(winner: dict, product: str, quantity: int) -> dict:
    try:
        result, latency = order_cb.call(
            traced_a2a_call, ORDER_AGENT_URL,
            {"task": "confirm_order", "product": product, "quantity": quantity,
             "supplier": winner["supplier"], "unit_price": winner["unit_price"],
             "total_price": winner["total_price"], "delivery_days": winner["delivery_days"],
             "score": winner.get("score"), "llm_reasoning": winner.get("llm_reasoning", "")}
        )
        result["latency_ms"] = latency
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

def check_and_restock() -> dict:
    """Full restock pipeline: detect low stock → bid → finance approval → order."""
    low_stock = get_low_stock()
    if not low_stock:
        return {"status": "ok", "message": "All products above threshold", "restocked": []}

    restocked = []
    for p in low_stock:
        product = p["product"]
        current_qty = p["quantity"]
        price = float(p["price"])

        log.info(f"Low stock: {product} qty={current_qty} — running bidding")
        notify_low_stock(product, current_qty)

        # LLM decides restock quantity
        restock_qty = get_restock_quantity(product, current_qty, price)

        # Run parallel bidding with LLM winner selection
        winner, all_bids = run_bidding(product, restock_qty, price)
        if not winner:
            log.warning(f"No accepted bids for {product}")
            continue

        # Finance Agent approval
        finance_result = request_finance_approval(winner, product, restock_qty)
        if not finance_result.get("approved", False):
            log.warning(f"Finance rejected order for {product}: {finance_result.get('reason')}")
            memory.record_decision("inventory-agent", {
                "type": "finance_rejection",
                "product": product,
                "reason": finance_result.get("reason"),
                "total_price": winner.get("total_price"),
            })
            continue

        # Confirm order
        result = confirm_order(winner, product, restock_qty)
        if result.get("status") == "success":
            # Record supplier performance in memory
            memory.record_supplier_performance(
                supplier=winner["supplier"],
                product=product,
                promised_days=winner.get("delivery_days", 0),
                actual_days=winner.get("delivery_days", 0),  # Will be updated when delivery arrives
                unit_price=winner.get("unit_price", 0),
                quality_score=0.8,
                order_id=result.get("order_id"),
            )
            restocked.append({
                "product": product,
                "supplier": winner["supplier"],
                "quantity": restock_qty,
                "order_id": result.get("order_id"),
                "llm_reasoning": winner.get("llm_reasoning", ""),
                "finance_approved": True,
            })

    return {"status": "success", "restocked": restocked, "low_stock_count": len(low_stock)}

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Inventory Agent v1.0")

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

        if task == "update_price":
            product   = body.get("product")
            new_price = body.get("new_price")
            old_price = body.get("old_price", "?")
            pct       = body.get("pct_change", 0)
            if not product or new_price is None:
                return JSONResponse(status_code=400, content={"status": "error", "message": "Missing product or new_price"})
            row = do_update_price(product, new_price)
            if not row:
                return JSONResponse(status_code=404, content={"status": "error", "message": f"Product '{product}' not found"})
            log.info(f"Price updated: {product} ${old_price} → ${new_price} ({pct:+.1f}%)")
            return JSONResponse(content={"status": "success", "product": product, "price": float(row["price"])})

        elif task == "get_inventory":
            products = get_all_products()
            return JSONResponse(content={"status": "success",
                "products": [{**p, "price": str(p["price"]), "updated_at": str(p["updated_at"])} for p in products]})

        elif task == "check_and_restock":
            result = check_and_restock()
            return JSONResponse(content=result)

        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Unknown task: {task}"})

    except Exception as e:
        log.error(f"Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    db_ok = check_db_connection(DB_CONFIG)
    deps = {
        "order-agent": order_cb.get_status(),
        "notification-agent": notify_cb.get_status(),
        "finance-agent": finance_cb.get_status(),
    }
    for url, cb in supplier_cbs.items():
        deps[f"supplier-{url.split(':')[-1]}"] = cb.get_status()
    return JSONResponse(content=build_health_response(
        "Inventory Agent", "1.0.0", db_connected=db_ok, dependencies=deps
    ))

if __name__ == "__main__":
    init_db()
    log.info("Inventory Agent v1.0 starting on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
