"""Bulk import registry items from YAML/JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from registry.store import RegistryStore
from registry.skills import SkillRegistry
from registry.policies import PolicyRegistry
from registry.tool_contracts import ToolContractRegistry
from registry.handoff_schemas import HandoffSchemaRegistry


def import_from_file(file_path: str, store: RegistryStore) -> dict[str, int]:
    """Import registry items from YAML/JSON. Returns {type: count} of imported items.

    Supports format::

        skills:
          - name: returns_handling
            instructions: "..."
        policies:
          - name: safety_rules
            rules: [...]
        tool_contracts:
          - tool_name: order_lookup
            ...
        handoff_schemas:
          - name: support_to_billing
            ...
    """
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")

    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError("PyYAML is required for YAML import: pip install pyyaml") from exc
        data: dict[str, Any] = yaml.safe_load(text) or {}
    elif path.suffix == ".json":
        data = json.loads(text)
    else:
        # Try JSON first, then YAML
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                import yaml  # type: ignore[import-untyped]
                data = yaml.safe_load(text) or {}
            except ImportError as exc:
                raise ImportError(
                    "PyYAML is required for non-JSON import: pip install pyyaml"
                ) from exc

    counts: dict[str, int] = {}

    # Skills
    skills_data = data.get("skills", [])
    if skills_data:
        reg = SkillRegistry(store)
        for item in skills_data:
            reg.register(
                name=item["name"],
                instructions=item.get("instructions", ""),
                examples=item.get("examples"),
                tool_requirements=item.get("tool_requirements"),
                constraints=item.get("constraints"),
                metadata=item.get("metadata"),
            )
        counts["skills"] = len(skills_data)

    # Policies
    policies_data = data.get("policies", [])
    if policies_data:
        reg_p = PolicyRegistry(store)
        for item in policies_data:
            reg_p.register(
                name=item["name"],
                rules=item.get("rules", []),
                enforcement=item.get("enforcement", "hard"),
                scope=item.get("scope", "global"),
                metadata=item.get("metadata"),
            )
        counts["policies"] = len(policies_data)

    # Tool contracts
    tc_data = data.get("tool_contracts", [])
    if tc_data:
        reg_tc = ToolContractRegistry(store)
        for item in tc_data:
            reg_tc.register(
                tool_name=item["tool_name"],
                input_schema=item.get("input_schema"),
                output_schema=item.get("output_schema"),
                side_effect_class=item.get("side_effect_class", "pure"),
                replay_mode=item.get("replay_mode", "deterministic_stub"),
                description=item.get("description", ""),
                metadata=item.get("metadata"),
            )
        counts["tool_contracts"] = len(tc_data)

    # Handoff schemas
    hs_data = data.get("handoff_schemas", [])
    if hs_data:
        reg_hs = HandoffSchemaRegistry(store)
        for item in hs_data:
            reg_hs.register(
                name=item["name"],
                from_agent=item.get("from_agent", ""),
                to_agent=item.get("to_agent", ""),
                required_fields=item.get("required_fields", []),
                optional_fields=item.get("optional_fields"),
                validation_rules=item.get("validation_rules"),
                metadata=item.get("metadata"),
            )
        counts["handoff_schemas"] = len(hs_data)

    return counts
