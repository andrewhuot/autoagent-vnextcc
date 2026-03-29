
from google import genai

agent = genai.Agent(
    name="test",
    model="gemini-2.0-flash",
    instruction="Original instruction",
)
