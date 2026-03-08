# 05 - Shared Infrastructure & Tech Stack

This document details the connective tissue that allows the 9 independent microservices to function as a cohesive, intelligent whole.

## PostgreSQL & `pgvector`

The system abandons the traditional Model Context Protocol (where the LLM holds all state) in favor of a robust, persistent database layer.

*   **Relational Data:** PostgreSQL 16 handles all standard relational requirements, ensuring ACID compliance for critical tables like `inventory`, `orders`, and `budget`.
*   **Vector Search (`pgvector`):** The `agent_memory` table utilizes the `pgvector` extension. Every significant decision an agent makes is embedded into a 1536-dimensional vector using OpenAI's embedding model. This allows the agents to perform similarity searches on past decisions, effectively giving the AI a "memory" of prior supply chain conditions and the outcomes of its actions.

## Redis & Celery

To prevent the system from becoming a tangled mess of synchronous HTTP requests, it heavily relies on event-driven architecture.

*   **Redis 7 (Broker & Result Backend):** Redis handles all transient messages. It serves as the incredibly fast, in-memory message broker for the background workers, and as the Pub/Sub mechanism for real-time WebSocket events.
*   **Celery Workers:** The `celery-worker` container is the heartbeat of the autonomous portions of the system. It runs continuous polling jobs (like `tick_pricing` or `check_stock`). Instead of a long-running synchronous process, an agent can queue a massive operation (like a multi-supplier negotiation) into Celery and return a response immediately.

## The LLM Core (Google Gemini 2.5 Flash)

All "reasoning" within the system is offloaded to the `shared/llm.py` utility, which wraps the Google GenAI SDK.

*   **Gemini 2.5 Flash:** Chosen for its extremely low latency and high reasoning capability, making it perfect for real-time, high-volume automated decision making.
*   **System Prompts:** Every call to the LLM is wrapped in strict System Instructions to define the persona (e.g., "You are an expert procurement officer...") and the expected JSON output format.
*   **Structured Output:** The system strictly enforces JSON outputs from the LLM to easily parse decisions (like chosen supplier, calculated price, or logical reasoning strings) back into the Python application layer.

## The API Gateway & Frontend

*   **API Gateway:** A single entry point (`localhost:8080`) that handles all incoming traffic. This simplifies the Next.js frontend, as it only needs to point to one URL rather than tracking all 9 microservices. It also centralizes WebSocket management for real-time dashboard updates.
*   **Next.js Dashboard:** Built with Next.js 14, TailwindCSS, and Recharts, it presents a unified view of the entire AI supply chain, visualizing the data flowing through PostgreSQL and the events emitted by Redis.
