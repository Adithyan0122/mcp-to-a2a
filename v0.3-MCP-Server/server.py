import json
import asyncio
import sys
import time
import logging
import os
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("mcp-inventory")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME", "inventory_db"),
    "user":     os.getenv("DB_USER", "adithyan"),
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}
API_KEY = os.getenv("API_KEY")

# ── Connection Pool ───────────────────────────────────────────────────────────

try:
    db_pool = psycopg2.pool.SimpleConnectionPool(
        minconn=1,
        maxconn=5,
        **DB_CONFIG
    )
    log.info("Database connection pool created (min=1, max=5)")
except Exception as e:
    log.error(f"Failed to create connection pool: {e}")
    sys.exit(1)

def get_db():
    return db_pool.getconn()

def release_db(conn):
    db_pool.putconn(conn)

# ── Auth ──────────────────────────────────────────────────────────────────────

def verify_api_key():
    if not API_KEY:
        log.warning("No API_KEY set in .env — running without auth")
        return
    log.info("API key loaded successfully")

# ── Database Init ─────────────────────────────────────────────────────────────

def init_db():
    conn = get_db()
    try:
        cur = conn.cursor()
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
                    ("Monitor",  25, 349.99),
                    ("Webcam",   20,  89.99),
                ]
            )
            log.info("Database seeded with 5 products")
        conn.commit()
        cur.close()
        log.info("Database initialized successfully")
    except Exception as e:
        log.error(f"Database init failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        release_db(conn)

# ── MCP Server ────────────────────────────────────────────────────────────────

app = Server("inventory-server-v3")

# ── Tools ─────────────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="read_stock",
            description="Read the current stock level and price of a product by name",
            inputSchema={
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product name to look up"}
                },
                "required": ["product"]
            }
        ),
        types.Tool(
            name="write_stock",
            description="Update the stock quantity of a product",
            inputSchema={
                "type": "object",
                "properties": {
                    "product":  {"type": "string",  "description": "Product name to update"},
                    "quantity": {"type": "integer", "description": "New stock quantity"}
                },
                "required": ["product", "quantity"]
            }
        ),
        types.Tool(
            name="search_product",
            description="Search for products by partial name or filter by price range",
            inputSchema={
                "type": "object",
                "properties": {
                    "query":     {"type": "string", "description": "Partial product name to search for"},
                    "min_price": {"type": "number", "description": "Minimum price filter (optional)"},
                    "max_price": {"type": "number", "description": "Maximum price filter (optional)"}
                },
                "required": []
            }
        ),
        types.Tool(
            name="update_price",
            description="Update the price of a product",
            inputSchema={
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product name to update"},
                    "price":   {"type": "number", "description": "New price"}
                },
                "required": ["product", "price"]
            }
        ),
    ]

# ── Tool Execution ────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    start = time.time()
    conn  = None

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if name == "read_stock":
            product = arguments.get("product", "").strip()
            if not product:
                raise ValueError("'product' field is required and cannot be empty")
            cur.execute(
                "SELECT * FROM inventory WHERE LOWER(product) = LOWER(%s)",
                (product,)
            )
            row    = cur.fetchone()
            result = dict(row) if row else {"error": f"Product '{product}' not found"}

        elif name == "write_stock":
            product  = arguments.get("product", "").strip()
            quantity = arguments.get("quantity")
            if not product:
                raise ValueError("'product' field is required")
            if quantity is None or quantity < 0:
                raise ValueError("'quantity' must be a non-negative integer")
            cur.execute(
                "UPDATE inventory SET quantity = %s WHERE LOWER(product) = LOWER(%s) RETURNING *",
                (quantity, product)
            )
            row = cur.fetchone()
            conn.commit()
            result = dict(row) if row else {"error": f"Product '{product}' not found"}

        elif name == "search_product":
            query     = arguments.get("query", "")
            min_price = arguments.get("min_price")
            max_price = arguments.get("max_price")
            sql       = "SELECT * FROM inventory WHERE product ILIKE %s"
            params    = [f"%{query}%"]
            if min_price is not None:
                sql += " AND price >= %s"
                params.append(min_price)
            if max_price is not None:
                sql += " AND price <= %s"
                params.append(max_price)
            cur.execute(sql, params)
            result = [dict(r) for r in cur.fetchall()]

        elif name == "update_price":
            product = arguments.get("product", "").strip()
            price   = arguments.get("price")
            if not product:
                raise ValueError("'product' field is required")
            if price is None or price < 0:
                raise ValueError("'price' must be a non-negative number")
            cur.execute(
                "UPDATE inventory SET price = %s WHERE LOWER(product) = LOWER(%s) RETURNING *",
                (price, product)
            )
            row = cur.fetchone()
            conn.commit()
            result = dict(row) if row else {"error": f"Product '{product}' not found"}

        else:
            raise ValueError(f"Unknown tool: {name}")

        cur.close()

    except ValueError as e:
        log.warning(f"[{name}] Validation error: {e}")
        result = {"error": str(e)}
        if conn:
            conn.rollback()

    except psycopg2.Error as e:
        log.error(f"[{name}] Database error: {e}")
        result = {"error": f"Database error: {str(e)}"}
        if conn:
            conn.rollback()

    except Exception as e:
        log.error(f"[{name}] Unexpected error: {e}")
        result = {"error": f"Unexpected error: {str(e)}"}
        if conn:
            conn.rollback()

    finally:
        if conn:
            release_db(conn)

    latency_ms = round((time.time() - start) * 1000, 2)
    log.info(f"[{name}] completed in {latency_ms}ms")

    payload = {"result": result, "latency_ms": latency_ms}
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]

# ── Entry Point ───────────────────────────────────────────────────────────────

async def main():
    verify_api_key()
    log.info("MCP Inventory Server v0.3 starting...")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    init_db()
    asyncio.run(main())