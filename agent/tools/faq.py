"""Mock FAQ search tool."""

from __future__ import annotations

FAQ_ENTRIES: list[dict] = [
    {
        "question": "What is your return policy?",
        "answer": "You can return any item within 30 days of delivery for a full refund. Items must be in original condition with tags attached.",
    },
    {
        "question": "How long does shipping take?",
        "answer": "Standard shipping takes 5-7 business days. Express shipping takes 2-3 business days. Free shipping on orders over $50.",
    },
    {
        "question": "How do I track my order?",
        "answer": "You can track your order using the order ID on our website, or ask me with your order number and I'll look it up for you.",
    },
    {
        "question": "Do you offer international shipping?",
        "answer": "Yes, we ship to over 50 countries. International shipping takes 10-15 business days. Additional customs fees may apply.",
    },
    {
        "question": "How do I cancel an order?",
        "answer": "Orders can be cancelled within 1 hour of placement if they haven't entered processing. Contact support with your order ID.",
    },
    {
        "question": "What payment methods do you accept?",
        "answer": "We accept Visa, Mastercard, American Express, PayPal, Apple Pay, and Google Pay.",
    },
    {
        "question": "How do I contact customer support?",
        "answer": "You can reach us via this chat, email at support@autoagent.example.com, or call 1-800-555-0199 Mon-Fri 9am-6pm EST.",
    },
    {
        "question": "Do you offer warranty on products?",
        "answer": "All electronics come with a 1-year manufacturer warranty. Furniture has a 2-year warranty. Extended warranties are available at checkout.",
    },
    {
        "question": "How do I change my shipping address?",
        "answer": "You can update your shipping address before the order ships. Go to your order details or contact support with the new address.",
    },
    {
        "question": "Do you price match?",
        "answer": "Yes, we offer price matching within 14 days of purchase. The item must be identical and from an authorized retailer.",
    },
    {
        "question": "What if my item arrives damaged?",
        "answer": "Contact support within 48 hours with photos of the damage. We'll arrange a free replacement or full refund.",
    },
    {
        "question": "Do you have a loyalty program?",
        "answer": "Yes! Join AutoRewards for free. Earn 1 point per dollar spent. 100 points = $5 off. Plus exclusive member-only deals.",
    },
]


def search_faq(query: str) -> list[dict]:
    """Search FAQ entries by keyword matching, returning top 3 results.

    Args:
        query: Search query string.

    Returns:
        List of up to 3 matching FAQ dicts with question and answer.
    """
    query_lower = query.lower()
    terms = query_lower.split()

    scored: list[tuple[int, dict]] = []
    for entry in FAQ_ENTRIES:
        searchable = f"{entry['question']} {entry['answer']}".lower()
        score = sum(1 for term in terms if term in searchable)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored[:3]]
