"""CX Studio-specific portability and readiness reporting."""

from __future__ import annotations

from cx_studio.types import CxAgentSnapshot
from portability.reporting import build_export_matrix, build_portability_report
from portability.types import (
    ExportCapabilityMatrix,
    ExportReadinessStatus,
    ImportCoverageStatus,
    ImportGraphEdge,
    ImportGraphNode,
    ImportTopology,
    ImportTopologySummary,
    PortabilityReport,
    PortabilityStatus,
    PortabilitySurface,
)


def build_cx_portability_report(snapshot: CxAgentSnapshot) -> PortabilityReport:
    """Build the shared portability report for a CX snapshot."""

    topology = _build_topology(snapshot)
    surfaces = _build_surfaces(snapshot)
    notes = [
        "CX imports expose more runtime resources than are currently editable through AgentLab config.",
        "Webhook settings round-trip today, while routes, entity types, app-level tools, and generator-like callbacks remain limited.",
    ]
    return build_portability_report(
        platform="cx_studio",
        source=snapshot.agent.name,
        surfaces=surfaces,
        topology=topology,
        callbacks=[],
        notes=notes,
    )


def build_cx_export_matrix(snapshot: CxAgentSnapshot) -> ExportCapabilityMatrix:
    """Return the CX export capability matrix for the imported snapshot."""

    return build_export_matrix(_build_surfaces(snapshot))


def _build_surfaces(snapshot: CxAgentSnapshot) -> list[PortabilitySurface]:
    """Build surfaced CX rows aligned to current importer/exporter behavior."""

    has_instructions = bool(snapshot.playbooks or snapshot.agent.description)
    has_model = bool(snapshot.agent.generative_settings)
    has_webhooks = bool(snapshot.webhooks)
    has_tools = bool(snapshot.tools)
    has_routing = bool(snapshot.flows or snapshot.intents)
    has_flows = bool(snapshot.flows)
    has_intents = bool(snapshot.intents)
    has_entities = bool(snapshot.entity_types)
    has_test_cases = bool(snapshot.test_cases)

    return [
        PortabilitySurface(
            surface_id="instructions",
            label="Instructions",
            coverage_status=ImportCoverageStatus.IMPORTED if has_instructions else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.OPTIMIZABLE,
            export_status=ExportReadinessStatus.READY,
            optimization_surface_id="instructions",
            rationale=["Playbook or agent instructions map cleanly into AgentLab prompts and back to CX playbooks."],
        ),
        PortabilitySurface(
            surface_id="model",
            label="Model Selection",
            coverage_status=ImportCoverageStatus.IMPORTED if has_model else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.OPTIMIZABLE,
            export_status=ExportReadinessStatus.READY,
            optimization_surface_id="model_selection",
            rationale=["Generative model settings are represented in the workspace config and exporter payloads."],
        ),
        PortabilitySurface(
            surface_id="webhooks",
            label="Webhooks",
            coverage_status=ImportCoverageStatus.IMPORTED if has_webhooks else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.OPTIMIZABLE if has_webhooks else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.READY if has_webhooks else ExportReadinessStatus.BLOCKED,
            optimization_surface_id="tool_runtime_config",
            rationale=["Webhook URI, headers, timeout, and enabled state are mapped into tools config and exporter write-back."],
            metadata={"webhook_count": len(snapshot.webhooks)},
        ),
        PortabilitySurface(
            surface_id="app_tools",
            label="App Tools",
            coverage_status=ImportCoverageStatus.IMPORTED if has_tools else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.READ_ONLY if has_tools else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED,
            optimization_surface_id="tool_runtime_config",
            rationale=["CX app-level tools are visible in the import, but current mapper/exporter flows do not push edits back to them."],
            metadata={"tool_count": len(snapshot.tools)},
        ),
        PortabilitySurface(
            surface_id="routing",
            label="Routing",
            coverage_status=ImportCoverageStatus.IMPORTED if has_routing else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.OPTIMIZABLE if has_routing else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED if has_routing else ExportReadinessStatus.BLOCKED,
            optimization_surface_id="routing",
            rationale=["Flow routes and intent cues are translated into AgentLab routing rules, but mapper write-back for routing edits is not implemented yet."],
        ),
        PortabilitySurface(
            surface_id="flows",
            label="Flows and Pages",
            coverage_status=ImportCoverageStatus.IMPORTED if has_flows else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.READ_ONLY if has_flows else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED,
            optimization_surface_id="workflow_topology",
            rationale=["Detailed flow and page topology is surfaced for review, but not represented as a directly editable config surface."],
        ),
        PortabilitySurface(
            surface_id="intents",
            label="Intents",
            coverage_status=ImportCoverageStatus.IMPORTED if has_intents else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.READ_ONLY if has_intents else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED,
            rationale=["Intent phrases are imported into the snapshot and routing hints, but not fully editable through the AgentLab config contract."],
        ),
        PortabilitySurface(
            surface_id="entity_types",
            label="Entity Types",
            coverage_status=ImportCoverageStatus.IMPORTED if has_entities else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.READ_ONLY if has_entities else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED,
            rationale=["Entity types are imported for visibility but are not yet surfaced as an editable optimization surface."],
        ),
        PortabilitySurface(
            surface_id="test_cases",
            label="Imported Test Cases",
            coverage_status=ImportCoverageStatus.IMPORTED if has_test_cases else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.READ_ONLY if has_test_cases else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED,
            optimization_surface_id="few_shot_examples",
            rationale=["CX test cases are materialized into starter evals, but they are not pushed back into Dialogflow CX."],
        ),
        PortabilitySurface(
            surface_id="callbacks",
            label="Callbacks",
            coverage_status=ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED,
            optimization_surface_id="callbacks",
            rationale=["Generator and callback-like processors are not currently fetched into the CX import snapshot."],
        ),
        PortabilitySurface(
            surface_id="workflow_topology",
            label="Workflow Topology",
            coverage_status=ImportCoverageStatus.IMPORTED if has_flows else ImportCoverageStatus.MISSING,
            portability_status=PortabilityStatus.READ_ONLY if has_flows else PortabilityStatus.UNSUPPORTED,
            export_status=ExportReadinessStatus.BLOCKED,
            optimization_surface_id="workflow_topology",
            rationale=["The CX flow/page graph is surfaced for visibility, but structural topology edits are not round-tripped today."],
        ),
    ]


def _build_topology(snapshot: CxAgentSnapshot) -> ImportTopology:
    """Build a normalized topology view for a CX snapshot."""

    nodes: list[ImportGraphNode] = []
    edges: list[ImportGraphEdge] = []

    agent_id = f"agent:{snapshot.agent.name}"
    nodes.append(ImportGraphNode(node_id=agent_id, node_type="agent", label=snapshot.agent.display_name or snapshot.agent.name.split("/")[-1]))

    for playbook in snapshot.playbooks:
        playbook_id = f"playbook:{playbook.name}"
        nodes.append(ImportGraphNode(node_id=playbook_id, node_type="playbook", label=playbook.display_name or playbook.name.split("/")[-1]))
        edges.append(ImportGraphEdge(source_id=agent_id, target_id=playbook_id, edge_type="contains"))

    for flow in snapshot.flows:
        flow_id = f"flow:{flow.name}"
        nodes.append(ImportGraphNode(node_id=flow_id, node_type="flow", label=flow.display_name or flow.name.split("/")[-1]))
        edges.append(ImportGraphEdge(source_id=agent_id, target_id=flow_id, edge_type="contains"))
        for page in flow.pages:
            page_id = f"page:{page.name}"
            nodes.append(ImportGraphNode(node_id=page_id, node_type="page", label=page.display_name or page.name.split("/")[-1]))
            edges.append(ImportGraphEdge(source_id=flow_id, target_id=page_id, edge_type="contains"))

    for intent in snapshot.intents:
        intent_id = f"intent:{intent.name}"
        nodes.append(ImportGraphNode(node_id=intent_id, node_type="intent", label=intent.display_name or intent.name.split("/")[-1]))
        edges.append(ImportGraphEdge(source_id=agent_id, target_id=intent_id, edge_type="contains"))

    for webhook in snapshot.webhooks:
        webhook_id = f"webhook:{webhook.name}"
        nodes.append(ImportGraphNode(node_id=webhook_id, node_type="webhook", label=webhook.display_name or webhook.name.split("/")[-1]))
        edges.append(ImportGraphEdge(source_id=agent_id, target_id=webhook_id, edge_type="uses_tool"))

    for tool in snapshot.tools:
        tool_id = f"tool:{tool.name}"
        nodes.append(ImportGraphNode(node_id=tool_id, node_type="tool", label=tool.display_name or tool.name.split("/")[-1]))
        edges.append(ImportGraphEdge(source_id=agent_id, target_id=tool_id, edge_type="uses_tool"))

    for test_case in snapshot.test_cases:
        case_id = f"test_case:{test_case.name}"
        nodes.append(ImportGraphNode(node_id=case_id, node_type="test_case", label=test_case.display_name or test_case.name.split("/")[-1]))
        edges.append(ImportGraphEdge(source_id=agent_id, target_id=case_id, edge_type="has_test_case"))

    summary = ImportTopologySummary(
        node_count=len(nodes),
        edge_count=len(edges),
        max_depth=2 if any(flow.pages for flow in snapshot.flows) else 1,
        agent_count=1,
        tool_count=len(snapshot.webhooks) + len(snapshot.tools),
        flow_count=len(snapshot.flows),
        page_count=sum(len(flow.pages) for flow in snapshot.flows),
        intent_count=len(snapshot.intents),
        webhook_count=len(snapshot.webhooks),
        test_case_count=len(snapshot.test_cases),
        orchestration_modes=["cx_flow_graph"],
    )

    return ImportTopology(nodes=nodes, edges=edges, summary=summary)
