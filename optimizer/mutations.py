"""Typed mutation registry for prompt/config optimization.

Provides a strongly-typed registry of mutation operators that the optimizer
can apply to agent configurations. Each operator declares its risk class,
target surface, preconditions, and rollback strategy.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskClass(Enum):
    """Risk classification for mutation operators."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"

    def __le__(self, other: RiskClass) -> bool:  # type: ignore[override]
        order = [RiskClass.low, RiskClass.medium, RiskClass.high, RiskClass.critical]
        return order.index(self) <= order.index(other)

    def __lt__(self, other: RiskClass) -> bool:  # type: ignore[override]
        order = [RiskClass.low, RiskClass.medium, RiskClass.high, RiskClass.critical]
        return order.index(self) < order.index(other)

    def __ge__(self, other: RiskClass) -> bool:  # type: ignore[override]
        return not self.__lt__(other)

    def __gt__(self, other: RiskClass) -> bool:  # type: ignore[override]
        return not self.__le__(other)


class MutationSurface(Enum):
    """Target surface that a mutation operator modifies."""

    instruction = "instruction"
    few_shot = "few_shot"
    tool_description = "tool_description"
    model = "model"
    generation_settings = "generation_settings"
    callback = "callback"
    context_caching = "context_caching"
    memory_policy = "memory_policy"
    routing = "routing"
    workflow = "workflow"
    skill = "skill"
    policy = "policy"
    tool_contract = "tool_contract"
    handoff_schema = "handoff_schema"


@dataclass
class MutationOperator:
    """A single mutation operator that can be applied to an agent config.

    Attributes:
        name: Unique identifier for this operator.
        surface: Which part of the config this operator targets.
        risk_class: How risky this mutation is to apply.
        preconditions: Human-readable preconditions that must hold.
        validator: Optional callable that validates the output config.
        rollback_strategy: Description of how to undo this mutation.
        estimated_eval_cost: Estimated cost (in USD) to evaluate this mutation.
        supports_autodeploy: Whether this mutation can be auto-promoted.
        description: Human-readable description of what this operator does.
        apply: Function that takes (current_config, params) and returns new_config.
    """

    name: str
    surface: MutationSurface
    risk_class: RiskClass
    preconditions: list[str] = field(default_factory=list)
    validator: Callable[[dict[str, Any]], bool] | None = None
    rollback_strategy: str = "revert to previous config"
    estimated_eval_cost: float = 0.0
    supports_autodeploy: bool = False
    description: str = ""
    apply: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] = field(
        default_factory=lambda: lambda config, params: config
    )
    ready: bool = True


class MutationRegistry:
    """Registry of available mutation operators."""

    def __init__(self) -> None:
        self._operators: dict[str, MutationOperator] = {}

    def register(self, operator: MutationOperator) -> None:
        """Register a mutation operator."""
        self._operators[operator.name] = operator

    def get(self, name: str) -> MutationOperator | None:
        """Get an operator by name, or None if not found."""
        return self._operators.get(name)

    def list_all(self) -> list[MutationOperator]:
        """Return all registered operators."""
        return list(self._operators.values())

    def list_by_surface(self, surface: MutationSurface) -> list[MutationOperator]:
        """Return operators targeting a specific surface."""
        return [op for op in self._operators.values() if op.surface == surface]

    def list_by_risk(self, max_risk: RiskClass) -> list[MutationOperator]:
        """Return operators at or below the given risk level."""
        return [op for op in self._operators.values() if op.risk_class <= max_risk]

    def list_autodeploy(self) -> list[MutationOperator]:
        """Return only operators that support auto-deployment."""
        return [op for op in self._operators.values() if op.supports_autodeploy]

    def get_ready_operators(self) -> list[MutationOperator]:
        """Return only operators that are ready to use (ready=True)."""
        return [op for op in self._operators.values() if op.ready]


# ---------------------------------------------------------------------------
# Default operator apply functions
# ---------------------------------------------------------------------------


def _apply_instruction_rewrite(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Rewrite a system prompt (root or specialist)."""
    cfg = copy.deepcopy(config)
    target = params.get("target", "root")
    new_text = params.get("text", "")
    if "prompts" not in cfg:
        cfg["prompts"] = {}
    cfg["prompts"][target] = new_text
    return cfg


def _validate_instruction_rewrite(config: dict[str, Any]) -> bool:
    return isinstance(config.get("prompts"), dict) and any(
        isinstance(v, str) for v in config["prompts"].values()
    )


def _apply_few_shot_edit(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Add or modify few-shot examples."""
    cfg = copy.deepcopy(config)
    target = params.get("target", "root")
    examples = params.get("examples", [])
    if "few_shot" not in cfg:
        cfg["few_shot"] = {}
    cfg["few_shot"][target] = examples
    return cfg


def _validate_few_shot_edit(config: dict[str, Any]) -> bool:
    return isinstance(config.get("few_shot"), dict)


def _apply_tool_description_edit(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Modify a tool's configuration."""
    cfg = copy.deepcopy(config)
    tool_name = params.get("tool_name", "")
    updates = params.get("updates", {})
    if "tools" not in cfg:
        cfg["tools"] = {}
    if tool_name not in cfg["tools"]:
        cfg["tools"][tool_name] = {}
    cfg["tools"][tool_name].update(updates)
    return cfg


def _validate_tool_description_edit(config: dict[str, Any]) -> bool:
    return isinstance(config.get("tools"), dict)


def _apply_model_swap(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Swap the model field."""
    cfg = copy.deepcopy(config)
    cfg["model"] = params.get("model", cfg.get("model", "gemini-2.0-flash"))
    return cfg


def _validate_model_swap(config: dict[str, Any]) -> bool:
    return isinstance(config.get("model"), str) and len(config["model"]) > 0


def _apply_generation_settings(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Adjust generation settings (temperature, max_tokens, etc.)."""
    cfg = copy.deepcopy(config)
    if "generation_settings" not in cfg:
        cfg["generation_settings"] = {}
    for key in ("temperature", "max_tokens", "top_p", "top_k"):
        if key in params:
            cfg["generation_settings"][key] = params[key]
    return cfg


def _validate_generation_settings(config: dict[str, Any]) -> bool:
    gs = config.get("generation_settings")
    return isinstance(gs, dict)


def _apply_callback_patch(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Modify callback configurations."""
    cfg = copy.deepcopy(config)
    callback_name = params.get("callback_name", "")
    callback_config = params.get("config", {})
    if "callbacks" not in cfg:
        cfg["callbacks"] = {}
    cfg["callbacks"][callback_name] = callback_config
    return cfg


def _validate_callback_patch(config: dict[str, Any]) -> bool:
    return isinstance(config.get("callbacks"), dict)


def _apply_context_caching(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Adjust context caching thresholds and TTL."""
    cfg = copy.deepcopy(config)
    if "context_caching" not in cfg:
        cfg["context_caching"] = {}
    for key in ("enabled", "threshold_tokens", "ttl_seconds", "max_use_count"):
        if key in params:
            cfg["context_caching"][key] = params[key]
    return cfg


def _validate_context_caching(config: dict[str, Any]) -> bool:
    return isinstance(config.get("context_caching"), dict)


def _apply_memory_policy(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Adjust memory preload/writeback policy."""
    cfg = copy.deepcopy(config)
    if "memory_policy" not in cfg:
        cfg["memory_policy"] = {}
    for key in ("preload", "on_demand", "write_back", "max_entries"):
        if key in params:
            cfg["memory_policy"][key] = params[key]
    return cfg


def _validate_memory_policy(config: dict[str, Any]) -> bool:
    return isinstance(config.get("memory_policy"), dict)


def _apply_routing_edit(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Modify routing rules and keywords."""
    cfg = copy.deepcopy(config)
    if "routing" not in cfg:
        cfg["routing"] = {}
    if "rules" not in cfg["routing"]:
        cfg["routing"]["rules"] = []
    action = params.get("action", "add")
    if action == "add":
        rule = params.get("rule", {})
        cfg["routing"]["rules"].append(rule)
    elif action == "remove":
        index = params.get("index", -1)
        if 0 <= index < len(cfg["routing"]["rules"]):
            cfg["routing"]["rules"].pop(index)
    elif action == "replace":
        cfg["routing"]["rules"] = params.get("rules", [])
    return cfg


def _validate_routing_edit(config: dict[str, Any]) -> bool:
    routing = config.get("routing")
    return isinstance(routing, dict) and isinstance(routing.get("rules"), list)


# ---------------------------------------------------------------------------
# Registry-aware mutation apply functions
# ---------------------------------------------------------------------------


def _apply_skill_rewrite(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Rewrite a skill's instructions or metadata by (name, version)."""
    cfg = copy.deepcopy(config)
    skill_name = params.get("name", "")
    if "skills" not in cfg:
        cfg["skills"] = {}
    if skill_name not in cfg["skills"]:
        cfg["skills"][skill_name] = {}
    for key in ("instructions", "examples", "constraints", "tool_requirements", "metadata"):
        if key in params:
            cfg["skills"][skill_name][key] = params[key]
    return cfg


def _validate_skill_rewrite(config: dict[str, Any]) -> bool:
    return isinstance(config.get("skills"), dict)


def _apply_policy_edit(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Edit a policy pack's rules or enforcement settings."""
    cfg = copy.deepcopy(config)
    policy_name = params.get("name", "")
    if "policies" not in cfg:
        cfg["policies"] = {}
    if policy_name not in cfg["policies"]:
        cfg["policies"][policy_name] = {}
    for key in ("rules", "enforcement", "scope", "metadata"):
        if key in params:
            cfg["policies"][policy_name][key] = params[key]
    return cfg


def _validate_policy_edit(config: dict[str, Any]) -> bool:
    return isinstance(config.get("policies"), dict)


def _apply_tool_contract_edit(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Edit a tool contract's schema or replay settings."""
    cfg = copy.deepcopy(config)
    tool_name = params.get("tool_name", "")
    if "tool_contracts" not in cfg:
        cfg["tool_contracts"] = {}
    if tool_name not in cfg["tool_contracts"]:
        cfg["tool_contracts"][tool_name] = {}
    for key in ("input_schema", "output_schema", "side_effect_class", "replay_mode", "description", "metadata"):
        if key in params:
            cfg["tool_contracts"][tool_name][key] = params[key]
    return cfg


def _validate_tool_contract_edit(config: dict[str, Any]) -> bool:
    return isinstance(config.get("tool_contracts"), dict)


def _apply_handoff_schema_edit(
    config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Edit a handoff schema's fields or validation rules."""
    cfg = copy.deepcopy(config)
    schema_name = params.get("name", "")
    if "handoff_schemas" not in cfg:
        cfg["handoff_schemas"] = {}
    if schema_name not in cfg["handoff_schemas"]:
        cfg["handoff_schemas"][schema_name] = {}
    for key in ("from_agent", "to_agent", "required_fields", "optional_fields", "validation_rules", "metadata"):
        if key in params:
            cfg["handoff_schemas"][schema_name][key] = params[key]
    return cfg


def _validate_handoff_schema_edit(config: dict[str, Any]) -> bool:
    return isinstance(config.get("handoff_schemas"), dict)


# ---------------------------------------------------------------------------
# Default registry factory
# ---------------------------------------------------------------------------


def create_default_registry() -> MutationRegistry:
    """Create a MutationRegistry pre-populated with the 13 first-party operators."""
    registry = MutationRegistry()

    registry.register(
        MutationOperator(
            name="instruction_rewrite",
            surface=MutationSurface.instruction,
            risk_class=RiskClass.low,
            preconditions=["prompts section exists in config"],
            validator=_validate_instruction_rewrite,
            rollback_strategy="revert prompts to previous version",
            estimated_eval_cost=0.01,
            supports_autodeploy=True,
            description="Rewrite root or specialist system prompts.",
            apply=_apply_instruction_rewrite,
        )
    )

    registry.register(
        MutationOperator(
            name="few_shot_edit",
            surface=MutationSurface.few_shot,
            risk_class=RiskClass.low,
            preconditions=[],
            validator=_validate_few_shot_edit,
            rollback_strategy="remove added few-shot examples",
            estimated_eval_cost=0.02,
            supports_autodeploy=True,
            description="Add or modify few-shot examples for any agent.",
            apply=_apply_few_shot_edit,
        )
    )

    registry.register(
        MutationOperator(
            name="tool_description_edit",
            surface=MutationSurface.tool_description,
            risk_class=RiskClass.medium,
            preconditions=["tools section exists in config"],
            validator=_validate_tool_description_edit,
            rollback_strategy="revert tool config to previous version",
            estimated_eval_cost=0.03,
            supports_autodeploy=False,
            description="Modify tool configurations (timeout, description, etc.).",
            apply=_apply_tool_description_edit,
        )
    )

    registry.register(
        MutationOperator(
            name="model_swap",
            surface=MutationSurface.model,
            risk_class=RiskClass.high,
            preconditions=["target model is available in provider"],
            validator=_validate_model_swap,
            rollback_strategy="revert to previous model",
            estimated_eval_cost=0.10,
            supports_autodeploy=False,
            description="Change the model used by the agent.",
            apply=_apply_model_swap,
        )
    )

    registry.register(
        MutationOperator(
            name="generation_settings",
            surface=MutationSurface.generation_settings,
            risk_class=RiskClass.low,
            preconditions=[],
            validator=_validate_generation_settings,
            rollback_strategy="revert generation settings",
            estimated_eval_cost=0.01,
            supports_autodeploy=True,
            description="Adjust temperature, max_tokens, and other generation params.",
            apply=_apply_generation_settings,
        )
    )

    registry.register(
        MutationOperator(
            name="callback_patch",
            surface=MutationSurface.callback,
            risk_class=RiskClass.high,
            preconditions=["callback system is initialized"],
            validator=_validate_callback_patch,
            rollback_strategy="remove patched callback and restore original",
            estimated_eval_cost=0.05,
            supports_autodeploy=False,
            description="Modify callback configurations.",
            apply=_apply_callback_patch,
        )
    )

    registry.register(
        MutationOperator(
            name="context_caching",
            surface=MutationSurface.context_caching,
            risk_class=RiskClass.medium,
            preconditions=["context caching is supported by provider"],
            validator=_validate_context_caching,
            rollback_strategy="revert caching settings to defaults",
            estimated_eval_cost=0.02,
            supports_autodeploy=True,
            description="Adjust context caching thresholds and TTL.",
            apply=_apply_context_caching,
        )
    )

    registry.register(
        MutationOperator(
            name="memory_policy",
            surface=MutationSurface.memory_policy,
            risk_class=RiskClass.medium,
            preconditions=["memory subsystem is enabled"],
            validator=_validate_memory_policy,
            rollback_strategy="revert memory policy to defaults",
            estimated_eval_cost=0.02,
            supports_autodeploy=True,
            description="Adjust memory preload/writeback policy.",
            apply=_apply_memory_policy,
        )
    )

    registry.register(
        MutationOperator(
            name="routing_edit",
            surface=MutationSurface.routing,
            risk_class=RiskClass.medium,
            preconditions=["routing section exists in config"],
            validator=_validate_routing_edit,
            rollback_strategy="revert routing rules to previous version",
            estimated_eval_cost=0.03,
            supports_autodeploy=False,
            description="Modify routing rules and keyword mappings.",
            apply=_apply_routing_edit,
        )
    )

    # --- Registry-aware operators ---

    registry.register(
        MutationOperator(
            name="skill_rewrite",
            surface=MutationSurface.skill,
            risk_class=RiskClass.low,
            preconditions=["skill exists in registry"],
            validator=_validate_skill_rewrite,
            rollback_strategy="revert skill to previous version in registry",
            estimated_eval_cost=0.01,
            supports_autodeploy=True,
            description="Rewrite a skill's instructions or metadata.",
            apply=_apply_skill_rewrite,
        )
    )

    registry.register(
        MutationOperator(
            name="policy_edit",
            surface=MutationSurface.policy,
            risk_class=RiskClass.medium,
            preconditions=["policy exists in registry"],
            validator=_validate_policy_edit,
            rollback_strategy="revert policy to previous version in registry",
            estimated_eval_cost=0.02,
            supports_autodeploy=False,
            description="Edit a policy pack's rules or enforcement settings.",
            apply=_apply_policy_edit,
        )
    )

    registry.register(
        MutationOperator(
            name="tool_contract_edit",
            surface=MutationSurface.tool_contract,
            risk_class=RiskClass.medium,
            preconditions=["tool contract exists in registry"],
            validator=_validate_tool_contract_edit,
            rollback_strategy="revert tool contract to previous version in registry",
            estimated_eval_cost=0.03,
            supports_autodeploy=False,
            description="Edit a tool contract's schema or replay settings.",
            apply=_apply_tool_contract_edit,
        )
    )

    registry.register(
        MutationOperator(
            name="handoff_schema_edit",
            surface=MutationSurface.handoff_schema,
            risk_class=RiskClass.medium,
            preconditions=["handoff schema exists in registry"],
            validator=_validate_handoff_schema_edit,
            rollback_strategy="revert handoff schema to previous version in registry",
            estimated_eval_cost=0.02,
            supports_autodeploy=False,
            description="Edit a handoff schema's fields or validation rules.",
            apply=_apply_handoff_schema_edit,
        )
    )

    return registry
