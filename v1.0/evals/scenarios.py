"""
Eval Scenarios — Supply Chain v1.0
Test scenario definitions for the evaluation framework.
"""

SCENARIOS = [
    {
        "name": "standard_restock",
        "description": "Normal low stock detected for Monitor and Laptop — expects bidding + order",
        "setup": {
            "inventory_overrides": {
                "Monitor": {"quantity": 8},
                "Laptop": {"quantity": 10},
            },
            "budget": 50000,
        },
        "expected": {
            "orders_placed": 2,
            "winner_in": ["SupplierA", "SupplierB", "SupplierC"],
            "emails_sent_min": 2,
            "pipeline_completed": True,
        },
        "timeout_s": 60,
    },
    {
        "name": "budget_constrained",
        "description": "Budget is too low — Finance Agent should escalate",
        "setup": {
            "inventory_overrides": {
                "Monitor": {"quantity": 8},
            },
            "budget": 500,  # Very low budget
        },
        "expected": {
            "finance_escalated": True,
            "orders_placed": 0,
            "pipeline_completed": True,
        },
        "timeout_s": 60,
    },
    {
        "name": "supplier_b_down",
        "description": "Supplier B is offline — circuit breaker should trigger, other suppliers handle it",
        "setup": {
            "inventory_overrides": {
                "Monitor": {"quantity": 8},
            },
            "supplier_b_offline": True,
            "budget": 50000,
        },
        "expected": {
            "winner_in": ["SupplierA", "SupplierC"],
            "circuit_breaker_triggered": True,
            "orders_placed": 1,
            "pipeline_completed": True,
        },
        "timeout_s": 60,
    },
    {
        "name": "all_stock_healthy",
        "description": "All products above threshold — no orders should be placed",
        "setup": {
            "inventory_overrides": {
                "Laptop": {"quantity": 50},
                "Mouse": {"quantity": 50},
                "Keyboard": {"quantity": 50},
                "Monitor": {"quantity": 50},
                "Webcam": {"quantity": 50},
            },
            "budget": 50000,
        },
        "expected": {
            "orders_placed": 0,
            "pipeline_completed": True,
            "pipeline_steps": ["price_sync"],
        },
        "timeout_s": 30,
    },
]

METRICS = [
    "correct_supplier_selected",
    "correct_quantity_ordered",
    "pipeline_completed",
    "latency_under_threshold",
    "emails_sent_correctly",
    "budget_respected",
    "circuit_breaker_triggered",
]
