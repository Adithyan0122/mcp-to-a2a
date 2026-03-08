"""
Memory Client — Supply Chain v1.0
Semantic memory using pgvector for all agents.
Stores decisions, supplier performance, and price events.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras
from langsmith import traceable

from shared.config import DB_CONFIG

log = logging.getLogger("memory")

# We use OpenAI text-embedding-3-small for embeddings
# If unavailable, we skip embedding storage
try:
    import openai
    from shared.config import OPENAI_API_KEY
    _openai_client = openai.OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except ImportError:
    _openai_client = None

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def _get_embedding(text: str) -> list[float] | None:
    """Get embedding vector for text. Returns None if unavailable."""
    if not _openai_client:
        return None
    try:
        response = _openai_client.embeddings.create(
            model=EMBEDDING_MODEL, input=text
        )
        return response.data[0].embedding
    except Exception as e:
        log.warning(f"Embedding failed: {e}")
        return None


class MemoryClient:
    """Shared memory interface for all agents using pgvector."""

    def __init__(self):
        self._db_config = DB_CONFIG

    def _conn(self):
        return psycopg2.connect(**self._db_config)

    @traceable(name="memory_store")
    def store(self, agent: str, memory_type: str, content: str, metadata: dict = None) -> int:
        """Store a memory with optional vector embedding."""
        embedding = _get_embedding(content)
        conn = self._conn()
        cur = conn.cursor()
        if embedding:
            cur.execute(
                """INSERT INTO agent_memory (agent, memory_type, content, embedding, metadata)
                   VALUES (%s, %s, %s, %s::vector, %s) RETURNING id""",
                (agent, memory_type, content, str(embedding), json.dumps(metadata or {})),
            )
        else:
            cur.execute(
                """INSERT INTO agent_memory (agent, memory_type, content, metadata)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (agent, memory_type, content, json.dumps(metadata or {})),
            )
        mem_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return mem_id

    @traceable(name="memory_search")
    def search(self, query: str, agent: str = None, limit: int = 5) -> list:
        """Semantic similarity search over agent memories."""
        embedding = _get_embedding(query)
        conn = self._conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if embedding:
            if agent:
                cur.execute(
                    """SELECT id, agent, memory_type, content, metadata, created_at,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM agent_memory
                       WHERE agent = %s AND embedding IS NOT NULL
                       ORDER BY embedding <=> %s::vector
                       LIMIT %s""",
                    (str(embedding), agent, str(embedding), limit),
                )
            else:
                cur.execute(
                    """SELECT id, agent, memory_type, content, metadata, created_at,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM agent_memory
                       WHERE embedding IS NOT NULL
                       ORDER BY embedding <=> %s::vector
                       LIMIT %s""",
                    (str(embedding), str(embedding), limit),
                )
        else:
            # Fallback: text search
            if agent:
                cur.execute(
                    """SELECT id, agent, memory_type, content, metadata, created_at
                       FROM agent_memory WHERE agent = %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (agent, limit),
                )
            else:
                cur.execute(
                    """SELECT id, agent, memory_type, content, metadata, created_at
                       FROM agent_memory ORDER BY created_at DESC LIMIT %s""",
                    (limit,),
                )

        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        for r in rows:
            r["created_at"] = str(r["created_at"])
            if isinstance(r.get("metadata"), str):
                try:
                    r["metadata"] = json.loads(r["metadata"])
                except:
                    pass
        return rows

    @traceable(name="memory_get_supplier_history")
    def get_supplier_history(self, supplier: str, product: str = None) -> dict:
        """Get aggregate supplier performance data."""
        conn = self._conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query = "SELECT * FROM supplier_performance WHERE supplier = %s"
        params = [supplier]
        if product:
            query += " AND product = %s"
            params.append(product)
        query += " ORDER BY created_at DESC LIMIT 20"

        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()

        if not rows:
            return {"supplier": supplier, "total_orders": 0}

        avg_price = sum(float(r.get("unit_price", 0)) for r in rows) / len(rows)
        avg_delivery = sum(r.get("actual_days", r.get("promised_days", 0)) for r in rows) / len(rows)
        on_time = sum(1 for r in rows if r.get("actual_days", 999) <= r.get("promised_days", 0))
        avg_quality = sum(float(r.get("quality_score", 0.5)) for r in rows) / len(rows)

        return {
            "supplier": supplier,
            "total_orders": len(rows),
            "avg_unit_price": round(avg_price, 2),
            "avg_delivery_days": round(avg_delivery, 1),
            "on_time_pct": round(on_time / len(rows) * 100, 1) if rows else 0,
            "avg_quality_score": round(avg_quality, 2),
        }

    @traceable(name="memory_get_price_history")
    def get_price_history(self, product: str, days: int = 30) -> list:
        """Get price event history for a product."""
        conn = self._conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        since = datetime.utcnow() - timedelta(days=days)
        cur.execute(
            """SELECT * FROM price_events
               WHERE product = %s AND created_at >= %s
               ORDER BY created_at DESC LIMIT 100""",
            (product, since),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        for r in rows:
            r["created_at"] = str(r["created_at"])
            r["old_price"] = str(r["old_price"])
            r["new_price"] = str(r["new_price"])
            r["pct_change"] = str(r["pct_change"])
        return rows

    def record_supplier_performance(
        self, supplier: str, product: str, promised_days: int,
        actual_days: int, unit_price: float, quality_score: float = 0.8,
        order_id: int = None
    ):
        """Record supplier delivery performance."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO supplier_performance
               (supplier, product, promised_days, actual_days, unit_price, quality_score, order_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (supplier, product, promised_days, actual_days, unit_price, quality_score, order_id),
        )
        conn.commit()
        cur.close()
        conn.close()

    def record_price_event(
        self, product: str, old_price: float, new_price: float,
        pct_change: float, source: str = "market_sync"
    ):
        """Record a price change event."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO price_events (product, old_price, new_price, pct_change, source)
               VALUES (%s, %s, %s, %s, %s)""",
            (product, old_price, new_price, pct_change, source),
        )
        conn.commit()
        cur.close()
        conn.close()

    @traceable(name="memory_record_decision")
    def record_decision(self, agent: str, decision: dict, outcome: dict = None):
        """Record an LLM decision for tracing and analysis."""
        content = json.dumps(decision)
        metadata = {"outcome": outcome} if outcome else {}
        self.store(agent, "decision", content, metadata)
