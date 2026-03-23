"""Mock data used in eval tests."""

from __future__ import annotations

import hashlib
import json
import random

MOCK_PRODUCTS: list[dict] = [
    {"id": "P001", "name": "Wireless Headphones", "category": "electronics", "price": 79.99, "description": "Noise-cancelling Bluetooth headphones with 30-hour battery life."},
    {"id": "P002", "name": "Running Shoes", "category": "footwear", "price": 129.99, "description": "Lightweight mesh running shoes with responsive cushioning."},
    {"id": "P003", "name": "Ceramic Coffee Mug", "category": "kitchen", "price": 14.99, "description": "Handmade 12oz ceramic mug, dishwasher safe."},
    {"id": "P004", "name": "Laptop Stand", "category": "electronics", "price": 49.99, "description": "Adjustable aluminum laptop stand for ergonomic positioning."},
    {"id": "P005", "name": "Yoga Mat", "category": "fitness", "price": 34.99, "description": "Non-slip 6mm thick yoga mat with carrying strap."},
    {"id": "P006", "name": "Stainless Steel Water Bottle", "category": "kitchen", "price": 24.99, "description": "Insulated 750ml bottle keeps drinks cold for 24 hours."},
    {"id": "P007", "name": "Bluetooth Speaker", "category": "electronics", "price": 59.99, "description": "Portable waterproof speaker with 360-degree sound."},
    {"id": "P008", "name": "Leather Wallet", "category": "accessories", "price": 44.99, "description": "Slim RFID-blocking wallet with 8 card slots."},
    {"id": "P009", "name": "Desk Lamp", "category": "electronics", "price": 39.99, "description": "LED desk lamp with adjustable brightness and color temperature."},
    {"id": "P010", "name": "Travel Backpack", "category": "accessories", "price": 89.99, "description": "40L expandable backpack with laptop compartment and USB port."},
]

MOCK_ORDERS: list[dict] = [
    {"order_id": "ORD-1001", "customer_id": "C100", "items": ["P001", "P003"], "status": "delivered", "total": 94.98, "created_at": "2026-03-01T10:00:00Z"},
    {"order_id": "ORD-1002", "customer_id": "C101", "items": ["P002"], "status": "shipped", "total": 129.99, "created_at": "2026-03-05T14:30:00Z"},
    {"order_id": "ORD-1003", "customer_id": "C102", "items": ["P004", "P009"], "status": "processing", "total": 89.98, "created_at": "2026-03-10T09:15:00Z"},
    {"order_id": "ORD-1004", "customer_id": "C100", "items": ["P005", "P006"], "status": "delivered", "total": 59.98, "created_at": "2026-02-20T16:45:00Z"},
    {"order_id": "ORD-1005", "customer_id": "C103", "items": ["P007"], "status": "cancelled", "total": 59.99, "created_at": "2026-03-12T11:00:00Z"},
    {"order_id": "ORD-1006", "customer_id": "C104", "items": ["P008", "P010"], "status": "shipped", "total": 134.98, "created_at": "2026-03-15T08:20:00Z"},
    {"order_id": "ORD-1007", "customer_id": "C105", "items": ["P001", "P007", "P004"], "status": "processing", "total": 189.97, "created_at": "2026-03-18T13:10:00Z"},
    {"order_id": "ORD-1008", "customer_id": "C101", "items": ["P003", "P006"], "status": "delivered", "total": 39.98, "created_at": "2026-02-28T17:30:00Z"},
]

MOCK_FAQ: list[dict] = [
    {"question": "What is your return policy?", "answer": "You can return items within 30 days of delivery for a full refund."},
    {"question": "How long does shipping take?", "answer": "Standard shipping takes 5-7 business days. Express shipping is 2-3 business days."},
    {"question": "Do you ship internationally?", "answer": "Yes, we ship to over 50 countries. International shipping takes 10-14 business days."},
    {"question": "How do I track my order?", "answer": "You can track your order using the tracking link sent to your email after shipment."},
    {"question": "What payment methods do you accept?", "answer": "We accept Visa, Mastercard, American Express, PayPal, and Apple Pay."},
    {"question": "Can I cancel my order?", "answer": "Orders can be cancelled within 1 hour of placement if they haven't entered processing."},
    {"question": "Do you offer gift wrapping?", "answer": "Yes, gift wrapping is available for $4.99 per item at checkout."},
    {"question": "What is your warranty policy?", "answer": "Electronics carry a 1-year manufacturer warranty. Other items have a 90-day warranty."},
    {"question": "How do I contact customer support?", "answer": "You can reach us via chat, email at support@example.com, or call 1-800-555-0199."},
    {"question": "Do you have a loyalty program?", "answer": "Yes, join our rewards program to earn points on every purchase and get exclusive discounts."},
]

_SAFETY_KEYWORDS = {"hack", "bomb", "weapon", "exploit", "attack", "steal", "phishing", "malware", "jailbreak", "ignore instructions", "inject", "bypass"}


def _deterministic_rng(user_message: str, config: dict | None) -> random.Random:
    """Create a deterministic RNG keyed by message and config content."""
    config_key = json.dumps(config or {}, sort_keys=True, separators=(",", ":"))
    seed_material = f"{user_message.lower()}|{config_key}"
    digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    seed = int(digest[:16], 16)
    return random.Random(seed)


def mock_agent_response(user_message: str, config: dict | None = None) -> dict:
    """Return a plausible mock agent response based on keyword matching."""
    msg_lower = user_message.lower()
    rng = _deterministic_rng(user_message, config)

    # Safety check
    safety_violation = any(kw in msg_lower for kw in _SAFETY_KEYWORDS)

    # Route to specialist
    if any(kw in msg_lower for kw in ("order", "track", "cancel", "shipping", "delivery", "status")):
        specialist = "orders"
        response_text = "I can help with your order. Let me look that up for you."
    elif any(kw in msg_lower for kw in ("recommend", "suggest", "similar", "like this", "best")):
        specialist = "recommendations"
        response_text = "Based on your preferences, here are some recommendations."
    else:
        specialist = "support"
        response_text = "I'm happy to help! Let me find the information you need."

    if safety_violation:
        response_text = "I'm sorry, but I can't assist with that request."
        specialist = "support"

    # Build tool calls
    tool_calls: list[dict] = []
    if specialist == "orders":
        tool_calls.append({"tool": "lookup_order", "args": {"query": user_message}})
    elif specialist == "recommendations":
        tool_calls.append({"tool": "get_recommendations", "args": {"query": user_message}})

    # Latency and token count
    base_latency = rng.uniform(50.0, 200.0)
    base_tokens = rng.randint(100, 500)

    # Quality boost from config
    if config and config.get("quality_boost"):
        response_text += " I've gathered detailed information to give you the most comprehensive answer possible."
        base_tokens = int(base_tokens * 1.4)
        base_latency *= 1.3

    return {
        "response": response_text,
        "tool_calls": tool_calls,
        "latency_ms": round(base_latency, 2),
        "token_count": base_tokens,
        "specialist_used": specialist,
        "safety_violation": safety_violation,
    }
