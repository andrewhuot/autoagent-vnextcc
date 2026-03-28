"""MCP Prompts — templated interactions for AI coding assistants.

Prompts are named templates that accept arguments and produce ready-to-send
messages, enabling consistent interaction patterns across coding agents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class McpPrompt:
    """A single MCP prompt template."""
    name: str
    description: str
    arguments: list[dict[str, Any]]
    template: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
            "template": self.template,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "McpPrompt":
        return cls(
            name=d["name"],
            description=d["description"],
            arguments=d.get("arguments", []),
            template=d.get("template", ""),
        )


# ---------------------------------------------------------------------------
# Built-in prompt templates
# ---------------------------------------------------------------------------

_BUILTIN_PROMPTS: list[McpPrompt] = [
    McpPrompt(
        name="diagnose_agent",
        description=(
            "Diagnose the current agent state: analyse failure clusters, identify root causes, "
            "and propose prioritised fixes."
        ),
        arguments=[
            {
                "name": "failure_family",
                "description": "Optional failure type to focus the diagnosis on.",
                "required": False,
            },
            {
                "name": "limit",
                "description": "Maximum number of failure samples to include.",
                "required": False,
            },
        ],
        template=(
            "You are an expert AI agent reliability engineer. "
            "The following data describes the current health of the agent system.\n\n"
            "## Failure family\n{failure_family}\n\n"
            "## Sample limit\n{limit}\n\n"
            "Please:\n"
            "1. Identify the top failure modes and their root causes.\n"
            "2. Cluster similar failures together.\n"
            "3. Propose concrete, prioritised fixes.\n"
            "4. Estimate the impact of each fix on overall success rate.\n"
        ),
    ),
    McpPrompt(
        name="fix_failure_pattern",
        description=(
            "Generate a targeted configuration or instruction fix for a specific failure pattern."
        ),
        arguments=[
            {
                "name": "failure_pattern",
                "description": "Description of the failure pattern to fix.",
                "required": True,
            },
            {
                "name": "sample_conversations",
                "description": "JSON list of sample conversations exhibiting the failure.",
                "required": False,
            },
            {
                "name": "current_config",
                "description": "Current agent configuration (YAML or JSON).",
                "required": False,
            },
        ],
        template=(
            "You are an expert at improving AI agent configurations. "
            "Analyse the failure pattern and generate a targeted fix.\n\n"
            "## Failure pattern\n{failure_pattern}\n\n"
            "## Sample conversations\n{sample_conversations}\n\n"
            "## Current configuration\n{current_config}\n\n"
            "Please:\n"
            "1. Explain why this failure is occurring.\n"
            "2. Propose a minimal configuration change or instruction update to fix it.\n"
            "3. Write the exact YAML diff or instruction text to apply.\n"
            "4. Describe how to verify the fix worked.\n"
        ),
    ),
    McpPrompt(
        name="generate_evals",
        description=(
            "Generate a comprehensive eval pack (test cases) for a given agent capability or failure mode."
        ),
        arguments=[
            {
                "name": "capability",
                "description": "The capability or behaviour to generate evals for.",
                "required": True,
            },
            {
                "name": "num_cases",
                "description": "Number of eval cases to generate.",
                "required": False,
            },
            {
                "name": "include_adversarial",
                "description": "Whether to include adversarial/edge-case evals (true/false).",
                "required": False,
            },
        ],
        template=(
            "You are an expert at designing evaluation suites for AI agents. "
            "Generate a comprehensive eval pack for the specified capability.\n\n"
            "## Capability to evaluate\n{capability}\n\n"
            "## Number of cases\n{num_cases}\n\n"
            "## Include adversarial cases\n{include_adversarial}\n\n"
            "Please produce a YAML or JSON eval pack containing:\n"
            "1. Happy-path cases that verify the capability works correctly.\n"
            "2. Edge cases that probe boundary conditions.\n"
            "3. Adversarial cases that attempt to break the behaviour (if requested).\n"
            "4. For each case: task, expected_behavior, expected_keywords, and grading criteria.\n"
        ),
    ),
    McpPrompt(
        name="explain_diff",
        description=(
            "Explain what a configuration or code diff changes about the agent's behaviour "
            "in plain English."
        ),
        arguments=[
            {
                "name": "diff",
                "description": "The unified diff to explain.",
                "required": True,
            },
            {
                "name": "context",
                "description": "Additional context about the agent or the change motivation.",
                "required": False,
            },
        ],
        template=(
            "You are an expert AI agent engineer. "
            "Explain the following diff in plain English.\n\n"
            "## Diff\n```diff\n{diff}\n```\n\n"
            "## Context\n{context}\n\n"
            "Please provide:\n"
            "1. A one-sentence summary of the change.\n"
            "2. A detailed explanation of what behaviours will change.\n"
            "3. Potential risks or regressions introduced by this change.\n"
            "4. Suggested eval cases to verify the change behaves as intended.\n"
        ),
    ),
    McpPrompt(
        name="optimize_instruction",
        description=(
            "Rewrite or improve an agent instruction to be clearer, more effective, "
            "and less likely to cause failures."
        ),
        arguments=[
            {
                "name": "instruction",
                "description": "The current instruction text to optimize.",
                "required": True,
            },
            {
                "name": "failure_examples",
                "description": "Examples of failures caused by the current instruction.",
                "required": False,
            },
            {
                "name": "objective",
                "description": "What the instruction is supposed to achieve.",
                "required": False,
            },
        ],
        template=(
            "You are an expert at writing clear, effective instructions for AI agents. "
            "Improve the following instruction.\n\n"
            "## Current instruction\n{instruction}\n\n"
            "## Failure examples\n{failure_examples}\n\n"
            "## Objective\n{objective}\n\n"
            "Please produce:\n"
            "1. An improved version of the instruction.\n"
            "2. A bullet-point explanation of each change you made and why.\n"
            "3. Any caveats or remaining risks with the improved instruction.\n"
        ),
    ),
]

_PROMPT_MAP: dict[str, McpPrompt] = {p.name: p for p in _BUILTIN_PROMPTS}


class PromptProvider:
    """Provides MCP prompts for the AutoAgent system."""

    def list_prompts(self) -> list[McpPrompt]:
        """Return all available prompts."""
        return list(_BUILTIN_PROMPTS)

    def get_prompt(self, name: str, arguments: dict[str, Any]) -> str:
        """Render a prompt template with the supplied arguments.

        Unknown argument keys are ignored; missing keys are replaced with an
        empty string so templates always render without raising KeyError.
        """
        prompt = _PROMPT_MAP.get(name)
        if prompt is None:
            raise ValueError(f"Unknown prompt: {name!r}. Available: {sorted(_PROMPT_MAP)}")

        # Build a defaultdict-style mapping so missing keys produce ""
        safe_args: dict[str, str] = {}
        for arg_def in prompt.arguments:
            key = arg_def["name"]
            safe_args[key] = str(arguments.get(key, ""))

        try:
            return prompt.template.format(**safe_args)
        except KeyError as exc:
            # Fallback: return template with raw placeholders
            return prompt.template + f"\n\n[Warning: missing argument {exc}]"
