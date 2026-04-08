"""ADK-specific portability and readiness reporting."""

from __future__ import annotations

from adk.types import AdkAgentTree, AdkAgentType
from portability.reporting import build_export_matrix, build_portability_report
from portability.types import (
    ExportCapabilityMatrix,
    ExportReadinessStatus,
    ImportCoverageStatus,
    ImportGraphEdge,
    ImportGraphNode,
    ImportTopology,
    ImportTopologySummary,
    ImportedCallback,
    PortabilityReport,
    PortabilityStatus,
    PortabilitySurface,
    ProjectionQualityStatus,
)


def build_adk_portability_report(agent_tree: AdkAgentTree) -> PortabilityReport:
    """Build the shared portability report for a parsed ADK tree."""

    callbacks = _collect_callbacks(agent_tree)
    topology = _build_topology(agent_tree, callbacks)
    surfaces = _build_surfaces(agent_tree, callbacks)
    notes = [
        "ADK import surfaces code, callbacks, and topology explicitly, but only a subset can round-trip back today.",
        "Routing and workflow topology are visible for analysis even when write-back support is not yet implemented.",
    ]
    return build_portability_report(
        platform="adk",
        source=str(agent_tree.source_path),
        surfaces=surfaces,
        topology=topology,
        callbacks=callbacks,
        notes=notes,
    )


def build_adk_export_matrix(agent_tree: AdkAgentTree) -> ExportCapabilityMatrix:
    """Return the ADK export capability matrix for a parsed tree."""

    return build_export_matrix(_build_surfaces(agent_tree, _collect_callbacks(agent_tree)))


def _build_surfaces(agent_tree: AdkAgentTree, callbacks: list[ImportedCallback]) -> list[PortabilitySurface]:
    """Build surfaced ADK rows aligned to what the importer/exporter can do today."""

    tool_count = _count_tools(agent_tree)
    agent_count = _count_agents(agent_tree)
    callback_count = len(callbacks)
    has_instruction = bool(agent_tree.agent.instruction)
    has_model = bool(agent_tree.agent.model or agent_tree.config.get("model"))
    has_generation = bool(agent_tree.agent.generate_config or agent_tree.config)
    has_routing = bool(agent_tree.sub_agents)

    surfaces = [
        PortabilitySurface(
            surface_id="instructions",
            label="Instructions",
            coverage_status=ImportCoverageStatus.IMPORTED if has_instruction else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.OPTIMIZABLE,
            export_status=ExportReadinessStatus.READY,
            optimization_surface_id="instructions",
            projection_quality=ProjectionQualityStatus.FAITHFUL,
            rationale=["Root and specialist instructions are parsed and can be written back to ADK source."],
        ),
        PortabilitySurface(
            surface_id="model",
            label="Model Selection",
            coverage_status=ImportCoverageStatus.IMPORTED if has_model else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.OPTIMIZABLE,
            export_status=ExportReadinessStatus.READY,
            optimization_surface_id="model_selection",
            projection_quality=ProjectionQualityStatus.FAITHFUL,
            rationale=["Model overrides are preserved through import and exporter write-back."],
        ),
        PortabilitySurface(
            surface_id="generation_settings",
            label="Generation Settings",
            coverage_status=ImportCoverageStatus.IMPORTED if has_generation else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.OPTIMIZABLE,
            export_status=ExportReadinessStatus.READY,
            optimization_surface_id="generation_settings",
            projection_quality=ProjectionQualityStatus.FAITHFUL,
            rationale=["Temperature and token limits are imported and exporter-managed via config.json."],
        ),
        PortabilitySurface(
            surface_id="tool_metadata",
            label="Tool Metadata",
            coverage_status=ImportCoverageStatus.IMPORTED if tool_count else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.OPTIMIZABLE if tool_count else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.READY if tool_count else ExportReadinessStatus.BLOCKED,
            optimization_surface_id="tool_runtime_config",
            projection_quality=ProjectionQualityStatus.APPROXIMATED if tool_count else None,
            rationale=["Tool descriptions and signatures are visible, and ADK docstrings can be patched on export."],
            metadata={"tool_count": tool_count},
        ),
        PortabilitySurface(
            surface_id="tool_code",
            label="Tool Code",
            coverage_status=ImportCoverageStatus.IMPORTED if tool_count else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.READ_ONLY if tool_count else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED,
            projection_quality=ProjectionQualityStatus.PRESERVED_ONLY if tool_count else None,
            rationale=["Tool function bodies are surfaced for review, but code edits are not pushed back automatically."],
            metadata={"tool_count": tool_count},
        ),
        PortabilitySurface(
            surface_id="routing",
            label="Routing and Delegation",
            coverage_status=ImportCoverageStatus.IMPORTED if has_routing else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.OPTIMIZABLE if has_routing else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED if has_routing else ExportReadinessStatus.BLOCKED,
            optimization_surface_id="routing",
            projection_quality=ProjectionQualityStatus.APPROXIMATED if has_routing else None,
            rationale=["Sub-agent routing is imported into AgentLab config, but exporter write-back for delegation changes is not implemented."],
            metadata={"agent_count": agent_count},
        ),
        PortabilitySurface(
            surface_id="callbacks",
            label="Callbacks",
            coverage_status=ImportCoverageStatus.IMPORTED if callback_count else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.READ_ONLY if callback_count else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED,
            optimization_surface_id="callbacks",
            projection_quality=ProjectionQualityStatus.PRESERVED_ONLY if callback_count else None,
            rationale=["Callback bindings are first-class in the report, but they are not yet editable through safe round-trip flows."],
            metadata={"callback_count": callback_count},
        ),
        PortabilitySurface(
            surface_id="workflow_topology",
            label="Workflow Topology",
            coverage_status=ImportCoverageStatus.IMPORTED if agent_count else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.READ_ONLY,
            export_status=ExportReadinessStatus.BLOCKED,
            optimization_surface_id="workflow_topology",
            projection_quality=ProjectionQualityStatus.APPROXIMATED if agent_count else None,
            rationale=["Agent hierarchy and orchestration type are surfaced for visibility, but topology edits are not written back today."],
            metadata={"agent_count": agent_count},
        ),
    ]

    return surfaces


def _build_topology(agent_tree: AdkAgentTree, callbacks: list[ImportedCallback]) -> ImportTopology:
    """Build a normalized topology view for a parsed ADK tree."""

    nodes: list[ImportGraphNode] = []
    edges: list[ImportGraphEdge] = []
    orchestration_modes: set[str] = set()

    def visit(tree: AdkAgentTree, depth: int, parent_agent_id: str | None = None) -> None:
        agent_id = f"agent:{tree.source_path.name}:{tree.agent.name or 'root'}"
        orchestration_modes.add(tree.agent.agent_type.value)
        nodes.append(
            ImportGraphNode(
                node_id=agent_id,
                node_type="agent",
                label=tree.agent.name or tree.source_path.name,
                metadata={"agent_type": tree.agent.agent_type.value, "depth": depth},
            )
        )
        if parent_agent_id:
            edges.append(
                ImportGraphEdge(
                    source_id=parent_agent_id,
                    target_id=agent_id,
                    edge_type="delegates_to",
                )
            )

        for tool in tree.tools:
            tool_id = f"tool:{agent_id}:{tool.name}"
            nodes.append(
                ImportGraphNode(
                    node_id=tool_id,
                    node_type="tool",
                    label=tool.name,
                )
            )
            edges.append(
                ImportGraphEdge(
                    source_id=agent_id,
                    target_id=tool_id,
                    edge_type="uses_tool",
                )
            )

        for callback in tree.callbacks:
            callback_id = f"callback:{agent_id}:{callback.callback_type}"
            nodes.append(
                ImportGraphNode(
                    node_id=callback_id,
                    node_type="callback",
                    label=callback.function_name,
                    metadata={"binding": callback.callback_type},
                )
            )
            edges.append(
                ImportGraphEdge(
                    source_id=agent_id,
                    target_id=callback_id,
                    edge_type="invokes_callback",
                )
            )

        for sub_tree in tree.sub_agents:
            visit(sub_tree, depth + 1, agent_id)

    visit(agent_tree, 0)

    summary = ImportTopologySummary(
        node_count=len(nodes),
        edge_count=len(edges),
        max_depth=_max_depth(agent_tree),
        agent_count=sum(1 for node in nodes if node.node_type == "agent"),
        tool_count=sum(1 for node in nodes if node.node_type == "tool"),
        callback_count=len(callbacks),
        orchestration_modes=sorted(orchestration_modes),
    )

    return ImportTopology(nodes=nodes, edges=edges, summary=summary)


def _collect_callbacks(agent_tree: AdkAgentTree) -> list[ImportedCallback]:
    """Collect callback bindings from the tree recursively."""

    callbacks: list[ImportedCallback] = []

    def visit(tree: AdkAgentTree) -> None:
        source_ref = str(tree.source_path / "agent.py")
        for spec in tree.callbacks:
            callbacks.append(
                ImportedCallback(
                    name=spec.function_name,
                    binding=spec.callback_type,
                    stage=spec.callback_type.replace("_callback", ""),
                    source_ref=source_ref,
                    portability_status=PortabilityStatus.READ_ONLY,
                    export_status=ExportReadinessStatus.BLOCKED,
                    rationale=["Imported from ADK source for visibility; callback editing is not yet round-trippable."],
                )
            )
        for child in tree.sub_agents:
            visit(child)

    visit(agent_tree)
    return callbacks


def _count_agents(agent_tree: AdkAgentTree) -> int:
    """Count all agents in the tree."""

    return 1 + sum(_count_agents(child) for child in agent_tree.sub_agents)


def _count_tools(agent_tree: AdkAgentTree) -> int:
    """Count all tools in the tree."""

    return len(agent_tree.tools) + sum(_count_tools(child) for child in agent_tree.sub_agents)


def _max_depth(agent_tree: AdkAgentTree) -> int:
    """Return the maximum delegation depth for the tree."""

    if not agent_tree.sub_agents:
        return 0
    return 1 + max(_max_depth(child) for child in agent_tree.sub_agents)
