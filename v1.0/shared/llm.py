"""
LLM Decision Wrapper — Supply Chain v1.0
Uses Google Gemini 1.5 Flash for intelligent supply chain decisions.
All responses are structured JSON with a reasoning field.
"""

import json
import logging
import time
from typing import Any

import google.generativeai as genai
from langsmith import traceable

from shared.config import GEMINI_API_KEY

log = logging.getLogger("llm")

SYSTEM_PROMPT = """You are a supply chain decision agent. You must respond ONLY in valid JSON.
No preamble, no explanation outside the JSON object.
Your decisions must be data-driven and include a "reasoning" field explaining your logic.
Always consider cost efficiency, delivery speed, reliability, and budget constraints."""

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

MODEL = "gemini-2.5-flash"


def _call_llm(prompt: str, max_retries: int = 3) -> dict:
    """Call Gemini with retry logic. Returns parsed JSON dict."""
    if not GEMINI_API_KEY:
        log.warning("No GEMINI_API_KEY — falling back to rule-based decision")
        return {}

    model = genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=SYSTEM_PROMPT,
        generation_config={"response_mime_type": "application/json", "max_output_tokens": 1024}
    )

    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(text)
        except json.JSONDecodeError as e:
            log.warning(f"LLM returned invalid JSON (attempt {attempt+1}): {e}")
            if attempt == max_retries - 1:
                return {"error": "invalid_json", "raw": text}
        except Exception as e:
            log.warning(f"LLM call failed (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                return {"error": str(e)}
    return {}


@traceable(name="llm_decide_supplier")
def decide_supplier(context: dict) -> dict:
    """
    Ask Gemini to pick the best supplier from accepted bids.
    Falls back to score-based selection if LLM is unavailable.
    """
    prompt = f"""Select the best supplier for restocking. Analyze all factors carefully.

Context:
- Product: {context.get('product')}
- Current stock: {context.get('current_stock')} units
- Restock threshold: {context.get('threshold', 15)} units
- Budget remaining: ${context.get('budget_remaining', 'unknown')}

Supplier bids:
{json.dumps(context.get('bids', []), indent=2)}

Supplier history (past performance):
{json.dumps(context.get('supplier_history', {}), indent=2)}

Respond with ONLY this JSON structure:
{{
    "winner": "<supplier name>",
    "reasoning": "<detailed explanation of why this supplier was chosen>",
    "confidence": <0.0 to 1.0>,
    "risk_factors": ["<list of concerns>"]
}}"""

    result = _call_llm(prompt)

    # Fallback to v0.9 logic if LLM fails
    if not result or "error" in result:
        bids = context.get("bids", [])
        if bids:
            winner = min(bids, key=lambda b: b.get("score", 999))
            return {
                "winner": winner.get("supplier"),
                "reasoning": "Fallback: selected by lowest score (LLM unavailable)",
                "confidence": 0.5,
                "risk_factors": ["llm_fallback"],
                "fallback": True,
            }
        return {"error": "no_bids"}

    return result


@traceable(name="llm_decide_restock_quantity")
def decide_restock_quantity(context: dict) -> dict:
    """
    Ask Gemini to determine the optimal restock quantity.
    Falls back to fixed quantity of 20 if LLM is unavailable.
    """
    prompt = f"""Determine the optimal restock quantity for this product.

Context:
- Product: {context.get('product')}
- Current stock: {context.get('current_stock')} units
- Restock threshold: {context.get('threshold', 15)} units
- Current unit price: ${context.get('unit_price', 'unknown')}
- Budget remaining: ${context.get('budget_remaining', 'unknown')}
- Winning supplier delivery days: {context.get('delivery_days', 'unknown')}

Price history (recent):
{json.dumps(context.get('price_history', [])[:10], indent=2)}

Respond with ONLY this JSON structure:
{{
    "quantity": <integer>,
    "reasoning": "<why this quantity is optimal>",
    "confidence": <0.0 to 1.0>,
    "estimated_days_of_stock": <how many days this quantity will last>
}}"""

    result = _call_llm(prompt)

    if not result or "error" in result or "quantity" not in result:
        return {
            "quantity": 20,
            "reasoning": "Fallback: default quantity of 20 (LLM unavailable)",
            "confidence": 0.5,
            "fallback": True,
        }

    return result


@traceable(name="llm_decide_reprice")
def decide_reprice(context: dict) -> dict:
    """
    Ask Gemini whether to update the inventory price based on market movement.
    Falls back to 5% threshold if LLM is unavailable.
    """
    prompt = f"""Decide whether to update the inventory price for this product based on market price movement.

Context:
- Product: {context.get('product')}
- Current DB price: ${context.get('db_price')}
- Current market price: ${context.get('market_price')}
- Price drift: {context.get('drift_pct', 0):.2f}%
- Market volatility (recent): {context.get('volatility', 'unknown')}

Recent price events:
{json.dumps(context.get('price_history', [])[:10], indent=2)}

Respond with ONLY this JSON structure:
{{
    "should_reprice": <true/false>,
    "reasoning": "<why or why not>",
    "confidence": <0.0 to 1.0>,
    "suggested_price": <the price to set, if repricing>
}}"""

    result = _call_llm(prompt)

    if not result or "error" in result:
        drift = abs(context.get("drift_pct", 0)) / 100
        return {
            "should_reprice": drift >= 0.05,
            "reasoning": f"Fallback: {'drift exceeds' if drift >= 0.05 else 'drift below'} 5% threshold (LLM unavailable)",
            "confidence": 0.5,
            "suggested_price": context.get("market_price"),
            "fallback": True,
        }

    return result


@traceable(name="llm_decide_budget_approval")
def decide_budget_approval(context: dict) -> dict:
    """
    Ask Gemini whether to approve a spend that falls in the mid-range (30-70% of remaining budget).
    """
    prompt = f"""Decide whether to approve this purchase order.

Context:
- Product: {context.get('product')}
- Order total: ${context.get('total_price')}
- Monthly budget: ${context.get('monthly_budget')}
- Already spent this month: ${context.get('spent')}
- Remaining budget: ${context.get('remaining')}
- Spend as % of remaining: {context.get('spend_pct', 0):.1f}%
- Supplier: {context.get('supplier')}
- Urgency (current stock): {context.get('current_stock')} units

Recent spending:
{json.dumps(context.get('recent_transactions', [])[:5], indent=2)}

Respond with ONLY this JSON structure:
{{
    "approved": <true/false>,
    "reasoning": "<detailed explanation>",
    "confidence": <0.0 to 1.0>,
    "suggested_action": "<approve/reject/reduce_quantity>"
}}"""

    result = _call_llm(prompt)

    if not result or "error" in result:
        return {
            "approved": True,
            "reasoning": "Fallback: auto-approved (LLM unavailable, within budget range)",
            "confidence": 0.5,
            "suggested_action": "approve",
            "fallback": True,
        }

    return result
