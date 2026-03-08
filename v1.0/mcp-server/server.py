"""
MCP Server — v1.0
Entry point for Claude Desktop.
Same 5 tools as v0.9 for backward compatibility.
Routes all calls through the API Gateway.
"""

import json
import asyncio
import sys
import os
import time
import logging
import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("mcp-server-v1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from shared.config import API_GATEWAY_URL

# ── Helpers ───────────────────────────────────────────────────────────────────

async def gateway_get(path: str, timeout: int = 30) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{API_GATEWAY_URL}{path}", timeout=timeout)
            return r.json()
    except Exception as e:
        return {"error": str(e)}

async def gateway_post(path: str, payload: dict = None, timeout: int = 60) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{API_GATEWAY_URL}{path}", json=payload or {}, timeout=timeout)
            return r.json()
    except Exception as e:
        return {"error": str(e)}

# ── MCP Server ────────────────────────────────────────────────────────────────

app = Server("mcp-supply-chain-v1")

@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="get_inventory",
            description=(
                "Get full inventory with live market prices. "
                "Automatically syncs prices, detects low stock, "
                "runs AI-powered supplier bidding with finance approval, "
                "places restock orders and sends email alerts. "
                "This triggers the entire supply chain pipeline."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="sync_prices",
            description="Manually trigger an AI-powered price sync between the market and inventory.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="check_stock",
            description="Check current stock levels without triggering any pipeline actions.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="get_orders",
            description="Get all confirmed restock orders placed by the Order Agent.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="get_market_prices",
            description="Get current live market prices from the Market API.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    start = time.time()

    try:
        if name == "get_inventory":
            log.info("=" * 60)
            log.info("Full pipeline triggered via MCP get_inventory")
            result = await gateway_post("/api/pipeline/trigger")
            # If async, wait a bit and get inventory
            if result.get("status") == "pipeline_triggered":
                await asyncio.sleep(2)
                result = await gateway_get("/api/inventory")

        elif name == "sync_prices":
            result = await gateway_post("/api/prices/sync")

        elif name == "check_stock":
            result = await gateway_get("/api/inventory")

        elif name == "get_orders":
            result = await gateway_get("/api/orders")

        elif name == "get_market_prices":
            result = await gateway_get("/api/market/prices")

        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as e:
        log.error(f"[{name}] Error: {e}")
        result = {"error": str(e)}

    ms = round((time.time() - start) * 1000, 2)
    log.info(f"[{name}] completed in {ms}ms")

    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

# ── Entry Point ───────────────────────────────────────────────────────────────

async def main():
    log.info("MCP Supply Chain Server v1.0 starting...")
    log.info(f"API Gateway: {API_GATEWAY_URL}")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
