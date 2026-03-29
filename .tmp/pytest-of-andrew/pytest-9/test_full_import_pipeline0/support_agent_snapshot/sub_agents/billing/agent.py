"""Billing specialist agent."""
from google.adk.agents import Agent
from .tools import get_billing_history, process_refund

billing_agent = Agent(
    model="gemini-2.0-flash",
    name="billing_agent",
    instruction="""You are a billing specialist.
You have access to billing records and can process refunds.
Always verify customer identity before discussing account details.""",
    tools=[get_billing_history, process_refund],
    generate_config={"temperature": 0.2, "max_output_tokens": 512},
)
