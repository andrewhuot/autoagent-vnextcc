"""Root support agent."""
from google.adk.agents import Agent
from .tools import lookup_order, search_knowledge_base, create_ticket
from .sub_agents.billing.agent import billing_agent
from .prompts import ROOT_INSTRUCTION

root_agent = Agent(
    model="gemini-2.0-flash",
    name="support_agent",
    instruction=ROOT_INSTRUCTION,
    tools=[lookup_order, search_knowledge_base, create_ticket],
    sub_agents=[billing_agent],
    generate_config={"temperature": 0.3, "max_output_tokens": 1024},
)
