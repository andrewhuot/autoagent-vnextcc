"""Extension methods for CxMapper to export AutoAgent artifacts to CX Studio format."""
from __future__ import annotations

from typing import Any

from .types import CxTool


def integration_templates_to_cx_tools(
    integration_templates: list[dict[str, Any]],
    agent_name: str,
) -> list[CxTool]:
    """Convert AutoAgent integration templates to CX Tool definitions.

    Args:
        integration_templates: List of integration templates from build_agent_artifact.
        agent_name: Fully-qualified agent name for resource path generation.

    Returns:
        List of CxTool instances ready to be created via CxClient.
    """
    tools: list[CxTool] = []
    for idx, template in enumerate(integration_templates):
        connector = template.get("connector", "Custom")
        name = template.get("name", f"tool_{idx}")
        method = template.get("method", "POST")
        endpoint = template.get("endpoint", "/")
        auth_strategy = template.get("auth_strategy", "bearer_token")

        # Build OpenAPI spec for this tool
        spec = {
            "type": "OPEN_API",
            "schema": {
                "openapi": "3.0.0",
                "info": {"title": f"{connector} Integration", "version": "1.0.0"},
                "servers": [{"url": "https://api.example.com"}],
                "paths": {
                    endpoint: {
                        method.lower(): {
                            "operationId": name,
                            "summary": f"{connector} {name}",
                            "parameters": [],
                            "responses": {"200": {"description": "Success"}},
                        }
                    }
                },
                "components": {
                    "securitySchemes": {
                        "auth": {
                            "type": "http" if "bearer" in auth_strategy else "apiKey",
                            "scheme": "bearer" if "bearer" in auth_strategy else None,
                        }
                    }
                },
            },
            "authentication": {"type": auth_strategy},
        }

        tools.append(
            CxTool(
                name=f"{agent_name}/tools/{name}",
                display_name=f"{connector}: {name}",
                tool_type="OPEN_API",
                spec=spec,
            )
        )
    return tools


def knowledge_asset_to_cx_datastore(
    knowledge_asset: dict[str, Any],
    display_name: str = "AutoAgent Knowledge Base",
) -> dict[str, Any]:
    """Convert AutoAgent knowledge asset to CX DataStore creation payload.

    Args:
        knowledge_asset: Knowledge asset dict from transcript intelligence.
        display_name: Display name for the data store.

    Returns:
        Dict suitable for CxClient.create_data_store call.
    """
    content_entries: list[dict[str, Any]] = []

    for entry in knowledge_asset.get("entries", []):
        entry_type = entry.get("type", "unknown")
        if entry_type == "faq":
            content_entries.append({
                "contentType": "FAQ",
                "question": entry.get("question", ""),
                "answer": entry.get("answer", ""),
                "metadata": {"intent": entry.get("intent", "")},
            })
        elif entry_type == "procedure":
            content_entries.append({
                "contentType": "DOCUMENT",
                "title": entry.get("intent", "Procedure"),
                "content": "\n".join(entry.get("steps", [])),
                "metadata": {"type": "procedure"},
            })
        elif entry_type == "workflow":
            content_entries.append({
                "contentType": "DOCUMENT",
                "title": entry.get("title", "Workflow"),
                "content": entry.get("description", ""),
                "metadata": {"type": "workflow"},
            })

    return {
        "display_name": display_name,
        "content_entries": content_entries,
        "data_store_type": "unstructured",
    }


def guardrails_to_cx_safety_settings(
    guardrails: list[str],
) -> dict[str, Any]:
    """Convert AutoAgent guardrails to CX Agent generativeSettings.safetySettings.

    Args:
        guardrails: List of guardrail strings from build_agent_artifact.

    Returns:
        Dict with CX safety settings configuration.
    """
    banned_phrases: list[str] = []
    safety_categories: list[str] = []

    for guardrail in guardrails:
        lower = guardrail.lower()
        if "never disclose" in lower or "do not share" in lower:
            # Extract what should not be disclosed
            if "internal notes" in lower:
                banned_phrases.append("internal notes")
            if "pricing" in lower:
                banned_phrases.append("pricing")
            safety_categories.append("HARM_CATEGORY_DANGEROUS_CONTENT")

        if "require verification" in lower or "verify" in lower:
            safety_categories.append("HARM_CATEGORY_HARASSMENT")

    return {
        "bannedPhrases": banned_phrases,
        "safetySettings": [
            {"category": cat, "threshold": "BLOCK_LOW_AND_ABOVE"}
            for cat in set(safety_categories)
        ],
    }


def skills_to_cx_playbooks(
    skills: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert AutoAgent runtime skills to CX Playbook definitions.

    Maps runtime skills to CX Agent Studio playbooks, tools, and generators.

    Args:
        skills: List of Skill dicts from core.skills

    Returns:
        List of CX playbook/tool definitions ready for export.
    """
    playbooks: list[dict[str, Any]] = []

    for skill in skills:
        skill_kind = skill.get("kind", "runtime")

        # Only export runtime skills to CX
        if skill_kind != "runtime":
            continue

        # Map to playbook if skill has instructions
        if skill.get("instructions"):
            playbooks.append({
                "type": "playbook",
                "name": skill.get("name", ""),
                "description": skill.get("description", ""),
                "instructions": skill.get("instructions", ""),
                "triggers": [t.get("failure_family") for t in skill.get("triggers", []) if t.get("failure_family")],
            })

        # Map to tools if skill has tool definitions
        for tool in skill.get("tools", []):
            playbooks.append({
                "type": "tool",
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
                "sandbox_policy": tool.get("sandbox_policy", "read_only"),
            })

        # Map policies to safety settings
        for policy in skill.get("policies", []):
            playbooks.append({
                "type": "policy",
                "name": policy.get("name", ""),
                "description": policy.get("description", ""),
                "rule_type": policy.get("rule_type", ""),
                "condition": policy.get("condition", ""),
                "action": policy.get("action", ""),
            })

    return playbooks
