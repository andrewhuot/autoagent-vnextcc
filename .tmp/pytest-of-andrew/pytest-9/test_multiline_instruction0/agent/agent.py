
from google.adk.agents import Agent

root_agent = Agent(
    name="test_agent",
    instruction="""This is a multi-line instruction.
It spans multiple lines.
And has multiple paragraphs.""",
)
