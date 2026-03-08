# v0.4 — Raw A2A: Two Agents Talking to Each Other

> Introduce Agent-to-Agent (A2A) communication. The Inventory Agent detects low stock and autonomously pings the Order Agent to place a restock order — no human in the loop.

---

## What Is A2A?

**A2A (Agent-to-Agent)** is an open protocol by Google that lets AI agents discover and communicate with each other in a standardized way.

Instead of hardcoding "call this URL with this payload", A2A adds a **discovery layer**:

1. Every agent publishes an **Agent Card** at `/.well-known/agent.json`
2. Other agents fetch this card to learn what the agent can do
3. Then they send structured **task requests**

Think of it like DNS for agents — you look up who's there and what they can do before talking to them.

---

## What This Project Does

Two agents run independently and communicate autonomously:

```
Inventory Agent                        Order Agent
─────────────────                      ─────────────────
1. Read inventory_db                   Serves Agent Card
2. Find low stock products             Receives A2A requests
3. Fetch Order Agent's card   ──────►  Returns capabilities
4. Send restock request       ──────►  Creates order in orders_db
5. Benchmark A2A vs direct             Returns order confirmation
```

No Claude Desktop involved. No human triggering anything. The Inventory Agent runs, detects a problem, and fixes it by talking to another agent.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        YOUR MACHINE                              │
│                                                                  │
│  ┌──────────────────────────┐     ┌──────────────────────────┐  │
│  │     Inventory Agent       │     │       Order Agent         │  │
│  │  inventory_agent.py       │     │    order_agent.py         │  │
│  │                           │     │                           │  │
│  │  1. Read inventory_db     │     │  GET /.well-known/        │  │
│  │  2. Find low stock        │     │      agent.json           │  │
│  │  3. Fetch Agent Card ─────┼────►│                           │  │
│  │  4. Send A2A request ─────┼────►│  POST /a2a               │  │
│  │  5. Log benchmark         │     │  Write to orders_db       │  │
│  └──────────┬────────────────┘     └──────────┬───────────────┘  │
│             │                                  │                  │
│             │ psycopg2                         │ psycopg2         │
│             ▼                                  ▼                  │
│  ┌──────────────────────┐        ┌──────────────────────────┐    │
│  │    inventory_db       │        │        orders_db          │    │
│  │    (PostgreSQL)       │        │       (PostgreSQL)        │    │
│  │                       │        │                           │    │
│  │  inventory table      │        │  orders table             │    │
│  │  product, qty, price  │        │  product, qty, status     │    │
│  └──────────────────────┘        └──────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### A2A Communication Flow

```
Inventory Agent                         Order Agent
      │                                      │
      │  GET /.well-known/agent.json         │
      │─────────────────────────────────────►│
      │  ◄── Agent Card (capabilities) ──────│  ~49ms (discovery)
      │                                      │
      │  POST /a2a                           │
      │  { task: place_order,                │
      │    product: Laptop, qty: 20 }        │
      │─────────────────────────────────────►│
      │  ◄── { status: success, order: {...} }│  ~24ms (task)
      │                                      │
```

---

## Project Structure

```
v0.4-Raw-A2A/
├── requirements.txt
├── inventory-agent/
│   ├── inventory_agent.py   ← detects low stock, sends A2A requests
│   └── .env                 ← points to inventory_db + order agent URL
└── order-agent/
    ├── order_agent.py       ← HTTP server, handles A2A requests, writes orders
    └── .env                 ← points to orders_db
```

---

## The Two Agents

### Inventory Agent (`inventory_agent.py`)

A script that runs on demand (or on a schedule in production):

1. Connects to `inventory_db` and reads all products
2. Finds products below the restock threshold (default: 15 units)
3. Fetches the Order Agent's **Agent Card** to verify it's alive and capable
4. Sends an A2A `place_order` task for each low-stock product
5. Runs the same request as a **direct API call** for benchmarking
6. Prints a full benchmark summary

**Config via `.env`:**
```
DB_NAME=inventory_db
DB_USER=your_user
DB_HOST=localhost
DB_PORT=5432
ORDER_AGENT_URL=http://localhost:8001
RESTOCK_THRESHOLD=15
RESTOCK_QUANTITY=20
```

### Order Agent (`order_agent.py`)

A FastAPI HTTP server that runs continuously on port 8001:

| Endpoint | Method | Purpose |
|---|---|---|
| `/.well-known/agent.json` | GET | Serve Agent Card (A2A discovery) |
| `/a2a` | POST | Receive task requests from other agents |
| `/orders` | GET | View all placed orders |

**Agent Card:**
```json
{
  "name": "Order Agent",
  "description": "Receives restock requests and creates orders",
  "version": "0.4.0",
  "url": "http://localhost:8001",
  "capabilities": ["place_order"]
}
```

**A2A Request format:**
```json
{ "task": "place_order", "product": "Laptop", "quantity": 20 }
```

**A2A Response format:**
```json
{
  "status": "success",
  "message": "Order placed for 20x Laptop",
  "order": {
    "id": 2,
    "product": "Laptop",
    "quantity": 20,
    "status": "placed",
    "created_at": "2026-03-08T15:39:06"
  }
}
```

---

## Setup & Running

### Prerequisites
- Python 3.10+
- PostgreSQL 16
- Both databases created:

```bash
createdb inventory_db   # reuse from v0.2/v0.3
createdb orders_db      # new for v0.4
```

### Install dependencies
```bash
pip install -r requirements.txt
```

### Terminal 1 — Start Order Agent
```bash
cd order-agent
python3 order_agent.py
```
You should see:
```
Orders DB initialized
Order Agent starting on http://localhost:8001
Agent Card: http://localhost:8001/.well-known/agent.json
```

### Terminal 2 — Run Inventory Agent
```bash
cd inventory-agent
python3 inventory_agent.py
```

### Verify orders were placed
```bash
curl http://localhost:8001/orders
```

---

## A2A vs Direct API — Key Insight

The benchmark reveals something important:

| Step | Latency |
|---|---|
| Agent Card discovery | ~49ms (one-time) |
| A2A task call | ~24ms |
| Direct API call | ~23.7ms |
| Per-call A2A overhead | **0.3ms** |

**The A2A overhead per call is essentially zero (0.3ms).** The only real cost is the one-time discovery step (~49ms). Once an agent knows where another agent is, talking to it is just as fast as a direct API call.

This means A2A is worth it even for performance-sensitive systems — as long as you cache the Agent Card after the first discovery.

See `benchmark.md` for the full analysis.

---

## What I Learned

### 1. A2A discovery is a one-time cost
The 49ms Agent Card fetch happens once. If you cache the card (which production systems do), subsequent calls are indistinguishable from direct API calls in terms of latency.

### 2. Agent Cards are the key primitive
The Agent Card is what makes A2A different from just "two services calling each other". It's a machine-readable description of capabilities — agents can decide at runtime whether to talk to each other based on what they find in the card.

### 3. Two databases, two concerns
Keeping `inventory_db` and `orders_db` separate enforces clean boundaries. The Inventory Agent owns stock data. The Order Agent owns order data. Neither can directly mess with the other's DB.

### 4. stdio vs HTTP is a fundamental shift
MCP (v0.1–v0.3) used stdio — one process talking to Claude via pipes. A2A uses HTTP — agents running as independent servers talking over the network. This is what enables true multi-agent systems.

---

## What's Next — v0.5

In v0.5 we build proper **Agent Cards** for 3 agents and test **discovery between them** — the foundation of a real multi-agent mesh.

---

## Tech Stack

| Tool | Purpose | Cost |
|---|---|---|
| Python 3.13 | Runtime | Free |
| FastAPI | Order Agent HTTP server | Free |
| uvicorn | ASGI server | Free |
| httpx | Async HTTP client | Free |
| psycopg2-binary | PostgreSQL driver | Free |
| python-dotenv | Config from .env | Free |
| PostgreSQL 16 | Two databases | Free |

**Total cost: $0**