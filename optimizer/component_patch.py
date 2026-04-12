"""Typed patch bundles for component-graph optimization.

A PatchBundle is a validated, serializable collection of ComponentPatch
objects that target specific components in a CanonicalAgent. It supports
apply (producing a new agent), rollback (via old_value tracking), preview,
and conversion to DiffHunk for review UI.

Layer: optimizer. Imports from shared/canonical_ir only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ComponentType(str, Enum):
    """Maps 1:1 to canonical IR component classes."""

    instruction = "instruction"
    tool = "tool"
    routing_rule = "routing_rule"
    guardrail = "guardrail"
    policy = "policy"
    handoff = "handoff"
    sub_agent = "sub_agent"
    mcp_server = "mcp_server"
    environment = "environment"


class PatchOperation(str, Enum):
    """What the patch does to the target component."""

    add = "add"
    modify = "modify"
    remove = "remove"


COMPONENT_TYPE_TO_AGENT_FIELD: dict[ComponentType, str] = {
    ComponentType.instruction: "instructions",
    ComponentType.tool: "tools",
    ComponentType.routing_rule: "routing_rules",
    ComponentType.guardrail: "guardrails",
    ComponentType.policy: "policies",
    ComponentType.handoff: "handoffs",
    ComponentType.sub_agent: "sub_agents",
    ComponentType.mcp_server: "mcp_servers",
    ComponentType.environment: "environment",
}

_NAME_FIELD: dict[ComponentType, str] = {
    ComponentType.instruction: "label",
    ComponentType.tool: "name",
    ComponentType.routing_rule: "target",
    ComponentType.guardrail: "name",
    ComponentType.policy: "name",
    ComponentType.handoff: "target",
    ComponentType.sub_agent: "name",
    ComponentType.mcp_server: "name",
}


@dataclass
class ComponentRef:
    """Path to a specific component in a CanonicalAgent.

    For list-type components, identify by index or name.
    For singleton components (environment), index and name are ignored.
    """

    component_type: ComponentType
    index: int | None = None
    name: str = ""
    sub_agent_path: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_type": self.component_type.value,
            "index": self.index,
            "name": self.name,
            "sub_agent_path": self.sub_agent_path,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ComponentRef:
        return cls(
            component_type=ComponentType(d["component_type"]),
            index=d.get("index"),
            name=d.get("name", ""),
            sub_agent_path=d.get("sub_agent_path", []),
        )

    def display_path(self) -> str:
        """Human-readable path like 'tools[0]' or 'guardrails.content_filter'."""
        agent_field = COMPONENT_TYPE_TO_AGENT_FIELD[self.component_type]
        prefix = "/".join(self.sub_agent_path) + "/" if self.sub_agent_path else ""
        if self.component_type == ComponentType.environment:
            return f"{prefix}{agent_field}"
        if self.name:
            return f"{prefix}{agent_field}.{self.name}"
        if self.index is not None:
            return f"{prefix}{agent_field}[{self.index}]"
        return f"{prefix}{agent_field}"


@dataclass
class ComponentPatch:
    """A single typed change to a component in the canonical agent graph.

    Carries old_value for rollback and conflict detection. For add
    operations, old_value is None. For remove, new_value is None.
    """

    patch_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    operation: PatchOperation = PatchOperation.modify
    ref: ComponentRef = field(default_factory=lambda: ComponentRef(ComponentType.instruction))
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "operation": self.operation.value,
            "ref": self.ref.to_dict(),
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ComponentPatch:
        return cls(
            patch_id=d.get("patch_id", uuid.uuid4().hex[:8]),
            operation=PatchOperation(d["operation"]),
            ref=ComponentRef.from_dict(d["ref"]),
            old_value=d.get("old_value"),
            new_value=d.get("new_value"),
            reasoning=d.get("reasoning", ""),
        )


@dataclass
class PatchValidationError:
    """One validation error in a patch bundle."""

    patch_id: str
    error: str

    def to_dict(self) -> dict[str, Any]:
        return {"patch_id": self.patch_id, "error": self.error}


@dataclass
class PatchBundle:
    """A validated collection of ComponentPatch objects.

    Immutable-apply semantics: apply() returns a new CanonicalAgent
    without modifying the input.
    """

    bundle_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    patches: list[ComponentPatch] = field(default_factory=list)
    description: str = ""
    risk_class: str = "low"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            [p.to_dict() for p in self.patches], sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def touched_surfaces(self) -> list[str]:
        """Unique component types touched by this bundle."""
        return list(dict.fromkeys(p.ref.component_type.value for p in self.patches))

    def validate(self) -> list[PatchValidationError]:
        """Check structural validity of all patches (does not require an agent)."""
        errors: list[PatchValidationError] = []
        for patch in self.patches:
            if patch.operation == PatchOperation.add and patch.new_value is None:
                errors.append(PatchValidationError(
                    patch.patch_id, "add operation requires new_value"
                ))
            if patch.operation == PatchOperation.remove and patch.ref.component_type == ComponentType.environment:
                errors.append(PatchValidationError(
                    patch.patch_id, "cannot remove singleton environment component"
                ))
            if patch.operation == PatchOperation.modify:
                if patch.new_value is None:
                    errors.append(PatchValidationError(
                        patch.patch_id, "modify operation requires new_value"
                    ))
            if (
                patch.ref.component_type != ComponentType.environment
                and patch.operation != PatchOperation.add
                and patch.ref.index is None
                and not patch.ref.name
            ):
                errors.append(PatchValidationError(
                    patch.patch_id,
                    "non-add patch on list component requires index or name",
                ))
        return errors

    def apply(self, agent: Any) -> Any:
        """Apply all patches to a CanonicalAgent, returning a new instance.

        Raises ValueError if a patch targets a component that doesn't exist
        or if old_value doesn't match (conflict detection).
        """
        from shared.canonical_ir import CanonicalAgent

        data = agent.model_dump()
        for patch in self.patches:
            data = _apply_one_patch(data, patch)
        return CanonicalAgent.model_validate(data)

    def preview(self) -> list[dict[str, Any]]:
        """Return a human-readable summary of each patch."""
        result = []
        for patch in self.patches:
            result.append({
                "patch_id": patch.patch_id,
                "operation": patch.operation.value,
                "target": patch.ref.display_path(),
                "reasoning": patch.reasoning,
            })
        return result

    def to_diff_hunks(self) -> list[dict[str, Any]]:
        """Convert patches to DiffHunk-compatible dicts for ProposedChangeCard."""
        hunks = []
        for patch in self.patches:
            hunks.append({
                "hunk_id": patch.patch_id,
                "surface": patch.ref.display_path(),
                "old_value": json.dumps(patch.old_value, indent=2) if patch.old_value else "",
                "new_value": json.dumps(patch.new_value, indent=2) if patch.new_value else "",
                "status": "pending",
            })
        return hunks

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "patches": [p.to_dict() for p in self.patches],
            "description": self.description,
            "risk_class": self.risk_class,
            "created_at": self.created_at,
            "content_hash": self.content_hash,
            "touched_surfaces": self.touched_surfaces,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PatchBundle:
        return cls(
            bundle_id=d.get("bundle_id", uuid.uuid4().hex[:12]),
            patches=[ComponentPatch.from_dict(p) for p in d.get("patches", [])],
            description=d.get("description", ""),
            risk_class=d.get("risk_class", "low"),
            created_at=d.get("created_at", time.time()),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_target_list(data: dict[str, Any], patch: ComponentPatch) -> tuple[dict[str, Any], str]:
    """Walk sub_agent_path and return (target_agent_data, field_name)."""
    target = data
    for sa_name in patch.ref.sub_agent_path:
        sub_agents = target.get("sub_agents", [])
        found = False
        for sa in sub_agents:
            if sa.get("name") == sa_name:
                target = sa
                found = True
                break
        if not found:
            raise ValueError(f"sub-agent '{sa_name}' not found in path")
    field_name = COMPONENT_TYPE_TO_AGENT_FIELD[patch.ref.component_type]
    return target, field_name


def _find_by_name(items: list[dict[str, Any]], name: str, component_type: ComponentType) -> int:
    """Find index of a component by its name field."""
    name_field = _NAME_FIELD.get(component_type, "name")
    for i, item in enumerate(items):
        if item.get(name_field) == name:
            return i
    return -1


def _resolve_index(items: list[dict[str, Any]], ref: ComponentRef) -> int:
    """Resolve a ComponentRef to a list index."""
    if ref.index is not None:
        if 0 <= ref.index < len(items):
            return ref.index
        raise ValueError(
            f"index {ref.index} out of range for {ref.display_path()} (len={len(items)})"
        )
    if ref.name:
        idx = _find_by_name(items, ref.name, ref.component_type)
        if idx < 0:
            raise ValueError(
                f"component '{ref.name}' not found in {ref.display_path()}"
            )
        return idx
    raise ValueError(f"cannot resolve index for {ref.display_path()}: no index or name")


def _apply_one_patch(data: dict[str, Any], patch: ComponentPatch) -> dict[str, Any]:
    """Apply a single patch to agent data dict (mutates in place for perf, caller copies)."""
    data = copy.deepcopy(data)
    target, field_name = _resolve_target_list(data, patch)

    if patch.ref.component_type == ComponentType.environment:
        if patch.operation == PatchOperation.modify:
            existing = target.get(field_name, {})
            if patch.old_value is not None:
                for k, v in patch.old_value.items():
                    if existing.get(k) != v:
                        raise ValueError(
                            f"conflict on {patch.ref.display_path()}.{k}: "
                            f"expected {v!r}, got {existing.get(k)!r}"
                        )
            if patch.new_value:
                existing.update(patch.new_value)
            target[field_name] = existing
        elif patch.operation == PatchOperation.add:
            existing = target.get(field_name, {})
            if patch.new_value:
                existing.update(patch.new_value)
            target[field_name] = existing
        return data

    items = target.get(field_name, [])

    if patch.operation == PatchOperation.add:
        if patch.new_value is not None:
            items.append(patch.new_value)
        target[field_name] = items
        return data

    idx = _resolve_index(items, patch.ref)

    if patch.operation == PatchOperation.remove:
        if patch.old_value is not None:
            name_field = _NAME_FIELD.get(patch.ref.component_type, "name")
            actual_name = items[idx].get(name_field, "")
            expected_name = patch.old_value.get(name_field, "")
            if expected_name and actual_name != expected_name:
                raise ValueError(
                    f"conflict on {patch.ref.display_path()}: "
                    f"expected name={expected_name!r}, got {actual_name!r}"
                )
        items.pop(idx)
        target[field_name] = items
        return data

    if patch.operation == PatchOperation.modify:
        existing = items[idx]
        if patch.old_value is not None:
            for k, v in patch.old_value.items():
                if existing.get(k) != v:
                    raise ValueError(
                        f"conflict on {patch.ref.display_path()}.{k}: "
                        f"expected {v!r}, got {existing.get(k)!r}"
                    )
        if patch.new_value is not None:
            existing.update(patch.new_value)
        items[idx] = existing
        target[field_name] = items
        return data

    return data
