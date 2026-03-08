"""
Inventory Agent — v0.7 Supplier Agents
Checks stock levels, sends bid requests to all 3 suppliers simultaneously,
scores the responses, picks the winner and confirms the order.
"""

import logging
import sys
import os
import time
import psycopg2
import psycopg2.extras
import httpx
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    "dbname":   os.getenv("DB_NAME",     "supplier_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

SUPPLIER_URLS = [
    os.getenv("SUPPLIER_A_URL", "http://localhost:8011"),
    os.getenv("SUPPLIER_B_URL", "http://localhost:8012"),
    os.getenv("SUPPLIER_C_URL", "http://localhost:8013"),
]

ORDER_AGENT_URL   = os.getenv("ORDER_AGENT_URL",   "http://localhost:8001")
RESTOCK_THRESHOLD = int(os.getenv("RESTOCK_THRESHOLD", 15))
RESTOCK_QUANTITY  = 20
DEADLINE_DAYS     = 6

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id        SERIAL PRIMARY KEY,
            product   TEXT           NOT NULL UNIQUE,
            quantity  INTEGER        DEFAULT 0,
            price     NUMERIC(10, 2) DEFAULT 0.00
        )
    """)
    cur.execute("SELECT COUNT(*) FROM inventory")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO inventory (product, quantity, price) VALUES (%s, %s, %s)",
            [
                ("Laptop",   10, 999.99),
                ("Mouse",    50,  29.99),
                ("Keyboard", 30,  79.99),
                ("Monitor",   8, 349.99),
                ("Webcam",   20,  89.99),
            ]
        )
        log.info("Inventory seeded with 5 products")
    conn.commit()
    cur.close()
    conn.close()

def get_low_stock() -> list:
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

def get_all_products() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM inventory ORDER BY quantity ASC")
    products = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return products

# ── A2A Helpers ───────────────────────────────────────────────────────────────

_card_cache = {}

def discover_agent(url: str) -> dict | None:
    if url in _card_cache:
        return _card_cache[url]
    try:
        r    = httpx.get(f"{url}/.well-known/agent.json", timeout=5)
        card = r.json()
        _card_cache[url] = card
        log.info(f"Discovered: {card.get('name')} at {url}")
        return card
    except Exception as e:
        log.warning(f"Could not discover agent at {url}: {e}")
        return None

def send_bid_request(supplier_url: str, product: str, quantity: int, base_price: float) -> dict:
    """Send a bid request to one supplier and return the response with latency."""
    start = time.time()
    try:
        card = discover_agent(supplier_url)
        if not card:
            return {"status": "error", "supplier": supplier_url, "message": "Agent not found"}

        response = httpx.post(
            f"{supplier_url}/a2a",
            json={
                "task":          "submit_bid",
                "product":       product,
                "quantity":      quantity,
                "base_price":    base_price,
                "deadline_days": DEADLINE_DAYS
            },
            timeout=5
        )
        result            = response.json()
        result["latency_ms"] = round((time.time() - start) * 1000, 2)
        return result

    except Exception as e:
        return {
            "status":     "error",
            "supplier":   supplier_url,
            "message":    str(e),
            "latency_ms": round((time.time() - start) * 1000, 2)
        }

def collect_bids(product: str, quantity: int, base_price: float) -> list:
    """
    Send bid requests to ALL suppliers simultaneously using threads.
    This is faster than sequential requests.
    """
    log.info(f"Sending bid requests to {len(SUPPLIER_URLS)} suppliers simultaneously...")
    bids = []

    with ThreadPoolExecutor(max_workers=len(SUPPLIER_URLS)) as executor:
        futures = {
            executor.submit(send_bid_request, url, product, quantity, base_price): url
            for url in SUPPLIER_URLS
        }
        for future in as_completed(futures):
            bid = future.result()
            bids.append(bid)

    return bids

def pick_winner(bids: list) -> dict | None:
    """Pick the supplier with the lowest score. Skip declined/error bids."""
    accepted = [b for b in bids if b.get("status") == "accepted"]
    if not accepted:
        return None
    return min(accepted, key=lambda b: b.get("score", 999))

def confirm_order(winner: dict, product: str, quantity: int) -> dict:
    """Send the winning bid to the Order Agent to confirm."""
    try:
        response = httpx.post(
            f"{ORDER_AGENT_URL}/a2a",
            json={
                "task":          "confirm_order",
                "product":       product,
                "quantity":      quantity,
                "supplier":      winner["supplier"],
                "unit_price":    winner["unit_price"],
                "total_price":   winner["total_price"],
                "delivery_days": winner["delivery_days"],
                "score":         winner["score"]
            },
            timeout=5
        )
        return response.json()
    except Exception as e:
        log.error(f"Failed to confirm order: {e}")
        return {"status": "error", "message": str(e)}

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    log.info("=" * 60)
    log.info("Inventory Agent v0.7 started")
    log.info(f"Restock threshold: {RESTOCK_THRESHOLD} units")
    log.info(f"Deadline: {DEADLINE_DAYS} days")
    log.info("=" * 60)

    # Step 1 — Show inventory
    all_products = get_all_products()
    log.info("Current inventory:")
    for p in all_products:
        flag = " ⚠️  LOW" if p["quantity"] < RESTOCK_THRESHOLD else ""
        log.info(f"  {p['product']:12} qty={p['quantity']:3}  price=${p['price']}{flag}")

    # Step 2 — Find low stock
    low_stock = get_low_stock()
    if not low_stock:
        log.info("All products above threshold. No restocking needed.")
        return

    log.info(f"\n{len(low_stock)} product(s) need restocking")

    # Step 3 — Run bidding for each low stock product
    for product in low_stock:
        name       = product["product"]
        base_price = float(product["price"])

        log.info(f"\n── Bidding for {name} (base price: ${base_price}) ──────────────")

        # Collect bids simultaneously
        start = time.time()
        bids  = collect_bids(name, RESTOCK_QUANTITY, base_price)
        total_bid_time = round((time.time() - start) * 1000, 2)

        # Print bid comparison table
        log.info(f"\n  {'Supplier':<14} {'Status':<10} {'Unit Price':<12} {'Delivery':<10} {'Reliability':<13} {'Score':<8} {'Latency'}")
        log.info(f"  {'-'*75}")
        for bid in sorted(bids, key=lambda b: b.get("score", 999)):
            if bid.get("status") == "accepted":
                log.info(
                    f"  {bid['supplier']:<14} "
                    f"{'✅ accepted':<10} "
                    f"${bid['unit_price']:<11} "
                    f"{bid['delivery_days']} days{'':<4} "
                    f"{bid['reliability_pct']}%{'':<9} "
                    f"{bid['score']:<8} "
                    f"{bid['latency_ms']}ms"
                )
            else:
                reason = bid.get("reason") or bid.get("message", "unknown")
                log.info(f"  {bid.get('supplier', 'unknown'):<14} ❌ {bid.get('status','error'):<9} {reason}")

        log.info(f"\n  All bids collected in {total_bid_time}ms (parallel)")

        # Pick winner
        winner = pick_winner(bids)
        if not winner:
            log.warning(f"No valid bids for {name} — skipping")
            continue

        log.info(f"\n  🏆 Winner: {winner['supplier']}")
        log.info(f"     Price:    ${winner['unit_price']} x {RESTOCK_QUANTITY} = ${winner['total_price']}")
        log.info(f"     Delivery: {winner['delivery_days']} days")
        log.info(f"     Score:    {winner['score']}")

        # Confirm order
        order_result = confirm_order(winner, name, RESTOCK_QUANTITY)
        if order_result.get("status") == "success":
            log.info(f"  ✅ Order confirmed: {order_result.get('message')}")
        else:
            log.error(f"  ❌ Order failed: {order_result.get('message')}")

    log.info("\n" + "=" * 60)
    log.info("✅ Inventory Agent completed")
    log.info("=" * 60)

if __name__ == "__main__":
    init_db()
    run()