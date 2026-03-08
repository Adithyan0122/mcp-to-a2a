# 01 - System Architecture & Data Flow

## High-Level Overview

The AI Supply Chain System v1.0 is a state-of-the-art event-driven architecture that models a completely autonomous supply chain. It consists of **9 independent Python FastAPI microservices**, which communicate via asynchronous message queues (Redis/Celery) and direct REST API calls, backed by a robust PostgreSQL database incorporating vector search capabilities (`pgvector`). The system is visualized and monitored through a real-time Next.js 14 dashboard.

## Component Architecture

At its core, the system utilizes a **Hub-and-Spoke** combined with an **Event-Driven** model.

### 1. The Processing Layer
*   **PostgreSQL 16 (w/ pgvector):** The absolute source of truth. It stores:
    *   Current inventory levels (`inventory` table)
    *   Order history and tracking (`orders` table)
    *   Agent memories and embeddings (`agent_memory` table) for RAG (Retrieval-Augmented Generation) based decision making.
    *   Supplier performance metrics (`supplier_performance` table)
    *   Financial budgeting (`budget` and `budget_transactions` tables)
*   **Redis 7:** Acts as both the Pub/Sub message broker and the Celery backend, facilitating rapid, distributed communication between the agents without creating HTTP bottlenecks.
*   **Celery Workers:** Background processors that execute continuous polling tasks, such as triggering the Pricing Agent to check the market, and triggering the Inventory Agent to check stock levels.

### 2. The Agent Layer (Microservices)

The business logic is entirely distributed across specialized AI agents. Every agent runs on its own FastAPI container and is equipped with Google Gemini 2.5 Flash for reasoning.

*   **Market API (`market-api`):** Simulates real-world market volatility, providing simulated external price fluctuations.
*   **Pricing Agent (`pricing-agent`):** Continuously monitors the Market API and internal stock to dynamically adjust the selling price of inventory.
*   **Inventory Agent (`inventory-agent`):** The sentinel. It monitors stock levels and automatically initiates the restocking lifecycle when items drop below a predefined threshold.
*   **Supplier Agents (`supplier-a`, `supplier-b`, `supplier-c`):** Mock external vendors. Each has unique characteristics (e.g., Supplier A is fast but expensive, Supplier C is cheap but slow and less reliable).
*   **Order Agent (`order-agent`):** The negotiator. It receives quotes from the suppliers and uses an LLM to select the most optimal quote based on current business needs.
*   **Finance Agent (`finance-agent`):** The gatekeeper. It holds the purse strings, automatically approving routine orders while flagging expensive orders for review.
*   **Notification Agent (`notification-agent`):** The broadcaster. It pushes critical events out via WebSocket to the frontend and via Email to human administrators.

### 3. The Visualization Layer
*   **API Gateway (`api-gateway`):** A unified entry point that routes requests from the frontend to the appropriate internal microservices. It also handles WebSocket connections for real-time updates.
*   **Next.js Frontend (`frontend`):** A modern, dark-themed React dashboard built with TailwindCSS and Recharts. It subscribes to WebSocket events to update graphs and data tables instantly as the AI agents make decisions in the background.

## The A2A (Agent-to-Agent) Data Flow

The magic of this system happens in the continuous, unprompted communication between the agents. The primary workflow—the **Restock Pipeline**—looks like this:

1.  **Trigger:** A Celery beat schedule tells the `inventory-agent` to evaluate stock levels.
2.  **Detection:** The `inventory-agent` queries the DB. It notices that "Webcams" are below the `RESTOCK_THRESHOLD` of 15.
3.  **Solicitation (Parallel):** The `inventory-agent` fires off asynchronous API requests to `supplier-a`, `supplier-b`, and `supplier-c` asking for quotes on Webcams.
4.  **Bidding:** The suppliers respond with quotes containing price and delivery days.
5.  **Delegation:** The `inventory-agent` forwards the collected quotes to the `order-agent`.
6.  **Reasoning:** The `order-agent` constructs a prompt with the quotes and calls Google Gemini. Gemini evaluates the trade-offs (e.g., "Supplier A is $5 cheaper, but Supplier B delivers 2 days faster. We need this inventory immediately. Choose Supplier B.")
7.  **Financial Check:** The `order-agent` sends the proposed order to the `finance-agent`.
8.  **Approval:** The `finance-agent` checks the `MONTHLY_BUDGET`. If the order is below `BUDGET_AUTO_APPROVE_PCT` (e.g., 30% of total budget), it instantly marks it `approved=True` in the database.
9.  **Commitment:** The `order-agent` officially logs the order in the `orders` table.
10. **Notification:** Finally, a message is published to Redis. The `notification-agent` picks it up and pushes a WebSocket event to the dashboard, turning a pixel red on the user's screen instantly.

This entire sequence occurs in roughly 1-3 seconds, fully autonomously.
