"""Round-trip tests for real Dialogflow CX import/export behavior."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.cx_agent_mapper import CxAgentMapper
from adapters.cx_studio_client import CxStudioClient, build_dialogflow_cx_base_url
from cx_studio.exporter import CxExporter
from cx_studio.importer import CxImporter
from cx_studio.types import (
    CxAgent,
    CxAgentRef,
    CxAgentSnapshot,
    CxEntityType,
    CxFlow,
    CxIntent,
    CxPage,
    CxPlaybook,
    CxTestCase,
    CxWebhook,
)


def _make_snapshot() -> CxAgentSnapshot:
    agent_name = "projects/demo-project/locations/us-central1/agents/support-bot"
    start_flow_name = f"{agent_name}/flows/00000000-0000-0000-0000-000000000000"
    page_name = f"{start_flow_name}/pages/order-status"
    intent_name = f"{agent_name}/intents/order-status"
    webhook_name = f"{agent_name}/webhooks/order-service"
    entity_type_name = f"{agent_name}/entityTypes/order-id"
    playbook_name = f"{agent_name}/playbooks/escalation-playbook"

    return CxAgentSnapshot(
        agent=CxAgent(
            name=agent_name,
            display_name="Support Bot",
            default_language_code="en",
            description="Primary customer support agent",
            generative_settings={
                "llmModelSettings": {
                    "model": "gemini-2.0-flash",
                }
            },
        ),
        flows=[
            CxFlow(
                name=start_flow_name,
                display_name="Default Start Flow",
                description="Route support issues to the right specialist.",
                transition_routes=[
                    {
                        "intent": intent_name,
                        "targetPage": page_name,
                        "condition": "$session.params.order_id != null",
                        "triggerFulfillment": {
                            "messages": [
                                {"text": {"text": ["I can look that order up for you."]}}
                            ]
                        },
                    }
                ],
                event_handlers=[],
                pages=[
                    CxPage(
                        name=page_name,
                        display_name="Order Status",
                        entry_fulfillment={
                            "messages": [
                                {"text": {"text": ["Checking order status."]}}
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
                display_name="Order Status",
                training_phrases=[
                    {"parts": [{"text": "where is my order"}]},
                    {"parts": [{"text": "track order 1234"}]},
                ],
            )
        ],
        entity_types=[
            CxEntityType(
                name=entity_type_name,
                display_name="order-id",
                kind="KIND_REGEXP",
                entities=[
                    {
                        "value": "1234",
                        "synonyms": ["1234", "order 1234"],
                    }
                ],
                excluded_phrases=["example only"],
            )
        ],
        webhooks=[
            CxWebhook(
                name=webhook_name,
                display_name="Order Service",
                generic_web_service={
                    "uri": "https://orders.example.com/webhook",
                    "requestHeaders": {"x-api-version": "2026-03"},
                },
                timeout_seconds=8,
            )
        ],
        playbooks=[
            CxPlaybook(
                name=playbook_name,
                display_name="Escalation",
                instruction="Escalate billing threats to a supervisor with context.",
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
                expected_output={"targetPage": page_name},
            )
        ],
        fetched_at="2026-03-31T12:00:00Z",
    )


class _FakeAuth:
    def get_headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        }


def test_build_dialogflow_cx_base_url_supports_global_and_regional_locations() -> None:
    """The client should target the global or regional Dialogflow CX endpoint correctly."""
    assert build_dialogflow_cx_base_url("global") == "https://dialogflow.googleapis.com/v3"
    assert build_dialogflow_cx_base_url("us-central1") == "https://us-central1-dialogflow.googleapis.com/v3"


def test_client_list_agents_follows_pagination(monkeypatch) -> None:
    """Listing agents should follow nextPageToken until all pages are consumed."""
    client = CxStudioClient(auth=_FakeAuth())
    calls: list[tuple[str, dict[str, object] | None]] = []

    def _fake_request(
        method: str,
        path: str,
        *,
        location: str,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((path, params))
        if not params or not params.get("pageToken"):
            return {
                "agents": [
                    {
                        "name": "projects/demo-project/locations/us-central1/agents/a1",
                        "displayName": "Agent One",
                        "defaultLanguageCode": "en",
                    }
                ],
                "nextPageToken": "page-2",
            }
        return {
            "agents": [
                {
                    "name": "projects/demo-project/locations/us-central1/agents/a2",
                    "displayName": "Agent Two",
                    "defaultLanguageCode": "en",
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", _fake_request)

    agents = client.list_agents(project="demo-project", location="us-central1")

    assert [agent.display_name for agent in agents] == ["Agent One", "Agent Two"]
    assert calls == [
        ("projects/demo-project/locations/us-central1/agents", {"pageSize": 100}),
        ("projects/demo-project/locations/us-central1/agents", {"pageSize": 100, "pageToken": "page-2"}),
    ]


def test_mapper_round_trip_preserves_flows_intents_entities_webhooks_and_playbooks() -> None:
    """A CX snapshot should round-trip through the AutoAgent mapping without losing supported surfaces."""
    mapper = CxAgentMapper()
    snapshot = _make_snapshot()

    workspace = mapper.cx_to_workspace(snapshot)
    remapped_snapshot = mapper.workspace_to_cx(workspace.config, snapshot)

    assert remapped_snapshot.flows[0].model_dump() == snapshot.flows[0].model_dump()
    assert remapped_snapshot.intents[0].model_dump() == snapshot.intents[0].model_dump()
    assert remapped_snapshot.entity_types[0].model_dump() == snapshot.entity_types[0].model_dump()
    assert remapped_snapshot.webhooks[0].model_dump() == snapshot.webhooks[0].model_dump()
    assert remapped_snapshot.playbooks[0].model_dump() == snapshot.playbooks[0].model_dump()
    assert workspace.config["_cx"]["agent"]["display_name"] == "Support Bot"


def test_importer_and_exporter_support_three_way_conflict_detection(tmp_path: Path) -> None:
    """Sync should report conflicts when both the local workspace and remote agent changed the same field."""
    snapshot = _make_snapshot()
    remote_snapshot = snapshot.model_copy(deep=True)
    remote_snapshot.playbooks[0].instruction = "Remote operator changed escalation instructions."

    importer_client = type(
        "ImporterClient",
        (),
        {"fetch_snapshot": lambda self, agent_name: snapshot},
    )()
    importer = CxImporter(importer_client)

    result = importer.import_agent(
        CxAgentRef(project="demo-project", location="us-central1", agent_id="support-bot"),
        output_dir=str(tmp_path),
    )

    config = json.loads(Path(result.workspace_path, ".autoagent", "cx", "workspace.json").read_text(encoding="utf-8"))
    config["prompts"]["root"] = "Local editor changed escalation instructions."

    exporter_client = type(
        "ExporterClient",
        (),
        {
            "fetch_snapshot": lambda self, agent_name: remote_snapshot,
            "update_agent": lambda self, agent_name, updates, update_mask=None: None,
            "update_playbook": lambda self, name, updates, update_mask=None: None,
            "update_flow": lambda self, name, updates, update_mask=None: None,
            "update_intent": lambda self, name, updates, update_mask=None: None,
            "update_entity_type": lambda self, name, updates, update_mask=None: None,
            "update_webhook": lambda self, name, updates, update_mask=None: None,
            "create_intent": lambda self, parent, payload, intent_id=None: None,
            "create_entity_type": lambda self, parent, payload, entity_type_id=None: None,
            "create_webhook": lambda self, parent, payload, webhook_id=None: None,
            "create_playbook": lambda self, parent, payload, playbook_id=None: None,
            "create_flow": lambda self, parent, payload, flow_id=None: None,
        },
    )()
    exporter = CxExporter(exporter_client)

    sync_result = exporter.sync_agent(
        config=config,
        ref=CxAgentRef(project="demo-project", location="us-central1", agent_id="support-bot"),
        snapshot_path=result.snapshot_path,
        conflict_strategy="detect",
    )

    assert sync_result.pushed is False
    assert sync_result.conflicts == [
        {
            "resource": "playbook",
            "name": "Escalation",
            "field": "instruction",
            "base": "Escalate billing threats to a supervisor with context.",
            "local": "Local editor changed escalation instructions.",
            "remote": "Remote operator changed escalation instructions.",
        }
    ]
