"""Mock order database tool."""

from __future__ import annotations

from datetime import datetime

ORDERS: dict[str, dict] = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "customer_id": "CUST-100",
        "items": [{"product_id": "PROD-001", "quantity": 1, "price": 79.99}],
        "status": "delivered",
        "total": 79.99,
        "created_at": "2026-03-15T10:30:00Z",
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "customer_id": "CUST-100",
        "items": [
            {"product_id": "PROD-004", "quantity": 1, "price": 129.99},
            {"product_id": "PROD-010", "quantity": 1, "price": 39.99},
        ],
        "status": "shipped",
        "total": 169.98,
        "created_at": "2026-03-18T14:15:00Z",
    },
    "ORD-1003": {
        "order_id": "ORD-1003",
        "customer_id": "CUST-101",
        "items": [{"product_id": "PROD-003", "quantity": 1, "price": 349.99}],
        "status": "processing",
        "total": 349.99,
        "created_at": "2026-03-20T09:00:00Z",
    },
    "ORD-1004": {
        "order_id": "ORD-1004",
        "customer_id": "CUST-102",
        "items": [{"product_id": "PROD-006", "quantity": 2, "price": 119.99}],
        "status": "delivered",
        "total": 239.98,
        "created_at": "2026-03-10T11:45:00Z",
    },
    "ORD-1005": {
        "order_id": "ORD-1005",
        "customer_id": "CUST-103",
        "items": [
            {"product_id": "PROD-008", "quantity": 3, "price": 24.99},
            {"product_id": "PROD-007", "quantity": 1, "price": 49.99},
        ],
        "status": "shipped",
        "total": 124.96,
        "created_at": "2026-03-19T16:30:00Z",
    },
    "ORD-1006": {
        "order_id": "ORD-1006",
        "customer_id": "CUST-101",
        "items": [{"product_id": "PROD-009", "quantity": 1, "price": 69.99}],
        "status": "cancelled",
        "total": 69.99,
        "created_at": "2026-03-17T08:20:00Z",
    },
    "ORD-1007": {
        "order_id": "ORD-1007",
        "customer_id": "CUST-104",
        "items": [
            {"product_id": "PROD-002", "quantity": 1, "price": 29.99},
            {"product_id": "PROD-012", "quantity": 1, "price": 59.99},
        ],
        "status": "processing",
        "total": 89.98,
        "created_at": "2026-03-21T13:10:00Z",
    },
    "ORD-1008": {
        "order_id": "ORD-1008",
        "customer_id": "CUST-102",
        "items": [
            {"product_id": "PROD-005", "quantity": 1, "price": 199.99},
            {"product_id": "PROD-011", "quantity": 1, "price": 44.99},
        ],
        "status": "shipped",
        "total": 244.98,
        "created_at": "2026-03-22T10:00:00Z",
    },
}

VALID_STATUSES = {"processing", "shipped", "delivered", "cancelled", "returned"}


def get_order(order_id: str) -> dict | None:
    """Look up an order by its ID.

    Args:
        order_id: The order ID to look up.

    Returns:
        Order dict or None if not found.
    """
    return ORDERS.get(order_id)


def list_orders(customer_id: str) -> list[dict]:
    """List all orders for a customer.

    Args:
        customer_id: The customer ID to look up orders for.

    Returns:
        List of order dicts for that customer.
    """
    return [o for o in ORDERS.values() if o["customer_id"] == customer_id]


def update_order_status(order_id: str, status: str) -> dict:
    """Update the status of an order.

    Args:
        order_id: The order ID to update.
        status: New status (processing, shipped, delivered, cancelled, returned).

    Returns:
        Dict with success status and order details or error message.
    """
    if status not in VALID_STATUSES:
        return {"success": False, "error": f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}"}

    order = ORDERS.get(order_id)
    if order is None:
        return {"success": False, "error": f"Order {order_id} not found."}

    old_status = order["status"]
    order["status"] = status
    return {
        "success": True,
        "order_id": order_id,
        "old_status": old_status,
        "new_status": status,
    }
