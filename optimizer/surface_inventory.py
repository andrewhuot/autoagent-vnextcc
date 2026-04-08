"""Structured inventory of optimization component coverage.

This module answers a practical question for the UI, audits, and coding-agent
integrations: which agent surfaces are merely declared in theory, and which
surfaces are actually reachable through the current optimization loop?
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from agent.config.schema import AgentConfig
from observer.opportunities import _BUCKET_TO_OPERATORS
from optimizer.mutations import create_default_registry
from optimizer.mutations_topology import register_topology_operators
from optimizer.nl_editor import KEYWORD_SURFACE_MAP
from optimizer.search import _OPERATOR_TO_FAMILY


_SUPPORT_LEVELS = ("full", "partial", "nominal", "none")


@dataclass(frozen=True)
class SurfaceInventoryRow:
    """One normalized row in the optimization coverage inventory."""

    surface_id: str
    label: str
    support_level: str
    mutation_surfaces: list[str]
    default_operator_names: list[str]
    experimental_operator_names: list[str]
    optimization_paths: list[str]
    representation_paths: list[str]
    has_default_operator: bool
    has_experimental_operator: bool
    reachable_from_simple_proposer: bool
    reachable_from_adaptive_loop: bool
    reachable_from_opportunity_generation: bool
    reachable_from_nl_editor: bool
    reachable_from_autofix: bool
    represented_in_agent_config: bool
    represented_in_adk_import: bool
    represented_in_adk_export: bool
    represented_in_connect_import: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


_SURFACE_METADATA: list[dict[str, Any]] = [
    {
        "surface_id": "instructions",
        "label": "Instructions",
        "support_level": "full",
        "mutation_surfaces": ["instruction"],
        "simple_proposer": True,
        "nl_editor": True,
        "autofix": True,
        "agent_config": True,
        "adk_import": True,
        "adk_export": True,
        "connect_import": True,
        "notes": "Root and specialist prompts are the most complete end-to-end surface today.",
    },
    {
        "surface_id": "few_shot_examples",
        "label": "Few-shot examples",
        "support_level": "partial",
        "mutation_surfaces": ["few_shot"],
        "simple_proposer": False,
        "nl_editor": True,
        "autofix": True,
        "agent_config": False,
        "adk_import": False,
        "adk_export": False,
        "connect_import": False,
        "notes": "The optimizer can propose few-shot mutations, but the canonical AgentConfig schema does not represent them.",
    },
    {
        "surface_id": "tool_runtime_config",
        "label": "Tool runtime config",
        "support_level": "partial",
        "mutation_surfaces": ["tool_description"],
        "simple_proposer": True,
        "nl_editor": True,
        "autofix": False,
        "agent_config": True,
        "adk_import": True,
        "adk_export": False,
        "connect_import": True,
        "notes": "Enabled flags survive ADK/connect imports, but explicit timeout tuning and write-back support are still incomplete.",
    },
    {
        "surface_id": "tool_descriptions",
        "label": "Tool descriptions",
        "support_level": "partial",
        "mutation_surfaces": ["tool_description"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": False,
        "adk_import": True,
        "adk_export": True,
        "connect_import": True,
        "notes": "Tool descriptions are imported from ADK and connected runtimes, but they are not preserved by the main AgentConfig schema.",
    },
    {
        "surface_id": "model_selection",
        "label": "Model selection",
        "support_level": "partial",
        "mutation_surfaces": ["model"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": True,
        "agent_config": True,
        "adk_import": True,
        "adk_export": True,
        "connect_import": True,
        "notes": "Model swaps are reachable in adaptive search and AutoFix, but they remain relatively high-risk changes.",
    },
    {
        "surface_id": "generation_settings",
        "label": "Generation settings",
        "support_level": "partial",
        "mutation_surfaces": ["generation_settings"],
        "simple_proposer": False,
        "nl_editor": True,
        "autofix": True,
        "agent_config": False,
        "adk_import": True,
        "adk_export": True,
        "connect_import": False,
        "notes": "Generation settings exist across optimizer and ADK codepaths, but the naming contract is still split across generation, generation_settings, and generate_config.",
    },
    {
        "surface_id": "callbacks",
        "label": "Callbacks",
        "support_level": "nominal",
        "mutation_surfaces": ["callback"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": False,
        "adk_import": False,
        "adk_export": False,
        "connect_import": False,
        "notes": "Callbacks are a real runtime concept, but they are invisible to the canonical config and write-back flows.",
    },
    {
        "surface_id": "context_caching",
        "label": "Context caching",
        "support_level": "partial",
        "mutation_surfaces": ["context_caching"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": True,
        "adk_import": False,
        "adk_export": False,
        "connect_import": False,
        "notes": "This surface is represented in AgentConfig and adaptive search, but not in current ADK or external-runtime imports.",
    },
    {
        "surface_id": "memory_policy",
        "label": "Memory policy",
        "support_level": "partial",
        "mutation_surfaces": ["memory_policy"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": True,
        "adk_import": False,
        "adk_export": False,
        "connect_import": False,
        "notes": "Memory policy is schema-visible and adaptive-search-visible, but not connected to current ADK or runtime adapters.",
    },
    {
        "surface_id": "routing",
        "label": "Routing",
        "support_level": "full",
        "mutation_surfaces": ["routing"],
        "simple_proposer": True,
        "nl_editor": True,
        "autofix": False,
        "agent_config": True,
        "adk_import": True,
        "adk_export": False,
        "connect_import": True,
        "notes": "Routing is a first-class optimization surface, but export does not currently write routing changes back into ADK sub-agent structure.",
    },
    {
        "surface_id": "workflow_topology",
        "label": "Workflow topology",
        "support_level": "nominal",
        "mutation_surfaces": ["workflow"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": False,
        "adk_import": False,
        "adk_export": False,
        "connect_import": False,
        "notes": "Workflow edits are now reachable through adaptive search, while deeper topology reshaping still lives in experimental operators.",
    },
    {
        "surface_id": "skills",
        "label": "Skills",
        "support_level": "nominal",
        "mutation_surfaces": ["skill"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": False,
        "adk_import": False,
        "adk_export": False,
        "connect_import": False,
        "notes": "Skill mutations exist in the registry, but they are not represented in AgentConfig or opportunity generation.",
    },
    {
        "surface_id": "guardrails_policies",
        "label": "Guardrails and policies",
        "support_level": "nominal",
        "mutation_surfaces": ["policy"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": False,
        "adk_import": False,
        "adk_export": False,
        "connect_import": True,
        "notes": "Guardrails are imported from connected runtimes, but the optimizer only exposes policy mutations as registry-only surfaces today.",
    },
    {
        "surface_id": "tool_contracts",
        "label": "Tool contracts",
        "support_level": "nominal",
        "mutation_surfaces": ["tool_contract"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": False,
        "adk_import": False,
        "adk_export": False,
        "connect_import": False,
        "notes": "Tool contracts are declared mutation surfaces, but no current loop path generates or round-trips them.",
    },
    {
        "surface_id": "handoff_artifacts",
        "label": "Handoff artifacts",
        "support_level": "nominal",
        "mutation_surfaces": ["handoff_schema"],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": False,
        "adk_import": False,
        "adk_export": False,
        "connect_import": True,
        "notes": "Handoff quality is observed and adapters can import handoff edges, but the optimizer does not yet mutate structured handoff artifacts.",
    },
    {
        "surface_id": "thresholds",
        "label": "Thresholds",
        "support_level": "partial",
        "mutation_surfaces": [],
        "simple_proposer": True,
        "nl_editor": True,
        "autofix": False,
        "agent_config": True,
        "adk_import": False,
        "adk_export": False,
        "connect_import": False,
        "notes": "Threshold tuning is reachable through the simple proposer and NL editor, but it is not represented as a formal mutation surface.",
    },
    {
        "surface_id": "compaction",
        "label": "Context compaction",
        "support_level": "none",
        "mutation_surfaces": [],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": True,
        "adk_import": False,
        "adk_export": False,
        "connect_import": False,
        "notes": "Compaction is schema-visible and has a workbench, but there are no mutation operators targeting it yet.",
    },
    {
        "surface_id": "sub_agents",
        "label": "Sub-agents",
        "support_level": "nominal",
        "mutation_surfaces": [],
        "simple_proposer": False,
        "nl_editor": False,
        "autofix": False,
        "agent_config": False,
        "adk_import": True,
        "adk_export": False,
        "connect_import": True,
        "notes": "Sub-agent structure is imported and observed indirectly, but currently collapsed into routing rather than optimized as first-class topology.",
    },
]


_PROPOSER_SURFACES = {"instructions", "tool_runtime_config", "routing", "thresholds"}
_AUTOFIX_SURFACES = {"instructions", "few_shot_examples", "model_selection", "generation_settings"}
_NL_EDITOR_SURFACE_MAP = {
    "prompts.root": "instructions",
    "routing.rules": "routing",
    "thresholds": "thresholds",
    "tools": "tool_runtime_config",
    "examples": "few_shot_examples",
    "generation_settings": "generation_settings",
}


def build_surface_inventory() -> dict[str, Any]:
    """Return a normalized view of optimization surface coverage.

    The returned payload is intended for audits, UI consumption, and external
    coding agents that need a quick answer to "what can the optimizer actually
    see, mutate, and round-trip today?"
    """

    default_ops = _operators_by_surface(include_experimental=False)
    experimental_ops = _operators_by_surface(include_experimental=True)
    adaptive_surfaces = _adaptive_surfaces()
    opportunity_surfaces = _opportunity_surfaces()
    nl_editor_surfaces = _nl_editor_surfaces()

    rows: list[SurfaceInventoryRow] = []
    for item in _SURFACE_METADATA:
        mutation_surfaces = list(item["mutation_surfaces"])
        default_operator_names = _sorted_unique(
            name
            for surface in mutation_surfaces
            for name in default_ops.get(surface, [])
        )
        experimental_operator_names = _sorted_unique(
            name
            for surface in mutation_surfaces
            for name in experimental_ops.get(surface, [])
            if name not in default_operator_names
        )
        reachable_from_simple_proposer = bool(item["simple_proposer"])
        reachable_from_adaptive_loop = any(
            surface in adaptive_surfaces for surface in mutation_surfaces
        )
        reachable_from_opportunity_generation = any(
            surface in opportunity_surfaces for surface in mutation_surfaces
        )
        reachable_from_nl_editor = item["surface_id"] in nl_editor_surfaces
        reachable_from_autofix = item["surface_id"] in _AUTOFIX_SURFACES
        represented_in_agent_config = bool(item["agent_config"])
        represented_in_adk_import = bool(item["adk_import"])
        represented_in_adk_export = bool(item["adk_export"])
        represented_in_connect_import = bool(item["connect_import"])

        rows.append(
            SurfaceInventoryRow(
                surface_id=item["surface_id"],
                label=item["label"],
                support_level=item["support_level"],
                mutation_surfaces=mutation_surfaces,
                default_operator_names=default_operator_names,
                experimental_operator_names=experimental_operator_names,
                optimization_paths=_present_paths(
                    [
                        ("simple_proposer", reachable_from_simple_proposer),
                        ("adaptive_loop", reachable_from_adaptive_loop),
                        ("opportunity_generation", reachable_from_opportunity_generation),
                        ("nl_editor", reachable_from_nl_editor),
                        ("autofix", reachable_from_autofix),
                    ]
                ),
                representation_paths=_present_paths(
                    [
                        ("agent_config", represented_in_agent_config),
                        ("adk_import", represented_in_adk_import),
                        ("adk_export", represented_in_adk_export),
                        ("connect_import", represented_in_connect_import),
                    ]
                ),
                has_default_operator=bool(default_operator_names),
                has_experimental_operator=bool(experimental_operator_names),
                reachable_from_simple_proposer=reachable_from_simple_proposer,
                reachable_from_adaptive_loop=reachable_from_adaptive_loop,
                reachable_from_opportunity_generation=reachable_from_opportunity_generation,
                reachable_from_nl_editor=reachable_from_nl_editor,
                reachable_from_autofix=reachable_from_autofix,
                represented_in_agent_config=represented_in_agent_config,
                represented_in_adk_import=represented_in_adk_import,
                represented_in_adk_export=represented_in_adk_export,
                represented_in_connect_import=represented_in_connect_import,
                notes=item["notes"],
            )
        )

    return {
        "summary": _build_summary(rows),
        "surfaces": [row.to_dict() for row in rows],
    }


def _operators_by_surface(*, include_experimental: bool) -> dict[str, list[str]]:
    """Collect operator names grouped by mutation surface."""

    registry = create_default_registry()
    if include_experimental:
        register_topology_operators(registry)

    grouped: dict[str, list[str]] = defaultdict(list)
    for operator in registry.list_all():
        grouped[operator.surface.value].append(operator.name)
    return {surface: _sorted_unique(names) for surface, names in grouped.items()}


def _adaptive_surfaces() -> set[str]:
    """Return mutation surfaces reachable through adaptive search."""

    registry = create_default_registry()
    surfaces: set[str] = set()
    for operator_name in _OPERATOR_TO_FAMILY:
        operator = registry.get(operator_name)
        if operator is not None:
            surfaces.add(operator.surface.value)
    return surfaces


def _opportunity_surfaces() -> set[str]:
    """Return mutation surfaces reachable through opportunity generation."""

    registry = create_default_registry()
    surfaces: set[str] = set()
    for operator_names in _BUCKET_TO_OPERATORS.values():
        for operator_name in operator_names:
            operator = registry.get(operator_name)
            if operator is not None:
                surfaces.add(operator.surface.value)
    return surfaces


def _nl_editor_surfaces() -> set[str]:
    """Return normalized component surfaces reachable through the NL editor."""

    surfaces: set[str] = set()
    for _keywords, target_surfaces, _change_type in KEYWORD_SURFACE_MAP:
        for target_surface in target_surfaces:
            normalized = _NL_EDITOR_SURFACE_MAP.get(target_surface)
            if normalized is not None:
                surfaces.add(normalized)
    return surfaces


def _build_summary(rows: list[SurfaceInventoryRow]) -> dict[str, Any]:
    """Aggregate high-signal counts for dashboards and audits."""

    agent_config_fields = set(AgentConfig.model_fields)
    return {
        "total_surfaces": len(rows),
        "support_level_order": list(_SUPPORT_LEVELS),
        "support_level_counts": {
            level: sum(1 for row in rows if row.support_level == level)
            for level in _SUPPORT_LEVELS
        },
        "agent_config_fields": sorted(agent_config_fields),
        "surfaces_with_default_operator": sum(1 for row in rows if row.has_default_operator),
        "surfaces_with_experimental_only_operator": sum(
            1 for row in rows if not row.has_default_operator and row.has_experimental_operator
        ),
        "surfaces_missing_agent_config": sum(
            1 for row in rows if not row.represented_in_agent_config
        ),
        "surfaces_missing_adaptive_loop": sum(
            1 for row in rows if row.has_default_operator and not row.reachable_from_adaptive_loop
        ),
        "surfaces_missing_opportunity_generation": sum(
            1
            for row in rows
            if row.has_default_operator and not row.reachable_from_opportunity_generation
        ),
        "surfaces_missing_writeback": sum(
            1
            for row in rows
            if row.represented_in_adk_import and not row.represented_in_adk_export
        ),
    }


def _present_paths(flags: list[tuple[str, bool]]) -> list[str]:
    """Return the enabled path names in stable order."""

    return [name for name, enabled in flags if enabled]


def _sorted_unique(items: Any) -> list[str]:
    """Return sorted unique strings from an iterable."""

    return sorted({str(item) for item in items if str(item)})
