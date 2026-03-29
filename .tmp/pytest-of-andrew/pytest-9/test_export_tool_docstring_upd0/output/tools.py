"""Test tools."""
from google.adk.tools import tool

@tool
def lookup_data(query: str) -> str:
    """This is an updated description for the lookup_data tool."""
    return "data"

@tool
def process_data(data: str) -> str:
    """Process the given data."""
    return "processed"
