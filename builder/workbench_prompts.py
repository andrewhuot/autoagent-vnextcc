"""Prompt templates for the live Workbench builder agent.

Kept in a dedicated module so the text is grep-able, unit-testable, and
doesn't clutter the orchestration code. The schemas the LLM is expected to
produce live here too — the agent imports and validates against them.
"""

from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
You are the planner for an agent builder workbench. When the user describes
an agent they want, you respond with a concrete, layered PLAN TREE that a
downstream executor can run step by step.

STRICT RULES:
- Output MUST be a single JSON object, no prose, no markdown fences.
- The tree has one root, 3-5 children, and each child has 1-3 leaves.
- Each leaf task MUST map to exactly one of these executor kinds:
    role          — write the agent's role summary
    instructions  — draft the system prompt
    tool_schema   — design one tool schema
    tool_source   — generate one tool's source stub
    guardrail     — author one safety guardrail
    environment   — render source code for the deployment target
    eval_suite    — draft an evaluation suite with 1-3 cases
- Keep titles short (≤60 chars) and description sentences short (≤160 chars).
- Do NOT invent kinds. Do NOT emit extra fields.

SCHEMA:
{
  "root": {
    "title": "string",
    "description": "string",
    "children": [
      {
        "title": "string",
        "description": "string",
        "children": [
          {"title": "string", "description": "string", "kind": "<one of the 7 kinds>"}
        ]
      }
    ]
  },
  "assistant_intro": "one-sentence summary of the plan you're about to execute"
}
"""


def planner_user_prompt(brief: str, target: str, domain: str) -> str:
    """Shape the user-side prompt the planner receives."""
    return (
        f"Brief: {brief}\n"
        f"Target runtime: {target}\n"
        f"Detected domain: {domain}\n\n"
        "Produce the plan tree now as pure JSON."
    )


# ---------------------------------------------------------------------------
# Per-kind executor prompts
# ---------------------------------------------------------------------------

EXECUTOR_SYSTEM_PROMPT = """\
You are the executor for a single step of an agent builder plan. You receive
the agent brief, the current canonical model, and the step kind. You respond
with a single JSON object matching the requested schema. Never include prose,
markdown fences, or keys outside the schema.
"""


# Each schema is documented inline so the LLM can return a stable shape.
EXECUTOR_SCHEMAS: dict[str, dict[str, Any]] = {
    "role": {
        "description": "Write a one-paragraph role summary for the agent.",
        "schema": {"role_summary": "string"},
    },
    "instructions": {
        "description": "Draft a detailed system prompt with sections: # Role, ## Rules, ## Style.",
        "schema": {"system_prompt": "string (markdown)"},
    },
    "tool_schema": {
        "description": "Design ONE tool that the agent will call. Prefer a generic, portable tool.",
        "schema": {
            "name": "string (snake_case)",
            "description": "string",
            "parameters": ["list of parameter names (strings)"],
            "type": "function_tool",
        },
    },
    "tool_source": {
        "description": "Generate a short Python stub for the tool named <tool_name>.",
        "schema": {
            "name": "string",
            "source": "string (valid Python, single def)",
        },
    },
    "guardrail": {
        "description": "Author ONE safety guardrail.",
        "schema": {
            "name": "string",
            "rule": "string",
        },
    },
    "environment": {
        "description": "Render the ADK agent.py source based on the current canonical model.",
        "schema": {
            "filename": "string (agent.py)",
            "source": "string (Python with Agent(...) construct)",
        },
    },
    "eval_suite": {
        "description": "Draft an evaluation suite with 1-3 cases.",
        "schema": {
            "name": "string",
            "cases": [
                {
                    "input": "string",
                    "expected": "string",
                }
            ],
        },
    },
}


def executor_user_prompt(
    *,
    kind: str,
    brief: str,
    task_title: str,
    canonical_summary: dict[str, Any],
    extra_context: dict[str, Any] | None = None,
) -> str:
    """Build the per-task user prompt."""
    schema = EXECUTOR_SCHEMAS.get(kind)
    if schema is None:
        raise ValueError(f"Unknown executor kind: {kind}")
    schema_blob = json.dumps(schema["schema"], indent=2)
    context_blob = json.dumps(canonical_summary, indent=2, default=str)
    extra_blob = ""
    if extra_context:
        extra_blob = (
            "\nExtra context:\n"
            + json.dumps(extra_context, indent=2, default=str)
        )
    return (
        f"Task kind: {kind}\n"
        f"Task title: {task_title}\n"
        f"User brief: {brief}\n\n"
        f"Current canonical model summary:\n{context_blob}\n{extra_blob}\n\n"
        f"Schema description: {schema['description']}\n"
        f"Respond with JSON matching exactly this shape:\n{schema_blob}\n"
    )


__all__ = [
    "EXECUTOR_SCHEMAS",
    "EXECUTOR_SYSTEM_PROMPT",
    "PLANNER_SYSTEM_PROMPT",
    "executor_user_prompt",
    "planner_user_prompt",
]
