"""Billing tools."""
from google.adk.tools import tool


@tool
def get_billing_history(customer_id: str) -> list:
    """Retrieve billing history for a customer.

    Args:
        customer_id: The customer's unique identifier

    Returns:
        List of billing transactions
    """
    return [{"date": "2026-03-01", "amount": 99.99}]


@tool
def process_refund(order_id: str, amount: float) -> dict:
    """Process a refund for an order.

    Args:
        order_id: The order identifier
        amount: Refund amount in USD

    Returns:
        Refund confirmation details
    """
    return {"refund_id": "REF-001", "status": "processed"}
