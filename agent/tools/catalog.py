"""Mock product catalog tool."""

from __future__ import annotations

PRODUCTS: dict[str, dict] = {
    "PROD-001": {
        "id": "PROD-001",
        "name": "Wireless Bluetooth Headphones",
        "category": "electronics",
        "price": 79.99,
        "description": "Over-ear wireless headphones with noise cancellation and 30-hour battery life.",
    },
    "PROD-002": {
        "id": "PROD-002",
        "name": "USB-C Fast Charger",
        "category": "electronics",
        "price": 29.99,
        "description": "65W USB-C GaN charger compatible with laptops, phones, and tablets.",
    },
    "PROD-003": {
        "id": "PROD-003",
        "name": "Ergonomic Office Chair",
        "category": "furniture",
        "price": 349.99,
        "description": "Adjustable lumbar support, mesh back, and memory foam seat cushion.",
    },
    "PROD-004": {
        "id": "PROD-004",
        "name": "Mechanical Keyboard",
        "category": "electronics",
        "price": 129.99,
        "description": "Hot-swappable switches, RGB backlighting, and programmable macros.",
    },
    "PROD-005": {
        "id": "PROD-005",
        "name": "Standing Desk Converter",
        "category": "furniture",
        "price": 199.99,
        "description": "Height-adjustable desk riser with dual monitor support.",
    },
    "PROD-006": {
        "id": "PROD-006",
        "name": "Running Shoes Pro",
        "category": "sports",
        "price": 119.99,
        "description": "Lightweight running shoes with responsive cushioning and breathable mesh.",
    },
    "PROD-007": {
        "id": "PROD-007",
        "name": "Yoga Mat Premium",
        "category": "sports",
        "price": 49.99,
        "description": "Non-slip 6mm thick yoga mat with alignment markers.",
    },
    "PROD-008": {
        "id": "PROD-008",
        "name": "Stainless Steel Water Bottle",
        "category": "accessories",
        "price": 24.99,
        "description": "Double-wall insulated, keeps drinks cold 24h or hot 12h. 750ml capacity.",
    },
    "PROD-009": {
        "id": "PROD-009",
        "name": "Laptop Backpack",
        "category": "accessories",
        "price": 69.99,
        "description": "Water-resistant backpack with padded 15.6-inch laptop compartment and USB port.",
    },
    "PROD-010": {
        "id": "PROD-010",
        "name": "Wireless Mouse",
        "category": "electronics",
        "price": 39.99,
        "description": "Ergonomic wireless mouse with adjustable DPI and silent clicks.",
    },
    "PROD-011": {
        "id": "PROD-011",
        "name": "Desk Lamp LED",
        "category": "furniture",
        "price": 44.99,
        "description": "Adjustable LED desk lamp with 5 color temperatures and USB charging port.",
    },
    "PROD-012": {
        "id": "PROD-012",
        "name": "Fitness Tracker Band",
        "category": "electronics",
        "price": 59.99,
        "description": "Heart rate, sleep tracking, step counter, and 7-day battery life.",
    },
}


def search_catalog(query: str) -> list[dict]:
    """Search the product catalog by keyword matching.

    Args:
        query: Search query string.

    Returns:
        List of matching product dicts.
    """
    query_lower = query.lower()
    terms = query_lower.split()
    results = []
    for product in PRODUCTS.values():
        searchable = (
            f"{product['name']} {product['category']} {product['description']}"
        ).lower()
        if any(term in searchable for term in terms):
            results.append(product)
    return results


def get_product(product_id: str) -> dict | None:
    """Look up a product by its ID.

    Args:
        product_id: The product ID to look up.

    Returns:
        Product dict or None if not found.
    """
    return PRODUCTS.get(product_id)
