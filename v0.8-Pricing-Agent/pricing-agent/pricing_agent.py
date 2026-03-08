"""
Pricing Agent — v0.8 Pricing Agent
Watches the Market API for price changes.
When a product drifts beyond REPRICE_THRESHOLD, updates the DB via A2A.
Also runs the latency vs accuracy benchmark across 3 reprice intervals.
"""

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
log = logging.getLogger("pricing-agent")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

MARKET_API_URL      = os.getenv("MARKET_API_URL",      "http://localhost:9000")
INVENTORY_AGENT_URL = os.getenv("INVENTORY_AGENT_URL", "http://localhost:8000")
REPRICE_THRESHOLD   = float(os.getenv("REPRICE_THRESHOLD", 0.05))

DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "pricing_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_market_prices() -> dict:
    """Fetch current market prices from the Market API."""
    r = httpx.get(f"{MARKET_API_URL}/prices", timeout=5)
    return r.json()

def get_db_prices() -> dict:
    """Read current prices from pricing_db."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT product, price FROM inventory")
    rows = {r["product"]: float(r["price"]) for r in cur.fetchall()}
    cur.close()
    conn.close()
    return rows

def send_price_update(product: str, new_price: float, old_price: float) -> dict:
    """Send price update to Inventory Agent via A2A."""
    pct_change = ((new_price - old_price) / old_price) * 100
    r = httpx.post(
        f"{INVENTORY_AGENT_URL}/a2a",
        json={
            "task":       "update_price",
            "product":    product,
            "new_price":  new_price,
            "old_price":  old_price,
            "pct_change": round(pct_change, 2)
        },
        timeout=5
    )
    return r.json()

def price_error(market_price: float, db_price: float) -> float:
    """How far is the DB price from the current market price? (absolute %)"""
    return abs((market_price - db_price) / market_price) * 100

# ── Live Repricing ────────────────────────────────────────────────────────────

def run_live(duration_s: int = 30, interval_s: float = 5.0):
    """
    Watch the market for `duration_s` seconds.
    Every `interval_s` seconds, check for price drift.
    Trigger A2A price update if drift > REPRICE_THRESHOLD.
    """
    log.info("=" * 60)
    log.info(f"Live repricing — interval={interval_s}s threshold={REPRICE_THRESHOLD*100:.0f}%")
    log.info("=" * 60)

    updates_sent  = 0
    checks_done   = 0
    start         = time.time()

    while time.time() - start < duration_s:
        time.sleep(interval_s)
        checks_done += 1

        market_data = get_market_prices()
        market      = market_data["prices"]
        db_prices   = get_db_prices()

        log.info(f"\n── Check #{checks_done} (tick={market_data['tick']}) ──────────────────────────")
        log.info(f"  {'Product':<12} {'Market':>9} {'DB':>9} {'Drift':>8} {'Action'}")
        log.info(f"  {'-'*55}")

        for product, market_price in market.items():
            db_price = db_prices.get(product, market_price)
            drift    = ((market_price - db_price) / db_price) * 100

            if abs(drift) >= REPRICE_THRESHOLD * 100:
                result = send_price_update(product, market_price, db_price)
                action = f"✅ repriced ({drift:+.1f}%)"
                updates_sent += 1
            else:
                action = f"— no change ({drift:+.1f}%)"

            log.info(f"  {product:<12} ${market_price:>8.2f} ${db_price:>8.2f} {drift:>+7.1f}%  {action}")

    log.info(f"\n── Live run complete ───────────────────────────────────")
    log.info(f"  Checks done:   {checks_done}")
    log.info(f"  Updates sent:  {updates_sent}")
    log.info(f"  Duration:      {duration_s}s")
    log.info("=" * 60)

# ── Benchmark ─────────────────────────────────────────────────────────────────

def run_benchmark():
    """
    Latency vs Accuracy Tradeoff Benchmark.
    Test 3 reprice intervals: 2s, 5s, 10s.
    For each interval, measure:
      - avg price error (how stale is the DB price vs market)
      - number of A2A updates sent
      - total latency
    """
    log.info("\n" + "=" * 60)
    log.info("BENCHMARK — Latency vs Accuracy Tradeoff")
    log.info("=" * 60)

    intervals    = [2, 5, 10]
    duration_s   = 30
    results      = []

    for interval in intervals:
        log.info(f"\n── Testing interval={interval}s ──────────────────────────────")

        errors       = []
        updates_sent = 0
        latencies    = []
        checks_done  = 0
        start        = time.time()

        # Reset DB prices to base before each run
        base_prices = {
            "Laptop":   999.99,
            "Mouse":     29.99,
            "Keyboard":  79.99,
            "Monitor":  349.99,
            "Webcam":    89.99,
        }
        conn = psycopg2.connect(**DB_CONFIG)
        cur  = conn.cursor()
        for product, price in base_prices.items():
            cur.execute("UPDATE inventory SET price = %s WHERE product = %s", (price, product))
        conn.commit()
        cur.close()
        conn.close()
        log.info(f"  DB prices reset to base")

        while time.time() - start < duration_s:
            time.sleep(interval)
            checks_done += 1

            t0          = time.time()
            market_data = get_market_prices()
            market      = market_data["prices"]
            db_prices   = get_db_prices()
            latency_ms  = round((time.time() - t0) * 1000, 2)
            latencies.append(latency_ms)

            for product, market_price in market.items():
                db_price = db_prices.get(product, market_price)
                err      = price_error(market_price, db_price)
                errors.append(err)

                if err >= REPRICE_THRESHOLD * 100:
                    send_price_update(product, market_price, db_price)
                    updates_sent += 1

        avg_error   = round(sum(errors) / len(errors), 3) if errors else 0
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0

        results.append({
            "interval_s":   interval,
            "checks":       checks_done,
            "updates_sent": updates_sent,
            "avg_error_pct": avg_error,
            "avg_latency_ms": avg_latency
        })

        log.info(f"  Checks: {checks_done} | Updates: {updates_sent} | Avg error: {avg_error}% | Avg latency: {avg_latency}ms")

    # Print benchmark summary table
    log.info("\n" + "=" * 60)
    log.info("BENCHMARK RESULTS — Latency vs Accuracy Tradeoff")
    log.info("=" * 60)
    log.info(f"\n  {'Interval':<12} {'Checks':<8} {'Updates':<10} {'Avg Error':<14} {'Avg Latency'}")
    log.info(f"  {'-'*55}")
    for r in results:
        log.info(
            f"  {r['interval_s']}s{'':<10} "
            f"{r['checks']:<8} "
            f"{r['updates_sent']:<10} "
            f"{r['avg_error_pct']}%{'':<11} "
            f"{r['avg_latency_ms']}ms"
        )

    log.info("\nKey insight:")
    fastest = min(results, key=lambda r: r["avg_error_pct"])
    slowest = max(results, key=lambda r: r["avg_error_pct"])
    log.info(f"  {fastest['interval_s']}s interval → lowest avg error ({fastest['avg_error_pct']}%)")
    log.info(f"  {slowest['interval_s']}s interval → highest avg error ({slowest['avg_error_pct']}%)")
    log.info(f"  Tradeoff: more frequent checks = lower error but more A2A calls")
    log.info("=" * 60)

    return results

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Pricing Agent v0.8 starting...")
    log.info(f"Market API:      {MARKET_API_URL}")
    log.info(f"Inventory Agent: {INVENTORY_AGENT_URL}")
    log.info(f"Threshold:       {REPRICE_THRESHOLD*100:.0f}%")

    # Step 1 — Run live repricing for 30 seconds
    run_live(duration_s=30, interval_s=5.0)

    # Step 2 — Run the benchmark
    run_benchmark()