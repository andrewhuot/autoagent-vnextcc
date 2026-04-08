"""High-signal tests for ADK and CX portability reporting."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from adk.exporter import AdkExporter
from adk.importer import AdkImporter
from cx_studio.exporter import CxExporter
from cx_studio.importer import CxImporter
from cx_studio.types import (
    CxAgent,
    CxAgentRef,
    CxAgentSnapshot,
    CxEnvironment,
    CxGenerator,
    CxFlow,
    CxIntent,
    CxPage,
    CxPlaybook,
    CxTestCase,
    CxTool,
    CxWebhook,
)


def _surface(report, surface_id: str):  # noqa: ANN001
    """Return a single portability surface by identifier."""

    for surface in report.surfaces:
        if surface.surface_id == surface_id:
            return surface
    raise AssertionError(f"Surface not found: {surface_id}")


def _write_callback_rich_adk_agent(tmp_path: Path) -> Path:
    """Create a realistic ADK agent fixture with callbacks and delegation."""

    agent_dir = tmp_path / "callback_rich_agent"
    billing_dir = agent_dir / "sub_agents" / "billing"
    billing_dir.mkdir(parents=True)

    (agent_dir / "__init__.py").write_text("", encoding="utf-8")
    (billing_dir / "__init__.py").write_text("", encoding="utf-8")

    (agent_dir / "agent.py").write_text(
        '''
from google.adk.agents import SequentialAgent
from .tools import lookup_account
from .sub_agents.billing.agent import billing_agent


def guard_input(context):
    """Guard model input."""
    return context


def record_output(context):
    """Record model output."""
    return context


def enter_agent(context):
    """Before agent callback."""
    return context


def exit_agent(context):
    """After agent callback."""
    return context


def before_tool(context):
    """Before tool callback."""
    return context


def after_tool(context):
    """After tool callback."""
    return context


root_agent = SequentialAgent(
    name="ops_router",
    model="gemini-2.0-flash",
    instruction="Route account issues to the right specialist.",
    tools=[lookup_account],
    sub_agents=[billing_agent],
    generate_config={"temperature": 0.2, "max_output_tokens": 256},
    before_model_callback=guard_input,
    after_model_callback=record_output,
    before_agent_callback=enter_agent,
    after_agent_callback=exit_agent,
    before_tool_callback=before_tool,
    after_tool_callback=after_tool,
)
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    (agent_dir / "tools.py").write_text(
        '''
from google.adk.tools import tool


@tool
def lookup_account(account_id: str) -> dict:
    """Look up an account."""
    return {"account_id": account_id}
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    (billing_dir / "agent.py").write_text(
        '''
from google.adk.agents import Agent
from .tools import issue_refund


billing_agent = Agent(
    name="billing_specialist",
    model="gemini-2.0-flash",
    instruction="Handle billing issues carefully.",
    tools=[issue_refund],
)
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    (billing_dir / "tools.py").write_text(
        '''
from google.adk.tools import tool


@tool
def issue_refund(order_id: str) -> dict:
    """Issue a refund."""
    return {"order_id": order_id, "status": "queued"}
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    (agent_dir / "config.json").write_text(
        json.dumps({"temperature": 0.2, "max_output_tokens": 256}, indent=2),
        encoding="utf-8",
    )

    return agent_dir


def _make_cx_snapshot() -> CxAgentSnapshot:
    """Build a realistic CX snapshot with both writable and read-only surfaces."""

    agent_name = "projects/demo-project/locations/us-central1/agents/support-bot"
    start_flow_name = f"{agent_name}/flows/default-start"
    order_page = f"{start_flow_name}/pages/order-status"
    intent_name = f"{agent_name}/intents/order-status"
    webhook_name = f"{agent_name}/webhooks/order-service"
    tool_name = f"{agent_name}/tools/faq-lookup"
    playbook_name = f"{agent_name}/playbooks/main"

    return CxAgentSnapshot(
        agent=CxAgent(
            name=agent_name,
            display_name="Support Bot",
            description="Primary customer support agent.",
            start_flow=start_flow_name,
            generative_settings={"llmModelSettings": {"model": "gemini-2.0-flash"}},
            speech_to_text_settings={"enableSpeechAdaptation": True},
            text_to_speech_settings={"outputAudioEncoding": "OUTPUT_AUDIO_ENCODING_LINEAR_16"},
        ),
        playbooks=[
            CxPlaybook(
                name=playbook_name,
                display_name="Main",
                instruction="Resolve support issues quickly and safely.",
                input_parameter_definitions=[{"name": "order_id", "type": "string"}],
                output_parameter_definitions=[{"name": "resolution_status", "type": "string"}],
                code_block={"language": "python", "code": "return {'resolution_status': 'queued'}"},
                handlers=[{"event": "playbook-complete", "generator": f"{agent_name}/generators/resolve-summary"}],
            )
        ],
        flows=[
            CxFlow(
                name=start_flow_name,
                display_name="Default Start Flow",
                description="Handles incoming support requests.",
                transition_route_groups=[f"{agent_name}/transitionRouteGroups/shared-escalation"],
                transition_routes=[
                    {
                        "intent": intent_name,
                        "targetPage": order_page,
                        "condition": "$session.params.order_id != null",
                    }
                ],
                pages=[
                    CxPage(
                        name=order_page,
                        display_name="Order Status",
                        form={"parameters": [{"displayName": "order_id", "required": True}]},
                        transition_route_groups=[f"{agent_name}/transitionRouteGroups/shared-escalation"],
                        transition_routes=[],
                        event_handlers=[{"event": "sys.no-match-default", "targetFlow": start_flow_name}],
                    )
                ],
                event_handlers=[{"event": "sys.no-input-default", "targetPage": order_page}],
            )
        ],
        intents=[
            CxIntent(
                name=intent_name,
                display_name="Order Status",
                training_phrases=[{"parts": [{"text": "where is my order"}]}],
                parameters=[{"id": "order_id", "entityType": "@sys.any"}],
            )
        ],
        webhooks=[
            CxWebhook(
                name=webhook_name,
                display_name="Order Service",
                generic_web_service={"uri": "https://orders.example.com/webhook"},
                timeout_seconds=8,
            )
        ],
        tools=[
            CxTool(
                name=tool_name,
                display_name="FAQ Lookup",
                tool_type="OPEN_API",
                spec={"description": "Search the FAQ index", "timeout_ms": 3000},
            )
        ],
        generators=[
            CxGenerator(
                name=f"{agent_name}/generators/resolve-summary",
                display_name="Resolve Summary",
                prompt_text="Summarize the resolution outcome for the customer.",
                placeholders=[{"name": "resolution_status"}],
            )
        ],
        test_cases=[
            CxTestCase(
                name=f"{agent_name}/testCases/order-status-smoke",
                display_name="Order status smoke",
                tags=["smoke"],
                conversation_turns=[
                    {
                        "userInput": {"input": {"text": {"text": "Where is my order 1234?"}}}
                    }
                ],
                expected_output={"targetPage": order_page},
            )
        ],
        environments=[
            CxEnvironment(
                name=f"{agent_name}/environments/production",
                display_name="Production",
                version_configs=[{"flow": start_flow_name, "version": f"{start_flow_name}/versions/5"}],
            )
        ],
        fetched_at="2026-04-08T12:00:00Z",
    )


def test_adk_import_builds_portability_report_for_callback_rich_agent(tmp_path: Path) -> None:
    """ADK imports should expose coverage, callbacks, topology, and readiness."""

    agent_dir = _write_callback_rich_adk_agent(tmp_path)
    result = AdkImporter().import_agent(str(agent_dir), output_dir=str(tmp_path / "out"))

    report = result.portability_report

    assert report.platform == "adk"
    assert report.summary.imported_surfaces >= 6
    assert report.optimization_eligibility.score > 0
    assert report.topology.summary.agent_count == 2
    assert report.topology.summary.callback_count == 6
    assert "sequential_agent" in report.topology.summary.orchestration_modes

    callbacks_surface = _surface(report, "callbacks")
    assert callbacks_surface.coverage_status == "imported"
    assert callbacks_surface.portability_status == "read_only"
    assert callbacks_surface.export_status == "blocked"

    callback_bindings = {callback.binding for callback in report.callbacks}
    assert callback_bindings == {
        "before_model_callback",
        "after_model_callback",
        "before_agent_callback",
        "after_agent_callback",
        "before_tool_callback",
        "after_tool_callback",
    }

    assert "routing" in report.export_matrix.blocked_surfaces
    assert "tool_code" in report.export_matrix.blocked_surfaces
    assert "callbacks" in report.export_matrix.blocked_surfaces


def test_adk_export_reports_round_trip_readiness_for_imported_agent(tmp_path: Path) -> None:
    """ADK export should expose a machine-readable round-trip readiness matrix."""

    agent_dir = _write_callback_rich_adk_agent(tmp_path)
    import_result = AdkImporter().import_agent(str(agent_dir), output_dir=str(tmp_path / "out"))

    config = yaml.safe_load(Path(import_result.config_path).read_text(encoding="utf-8"))
    config["prompts"]["root"] = "Updated root instruction."
    config["routing"]["rules"].append(
        {
            "specialist": "fraud_specialist",
            "keywords": ["fraud", "chargeback"],
            "patterns": [],
        }
    )

    export_result = AdkExporter().export_agent(
        config=config,
        snapshot_path=import_result.snapshot_path,
        output_dir=str(tmp_path / "export"),
        dry_run=True,
    )

    matrix = export_result.export_matrix

    assert matrix.status == "lossy"
    assert "instructions" in matrix.ready_surfaces
    assert "routing" in matrix.blocked_surfaces
    assert "callbacks" in matrix.blocked_surfaces
    assert any(row.surface_id == "tool_code" and row.status == "blocked" for row in matrix.surfaces)


def test_cx_import_builds_portability_report_for_realistic_snapshot(tmp_path: Path) -> None:
    """CX imports should expose imported, optimizable, and blocked surfaces clearly."""

    snapshot = _make_cx_snapshot()
    client = MagicMock()
    client.fetch_snapshot.return_value = snapshot

    result = CxImporter(client).import_agent(
        CxAgentRef(project="demo-project", location="us-central1", agent_id="support-bot"),
        output_dir=str(tmp_path),
    )

    report = result.portability_report

    assert report.platform == "cx_studio"
    assert report.summary.imported_surfaces >= 10
    assert report.optimization_eligibility.score > 0
    assert report.topology.summary.flow_count == 1
    assert report.topology.summary.page_count == 1
    assert report.topology.summary.webhook_count == 1
    assert report.topology.summary.tool_count == 2
    assert report.summary.supported_parity_surfaces >= 3
    assert report.summary.partial_parity_surfaces >= 2
    assert report.summary.read_only_parity_surfaces >= 6
    assert report.summary.unsupported_parity_surfaces >= 2

    instructions = _surface(report, "instructions")
    assert instructions.coverage_status == "imported"
    assert instructions.parity_status == "supported"
    assert instructions.portability_status == "optimizable"
    assert instructions.export_status == "ready"
    assert any("projects.locations.agents.playbooks" in ref for ref in instructions.documentation_refs)
    assert any("cx_studio/surface_inventory.py" in ref for ref in instructions.code_refs)

    callbacks = _surface(report, "callbacks")
    assert callbacks.coverage_status == "missing"
    assert callbacks.parity_status == "unsupported"
    assert callbacks.portability_status == "unsupported"
    assert callbacks.export_status == "blocked"

    routing = _surface(report, "routing")
    assert routing.parity_status == "partial"
    assert routing.export_status == "blocked"

    tools = _surface(report, "app_tools")
    assert tools.coverage_status == "imported"
    assert tools.parity_status == "read_only"
    assert tools.export_status == "blocked"

    speech = _surface(report, "agent_speech_settings")
    assert speech.coverage_status == "imported"
    assert speech.parity_status == "read_only"

    playbook_parameters = _surface(report, "playbook_parameters")
    assert playbook_parameters.coverage_status == "imported"
    assert playbook_parameters.parity_status == "read_only"

    playbook_handlers = _surface(report, "playbook_handlers")
    assert playbook_handlers.coverage_status == "imported"
    assert playbook_handlers.parity_status == "read_only"

    page_forms = _surface(report, "page_forms")
    assert page_forms.coverage_status == "imported"
    assert page_forms.parity_status == "read_only"

    intent_parameters = _surface(report, "intent_parameters")
    assert intent_parameters.coverage_status == "imported"
    assert intent_parameters.parity_status == "read_only"

    route_groups = _surface(report, "transition_route_groups")
    assert route_groups.coverage_status == "referenced"
    assert route_groups.parity_status == "partial"

    generators = _surface(report, "generators")
    assert generators.coverage_status == "imported"
    assert generators.parity_status == "read_only"

    environments = _surface(report, "environments")
    assert environments.coverage_status == "imported"
    assert environments.parity_status == "read_only"

    versions = _surface(report, "versions")
    assert versions.coverage_status == "referenced"
    assert versions.parity_status == "partial"

    playbook_examples = _surface(report, "playbook_examples")
    assert playbook_examples.coverage_status == "missing"
    assert playbook_examples.parity_status == "unsupported"

    assert "app_tools" in report.export_matrix.blocked_surfaces


def test_cx_export_reports_round_trip_readiness_for_workspace_config(tmp_path: Path) -> None:
    """CX export should expose what is actually pushable back to production today."""

    snapshot = _make_cx_snapshot()
    client = MagicMock()
    client.fetch_snapshot.return_value = snapshot
    importer = CxImporter(client)
    ref = CxAgentRef(project="demo-project", location="us-central1", agent_id="support-bot")
    import_result = importer.import_agent(ref, output_dir=str(tmp_path))

    config = json.loads(
        Path(import_result.workspace_path, ".agentlab", "cx", "workspace.json").read_text(encoding="utf-8")
    )
    config["prompts"]["root"] = "Updated CX instruction."
    config["routing"]["rules"].append(
        {
            "specialist": "fraud_review",
            "keywords": ["chargeback"],
            "patterns": [],
        }
    )

    export_result = CxExporter(client).export_agent(
        config=config,
        ref=ref,
        snapshot_path=import_result.snapshot_path,
        dry_run=True,
    )

    matrix = export_result.export_matrix

    assert matrix.status == "lossy"
    assert "instructions" in matrix.ready_surfaces
    assert "webhooks" in matrix.ready_surfaces
    assert "routing" in matrix.blocked_surfaces
    assert "app_tools" in matrix.blocked_surfaces
