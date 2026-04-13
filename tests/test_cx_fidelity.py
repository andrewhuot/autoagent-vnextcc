"""Tests for CX import/export fidelity improvements.

Covers the specific gaps addressed in feat/cx-agent-studio-compat-claude-sonnet:
- update_mask camelCase correctness (API requirement)
- page.entry_fulfillment tracked in diff and conflict detection
- playbook.goal tracked in diff and conflict detection
- playbook.referenced_tools/playbooks/flows exported and round-tripped
- intent.description and labels exported and round-tripped
- entity_type.auto_expansion_mode tracked in diff
- new page creation via export (create_page)
- _set_field handles new fields for sync merge
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from adapters.cx_agent_mapper import CxAgentMapper
from cx_studio.exporter import CxExporter
from cx_studio.importer import CxImporter
from cx_studio.types import (
    CxAgent,
    CxAgentRef,
    CxAgentSnapshot,
    CxEntityType,
    CxFlow,
    CxGenerator,
    CxIntent,
    CxPage,
    CxPlaybook,
    CxTestCase,
    CxTransitionRouteGroup,
    CxWebhook,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _base_agent_name() -> str:
    return "projects/demo-project/locations/us-central1/agents/fidelity-bot"


def _make_rich_snapshot() -> CxAgentSnapshot:
    """Snapshot with a broad surface area for fidelity testing."""

    agent_name = _base_agent_name()
    flow_name = f"{agent_name}/flows/00000000-0000-0000-0000-000000000000"
    page_name = f"{flow_name}/pages/checkout"
    intent_name = f"{agent_name}/intents/buy-intent"
    entity_type_name = f"{agent_name}/entityTypes/product-sku"
    webhook_name = f"{agent_name}/webhooks/order-service"
    playbook_name = f"{agent_name}/playbooks/main-playbook"
    tool_ref = f"{agent_name}/tools/shopify-lookup"
    generator_name = f"{agent_name}/generators/response-gen"
    route_group_name = f"{agent_name}/transitionRouteGroups/global-exits"

    return CxAgentSnapshot(
        agent=CxAgent(
            name=agent_name,
            display_name="Fidelity Bot",
            description="Full-surface fidelity test agent",
            generative_settings={"llmModelSettings": {"model": "gemini-2.0-flash"}},
        ),
        flows=[
            CxFlow(
                name=flow_name,
                display_name="Default Start Flow",
                description="Main routing flow",
                transition_routes=[
                    {
                        "intent": intent_name,
                        "targetPage": page_name,
                        "condition": "$session.params.sku != null",
                    }
                ],
                event_handlers=[],
                pages=[
                    CxPage(
                        name=page_name,
                        display_name="Checkout",
                        entry_fulfillment={
                            "messages": [{"text": {"text": ["Ready to checkout."]}}]
                        },
                        form={
                            "parameters": [
                                {
                                    "displayName": "quantity",
                                    "entityType": "@sys.number",
                                    "required": True,
                                }
                            ]
                        },
                        transition_routes=[],
                        event_handlers=[],
                    )
                ],
            )
        ],
        intents=[
            CxIntent(
                name=intent_name,
                display_name="Buy Intent",
                description="Intent for purchasing products",
                training_phrases=[
                    {"parts": [{"text": "I want to buy"}]},
                    {"parts": [{"text": "purchase item"}]},
                ],
                parameters=[
                    {"id": "sku", "entityType": f"@{entity_type_name}", "isList": False}
                ],
                labels={"category": "purchase", "priority": "high"},
            )
        ],
        entity_types=[
            CxEntityType(
                name=entity_type_name,
                display_name="product-sku",
                kind="KIND_MAP",
                auto_expansion_mode="AUTO_EXPANSION_MODE_DEFAULT",
                entities=[
                    {"value": "WIDGET-100", "synonyms": ["widget", "WIDGET-100"]}
                ],
                excluded_phrases=["N/A"],
            )
        ],
        webhooks=[
            CxWebhook(
                name=webhook_name,
                display_name="Order Service",
                generic_web_service={
                    "uri": "https://orders.example.com/webhook",
                    "requestHeaders": {"x-api-version": "v2"},
                },
                timeout_seconds=10,
            )
        ],
        playbooks=[
            CxPlaybook(
                name=playbook_name,
                display_name="Main Playbook",
                instruction="Help customers browse and purchase products.",
                goal="Enable complete end-to-end purchase flow.",
                referenced_tools=[tool_ref],
                referenced_playbooks=[],
                referenced_flows=[flow_name],
                input_parameter_definitions=[
                    {"name": "customer_id", "type": "TYPE_STRING"}
                ],
                output_parameter_definitions=[
                    {"name": "order_id", "type": "TYPE_STRING"}
                ],
                handlers=[
                    {"name": "no-match", "event": "sys.no-match-default"}
                ],
            )
        ],
        generators=[
            CxGenerator(
                name=generator_name,
                display_name="Response Generator",
                prompt_text="Generate a helpful response for: $query",
                placeholders=[{"id": "query", "name": "query"}],
                llm_model_settings={"model": "gemini-2.0-flash"},
            )
        ],
        transition_route_groups=[
            CxTransitionRouteGroup(
                name=route_group_name,
                display_name="Global Exits",
                transition_routes=[
                    {
                        "intent": f"{agent_name}/intents/escalate",
                        "targetFlow": f"{agent_name}/flows/escalate-flow",
                    }
                ],
            )
        ],
        test_cases=[
            CxTestCase(
                name=f"{agent_name}/testCases/buy-smoke",
                display_name="Buy smoke",
                tags=["smoke"],
                conversation_turns=[
                    {"userInput": {"input": {"text": {"text": "I want to buy a WIDGET-100"}}}}
                ],
                expected_output={"targetPage": page_name},
            )
        ],
        fetched_at="2026-04-13T00:00:00Z",
    )


def _make_fake_exporter_client(
    *,
    calls: dict[str, list[dict[str, Any]]] | None = None,
    remote_snapshot: CxAgentSnapshot | None = None,
) -> Any:
    """Build a minimal fake CX client that records update/create calls."""

    log: dict[str, list[dict[str, Any]]] = calls if calls is not None else {}
    _remote = remote_snapshot

    class FakeClient:
        def fetch_snapshot(self, agent_name: str) -> CxAgentSnapshot:
            if _remote is None:
                raise RuntimeError("No remote snapshot configured")
            return _remote

        def _record(self, method: str, resource_name: str, payload: Any, update_mask: list[str] | None = None) -> None:
            log.setdefault(method, []).append(
                {"resource": resource_name, "payload": payload, "update_mask": update_mask}
            )

        def update_agent(self, name: str, updates: Any, update_mask: list[str] | None = None) -> None:
            self._record("update_agent", name, updates, update_mask)

        def update_playbook(self, name: str, updates: Any, update_mask: list[str] | None = None) -> None:
            self._record("update_playbook", name, updates, update_mask)

        def create_playbook(self, parent: str, payload: Any, playbook_id: str | None = None) -> None:
            self._record("create_playbook", parent, payload)

        def update_flow(self, name: str, updates: Any, update_mask: list[str] | None = None) -> None:
            self._record("update_flow", name, updates, update_mask)

        def create_flow(self, parent: str, payload: Any, flow_id: str | None = None) -> None:
            self._record("create_flow", parent, payload)

        def update_page(self, name: str, updates: Any, update_mask: list[str] | None = None) -> None:
            self._record("update_page", name, updates, update_mask)

        def create_page(self, flow_name: str, payload: Any, page_id: str | None = None) -> None:
            self._record("create_page", flow_name, payload)

        def update_intent(self, name: str, updates: Any, update_mask: list[str] | None = None) -> None:
            self._record("update_intent", name, updates, update_mask)

        def create_intent(self, parent: str, payload: Any, intent_id: str | None = None) -> None:
            self._record("create_intent", parent, payload)

        def update_entity_type(self, name: str, updates: Any, update_mask: list[str] | None = None) -> None:
            self._record("update_entity_type", name, updates, update_mask)

        def create_entity_type(self, parent: str, payload: Any, entity_type_id: str | None = None) -> None:
            self._record("create_entity_type", parent, payload)

        def update_webhook(self, name: str, updates: Any, update_mask: list[str] | None = None) -> None:
            self._record("update_webhook", name, updates, update_mask)

        def create_webhook(self, parent: str, payload: Any, webhook_id: str | None = None) -> None:
            self._record("create_webhook", parent, payload)

        def update_transition_route_group(self, name: str, updates: Any, update_mask: list[str] | None = None) -> None:
            self._record("update_transition_route_group", name, updates, update_mask)

        def create_transition_route_group(self, parent: str, payload: Any, route_group_id: str | None = None) -> None:
            self._record("create_transition_route_group", parent, payload)

        def update_generator(self, name: str, updates: Any, update_mask: list[str] | None = None) -> None:
            self._record("update_generator", name, updates, update_mask)

        def create_generator(self, parent: str, payload: Any, generator_id: str | None = None) -> None:
            self._record("create_generator", parent, payload)

    return FakeClient(), log


# ---------------------------------------------------------------------------
# update_mask camelCase tests
# ---------------------------------------------------------------------------

class TestUpdateMaskCamelCase:
    """Verify that all update_mask field names use camelCase (CX REST API requirement)."""

    def _make_exporter_with_log(self) -> tuple[CxExporter, dict]:
        client, log = _make_fake_exporter_client()
        return CxExporter(client), log

    def test_agent_update_mask_uses_camelcase(self, tmp_path: Path) -> None:
        """Agent update_mask should use generativeSettings not generative_settings."""
        snapshot = _make_rich_snapshot()
        exporter, log = self._make_exporter_with_log()

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified_snapshot = snapshot.model_copy(deep=True)
        modified_snapshot.agent.generative_settings = {"llmModelSettings": {"model": "gemini-1.5-pro"}}

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified_snapshot)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        agent_calls = log.get("update_agent", [])
        assert agent_calls, "Expected update_agent to be called"
        mask = agent_calls[0]["update_mask"]
        assert mask is not None
        assert "generativeSettings" in mask, f"Expected camelCase 'generativeSettings' in update_mask, got: {mask}"
        assert "generative_settings" not in mask, f"Snake_case 'generative_settings' must not appear in update_mask"

    def test_playbook_update_mask_uses_camelcase(self, tmp_path: Path) -> None:
        """Playbook update_mask should use inputParameterDefinitions not input_parameter_definitions."""
        snapshot = _make_rich_snapshot()
        exporter, log = self._make_exporter_with_log()

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified_snapshot = snapshot.model_copy(deep=True)
        modified_snapshot.playbooks[0].input_parameter_definitions = [
            {"name": "customer_id", "type": "TYPE_STRING"},
            {"name": "session_id", "type": "TYPE_STRING"},
        ]

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified_snapshot)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        playbook_calls = log.get("update_playbook", [])
        assert playbook_calls, "Expected update_playbook to be called"
        mask = playbook_calls[0]["update_mask"]
        assert mask is not None
        assert "inputParameterDefinitions" in mask, f"Expected camelCase in mask, got: {mask}"
        assert "outputParameterDefinitions" in mask, f"Expected camelCase in mask, got: {mask}"
        assert "input_parameter_definitions" not in mask
        assert "output_parameter_definitions" not in mask

    def test_intent_update_mask_uses_camelcase(self, tmp_path: Path) -> None:
        """Intent update_mask should use trainingPhrases not training_phrases."""
        snapshot = _make_rich_snapshot()
        exporter, log = self._make_exporter_with_log()

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified_snapshot = snapshot.model_copy(deep=True)
        modified_snapshot.intents[0].training_phrases = [
            {"parts": [{"text": "buy now"}]},
        ]

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified_snapshot)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        intent_calls = log.get("update_intent", [])
        assert intent_calls, "Expected update_intent to be called"
        mask = intent_calls[0]["update_mask"]
        assert mask is not None
        assert "trainingPhrases" in mask, f"Expected camelCase 'trainingPhrases', got: {mask}"
        assert "training_phrases" not in mask

    def test_entity_type_update_mask_uses_camelcase(self, tmp_path: Path) -> None:
        """Entity type update_mask should use autoExpansionMode not auto_expansion_mode."""
        snapshot = _make_rich_snapshot()
        exporter, log = self._make_exporter_with_log()

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified_snapshot = snapshot.model_copy(deep=True)
        modified_snapshot.entity_types[0].auto_expansion_mode = "AUTO_EXPANSION_MODE_UNSPECIFIED"

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified_snapshot)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        et_calls = log.get("update_entity_type", [])
        assert et_calls, "Expected update_entity_type to be called"
        mask = et_calls[0]["update_mask"]
        assert mask is not None
        assert "autoExpansionMode" in mask, f"Expected 'autoExpansionMode' in mask, got: {mask}"
        assert "excludedPhrases" in mask, f"Expected 'excludedPhrases' in mask, got: {mask}"
        assert "auto_expansion_mode" not in mask
        assert "excluded_phrases" not in mask

    def test_webhook_update_mask_uses_camelcase(self, tmp_path: Path) -> None:
        """Webhook update_mask should use genericWebService not generic_web_service."""
        snapshot = _make_rich_snapshot()
        exporter, log = self._make_exporter_with_log()

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified_snapshot = snapshot.model_copy(deep=True)
        modified_snapshot.webhooks[0].timeout_seconds = 20

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified_snapshot)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        wh_calls = log.get("update_webhook", [])
        assert wh_calls, "Expected update_webhook to be called"
        mask = wh_calls[0]["update_mask"]
        assert mask is not None
        assert "genericWebService" in mask, f"Expected 'genericWebService' in mask, got: {mask}"
        assert "generic_web_service" not in mask

    def test_generator_update_mask_uses_camelcase(self, tmp_path: Path) -> None:
        """Generator update_mask should use promptText and llmModelSettings."""
        snapshot = _make_rich_snapshot()
        exporter, log = self._make_exporter_with_log()

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified_snapshot = snapshot.model_copy(deep=True)
        modified_snapshot.generators[0].prompt_text = "Generate a concise response for: $query"

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified_snapshot)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        gen_calls = log.get("update_generator", [])
        assert gen_calls, "Expected update_generator to be called"
        mask = gen_calls[0]["update_mask"]
        assert mask is not None
        assert "promptText" in mask, f"Expected 'promptText' in mask, got: {mask}"
        assert "llmModelSettings" in mask, f"Expected 'llmModelSettings' in mask, got: {mask}"
        assert "prompt_text" not in mask
        assert "llm_model_settings" not in mask

    def test_flow_update_mask_uses_camelcase(self, tmp_path: Path) -> None:
        """Flow update_mask should use transitionRoutes not transition_routes."""
        snapshot = _make_rich_snapshot()
        exporter, log = self._make_exporter_with_log()

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified_snapshot = snapshot.model_copy(deep=True)
        modified_snapshot.flows[0].description = "Updated flow description"

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified_snapshot)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        flow_calls = log.get("update_flow", [])
        assert flow_calls, "Expected update_flow to be called"
        mask = flow_calls[0]["update_mask"]
        assert mask is not None
        assert "transitionRoutes" in mask, f"Expected 'transitionRoutes' in mask, got: {mask}"
        assert "eventHandlers" in mask, f"Expected 'eventHandlers' in mask, got: {mask}"
        assert "transitionRouteGroups" in mask, f"Expected 'transitionRouteGroups' in mask, got: {mask}"
        assert "transition_routes" not in mask
        assert "event_handlers" not in mask

    def test_page_update_mask_uses_camelcase(self, tmp_path: Path) -> None:
        """Page update_mask should use entryFulfillment not entry_fulfillment."""
        snapshot = _make_rich_snapshot()
        exporter, log = self._make_exporter_with_log()

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified_snapshot = snapshot.model_copy(deep=True)
        modified_snapshot.flows[0].pages[0].entry_fulfillment = {
            "messages": [{"text": {"text": ["Welcome to checkout — updated."]}}]
        }

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified_snapshot)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        page_calls = log.get("update_page", [])
        assert page_calls, "Expected update_page to be called"
        mask = page_calls[0]["update_mask"]
        assert mask is not None
        assert "entryFulfillment" in mask, f"Expected 'entryFulfillment' in mask, got: {mask}"
        assert "transitionRoutes" in mask
        assert "entry_fulfillment" not in mask

    def test_transition_route_group_update_mask_uses_camelcase(self, tmp_path: Path) -> None:
        """Transition route group update_mask should use transitionRoutes."""
        snapshot = _make_rich_snapshot()
        exporter, log = self._make_exporter_with_log()

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified_snapshot = snapshot.model_copy(deep=True)
        modified_snapshot.transition_route_groups[0].transition_routes = [
            {
                "intent": f"{_base_agent_name()}/intents/escalate",
                "targetFlow": f"{_base_agent_name()}/flows/escalate-flow",
            },
            {
                "intent": f"{_base_agent_name()}/intents/goodbye",
                "targetFlow": f"{_base_agent_name()}/flows/end-flow",
            },
        ]

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified_snapshot)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        rg_calls = log.get("update_transition_route_group", [])
        assert rg_calls, "Expected update_transition_route_group to be called"
        mask = rg_calls[0]["update_mask"]
        assert mask is not None
        assert "transitionRoutes" in mask, f"Expected 'transitionRoutes' in mask, got: {mask}"
        assert "transition_routes" not in mask


# ---------------------------------------------------------------------------
# Playbook fidelity tests
# ---------------------------------------------------------------------------

class TestPlaybookFidelity:
    """Verify playbook goal and referenced resources round-trip correctly."""

    def test_playbook_goal_survives_round_trip(self) -> None:
        """Playbook goal should be preserved through import/export mapping."""
        mapper = CxAgentMapper()
        snapshot = _make_rich_snapshot()

        workspace = mapper.cx_to_workspace(snapshot)
        remapped = mapper.workspace_to_cx(workspace.config, snapshot)

        assert remapped.playbooks[0].goal == snapshot.playbooks[0].goal

    def test_playbook_goal_tracked_in_diff(self, tmp_path: Path) -> None:
        """A goal change on a playbook should appear in the computed diff."""
        snapshot = _make_rich_snapshot()
        client, log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.playbooks[0].goal = "Enable express checkout flow."

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)

        changes = exporter.preview_changes(config, str(snapshot_path))
        goal_change = next((c for c in changes if c["resource"] == "playbook" and c["field"] == "goal"), None)

        assert goal_change is not None, f"Expected playbook.goal change in diff. Changes: {changes}"
        assert goal_change["before"] == snapshot.playbooks[0].goal
        assert goal_change["after"] == "Enable express checkout flow."

    def test_playbook_referenced_tools_exported(self, tmp_path: Path) -> None:
        """Playbook tool references should appear in the export payload."""
        snapshot = _make_rich_snapshot()
        client, log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        new_tool = f"{_base_agent_name()}/tools/zendesk-ticket"
        modified = snapshot.model_copy(deep=True)
        modified.playbooks[0].referenced_tools = [
            f"{_base_agent_name()}/tools/shopify-lookup",
            new_tool,
        ]

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        pb_calls = log.get("update_playbook", [])
        assert pb_calls, "Expected update_playbook to be called"
        payload = pb_calls[0]["payload"]
        assert "referencedTools" in payload, f"Expected referencedTools in payload, got keys: {list(payload.keys())}"
        assert new_tool in payload["referencedTools"]

    def test_playbook_referenced_tools_in_update_mask(self, tmp_path: Path) -> None:
        """referencedTools should appear in the update_mask when tool refs change."""
        snapshot = _make_rich_snapshot()
        client, log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.playbooks[0].referenced_tools = [
            f"{_base_agent_name()}/tools/new-tool"
        ]

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        pb_calls = log.get("update_playbook", [])
        assert pb_calls
        mask = pb_calls[0]["update_mask"]
        assert mask is not None
        assert "referencedTools" in mask, f"Expected 'referencedTools' in update_mask, got: {mask}"
        assert "referencedPlaybooks" in mask
        assert "referencedFlows" in mask

    def test_playbook_referenced_flows_tracked_in_diff(self, tmp_path: Path) -> None:
        """A change to playbook.referenced_flows should appear in the computed diff."""
        snapshot = _make_rich_snapshot()
        client, _log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.playbooks[0].referenced_flows = []

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        changes = exporter.preview_changes(config, str(snapshot_path))

        flow_ref_change = next(
            (c for c in changes if c["resource"] == "playbook" and c["field"] == "referenced_flows"),
            None,
        )
        assert flow_ref_change is not None, f"Expected playbook.referenced_flows change. Changes: {changes}"

    def test_playbook_referenced_tools_round_trip(self) -> None:
        """Playbook referenced_tools should survive the full cx->workspace->cx round-trip."""
        mapper = CxAgentMapper()
        snapshot = _make_rich_snapshot()

        workspace = mapper.cx_to_workspace(snapshot)
        remapped = mapper.workspace_to_cx(workspace.config, snapshot)

        assert remapped.playbooks[0].referenced_tools == snapshot.playbooks[0].referenced_tools
        assert remapped.playbooks[0].referenced_flows == snapshot.playbooks[0].referenced_flows


# ---------------------------------------------------------------------------
# Intent fidelity tests
# ---------------------------------------------------------------------------

class TestIntentFidelity:
    """Verify intent description and labels round-trip and are exported."""

    def test_intent_description_survives_round_trip(self) -> None:
        """Intent description should be preserved through mapping."""
        mapper = CxAgentMapper()
        snapshot = _make_rich_snapshot()

        workspace = mapper.cx_to_workspace(snapshot)
        remapped = mapper.workspace_to_cx(workspace.config, snapshot)

        assert remapped.intents[0].description == snapshot.intents[0].description

    def test_intent_labels_survives_round_trip(self) -> None:
        """Intent labels should be preserved through mapping."""
        mapper = CxAgentMapper()
        snapshot = _make_rich_snapshot()

        workspace = mapper.cx_to_workspace(snapshot)
        remapped = mapper.workspace_to_cx(workspace.config, snapshot)

        assert remapped.intents[0].labels == snapshot.intents[0].labels

    def test_intent_description_exported(self, tmp_path: Path) -> None:
        """Intent description should appear in the export payload."""
        snapshot = _make_rich_snapshot()
        client, log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.intents[0].description = "Updated: triggers on any purchase intent."

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        intent_calls = log.get("update_intent", [])
        assert intent_calls, "Expected update_intent to be called"
        payload = intent_calls[0]["payload"]
        assert payload.get("description") == "Updated: triggers on any purchase intent."

    def test_intent_labels_exported(self, tmp_path: Path) -> None:
        """Intent labels change should be exported and appear in the payload."""
        snapshot = _make_rich_snapshot()
        client, log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.intents[0].labels = {"category": "purchase", "priority": "critical"}

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        intent_calls = log.get("update_intent", [])
        assert intent_calls, "Expected update_intent to be called"
        payload = intent_calls[0]["payload"]
        assert payload.get("labels") == {"category": "purchase", "priority": "critical"}

    def test_intent_description_tracked_in_diff(self, tmp_path: Path) -> None:
        """Intent description change should appear in the computed diff."""
        snapshot = _make_rich_snapshot()
        client, _log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.intents[0].description = "Triggers when user wants to make a purchase."

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        changes = exporter.preview_changes(config, str(snapshot_path))

        desc_change = next(
            (c for c in changes if c["resource"] == "intent" and c["field"] == "description"),
            None,
        )
        assert desc_change is not None, f"Expected intent.description change in diff. Got: {changes}"

    def test_intent_labels_tracked_in_diff(self, tmp_path: Path) -> None:
        """Intent labels change should appear in the computed diff."""
        snapshot = _make_rich_snapshot()
        client, _log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.intents[0].labels = {"category": "purchase", "tier": "premium"}

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        changes = exporter.preview_changes(config, str(snapshot_path))

        labels_change = next(
            (c for c in changes if c["resource"] == "intent" and c["field"] == "labels"),
            None,
        )
        assert labels_change is not None, f"Expected intent.labels change in diff. Got: {changes}"

    def test_intent_description_in_update_mask(self, tmp_path: Path) -> None:
        """Intent update_mask should include description and labels."""
        snapshot = _make_rich_snapshot()
        client, log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.intents[0].description = "New description."

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        intent_calls = log.get("update_intent", [])
        assert intent_calls
        mask = intent_calls[0]["update_mask"]
        assert "description" in mask
        assert "labels" in mask


# ---------------------------------------------------------------------------
# Page fidelity tests
# ---------------------------------------------------------------------------

class TestPageFidelity:
    """Verify page entry_fulfillment tracking and new page creation."""

    def test_page_entry_fulfillment_tracked_in_diff(self, tmp_path: Path) -> None:
        """A page entry_fulfillment change should appear in the computed diff."""
        snapshot = _make_rich_snapshot()
        client, _log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.flows[0].pages[0].entry_fulfillment = {
            "messages": [{"text": {"text": ["Ready to check out your items."]}}]
        }

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        changes = exporter.preview_changes(config, str(snapshot_path))

        ef_change = next(
            (c for c in changes if c["resource"] == "page" and c["field"] == "entry_fulfillment"),
            None,
        )
        assert ef_change is not None, f"Expected page.entry_fulfillment change in diff. Got: {changes}"

    def test_page_entry_fulfillment_change_is_classified_lossy(self, tmp_path: Path) -> None:
        """Page entry_fulfillment changes should be classified as lossy (not blocked)."""
        snapshot = _make_rich_snapshot()
        client, _log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.flows[0].pages[0].entry_fulfillment = {
            "messages": [{"text": {"text": ["Checkout updated."]}}]
        }

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        changes = exporter.preview_changes(config, str(snapshot_path))

        ef_change = next(
            (c for c in changes if c["resource"] == "page" and c["field"] == "entry_fulfillment"),
            None,
        )
        assert ef_change is not None
        assert ef_change["safety"] in ("lossy", "safe"), f"Expected lossy/safe, got: {ef_change['safety']}"
        assert ef_change["safety"] != "blocked", "entry_fulfillment must not be blocked — it is writable"

    def test_new_page_calls_create_page(self, tmp_path: Path) -> None:
        """A new page in the target snapshot should trigger create_page, not be silently skipped."""
        snapshot = _make_rich_snapshot()
        client, log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        flow_name = snapshot.flows[0].name
        new_page_name = f"{flow_name}/pages/confirmation"

        modified = snapshot.model_copy(deep=True)
        modified.flows[0].pages.append(
            CxPage(
                name=new_page_name,
                display_name="Confirmation",
                entry_fulfillment={"messages": [{"text": {"text": ["Order confirmed."]}}]},
            )
        )

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        create_calls = log.get("create_page", [])
        assert create_calls, "Expected create_page to be called for a new page, but it was silently skipped"
        assert any(c["resource"] == flow_name for c in create_calls), \
            f"Expected create_page to be called on flow {flow_name}, got: {create_calls}"

    def test_existing_page_update_uses_update_page(self, tmp_path: Path) -> None:
        """Modifying an existing page should use update_page, not create_page."""
        snapshot = _make_rich_snapshot()
        client, log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.flows[0].pages[0].entry_fulfillment = {
            "messages": [{"text": {"text": ["Updated checkout greeting."]}}]
        }

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        exporter.export_agent(config, CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"), str(snapshot_path))

        update_calls = log.get("update_page", [])
        create_calls = log.get("create_page", [])
        assert update_calls, "Expected update_page for an existing modified page"
        assert not create_calls, "create_page should NOT be called for an existing page"


# ---------------------------------------------------------------------------
# Entity type fidelity tests
# ---------------------------------------------------------------------------

class TestEntityTypeFidelity:
    """Verify entity type auto_expansion_mode is tracked."""

    def test_auto_expansion_mode_tracked_in_diff(self, tmp_path: Path) -> None:
        """A change to entity_type.auto_expansion_mode should appear in the diff."""
        snapshot = _make_rich_snapshot()
        client, _log = _make_fake_exporter_client()
        exporter = CxExporter(client)

        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot.model_dump()), encoding="utf-8")

        modified = snapshot.model_copy(deep=True)
        modified.entity_types[0].auto_expansion_mode = "AUTO_EXPANSION_MODE_UNSPECIFIED"

        mapper = CxAgentMapper()
        config = mapper.to_agentlab(modified)
        changes = exporter.preview_changes(config, str(snapshot_path))

        ae_change = next(
            (c for c in changes if c["resource"] == "entity_type" and c["field"] == "auto_expansion_mode"),
            None,
        )
        assert ae_change is not None, f"Expected entity_type.auto_expansion_mode change in diff. Got: {changes}"

    def test_auto_expansion_mode_survives_round_trip(self) -> None:
        """entity_type.auto_expansion_mode should be preserved through mapping."""
        mapper = CxAgentMapper()
        snapshot = _make_rich_snapshot()

        workspace = mapper.cx_to_workspace(snapshot)
        remapped = mapper.workspace_to_cx(workspace.config, snapshot)

        assert remapped.entity_types[0].auto_expansion_mode == snapshot.entity_types[0].auto_expansion_mode


# ---------------------------------------------------------------------------
# Sync merge _set_field tests (new fields handled in three-way sync)
# ---------------------------------------------------------------------------

class TestSetFieldNewFields:
    """Verify that _set_field correctly handles the newly tracked fields in sync merges."""

    def _make_exporter_for_sync(
        self,
        remote_snapshot: CxAgentSnapshot,
    ) -> tuple[CxExporter, dict]:
        client, log = _make_fake_exporter_client(remote_snapshot=remote_snapshot)
        return CxExporter(client), log

    def test_sync_merge_applies_playbook_goal_change(self, tmp_path: Path) -> None:
        """Sync should apply a local playbook.goal change when remote did not change it."""
        snapshot = _make_rich_snapshot()
        remote_snapshot = snapshot.model_copy(deep=True)  # remote unchanged

        importer_client = type(
            "IC", (), {"fetch_snapshot": lambda self, name: snapshot}
        )()
        importer = CxImporter(importer_client)
        result = importer.import_agent(
            CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"),
            output_dir=str(tmp_path),
        )

        # Local editor changes the goal
        config = json.loads(
            Path(result.workspace_path, ".agentlab", "cx", "workspace.json").read_text(encoding="utf-8")
        )
        cx = config.get("cx", {})
        playbook_key = next(iter(cx.get("playbooks", {})))
        cx["playbooks"][playbook_key]["goal"] = "Enable one-click checkout flow."
        config["cx"] = cx

        exporter, log = self._make_exporter_for_sync(remote_snapshot)
        sync_result = exporter.sync_agent(
            config=config,
            ref=CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"),
            snapshot_path=result.snapshot_path,
            conflict_strategy="override",
        )

        assert sync_result.pushed is True
        pb_calls = log.get("update_playbook", [])
        assert pb_calls, "Expected update_playbook after sync"
        goal_in_payload = pb_calls[0]["payload"].get("goal")
        assert goal_in_payload == "Enable one-click checkout flow.", \
            f"Expected updated goal in payload, got: {goal_in_payload}"

    def test_sync_detects_conflict_on_intent_labels(self, tmp_path: Path) -> None:
        """Sync should detect a conflict when both local and remote changed intent labels."""
        snapshot = _make_rich_snapshot()
        remote_snapshot = snapshot.model_copy(deep=True)
        remote_snapshot.intents[0].labels = {"category": "purchase", "priority": "urgent"}

        importer_client = type(
            "IC", (), {"fetch_snapshot": lambda self, name: snapshot}
        )()
        importer = CxImporter(importer_client)
        result = importer.import_agent(
            CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"),
            output_dir=str(tmp_path),
        )

        # Local editor also changes labels (different value from remote)
        config = json.loads(
            Path(result.workspace_path, ".agentlab", "cx", "workspace.json").read_text(encoding="utf-8")
        )
        cx = config.get("cx", {})
        intent_key = next(iter(cx.get("intents", {})))
        cx["intents"][intent_key]["labels"] = {"category": "purchase", "priority": "low"}
        config["cx"] = cx

        exporter, _log = self._make_exporter_for_sync(remote_snapshot)
        sync_result = exporter.sync_agent(
            config=config,
            ref=CxAgentRef(project="demo-project", location="us-central1", agent_id="fidelity-bot"),
            snapshot_path=result.snapshot_path,
            conflict_strategy="detect",
        )

        assert sync_result.pushed is False
        label_conflict = next(
            (c for c in sync_result.conflicts if c["resource"] == "intent" and c["field"] == "labels"),
            None,
        )
        assert label_conflict is not None, \
            f"Expected intent.labels conflict, got conflicts: {sync_result.conflicts}"
