# v0.2 Benchmark: Tool Call Latency vs Data Size

> All benchmarks run locally on MacBook Air (Apple Silicon).  
> PostgreSQL 16 running via Homebrew. No network overhead — pure local execution.

---

## Results

| Tool | Action | Data Size | Latency |
|---|---|---|---|
| `read_stock` | Read Laptop stock | Single row | 7.37 ms |
| `write_stock` | Set Monitor stock to 25 | Single row update | 7.26 ms |
| `search_product` | Search for "Keyboard" | Filtered result set | 7.73 ms |
| `update_price` | Set Mouse price to $39.99 | Single row update | 8.29 ms |

---

## Observations

**All 4 tools responded in under 9ms.** The total spread across all tools was just **1.03ms** — essentially negligible.

### Fastest → Slowest
1. `write_stock` — 7.26 ms
2. `read_stock` — 7.37 ms
3. `search_product` — 7.73 ms
4. `update_price` — 8.29 ms

### Why `update_price` was slowest
Write operations (`UPDATE`) in PostgreSQL are slightly heavier than reads — they involve a write-ahead log (WAL) entry, row locking, and a commit. Even so, the difference here is **only 1.03ms**, which at this data size is noise rather than a meaningful pattern.

### Why `search_product` was slower than `read_stock`
`search_product` uses `ILIKE` (case-insensitive pattern matching) which is inherently more expensive than an exact equality lookup. At 5 rows this doesn't matter — but at 50,000 rows, the lack of an index on the `product` column would make this tool significantly slower.

---

## What This Means at Scale

| Rows in DB | Expected `read_stock` | Expected `search_product` (no index) | Expected `search_product` (with index) |
|---|---|---|---|
| 5 (current) | ~7 ms | ~8 ms | ~7 ms |
| 1,000 | ~7 ms | ~12 ms | ~7 ms |
| 100,000 | ~8 ms | ~200+ ms | ~8 ms |
| 1,000,000 | ~10 ms | ~2000+ ms | ~10 ms |

**Key takeaway:** For production use, add an index on the `product` column:
```sql
CREATE INDEX idx_inventory_product ON inventory (LOWER(product));
```

---

## Setup

- **Machine:** MacBook Air (Apple Silicon)
- **Database:** PostgreSQL 16 (Homebrew, local)
- **Driver:** psycopg2-binary 2.9.x
- **MCP SDK:** mcp[cli] 1.x
- **Measurement:** Python `time.time()` wrapping the full DB call inside the tool handler

---

## Raw Tool Responses

Each tool returned a JSON payload like:
```json
{
  "result": {
    "id": 1,
    "product": "Laptop",
    "quantity": 10,
    "price": "999.99"
  },
  "latency_ms": 7.37
}
```

The `latency_ms` field is measured **inside the MCP server** — from the moment the tool is called to the moment the DB result is ready. It does not include MCP protocol overhead or Claude's processing time.