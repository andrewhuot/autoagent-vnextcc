"""Helpers for migrating plain-text instructions into Google-style XML.

WHY: Existing workspaces store plain-text instructions today, so we need a
deterministic upgrade path that creates a reasonable XML baseline instead of
forcing every user to rewrite instructions by hand.
"""

from __future__ import annotations

import re
from typing import Any

from agent.instruction_builder import build_xml_instruction, is_xml_instruction


def infer_instruction_sections(text: str, *, agent_name: str | None = None) -> dict[str, Any]:
    """Infer recommended XML sections from freeform plain-text instructions.

    WHY: CLI migration and generation flows need a structured intermediate
    representation before we can serialize the final XML safely.
    """
    normalized = " ".join(text.split()).strip()
    role = _infer_role(normalized, agent_name=agent_name)
    constraints = _infer_constraints(normalized)
    primary_goal = _infer_primary_goal(normalized, role=role)
    guidelines = _infer_guidelines(normalized, role=role, primary_goal=primary_goal, constraints=constraints)

    domain = _infer_domain(normalized, role=role)
    taskflow = _build_taskflow(domain)
    examples = _build_examples(domain)

    return {
        "preamble": "",
        "role": role,
        "persona": {
            "primary_goal": primary_goal,
            "guidelines": guidelines,
        },
        "constraints": constraints,
        "taskflow": taskflow,
        "examples": examples,
    }


def migrate_instruction_text(text: str, *, agent_name: str | None = None) -> str:
    """Convert plain-text instructions into the recommended XML structure.

    WHY: The CLI and migration tool need a one-call conversion function that can
    leave already-XML instructions alone while upgrading legacy prompts.
    """
    if is_xml_instruction(text):
        return text.strip()
    sections = infer_instruction_sections(text, agent_name=agent_name)
    return build_xml_instruction(sections)


def _infer_role(text: str, *, agent_name: str | None = None) -> str:
    """Infer an agent role sentence from plain-text instructions."""
    match = re.search(r"\bYou are\s+(?:an?\s+)?(.+?)(?:\.|$)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip(".").capitalize() + "."
    if agent_name:
        return f"{agent_name.strip()}."
    return "Helpful support assistant."


def _infer_primary_goal(text: str, *, role: str) -> str:
    """Infer the main objective from freeform instructions."""
    help_match = re.search(r"\b(help|assist|support|collect|route|qualify|triage)\b(.+?)(?:\.|$)", text, flags=re.IGNORECASE)
    if help_match:
        verb = help_match.group(1).lower()
        remainder = help_match.group(2).strip(" .")
        return f"{verb.capitalize()} {remainder}.".strip()
    return f"Help the user effectively while acting as {role.rstrip('.').lower()}."


def _infer_constraints(text: str) -> list[str]:
    """Extract likely hard rules from plain text."""
    sentences = _split_sentences(text)
    constraints: list[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(token in lowered for token in ("always", "never", "must", "do not", "don't", "avoid", "only", "refuse", "verify")):
            constraints.append(sentence.rstrip(".") + ".")

    if not constraints:
        constraints.append("Ask a clarifying question when key details are missing.")
        constraints.append("Refuse unsafe, harmful, or privacy-violating requests politely.")
    elif not any("unsafe" in item.lower() or "harmful" in item.lower() or "privacy" in item.lower() for item in constraints):
        constraints.append("Refuse unsafe, harmful, or privacy-violating requests politely.")
    return constraints


def _infer_guidelines(
    text: str,
    *,
    role: str,
    primary_goal: str,
    constraints: list[str],
) -> list[str]:
    """Infer softer behavioral guidelines from the remaining freeform text."""
    sentences = _split_sentences(text)
    guidelines: list[str] = []
    for sentence in sentences:
        sentence = sentence.rstrip(".") + "."
        lowered = sentence.lower()
        if sentence == role or sentence == primary_goal or sentence in constraints:
            continue
        if any(token in lowered for token in ("tone", "empathetic", "friendly", "warm", "concise", "clear", "calm")):
            guidelines.append(sentence)
            continue
        if not any(token in lowered for token in ("always", "never", "must", "do not", "don't", "verify")):
            guidelines.append(sentence)

    if not guidelines:
        guidelines.append("Keep responses clear, calm, and easy to follow.")
        guidelines.append("Follow the constraints and taskflow precisely.")
    return guidelines[:4]


def _infer_domain(text: str, *, role: str) -> str:
    """Infer a broad domain so migration can create better starter steps and examples."""
    lowered = f"{role} {text}".lower()
    if any(keyword in lowered for keyword in ("healthcare", "patient", "symptom", "appointment")):
        return "healthcare"
    if any(keyword in lowered for keyword in ("sales", "lead", "demo", "pricing", "qualification")):
        return "sales"
    if any(keyword in lowered for keyword in ("it ", "helpdesk", "vpn", "password", "access", "sso", "laptop")):
        return "it"
    return "support"


def _build_taskflow(domain: str) -> list[dict[str, Any]]:
    """Create a default taskflow suited to the inferred domain."""
    if domain == "healthcare":
        return [
            {
                "name": "Intake",
                "description": "Collect the minimum details needed to triage the request safely.",
                "steps": [
                    {
                        "name": "Collect Context",
                        "trigger": "The user asks for healthcare help or scheduling support.",
                        "action": "Gather the patient's core details, symptoms, and timing before routing.",
                    },
                    {
                        "name": "Escalate Urgent Issues",
                        "trigger": "The user describes urgent or emergency symptoms.",
                        "action": "Direct the user to emergency services or urgent clinical follow-up immediately.",
                    },
                ],
            }
        ]
    if domain == "sales":
        return [
            {
                "name": "Qualification",
                "description": "Identify fit, urgency, and the right next sales motion.",
                "steps": [
                    {
                        "name": "Assess Fit",
                        "trigger": "A lead describes their team, goals, or evaluation process.",
                        "action": "Capture company size, use case, urgency, and stakeholders.",
                    },
                    {
                        "name": "Route Next Step",
                        "trigger": "Enough qualification context is available.",
                        "action": "Recommend the right next step such as self-serve, demo, or enterprise follow-up.",
                    },
                ],
            }
        ]
    if domain == "it":
        return [
            {
                "name": "IT Triage",
                "description": "Classify the issue, collect the minimum facts, and escalate severe incidents quickly.",
                "steps": [
                    {
                        "name": "Identify Issue Type",
                        "trigger": "The user reports an IT problem.",
                        "action": "Determine whether the issue is access, device, network, or incident related.",
                    },
                    {
                        "name": "Guide Next Step",
                        "trigger": "The issue type is clear.",
                        "action": "Provide the next troubleshooting step or route the ticket appropriately.",
                    },
                ],
            }
        ]
    return [
        {
            "name": "Support Flow",
            "description": "Understand the request, clarify missing details, and resolve or refuse safely.",
            "steps": [
                {
                    "name": "Understand Request",
                    "trigger": "The user asks for help.",
                    "action": "Identify the main request and gather any missing details required to help.",
                },
                {
                    "name": "Respond Safely",
                    "trigger": "The request is clear enough to answer.",
                    "action": "Provide the next best step, or refuse politely if the request is unsafe or disallowed.",
                },
            ],
        }
    ]


def _build_examples(domain: str) -> list[str]:
    """Create a small example library aligned with the inferred domain."""
    if domain == "healthcare":
        return [
            "EXAMPLE 1:\nBegin example\n[user]\nI need to schedule an appointment for recurring migraines.\n[model]\nI can help with that. To route this correctly, what symptoms are you experiencing, how long have they been happening, and are you a new or returning patient?\nEnd example"
        ]
    if domain == "sales":
        return [
            "EXAMPLE 1:\nBegin example\n[user]\nWe have 300 agents and need SOC 2 details.\n[model]\nI can help qualify that. Are you evaluating for a current rollout, who is involved in security review, and what timeline are you working toward?\nEnd example"
        ]
    if domain == "it":
        return [
            "EXAMPLE 1:\nBegin example\n[user]\nI am locked out of Okta.\n[model]\nI can help. Before I suggest the next step, can you confirm whether this affects only Okta or other systems too, and whether you still have access to your recovery factors?\nEnd example"
        ]
    return [
        "EXAMPLE 1:\nBegin example\n[user]\nWhere is my order?\n[model]\nI can help with that. Please share your order number so I can guide the next step safely.\nEnd example"
    ]


def _split_sentences(text: str) -> list[str]:
    """Split freeform text into sentence-like chunks."""
    normalized = " ".join(text.split())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return [part.strip() for part in parts if part.strip()]
