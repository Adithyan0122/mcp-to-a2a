# 02 - The Market API & Pricing Agent

This document details the first segment of the autonomous cycle: how the system observes external realities and adjusts internal realities accordingly.

## The Market API (`market-api`)

Before any intelligent behavior can occur, the system needs an environment. In a real-world scenario, this would be live scraping of competitor prices or ingesting a commodity data feed. For this system, the environment is simulated by the Market API.

### Functionality
The Market API runs a continuous background generation loop utilizing Mathematical Finance models. 

*   **Geometric Brownian Motion (GBM):** The API simulates realistic asset price paths using GBM. 
*   **Volatility & Drift:** Environment variables `VOLATILITY` (e.g., 0.02) and `DRIFT` (e.g., 0.001) control the stochastic chaos of the market.
*   **Endpoints:** It exposes a `/market/{product}` endpoint that returns the dynamically generated "current market price" for any product in the catalog.

## The Pricing Agent (`pricing-agent`)

The Pricing Agent acts as the revenue optimization engine. Its fundamental goal is to continuously ensure that the system's inventory is priced competitively against the market, but also optimally against internal supply.

### The Polling Mechanism
The Pricing Agent is largely driven by the `celery-worker`. A scheduled task periodically hits the Pricing Agent's `/tick` or `/reprice` endpoints.

### The Decision Logic
When triggered, the Pricing Agent performs the following:

1.  **Gather Context:** It queries the Database for the current internal stock and price of a given product (e.g., "Laptops: 10 in stock, currently $999.99").
2.  **Observe Environment:** It calls the Market API to get the current external market price (e.g., "Market API says Laptops are trading at $1015.50").
3.  **LLM Reasoning:** It packages this context into a prompt and sends it to the Google Gemini model.
4.  **Strategic Adjustment:** The LLM acts as an economist. 
    *   If stock is high, it might suggest undercutting the market price slightly to move volume.
    *   If stock is critically low, it might suggest pricing significantly above the market to maximize margin on the remaining units.
5.  **Execution:** The Agent parses the LLM's response, extracting the new recommended numeric price. It then executes an `UPDATE` statement on the PostgreSQL `inventory` table and inserts a record into the `price_events` table for historical tracking.

### Vector Memory Integration
A critical feature of v1.0 is the introduction of `agent_memory` via `pgvector`.
As the Pricing Agent makes decisions, it stores the context, its decision, and the *outcome* into the vector database. 
Before making future pricing decisions, it can perform a similarity search to retrieve past scenarios: "The last time we had 10 laptops and the market spiked, we raised our price by 5%. How did that impact sales?" This allows the agent to iteratively improve its pricing models based on historical context rather than acting entirely statelessly.
