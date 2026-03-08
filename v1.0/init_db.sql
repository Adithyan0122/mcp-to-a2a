-- Supply Chain v1.0 — Database Initialization
-- Run against supply_chain_v1 database

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Core Tables (from v0.9) ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS inventory (
    id         SERIAL PRIMARY KEY,
    product    TEXT           NOT NULL UNIQUE,
    quantity   INTEGER        DEFAULT 0,
    price      NUMERIC(10,2)  DEFAULT 0.00,
    updated_at TIMESTAMPTZ    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id            SERIAL PRIMARY KEY,
    product       TEXT           NOT NULL,
    quantity      INTEGER        NOT NULL,
    supplier      TEXT           NOT NULL,
    unit_price    NUMERIC(10,2)  NOT NULL,
    total_price   NUMERIC(10,2)  NOT NULL,
    delivery_days INTEGER        NOT NULL,
    score         NUMERIC(6,4),
    status        TEXT           DEFAULT 'confirmed',
    created_at    TIMESTAMPTZ    DEFAULT NOW()
);

-- ── Memory Tables (v1.0) ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_memory (
    id          SERIAL PRIMARY KEY,
    agent       TEXT        NOT NULL,
    memory_type TEXT        NOT NULL,
    content     TEXT        NOT NULL,
    embedding   vector(1536),
    metadata    JSONB       DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS supplier_performance (
    id              SERIAL PRIMARY KEY,
    supplier        TEXT        NOT NULL,
    product         TEXT        NOT NULL,
    promised_days   INTEGER,
    actual_days     INTEGER,
    unit_price      NUMERIC(10,2),
    quality_score   NUMERIC(3,2),
    order_id        INTEGER REFERENCES orders(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS price_events (
    id          SERIAL PRIMARY KEY,
    product     TEXT           NOT NULL,
    old_price   NUMERIC(10,2),
    new_price   NUMERIC(10,2),
    pct_change  NUMERIC(6,2),
    source      TEXT,
    created_at  TIMESTAMPTZ    DEFAULT NOW()
);

-- ── Finance Tables (v1.0) ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS budget (
    id           SERIAL PRIMARY KEY,
    month        TEXT        NOT NULL UNIQUE,
    total_budget NUMERIC(12,2) DEFAULT 50000.00,
    spent        NUMERIC(12,2) DEFAULT 0.00,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS budget_transactions (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER REFERENCES orders(id),
    amount      NUMERIC(12,2),
    approved    BOOLEAN,
    reason      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ─────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_agent_memory_agent ON agent_memory(agent);
CREATE INDEX IF NOT EXISTS idx_agent_memory_type ON agent_memory(memory_type);
CREATE INDEX IF NOT EXISTS idx_supplier_perf_supplier ON supplier_performance(supplier);
CREATE INDEX IF NOT EXISTS idx_price_events_product ON price_events(product);
CREATE INDEX IF NOT EXISTS idx_budget_month ON budget(month);

-- ── Seed Data ───────────────────────────────────────────────────────────────

INSERT INTO inventory (product, quantity, price) VALUES
    ('Laptop',   10, 999.99),
    ('Mouse',    50,  29.99),
    ('Keyboard', 30,  79.99),
    ('Monitor',   8, 349.99),
    ('Webcam',   20,  89.99)
ON CONFLICT (product) DO NOTHING;

-- Seed current month budget
INSERT INTO budget (month, total_budget, spent) VALUES
    (TO_CHAR(NOW(), 'YYYY-MM'), 50000.00, 0.00)
ON CONFLICT (month) DO NOTHING;
