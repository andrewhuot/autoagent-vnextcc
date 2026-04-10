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
_PRIVACY_KEYWORDS = {
    "another customer's account",
    "another customers account",
    "someone else's account",
    "someone elses account",
    "customer account",
    "access another customer",
    "access another user's account",
}


def _semantic_config_view(config: dict | None) -> dict:
    """Return only the config surfaces that should influence deterministic mock behavior."""
    config = config or {}
    prompts = config.get("prompts") if isinstance(config.get("prompts"), dict) else {}
    routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}
    thresholds = config.get("thresholds") if isinstance(config.get("thresholds"), dict) else {}
    tools = config.get("tools") if isinstance(config.get("tools"), dict) else {}

    normalized_rules: list[dict] = []
    for rule in routing.get("rules", []) if isinstance(routing.get("rules"), list) else []:
        if not isinstance(rule, dict):
            continue
        normalized_rules.append(
            {
                "specialist": str(rule.get("specialist", "")),
                "keywords": sorted(str(keyword).lower() for keyword in rule.get("keywords", []) if str(keyword).strip()),
            }
        )

    normalized_tools = {
        name: {"enabled": bool((cfg or {}).get("enabled", False))}
        for name, cfg in tools.items()
        if isinstance(cfg, dict)
    }

    return {
        "quality_boost": bool(config.get("quality_boost", False)),
        "prompts": {
            "root": str(prompts.get("root", "")),
            "support": str(prompts.get("support", "")),
            "orders": str(prompts.get("orders", "")),
            "recommendations": str(prompts.get("recommendations", "")),
        },
        "routing": {"rules": normalized_rules},
        "thresholds": {
            "confidence_threshold": thresholds.get("confidence_threshold"),
            "max_turns": thresholds.get("max_turns"),
        },
        "tools": normalized_tools,
    }


def _has_explicit_safety_guardrail(config: dict | None) -> bool:
    """Detect whether the config explicitly instructs the agent to refuse unsafe requests."""
    semantic = _semantic_config_view(config)
    prompt_text = " ".join(semantic["prompts"].values()).lower()
    return any(
        phrase in prompt_text
        for phrase in (
            "never assist with harmful",
            "illegal",
            "dangerous requests",
            "refuse unsafe",
            "another customer's account",
            "privacy",
        )
    )


def _route_from_config(msg_lower: str, config: dict | None) -> str | None:
    """Route using config routing rules when available."""
    routing = _semantic_config_view(config).get("routing", {})
    rules = routing.get("rules", [])
    best_specialist: str | None = None
    best_score = 0
    for rule in rules:
        specialist = str(rule.get("specialist", "")).strip()
        keywords = rule.get("keywords", [])
        if not specialist or not keywords:
            continue
        score = sum(1 for keyword in keywords if keyword and keyword in msg_lower)
        if score > best_score:
            best_specialist = specialist
            best_score = score
    return best_specialist if best_score > 0 else None


def _journey_build_text(config: dict | None) -> str:
    """Collect Build-workspace metadata that can make mock previews domain aware."""
    if not isinstance(config, dict):
        return ""

    journey_build = config.get("journey_build")
    if not isinstance(journey_build, dict):
        return ""

    fragments: list[str] = []
    for key in ("agent_name", "system_prompt"):
        value = journey_build.get(key)
        if isinstance(value, str):
            fragments.append(value)

    for collection_name in ("tools", "routing_rules", "policies", "eval_criteria"):
        collection = journey_build.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            fragments.extend(str(value) for value in item.values() if isinstance(value, (str, int, float)))

    return " ".join(fragments).lower()


def _configured_tool_names(config: dict | None) -> list[str]:
    """Return the custom Build tool names preserved on the runtime config."""
    if not isinstance(config, dict):
        return []
    journey_build = config.get("journey_build")
    if not isinstance(journey_build, dict):
        return []

    names: list[str] = []
    for tool in journey_build.get("tools", []):
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _has_airline_domain(config: dict | None, msg_lower: str) -> bool:
    """Detect flight/booking agents so mock preview copy matches Build intent."""
    text = f"{msg_lower} {_journey_build_text(config)}"
    return any(
        token in text
        for token in (
            "airline",
            "flight",
            "booking",
            "reservation",
            "fare",
            "gate",
            "departure",
            "arrival",
            "traveler",
            "itinerary",
        )
    )


def _select_configured_tool(config: dict | None, msg_lower: str, fallback: str) -> str:
    """Pick the most relevant Build tool name, falling back to legacy tool IDs."""
    names = _configured_tool_names(config)
    if not names:
        return fallback

    preferred_keywords = []
    if any(token in msg_lower for token in ("cancel", "refund", "credit")):
        preferred_keywords.extend(["cancel", "refund"])
    if any(token in msg_lower for token in ("change", "rebook", "later", "earlier")):
        preferred_keywords.extend(["change", "booking"])
    if any(token in msg_lower for token in ("delay", "status", "gate", "depart", "arriv")):
        preferred_keywords.extend(["status", "flight"])

    for keyword in preferred_keywords:
        for name in names:
            if keyword in name.lower():
                return name
    return names[0]


def _deterministic_rng(user_message: str, config: dict | None) -> random.Random:
    """Create a deterministic RNG keyed by message and config content."""
    config_key = json.dumps(_semantic_config_view(config), sort_keys=True, separators=(",", ":"))
    seed_material = f"{user_message.lower()}|{config_key}"
    digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    seed = int(digest[:16], 16)
    return random.Random(seed)


def mock_agent_response(user_message: str, config: dict | None = None) -> dict:
    """Return a plausible mock agent response based on keyword matching."""
    msg_lower = user_message.lower()
    rng = _deterministic_rng(user_message, config)

    # Safety check
    explicit_safety_guardrail = _has_explicit_safety_guardrail(config)
    privacy_violation = any(kw in msg_lower for kw in _PRIVACY_KEYWORDS)
    harmful_request = any(kw in msg_lower for kw in _SAFETY_KEYWORDS)
    unsafe_request = harmful_request or privacy_violation

    # Route to specialist
    config_specialist = _route_from_config(msg_lower, config)
    if config_specialist:
        specialist = config_specialist
    elif any(kw in msg_lower for kw in ("order", "track", "cancel", "shipping", "delivery", "status")):
        specialist = "orders"
    elif any(kw in msg_lower for kw in ("recommend", "suggest", "similar", "like this", "best")):
        specialist = "recommendations"
    else:
        specialist = "support"

    airline_domain = _has_airline_domain(config, msg_lower)

    if specialist == "orders":
        if airline_domain:
            if any(token in msg_lower for token in ("change", "rebook", "later", "earlier")):
                response_text = (
                    "I can help with that booking change. I’ll verify the reservation, "
                    "check the fare rules, and explain any fee or credit options plainly."
                )
            elif any(token in msg_lower for token in ("status", "delay", "gate", "arrival", "departure")):
                response_text = (
                    "I can check the flight status and explain the latest delay, gate, "
                    "or arrival details before recommending the next step."
                )
            elif any(token in msg_lower for token in ("cancel", "refund", "credit")):
                response_text = (
                    "I can help with the cancellation path, confirm eligibility, and explain "
                    "whether the reservation returns to cash, credit, or another option."
                )
            else:
                response_text = "I can help with that reservation and walk through the next airline support step."
        else:
            response_text = "I can help with your order. Let me look that up for you."
    elif specialist == "recommendations":
        response_text = "Based on your preferences, here are some recommendations."
    else:
        response_text = "I'm happy to help! Let me find the information you need."

    refused_for_safety = False
    if harmful_request or (explicit_safety_guardrail and privacy_violation):
        response_text = "I'm sorry, but I can't assist with that request."
        specialist = "support"
        refused_for_safety = True

    safety_violation = unsafe_request and not refused_for_safety

    # Build tool calls
    tool_calls: list[dict] = []
    if specialist == "orders":
        tool_calls.append(
            {
                "tool": _select_configured_tool(config, msg_lower, "lookup_order"),
                "args": {"query": user_message},
            }
        )
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
