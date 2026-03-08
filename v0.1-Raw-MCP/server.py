import sqlite3
import json
import asyncio
import os
import sys
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# Initialize MCP server
app = Server("inventory-server")

# Absolute path to DB — works regardless of where Claude Desktop runs this from
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventory.db")

# ── Database helpers ──────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            product  TEXT    NOT NULL,
            quantity INTEGER DEFAULT 0,
            price    REAL    DEFAULT 0.0
        )
    """)
    count = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
    if count == 0:
        db.executemany(
            "INSERT INTO inventory (product, quantity, price) VALUES (?, ?, ?)",
            [
                ("Laptop",   10, 999.99),
                ("Mouse",    50,  29.99),
                ("Keyboard", 30,  79.99),
                ("Monitor",   8, 349.99),
                ("Webcam",   20,  89.99),
            ]
        )
        db.commit()
    db.close()

# ── Tool definitions ──────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="get_inventory",
            description="Get all products from the inventory database",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="get_product",
            description="Look up a single product by name",
            inputSchema={
                "type": "object",
                "properties": {
                    "product": {
                        "type": "string",
                        "description": "Name of the product to look up"
                    }
                },
                "required": ["product"]
            }
        )
    ]

# ── Tool execution ────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict):

    if name == "get_inventory":
        db = get_db()
        rows = db.execute("SELECT * FROM inventory ORDER BY id").fetchall()
        db.close()
        result = [dict(row) for row in rows]
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "get_product":
        product_name = arguments.get("product", "")
        db = get_db()
        row = db.execute(
            "SELECT * FROM inventory WHERE LOWER(product) = LOWER(?)",
            (product_name,)
        ).fetchone()
        db.close()
        if row:
            return [types.TextContent(type="text", text=json.dumps(dict(row), indent=2))]
        else:
            return [types.TextContent(type="text", text=f"Product '{product_name}' not found.")]

    raise ValueError(f"Unknown tool: {name}")

# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    # Log to stderr only — stdout must stay clean for MCP JSON communication
    print("MCP Inventory Server started...", file=sys.stderr, flush=True)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    init_db()
    asyncio.run(main())