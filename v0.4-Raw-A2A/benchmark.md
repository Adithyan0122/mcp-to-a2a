# v0.4 Benchmark: A2A Handshake vs Direct API Call

> Measured locally on MacBook Air (Apple Silicon).  
> Order Agent running via uvicorn on localhost:8001.  
> Inventory Agent connecting to local PostgreSQL 16.

---

## Setup

- **Inventory DB:** PostgreSQL 16, `inventory_db`, 5 products
- **Orders DB:** PostgreSQL 16, `orders_db`
- **Low stock products detected:** 1 (Laptop — 10 units, threshold 15)
- **Restock quantity:** 20 units per order

---

## Results

### Discovery Step (one-time per run)

| Step | Latency |
|---|---|
| GET `/.well-known/agent.json` | 49.61ms |

### Per-Call Comparison

| Product | A2A (ms) | Direct (ms) | Overhead (ms) |
|---|---|---|---|
| Laptop | 24.0 | 23.7 | 0.3 |

### Total Comparison

| Mode | Total Latency | Includes |
|---|---|---|
| A2A | 73.61ms | Discovery (49.61ms) + task call (24.0ms) |
| Direct | 23.7ms | Task call only |
| Overhead | 49.91ms | Almost entirely discovery |

---

## Analysis

### Finding 1 — Per-call A2A overhead is 0.3ms

Once discovery is done, A2A task calls are **0.3ms slower** than direct API calls. This is noise — not a meaningful difference. The protocol itself adds almost zero overhead.

### Finding 2 — Discovery is the real cost (49.61ms)

The Agent Card fetch is an extra HTTP GET request. At ~50ms locally, this would be higher over a real network (add ~20–100ms depending on geography). But this is a **one-time cost per session** — not per call.

### Finding 3 — Cache the Agent Card

In production, an agent should:
1. Fetch the Agent Card once on startup
2. Cache it in memory
3. Re-fetch only if a request fails (treat it like a circuit breaker)

With caching, A2A is effectively free after the first call.

---

## Projected Latency at Scale

### Scenario: 100 restock orders per run

| Mode | Latency (no cache) | Latency (with card cache) |
|---|---|---|
| Direct API | 100 × 23.7ms = 2,370ms | 2,370ms |
| A2A | 49.61ms + (100 × 24.0ms) = 2,449ms | 49.61ms + 2,400ms = 2,449ms |
| A2A overhead | +79ms total | +49.61ms (discovery only) |

Even at 100 orders, A2A adds less than 80ms total — well within acceptable range for a background restock job.

### Scenario: 10 different agents discovered per run

| Mode | Discovery cost | Per-call cost | Total (10 agents, 1 call each) |
|---|---|---|---|
| Direct | 0ms | 23.7ms | 237ms |
| A2A (no cache) | 10 × 49.61ms = 496ms | 10 × 24ms = 240ms | 736ms |
| A2A (with cache) | 49.61ms × 1 per agent | 240ms | ~736ms first run, ~240ms after |

**Key takeaway:** Without caching, A2A discovery becomes expensive when talking to many agents. With caching, it converges to direct API performance after the first run.

---

## When A2A Is Worth It vs When It Isn't

### ✅ Worth it when:
- You have **multiple agents** that need to discover each other dynamically
- Agents are **deployed independently** and their URLs may change
- You want **capability negotiation** — agents decide at runtime whether they can help
- Building toward a **multi-agent mesh** where agents come and go

### ❌ Not worth it when:
- You have **2 fixed services** that always talk to each other — just use a direct API call
- **Latency is critical** and you can't afford even the one-time discovery cost
- You control both agents and they'll **never change capabilities**

---

## Raw Log Output

```
2026-03-08T15:39:05 [INFO] Inventory Agent started
2026-03-08T15:39:05 [INFO] Restock threshold: 15 units
2026-03-08T15:39:05 [INFO] Laptop       qty= 10  price=$999.99 ⚠️  LOW STOCK
2026-03-08T15:39:05 [INFO] 1 product(s) need restocking
2026-03-08T15:39:05 [INFO] Agent Card fetched in 49.61ms — capabilities: ['place_order']
2026-03-08T15:39:06 [INFO] Laptop: A2A=24.0ms | Direct=23.7ms | status=success

── Benchmark Summary ──────────────────────────────────
  Agent Card discovery: 49.61ms (one-time overhead)
  Product      A2A (ms)     Direct (ms)    Overhead (ms)
  ----------------------------------------------------
  Laptop       24.0         23.7           0.3

  Total A2A latency:    73.61ms (incl. discovery)
  Total Direct latency: 23.7ms
  A2A overhead:         49.91ms

✅ Inventory Agent completed successfully
```

---

## Methodology

- **A2A latency** = time from sending POST `/a2a` to receiving response (measured with `time.time()` in Python)
- **Direct latency** = identical POST request, no prior discovery step
- **Discovery latency** = time for GET `/.well-known/agent.json`
- All measurements taken on the same machine, same network (localhost)
- No connection pooling on the HTTP client (httpx default)
- Results are single-run — for production benchmarks, take median of 100+ runs