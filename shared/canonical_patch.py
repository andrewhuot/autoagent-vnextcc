"""Typed patch bundles for canonical agent components.

This module gives optimizers and review tools a structured patch language that
targets the canonical component graph instead of opaque config buckets.  The
first version intentionally stays small: components are identified by stable
JSON-pointer paths inside ``CanonicalAgent`` and patches are applied only after
the referenced component validates against the current canonical graph.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, Field

from shared.canonical_ir import CanonicalAgent
from shared.canonical_ir_convert import from_config_dict, to_config_dict


PatchOp = Literal["add", "append", "remove", "replace", "set", "update"]


class ComponentReference(BaseModel):
    """Stable address for one component in a canonical agent graph."""

    component_id: str = ""
    component_type: str
    name: str
    path: str
    agent_path: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComponentAttribution(BaseModel):
    """Credit-assignment record linking a failure to one component."""

    component: ComponentReference
    failure_reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.5
    source: str = "eval"


class ComponentPatchOperation(BaseModel):
    """One typed mutation against a canonical component field."""

    op: PatchOp
    component: ComponentReference
    field_path: str = ""
    value: Any = None
    rationale: str = ""


class PatchValidationResult(BaseModel):
    """Validation result for a typed patch bundle."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TypedPatchBundle(BaseModel):
    """Reviewable group of typed operations against a canonical component graph."""

    schema_version: str = "canonical-component-patch/v1"
    bundle_id: str
    title: str = ""
    operations: list[ComponentPatchOperation] = Field(default_factory=list)
    source: str = ""
    component_attributions: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


_CANONICAL_CONFIG_KEYS = {
    "adapter",
    "flows",
    "generation",
    "guardrails",
    "handoffs",
    "mcp_servers",
    "model",
    "policies",
    "prompts",
    "routing",
    "tools_config",
}


def iter_component_references(
    agent: CanonicalAgent,
    *,
    path_prefix: str = "",
    agent_path: str = "",
) -> list[ComponentReference]:
    """Return canonical patch addresses for every optimizable component.

    WHY: optimizers need a stable vocabulary for proposals that survives config
    serialization and makes failures reviewable as component-specific evidence.
    """

    scope = agent_path or agent.name or "root"
    refs: list[ComponentReference] = []
    for index, instruction in enumerate(agent.instructions):
        name = instruction.label or f"{instruction.role.value}_{index}"
        refs.append(_reference(scope, "instruction", name, f"{path_prefix}/instructions/{index}"))
    for index, tool in enumerate(agent.tools):
        refs.append(_reference(scope, "tool_contract", tool.name, f"{path_prefix}/tools/{index}"))
    for index, rule in enumerate(agent.routing_rules):
        refs.append(_reference(scope, "routing_rule", rule.target, f"{path_prefix}/routing_rules/{index}"))
    for index, guardrail in enumerate(agent.guardrails):
        refs.append(_reference(scope, "guardrail", guardrail.name, f"{path_prefix}/guardrails/{index}"))
    for index, policy in enumerate(agent.policies):
        component_type = "callback" if policy.metadata.get("callback_type") else "policy"
        refs.append(_reference(scope, component_type, policy.name, f"{path_prefix}/policies/{index}"))
    for index, handoff in enumerate(agent.handoffs):
        name = f"{handoff.source}->{handoff.target}" if handoff.source else handoff.target
        refs.append(_reference(scope, "handoff", name, f"{path_prefix}/handoffs/{index}"))
    for index, server in enumerate(agent.mcp_servers):
        refs.append(_reference(scope, "mcp_server", server.name, f"{path_prefix}/mcp_servers/{index}"))

    refs.append(_reference(scope, "environment", "environment", f"{path_prefix}/environment"))

    for fi, flow in enumerate(agent.flows):
        flow_path = f"{path_prefix}/flows/{fi}"
        flow_name = flow.name or flow.display_name or f"flow_{fi}"
        refs.append(_reference(scope, "flow", flow_name, flow_path))
        for si, state in enumerate(flow.states):
            state_path = f"{flow_path}/states/{si}"
            state_name = state.name or state.display_name or f"state_{si}"
            refs.append(_reference(scope, "state", state_name, state_path))
            for ti, transition in enumerate(state.transitions):
                t_path = f"{state_path}/transitions/{ti}"
                t_name = transition.target or f"transition_{ti}"
                refs.append(_reference(scope, "transition", t_name, t_path))
        for ti, transition in enumerate(flow.transitions):
            t_path = f"{flow_path}/transitions/{ti}"
            t_name = transition.target or f"transition_{ti}"
            refs.append(_reference(scope, "transition", t_name, t_path))

    for index, sub_agent in enumerate(agent.sub_agents):
        sub_path = f"{path_prefix}/sub_agents/{index}"
        sub_scope = f"{scope}/{sub_agent.name or f'sub_agent_{index}'}"
        refs.append(_reference(scope, "sub_agent", sub_agent.name or f"sub_agent_{index}", sub_path))
        refs.extend(
            iter_component_references(
                sub_agent,
                path_prefix=sub_path,
                agent_path=sub_scope,
            )
        )
    return refs


def find_component_reference(
    agent: CanonicalAgent,
    component_type: str,
    name: str,
) -> ComponentReference | None:
    """Find the first component reference by type and case-insensitive name."""

    normalized_type = component_type.strip().lower()
    normalized_name = name.strip().lower()
    for ref in iter_component_references(agent):
        if ref.component_type.lower() != normalized_type:
            continue
        if ref.name.lower() == normalized_name:
            return ref
    return None


def validate_patch_bundle(
    agent: CanonicalAgent,
    bundle: TypedPatchBundle | dict[str, Any],
) -> PatchValidationResult:
    """Validate that every patch operation addresses an existing component."""

    typed_bundle = _coerce_bundle(bundle)
    available_by_path = {ref.path: ref for ref in iter_component_references(agent)}
    errors: list[str] = []
    warnings: list[str] = []
    payload = agent.model_dump(mode="python")

    for index, operation in enumerate(typed_bundle.operations):
        component = operation.component
        current_ref = available_by_path.get(component.path)
        if current_ref is None:
            errors.append(
                f"Operation {index} references missing component "
                f"{component.component_type}:{component.name} at {component.path}"
            )
            continue
        if current_ref.component_type != component.component_type:
            errors.append(
                f"Operation {index} component type mismatch at {component.path}: "
                f"expected {current_ref.component_type}, got {component.component_type}"
            )
        if current_ref.name != component.name:
            warnings.append(
                f"Operation {index} component name differs at {component.path}: "
                f"current={current_ref.name}, proposed={component.name}"
            )

        target_pointer = _operation_pointer(operation)
        if operation.op in {"append", "replace", "set", "update", "remove"}:
            try:
                target = _get_at_pointer(payload, target_pointer)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                errors.append(f"Operation {index} cannot resolve target {target_pointer}: {exc}")
                continue
            if operation.op == "append" and not isinstance(target, list):
                errors.append(f"Operation {index} target {target_pointer} is not a list")
        elif operation.op == "add":
            try:
                _parent_for_pointer(payload, target_pointer)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                errors.append(f"Operation {index} cannot resolve parent for {target_pointer}: {exc}")

    return PatchValidationResult(valid=not errors, errors=errors, warnings=warnings)


def apply_patch_bundle(
    agent: CanonicalAgent,
    bundle: TypedPatchBundle | dict[str, Any],
) -> CanonicalAgent:
    """Apply a validated patch bundle to a copy of ``agent``."""

    typed_bundle = _coerce_bundle(bundle)
    validation = validate_patch_bundle(agent, typed_bundle)
    if not validation.valid:
        raise ValueError("Invalid patch bundle: " + "; ".join(validation.errors))

    payload = copy.deepcopy(agent.model_dump(mode="python"))
    for operation in typed_bundle.operations:
        pointer = _operation_pointer(operation)
        if operation.op in {"replace", "set", "update", "add"}:
            _set_at_pointer(payload, pointer, operation.value)
        elif operation.op == "append":
            target = _get_at_pointer(payload, pointer)
            values = operation.value if isinstance(operation.value, list) else [operation.value]
            for value in values:
                if value not in target:
                    target.append(value)
        elif operation.op == "remove":
            _remove_at_pointer(payload, pointer)

    return CanonicalAgent.model_validate(payload)


def patch_bundle_to_config(
    current_config: dict[str, Any],
    bundle: TypedPatchBundle | dict[str, Any],
    *,
    agent_name: str = "",
    platform: str = "",
) -> dict[str, Any]:
    """Apply a canonical patch bundle and merge canonical surfaces back to config.

    WHY: current deployment and review flows still carry raw AgentLab config
    dictionaries.  This bridge lets typed component patches become the apply
    authority without dropping unrelated legacy keys such as thresholds.
    """

    before_agent = from_config_dict(current_config, name=agent_name, platform=platform)
    after_agent = apply_patch_bundle(before_agent, bundle)
    canonical_config = to_config_dict(after_agent)
    merged = copy.deepcopy(current_config)
    for key in _CANONICAL_CONFIG_KEYS:
        if key in canonical_config:
            merged[key] = canonical_config[key]
    return merged


def _reference(scope: str, component_type: str, name: str, path: str) -> ComponentReference:
    normalized_path = path or "/"
    component_id = f"{scope}:{component_type}:{name or normalized_path}"
    return ComponentReference(
        component_id=component_id,
        component_type=component_type,
        name=name,
        path=normalized_path,
        agent_path=scope,
    )


def _coerce_bundle(bundle: TypedPatchBundle | dict[str, Any]) -> TypedPatchBundle:
    if isinstance(bundle, TypedPatchBundle):
        return bundle
    return TypedPatchBundle.model_validate(bundle)


def _operation_pointer(operation: ComponentPatchOperation) -> str:
    field_path = operation.field_path.strip()
    base = operation.component.path.rstrip("/") or ""
    if not field_path:
        return base or "/"
    if field_path.startswith("/"):
        return f"{base}{field_path}"
    parts = [part for part in field_path.split(".") if part]
    suffix = "/" + "/".join(_escape_pointer_part(part) for part in parts)
    return f"{base}{suffix}"


def _escape_pointer_part(part: str) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def _unescape_pointer_part(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def _pointer_parts(pointer: str) -> list[str]:
    if pointer in {"", "/"}:
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {pointer}")
    return [_unescape_pointer_part(part) for part in pointer.split("/")[1:]]


def _get_at_pointer(payload: Any, pointer: str) -> Any:
    target = payload
    for part in _pointer_parts(pointer):
        if isinstance(target, list):
            target = target[int(part)]
        elif isinstance(target, dict):
            target = target[part]
        else:
            raise TypeError(f"Cannot traverse into {type(target).__name__}")
    return target


def _parent_for_pointer(payload: Any, pointer: str) -> tuple[Any, str]:
    parts = _pointer_parts(pointer)
    if not parts:
        raise ValueError("Cannot resolve a parent for the document root")
    parent_pointer = "/" + "/".join(_escape_pointer_part(part) for part in parts[:-1])
    if len(parts) == 1:
        parent_pointer = ""
    return _get_at_pointer(payload, parent_pointer), parts[-1]


def _set_at_pointer(payload: Any, pointer: str, value: Any) -> None:
    parent, key = _parent_for_pointer(payload, pointer)
    if isinstance(parent, list):
        index = int(key)
        if index == len(parent):
            parent.append(value)
        else:
            parent[index] = value
    elif isinstance(parent, dict):
        parent[key] = value
    else:
        raise TypeError(f"Cannot set value on {type(parent).__name__}")


def _remove_at_pointer(payload: Any, pointer: str) -> None:
    parent, key = _parent_for_pointer(payload, pointer)
    if isinstance(parent, list):
        del parent[int(key)]
    elif isinstance(parent, dict):
        del parent[key]
    else:
        raise TypeError(f"Cannot remove value from {type(parent).__name__}")
