"""Tests for runtime adapter discovery and transcript import."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.anthropic_claude import AnthropicClaudeAdapter
from adapters.http_webhook import HttpWebhookAdapter
from adapters.openai_agents import OpenAIAgentsAdapter
from adapters.transcript import TranscriptAdapter


def test_openai_agents_adapter_discovers_tools_handoffs_and_prompt(tmp_path: Path) -> None:
    """The OpenAI adapter should infer core agent topology from Python source."""

    source = tmp_path / "agent.py"
    source.write_text(
        """
from agents import Agent, function_tool

@function_tool
def lookup_order(order_id: str) -> str:
    \"\"\"Return order status.\"\"\"
    return "shipped"

billing_agent = Agent(name="Billing", instructions="Handle invoices and payments.")
support_agent = Agent(
    name="Support",
    instructions="Help customers with orders and refunds.",
    tools=[lookup_order],
    handoffs=[billing_agent],
)
""".strip(),
        encoding="utf-8",
    )

    spec = OpenAIAgentsAdapter(str(tmp_path)).discover()

    assert spec.adapter == "openai-agents"
    assert spec.agent_name == "Support"
    assert spec.tools[0]["name"] == "lookup_order"
    assert spec.handoffs[0]["target"] == "Billing"
    assert spec.config["prompts"]["root"] == "Help customers with orders and refunds."
    assert spec.starter_evals


def test_anthropic_adapter_discovers_mcp_guardrails_and_tools(tmp_path: Path) -> None:
    """The Anthropic adapter should extract prompts, tools, guardrails, and MCP refs."""

    source = tmp_path / "claude_app.py"
    source.write_text(
        """
import anthropic

SYSTEM_PROMPT = "You are a careful support assistant."
TOOLS = [{"name": "lookup_faq", "description": "Search the FAQ"}]

def refund_guardrail(message: str) -> bool:
    return "override" not in message

client = anthropic.Anthropic()
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "docs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}
                }
            }
        ),
        encoding="utf-8",
    )

    spec = AnthropicClaudeAdapter(str(tmp_path)).discover()

    assert spec.adapter == "anthropic"
    assert spec.system_prompts[0] == "You are a careful support assistant."
    assert spec.tools[0]["name"] == "lookup_faq"
    assert spec.guardrails[0]["name"] == "refund_guardrail"
    assert spec.mcp_refs[0]["name"] == "docs"


def test_transcript_adapter_builds_eval_fixtures_from_jsonl(tmp_path: Path) -> None:
    """Transcript imports should normalize conversations into starter evals."""

    transcript_file = tmp_path / "conversations.jsonl"
    transcript_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "conv-1",
                        "messages": [
                            {"role": "user", "content": "Where is my order ORD-42?"},
                            {
                                "role": "assistant",
                                "content": "Your order is in transit.",
                                "tool_calls": [{"name": "lookup_order"}],
                            },
                        ],
                    }
                )
            ]
        ),
        encoding="utf-8",
    )

    spec = TranscriptAdapter(str(transcript_file)).discover()

    assert spec.adapter == "transcript"
    assert len(spec.traces) == 1
    assert spec.tools[0]["name"] == "lookup_order"
    assert spec.starter_evals[0]["user_message"] == "Where is my order ORD-42?"


def test_http_webhook_adapter_creates_minimal_live_workspace_spec() -> None:
    """The HTTP adapter should expose a minimal spec even without introspection."""

    spec = HttpWebhookAdapter("https://agent.example.com/webhook").discover()

    assert spec.adapter == "http"
    assert spec.agent_name == "agent.example.com"
    assert spec.config["adapter"]["base_url"] == "https://agent.example.com/webhook"
    assert spec.starter_evals[0]["expected_behavior"] == "answer"
