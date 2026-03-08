# v0.3 — MCP Server: Production-Grade Claude + PostgreSQL in Docker

> Take the 4-tool MCP server from v0.2 and make it production-ready: connection pooling, authentication, structured logging, full error handling, and Docker deployment.

---

## What Changed from v0.2

| | v0.2 | v0.3 |
|---|---|---|
| **DB connections** | New connection per tool call | Connection pool (reused) |
| **Config** | Hardcoded in code | `.env` file |
| **Auth** | None | API key check on startup |
| **Logging** | `print()` to stderr | Structured logging with timestamps + levels |
| **Error handling** | Basic try/except | 3 distinct error types |
| **Input validation** | Minimal | Empty fields, negative values caught |
| **Deployment** | Run manually | Docker + docker-compose |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         YOUR MACHINE                              │
│                                                                   │
│   ┌─────────────┐   stdio    ┌──────────────────────────────┐   │
│   │   Claude    │ ◄────────► │        server.py              │   │
│   │   Desktop   │            │    (MCP Server v0.3)          │   │
│   └─────────────┘            │                               │   │
│                               │  ┌────────────────────────┐  │   │
│                               │  │   Connection Pool       │  │   │
│                               │  │   min=1, max=5          │  │   │
│                               │  └──────────┬─────────────┘  │   │
│                               └─────────────┼────────────────┘   │
│                                             │ psycopg2            │
│   ┌─────────────────────────────────────────▼──────────────────┐ │
│   │                    Docker Network                           │ │
│   │                                                             │ │
│   │   ┌─────────────────────┐      ┌──────────────────────┐   │ │
│   │   │  inventory_mcp      │      │  inventory_postgres   │   │ │
│   │   │  (MCP container)    │◄────►│  (PostgreSQL 16)      │   │ │
│   │   └─────────────────────┘      └──────────────────────┘   │ │
│   └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### Two Ways to Run

**For Claude Desktop** (stdio, local):
```
Claude Desktop ──stdio──► python3 server.py ──psycopg2──► PostgreSQL (local)
```

**For Docker** (portable, shareable):
```
docker compose up ──► inventory_mcp container ──► inventory_postgres container
```

---

## Project Structure

```
v0.3-MCP-Server/
├── server.py            ← MCP server with pooling, auth, logging, error handling
├── requirements.txt     ← mcp[cli] + psycopg2-binary + python-dotenv
├── Dockerfile           ← Containerizes the MCP server
├── docker-compose.yml   ← Spins up MCP server + PostgreSQL together
├── .env                 ← Your secrets (never commit this)
├── .env.example         ← Template for others to copy
└── README.md
```

---

## The 4 Tools (unchanged from v0.2)

| Tool | What It Does |
|---|---|
| `read_stock` | Get stock level + price for a product |
| `write_stock` | Update quantity of a product |
| `search_product` | Search by partial name + optional price range |
| `update_price` | Change the price of a product |

---

## What's New in Detail

### 1. Connection Pooling

In v0.2, every tool call did this:
```
open connection → query → close connection
```

In v0.3:
```
startup → open pool (1–5 connections)
tool call → borrow connection → query → return connection
shutdown → close pool
```

Connections are reused across tool calls. At scale this reduces DB overhead significantly.

```python
db_pool = psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=5, **DB_CONFIG)
```

### 2. Environment Variables via `.env`

All config lives in `.env` — nothing hardcoded:

```
DB_NAME=inventory_db
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=5432
API_KEY=your_secret_api_key
```

The server reads these via `python-dotenv` at startup. In Docker, these are injected via `env_file`.

### 3. Authentication

On startup the server checks for an API key:
```python
def verify_api_key():
    if not API_KEY:
        log.warning("No API_KEY set in .env — running without auth")
        return
    log.info("API key loaded successfully")
```

If no key is set, the server warns but still runs. In v0.4+ this will enforce rejection.

### 4. Structured Logging

Every event is logged with a timestamp and level:
```
2026-03-08T09:22:21 [INFO] Database connection pool created (min=1, max=5)
2026-03-08T09:22:21 [INFO] Database seeded with 5 products
2026-03-08T09:22:21 [INFO] Database initialized successfully
2026-03-08T09:22:21 [INFO] API key loaded successfully
2026-03-08T09:22:21 [INFO] MCP Inventory Server v0.3 starting...
```

Tool calls log their own latency:
```
2026-03-08T09:22:35 [INFO] [read_stock] completed in 4.21ms
```

### 5. Three-Layer Error Handling

Every tool call is wrapped in three distinct catch blocks:

```python
except ValueError as e:
    # Bad input — empty fields, negative numbers
    log.warning(f"[{name}] Validation error: {e}")

except psycopg2.Error as e:
    # Database failure — connection lost, query error
    log.error(f"[{name}] Database error: {e}")

except Exception as e:
    # Anything else unexpected
    log.error(f"[{name}] Unexpected error: {e}")
```

All errors return structured JSON to Claude rather than crashing:
```json
{ "error": "quantity must be a non-negative integer", "latency_ms": 0.45 }
```

---

## Setup

### Option A — Run Locally (for Claude Desktop)

**Prerequisites:** Python 3.10+, PostgreSQL 16, Claude Desktop

```bash
# 1. Clone and enter the folder
cd v0.3-MCP-Server

# 2. Activate your virtual environment
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and fill in .env
cp .env.example .env
# Edit .env with your DB credentials

# 5. Create the database
createdb inventory_db

# 6. Run the server
python3 server.py
```

Connect Claude Desktop by editing `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "inventory-v3": {
      "command": "/path/to/venv/bin/python3",
      "args": ["/path/to/v0.3-MCP-Server/server.py"]
    }
  }
}
```

### Option B — Run with Docker (portable)

**Prerequisites:** Docker Desktop

```bash
# 1. Copy and fill in .env
cp .env.example .env
# Edit .env with your credentials

# 2. Spin up both containers
docker compose up --build
```

You'll see:
```
inventory_postgres  | database system is ready to accept connections
inventory_mcp       | Database connection pool created (min=1, max=5)
inventory_mcp       | Database seeded with 5 products
inventory_mcp       | MCP Inventory Server v0.3 starting...
```

To stop:
```bash
docker compose down
```

To stop and wipe the database volume:
```bash
docker compose down -v
```

---

## Failure Analysis

### What breaks and how v0.3 handles it

| Failure | v0.2 behaviour | v0.3 behaviour |
|---|---|---|
| Product not found | Returns `null`, Claude confused | Returns `{"error": "Product 'X' not found"}` |
| Negative quantity | DB constraint error, server crashes | `ValueError` caught, returns clean error message |
| Empty product name | Empty string hits DB, returns nothing | Caught before DB call, returns validation error |
| DB connection drops | Unhandled exception, server crashes | `psycopg2.Error` caught, connection returned to pool, error returned to Claude |
| No `.env` file | Hardcoded values used silently | Warning logged, falls back to defaults |
| No API key set | N/A | Warning logged on startup |

### What v0.3 still doesn't do
- **Enforce** API key rejection (warns but doesn't block)
- **Retry** failed DB connections automatically
- **Rate limit** tool calls
- **Persist logs** to a file

These are intentional — they belong in v0.4+.

---

## .gitignore

Make sure these are in your `.gitignore`:

```
.env
__pycache__/
*.pyc
venv/
inventory.db
```

Never commit `.env` — it contains your DB password and API key.

---

## Tech Stack

| Tool | Purpose | Cost |
|---|---|---|
| Claude Desktop | AI interface | Free |
| Python 3.13 | Runtime | Free |
| `mcp[cli]` | MCP SDK | Free |
| `psycopg2-binary` | PostgreSQL driver | Free |
| `python-dotenv` | `.env` file loader | Free |
| PostgreSQL 16 | Database | Free |
| Docker Desktop | Containerization | Free |

**Total cost: $0**

---

## What's Next — v0.4

In v0.4 we introduce **A2A (Agent-to-Agent)** communication. Two agents talk directly to each other:
- An **Inventory Agent** pings an **Order Agent** via A2A protocol
- Side-by-side comparison: A2A handshake vs direct API call
- First look at multi-agent coordination