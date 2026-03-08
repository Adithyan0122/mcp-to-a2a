"""
Centralized Configuration — Supply Chain v1.0
Loads environment variables with defaults for all services.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/supply_chain_v1")
DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "supply_chain_v1"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", "postgres"),
}

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ── API Keys ──────────────────────────────────────────────────────────────────
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")

# ── LangSmith ─────────────────────────────────────────────────────────────────
_tracing = os.getenv("LANGCHAIN_TRACING_V2", "true").lower() == "true"
LANGCHAIN_API_KEY     = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT     = os.getenv("LANGCHAIN_PROJECT", "supply-chain-v1.0")
LANGCHAIN_TRACING_V2  = "true" if (_tracing and LANGCHAIN_API_KEY) else "false"

# Update environment for LangChain library
os.environ["LANGCHAIN_TRACING_V2"] = LANGCHAIN_TRACING_V2
if LANGCHAIN_API_KEY:
    os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY
os.environ["LANGCHAIN_PROJECT"] = LANGCHAIN_PROJECT

# ── Agent URLs ────────────────────────────────────────────────────────────────
MARKET_API_URL         = os.getenv("MARKET_API_URL",         "http://localhost:9000")
PRICING_AGENT_URL      = os.getenv("PRICING_AGENT_URL",      "http://localhost:9001")
INVENTORY_AGENT_URL    = os.getenv("INVENTORY_AGENT_URL",    "http://localhost:8000")
SUPPLIER_A_URL         = os.getenv("SUPPLIER_A_URL",         "http://localhost:8011")
SUPPLIER_B_URL         = os.getenv("SUPPLIER_B_URL",         "http://localhost:8012")
SUPPLIER_C_URL         = os.getenv("SUPPLIER_C_URL",         "http://localhost:8013")
ORDER_AGENT_URL        = os.getenv("ORDER_AGENT_URL",        "http://localhost:8001")
NOTIFICATION_AGENT_URL = os.getenv("NOTIFICATION_AGENT_URL", "http://localhost:8002")
FINANCE_AGENT_URL      = os.getenv("FINANCE_AGENT_URL",      "http://localhost:8003")
API_GATEWAY_URL        = os.getenv("API_GATEWAY_URL",        "http://localhost:8080")

# ── SMTP ──────────────────────────────────────────────────────────────────────
SMTP_HOST       = os.getenv("SMTP_HOST",       "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT",   587))
SMTP_USER       = os.getenv("SMTP_USER",       "")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD",   "")
ALERT_RECIPIENT = os.getenv("ALERT_RECIPIENT", "")

# ── Finance ───────────────────────────────────────────────────────────────────
MONTHLY_BUDGET         = float(os.getenv("MONTHLY_BUDGET",         50000))
BUDGET_AUTO_APPROVE_PCT = float(os.getenv("BUDGET_AUTO_APPROVE_PCT", 0.30))
BUDGET_ESCALATE_PCT     = float(os.getenv("BUDGET_ESCALATE_PCT",     0.70))

# ── Pipeline ──────────────────────────────────────────────────────────────────
RESTOCK_THRESHOLD = int(os.getenv("RESTOCK_THRESHOLD", 15))
DEADLINE_DAYS     = int(os.getenv("DEADLINE_DAYS",     6))

# ── Gateway ───────────────────────────────────────────────────────────────────
API_KEY = os.getenv("API_KEY", "dev-key-12345")

ALL_AGENT_URLS = {
    "market-api":         MARKET_API_URL,
    "pricing-agent":      PRICING_AGENT_URL,
    "inventory-agent":    INVENTORY_AGENT_URL,
    "supplier-a":         SUPPLIER_A_URL,
    "supplier-b":         SUPPLIER_B_URL,
    "supplier-c":         SUPPLIER_C_URL,
    "order-agent":        ORDER_AGENT_URL,
    "notification-agent": NOTIFICATION_AGENT_URL,
    "finance-agent":      FINANCE_AGENT_URL,
}
