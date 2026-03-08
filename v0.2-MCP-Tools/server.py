import json
import asyncio
import sys
import time
import psycopg2
import psycopg2.extras
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ── MCP Server ────────────────────────────────────────────────────────────────

app = Server("inventory-server-v2")

# ── Database ──────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "dbname":   "inventory_db",
    "user":     "adithyan",
    "host":     "localhost",
    "port":     5432,
}

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id        SERIAL PRIMARY KEY,
            product   TEXT    NOT NULL UNIQUE,
            quantity  INTEGER DEFAULT 0,
            price     NUMERIC(10, 2) DEFAULT 0.00
        )
    """)
    # Seed data
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
    db.commit()
    cur.close()
    db.close()

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
                    "query":     {"type": "string",  "description": "Partial product name to search for"},
                    "min_price": {"type": "number",  "description": "Minimum price filter (optional)"},
                    "max_price": {"type": "number",  "description": "Maximum price filter (optional)"}
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

    try:
        db = get_db()
        cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if name == "read_stock":
            product = arguments["product"]
            cur.execute(
                "SELECT * FROM inventory WHERE LOWER(product) = LOWER(%s)",
                (product,)
            )
            row = cur.fetchone()
            result = dict(row) if row else {"error": f"Product '{product}' not found"}

        elif name == "write_stock":
            product  = arguments["product"]
            quantity = arguments["quantity"]
            cur.execute(
                "UPDATE inventory SET quantity = %s WHERE LOWER(product) = LOWER(%s) RETURNING *",
                (quantity, product)
            )
            row = cur.fetchone()
            db.commit()
            result = dict(row) if row else {"error": f"Product '{product}' not found"}

        elif name == "search_product":
            query     = arguments.get("query", "")
            min_price = arguments.get("min_price")
            max_price = arguments.get("max_price")

            sql    = "SELECT * FROM inventory WHERE product ILIKE %s"
            params = [f"%{query}%"]

            if min_price is not None:
                sql += " AND price >= %s"
                params.append(min_price)
            if max_price is not None:
                sql += " AND price <= %s"
                params.append(max_price)

            cur.execute(sql, params)
            rows   = cur.fetchall()
            result = [dict(r) for r in rows]

        elif name == "update_price":
            product = arguments["product"]
            price   = arguments["price"]
            cur.execute(
                "UPDATE inventory SET price = %s WHERE LOWER(product) = LOWER(%s) RETURNING *",
                (price, product)
            )
            row = cur.fetchone()
            db.commit()
            result = dict(row) if row else {"error": f"Product '{product}' not found"}

        else:
            raise ValueError(f"Unknown tool: {name}")

        cur.close()
        db.close()

    except Exception as e:
        result = {"error": str(e)}

    latency_ms = round((time.time() - start) * 1000, 2)
    payload    = {"result": result, "latency_ms": latency_ms}

    print(f"[{name}] latency={latency_ms}ms", file=sys.stderr, flush=True)

    return [types.TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]

# ── Entry Point ───────────────────────────────────────────────────────────────

async def main():
    print("MCP Inventory Server v0.2 started...", file=sys.stderr, flush=True)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    init_db()
    asyncio.run(main())