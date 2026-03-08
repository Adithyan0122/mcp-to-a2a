"""
Inventory Agent — v0.4 Raw A2A
Checks stock levels in the inventory DB.
If a product is below the restock threshold, it pings the Order Agent via A2A.
Also benchmarks A2A handshake vs direct API call.
"""

import json
import logging
import sys
import os
import time
import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("inventory-agent")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "inventory_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

ORDER_AGENT_URL  = os.getenv("ORDER_AGENT_URL", "http://localhost:8001")
RESTOCK_THRESHOLD = int(os.getenv("RESTOCK_THRESHOLD", 15))
RESTOCK_QUANTITY  = int(os.getenv("RESTOCK_QUANTITY",  20))

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def get_low_stock_products() -> list[dict]:
    """Return all products where quantity is below the restock threshold."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM inventory WHERE quantity < %s ORDER BY quantity ASC",
        (RESTOCK_THRESHOLD,)
    )
    products = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return products

def get_all_products() -> list[dict]:
    """Return all products."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM inventory ORDER BY quantity ASC")
    products = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return products

# ── A2A Handshake ─────────────────────────────────────────────────────────────

def discover_order_agent() -> dict | None:
    """
    Step 1 of A2A: Fetch the Agent Card from the Order Agent.
    This is how agents discover each other's capabilities.
    """
    try:
        start    = time.time()
        response = httpx.get(f"{ORDER_AGENT_URL}/.well-known/agent.json", timeout=5)
        latency  = round((time.time() - start) * 1000, 2)
        card     = response.json()
        log.info(f"Agent Card fetched in {latency}ms — capabilities: {card.get('capabilities')}")
        return card, latency
    except Exception as e:
        log.error(f"Failed to fetch Agent Card: {e}")
        return None, 0

def send_a2a_order(product: str, quantity: int) -> tuple[dict, float]:
    """
    Step 2 of A2A: Send a task request to the Order Agent.
    """
    try:
        start    = time.time()
        response = httpx.post(
            f"{ORDER_AGENT_URL}/a2a",
            json={"task": "place_order", "product": product, "quantity": quantity},
            timeout=5
        )
        latency = round((time.time() - start) * 1000, 2)
        return response.json(), latency
    except Exception as e:
        log.error(f"Failed to send A2A order: {e}")
        return {"status": "error", "message": str(e)}, 0

def send_direct_order(product: str, quantity: int) -> tuple[dict, float]:
    """
    Direct API call — same request but WITHOUT the Agent Card discovery step.
    Used for benchmarking: A2A handshake vs direct call.
    """
    try:
        start    = time.time()
        response = httpx.post(
            f"{ORDER_AGENT_URL}/a2a",
            json={"task": "place_order", "product": product, "quantity": quantity},
            timeout=5
        )
        latency = round((time.time() - start) * 1000, 2)
        return response.json(), latency
    except Exception as e:
        log.error(f"Failed direct order: {e}")
        return {"status": "error", "message": str(e)}, 0

# ── Main Logic ────────────────────────────────────────────────────────────────

def run():
    log.info("=" * 60)
    log.info("Inventory Agent started")
    log.info(f"Restock threshold: {RESTOCK_THRESHOLD} units")
    log.info("=" * 60)

    # Step 1 — Check inventory
    all_products = get_all_products()
    log.info(f"Current inventory ({len(all_products)} products):")
    for p in all_products:
        flag = " ⚠️  LOW STOCK" if p["quantity"] < RESTOCK_THRESHOLD else ""
        log.info(f"  {p['product']:12} qty={p['quantity']:3}  price=${p['price']}{flag}")

    # Step 2 — Find low stock
    low_stock = get_low_stock_products()
    if not low_stock:
        log.info(f"All products are above threshold ({RESTOCK_THRESHOLD}). No restocking needed.")
        return

    log.info(f"\n{len(low_stock)} product(s) need restocking:")
    for p in low_stock:
        log.info(f"  {p['product']} — only {p['quantity']} left")

    # Step 3 — Discover Order Agent via A2A handshake
    log.info("\n── A2A Discovery ──────────────────────────────────────")
    card, discovery_latency = discover_order_agent()
    if not card:
        log.error("Could not reach Order Agent. Aborting.")
        return

    # Step 4 — Send A2A orders + benchmark vs direct calls
    log.info("\n── Placing Orders ─────────────────────────────────────")
    benchmark_results = []

    for product in low_stock:
        name = product["product"]

        # A2A (with prior discovery)
        a2a_result, a2a_latency = send_a2a_order(name, RESTOCK_QUANTITY)

        # Direct call (no discovery)
        direct_result, direct_latency = send_direct_order(name, RESTOCK_QUANTITY)

        status = a2a_result.get("status", "unknown")
        log.info(f"  {name}: A2A={a2a_latency}ms | Direct={direct_latency}ms | status={status}")

        benchmark_results.append({
            "product":         name,
            "a2a_latency_ms":  a2a_latency,
            "direct_latency_ms": direct_latency,
            "overhead_ms":     round(a2a_latency - direct_latency, 2),
            "status":          status
        })

    # Step 5 — Print benchmark summary
    log.info("\n── Benchmark Summary ──────────────────────────────────")
    log.info(f"  Agent Card discovery: {discovery_latency}ms (one-time overhead)")
    log.info(f"  {'Product':<12} {'A2A (ms)':<12} {'Direct (ms)':<14} {'Overhead (ms)'}")
    log.info(f"  {'-'*52}")
    for r in benchmark_results:
        log.info(f"  {r['product']:<12} {r['a2a_latency_ms']:<12} {r['direct_latency_ms']:<14} {r['overhead_ms']}")

    total_a2a    = sum(r["a2a_latency_ms"]    for r in benchmark_results)
    total_direct = sum(r["direct_latency_ms"] for r in benchmark_results)
    log.info(f"\n  Total A2A latency:    {round(total_a2a + discovery_latency, 2)}ms (incl. discovery)")
    log.info(f"  Total Direct latency: {total_direct}ms")
    log.info(f"  A2A overhead:         {round(total_a2a + discovery_latency - total_direct, 2)}ms")
    log.info("\n✅ Inventory Agent completed successfully")

if __name__ == "__main__":
    run()