"""CX Studio-specific portability and readiness reporting."""

from __future__ import annotations

from cx_studio.types import CxAgentSnapshot
from portability.reporting import build_export_matrix, build_portability_report
from portability.types import (
    ExportCapabilityMatrix,
    ImportGraphEdge,
    ImportGraphNode,
    ImportTopology,
    ImportTopologySummary,
    PortabilityReport,
    PortabilitySurface,
)

from .surface_inventory import build_cx_portability_surfaces


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

    return build_cx_portability_surfaces(snapshot)


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
