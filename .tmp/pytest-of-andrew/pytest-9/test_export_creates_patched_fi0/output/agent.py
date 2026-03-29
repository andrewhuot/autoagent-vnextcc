"""Test agent."""
from google.adk.agents import Agent

root_agent = Agent(
    name="test_agent",
    model="gemini-2.0-flash-exp",
    instruction="""You are an optimized test agent.
You help users efficiently.""",
    tools=[lookup_data, process_data],
    generate_config={"temperature": 0.3, "max_output_tokens": 1024},
)
