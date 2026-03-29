"""Test agent."""
from google.adk.agents import Agent

root_agent = Agent(
    name="test_agent",
    model="gemini-3.0-ultra",
    instruction="""You are a helpful test agent.
You assist users with testing.""",
    tools=[lookup_data, process_data],
    generate_config={"temperature": 0.3, "max_output_tokens": 1024},
)
