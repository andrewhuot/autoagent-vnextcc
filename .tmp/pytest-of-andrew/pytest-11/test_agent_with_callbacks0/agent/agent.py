
from google.adk.agents import Agent

def safety_check():
    pass

def log_response():
    pass

root_agent = Agent(
    name="test_agent",
    instruction="test",
    before_model_callback=safety_check,
    after_model_callback=log_response,
)
