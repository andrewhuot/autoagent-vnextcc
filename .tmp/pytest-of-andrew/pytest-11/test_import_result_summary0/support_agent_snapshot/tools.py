"""Tools for the support agent."""
from google.adk.tools import tool


@tool
def lookup_order(order_id: str) -> dict:
    """Look up order details by order ID.

    Args:
        order_id: The unique order identifier

    Returns:
        Order details including status, items, and shipping info
    """
    return {"order_id": order_id, "status": "shipped"}


@tool
def search_knowledge_base(query: str) -> list:
    """Search the knowledge base for relevant articles.

    Args:
        query: The search query

    Returns:
        List of matching knowledge base articles
    """
    return [{"title": "FAQ", "content": "Common questions"}]


@tool
def create_ticket(subject: str, description: str) -> dict:
    """Create a support ticket.

    Args:
        subject: Brief description of the issue
        description: Detailed description of the problem

    Returns:
        Created ticket details with ticket ID
    """
    return {"ticket_id": "TKT-001", "status": "open"}
