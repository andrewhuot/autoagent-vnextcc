"""Test tools."""
from google.adk.tools import tool

@tool
def lookup_data(query: str) -> str:
    """Look up data based on a query."""
    return "data"

@tool
def process_data(data: str) -> str:
    """Process the given data."""
    return "processed"
