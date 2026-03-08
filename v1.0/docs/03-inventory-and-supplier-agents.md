# 03 - Inventory & Supplier Agents

This document covers the core supply chain logistics: monitoring internal stock and negotiating with external vendors.

## The Inventory Agent (`inventory-agent`)

The Inventory Agent is the watcher. It is responsible for ensuring the system never runs out of stock, while avoiding overstocking.

### The Restock Trigger
Similar to the Pricing Agent, the Inventory Agent is prodded by a scheduled `celery-worker` polling task. When executing its `/check_stock` workflow:
1.  **Monitor:** It queries the PostgreSQL `inventory` table for all items.
2.  **Evaluate:** It compares every `quantity` against the environment variable `RESTOCK_THRESHOLD` (e.g., 15).
3.  **Act:** If `quantity < RESTOCK_THRESHOLD` for an item (e.g., "Webcams"), it automatically initiates the **Restock Process**.

### The Restock Process
The Restock Process is a highly concurrent operation. The Inventory Agent does not rely on a single vendor. Instead, it utilizes the **Scatter-Gather** pattern.

*   It fires asynchronous HTTP GET requests to `SUPPLIER_A_URL/quote`, `SUPPLIER_B_URL/quote`, and `SUPPLIER_C_URL/quote` simultaneously.
*   Once all suppliers have responded, it aggregates the JSON quotes into a single payload.
*   It then POSTs this aggregated payload to the `order-agent` for the actual purchasing decision.

## The Supplier Agents (`supplier-a`, `supplier-b`, `supplier-c`)

These are mock services that represent external vendors in a real-world supply chain. They are designed to provide dynamic and realistic responses to demonstrate the `order-agent`'s reasoning capabilities.

### Supplier Characteristics
Each supplier is configured via environment variables to have distinct behaviors:

*   **Supplier A:** High `BASE_PRICE_MULTIPLIER` (1.2), short `DELIVERY_DAYS` (2), high `RELIABILITY` (0.95). They are expensive, but fast and dependable.
*   **Supplier B:** Standard `BASE_PRICE_MULTIPLIER` (1.0), average `DELIVERY_DAYS` (4), average `RELIABILITY` (0.90). The balanced option.
*   **Supplier C:** Low `BASE_PRICE_MULTIPLIER` (0.85), long `DELIVERY_DAYS` (7), low `RELIABILITY` (0.80). They are cheap, but very slow and prone to delays.

### Dynamic Quoting
When a Supplier receives a `/quote/{product}` request, it doesn't just return a static number. The supplier introduces an element of randomness:
*   The base price is perturbed by the `RELIABILITY` metric. A less reliable supplier might offer a much cheaper quote one day, and a surprisingly expensive one the next.
*   The delivery time might fluctuate slightly based on simulated availability.

These dynamically generated quotes are what allow the LLM in the `order-agent` to perform complex, unprompted trade-off analysis during the next step of the pipeline.
