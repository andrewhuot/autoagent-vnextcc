"""Test agent."""
# Import Agent class
from google.adk.agents import Agent  # ADK framework

root_agent = Agent(
    name="test_agent",
    model="gemini-2.0-flash",
    instruction="""You are a helpful test agent.
You assist users with testing.""",
    tools=[lookup_data, process_data],
    generate_config={"temperature": 0.3, "max_output_tokens": 1024},
)
