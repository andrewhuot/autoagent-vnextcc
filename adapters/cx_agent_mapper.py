"""Bidirectional mapping between Dialogflow CX snapshots and AgentLab workspaces."""

from __future__ import annotations

import copy
import re
from typing import Any

from adapters.base import ImportedAgentSpec, keyword_candidates
from cx_studio.errors import CxMappingError
from cx_studio.types import (
    CxAgentSnapshot,
    CxEditableEntityType,
    CxEditableFlow,
    CxEditableGenerator,
    CxEditableIntent,
    CxEditablePage,
    CxEditablePlaybook,
    CxEditableTransitionRouteGroup,
    CxEditableWebhook,
    CxEditableWorkspace,
    CxEntityType,
    CxFlow,
    CxGenerator,
    CxIntent,
    CxPage,
    CxPlaybook,
    CxTool,
    CxTransitionRouteGroup,
    CxWebhook,
    CxProjectionMetadata,
    CxProjectionSummary,
)
from portability.types import ProjectionQualityStatus


def _slug(value: str) -> str:
    """Convert a display label into a stable config key."""

    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or "default"


def _resource_segment(resource_name: str) -> str:
    """Return the last segment of a resource name."""

    return resource_name.split("/")[-1] if resource_name else ""


def _projection(
    *,
    source_platform: str,
    source_refs: list[str],
    quality: ProjectionQualityStatus,
    rationale: list[str],
) -> CxProjectionMetadata:
    """Build projection metadata for a CX-native editable record."""

    return CxProjectionMetadata(
        quality=quality,
        source_platform=source_platform,
        source_refs=source_refs,
        rationale=rationale,
    )


def _projection_summary(
    *collections: dict[str, Any],
) -> CxProjectionSummary:
    """Aggregate projection quality counts across editable CX records."""

    qualities: list[ProjectionQualityStatus] = []
    for collection in collections:
        for value in collection.values():
            projection = getattr(value, "projection", None)
            if projection is None:
                continue
            qualities.append(projection.quality)

    return CxProjectionSummary(
        editable_surface_count=len(qualities),
        faithful_count=sum(1 for quality in qualities if quality == ProjectionQualityStatus.FAITHFUL),
        approximated_count=sum(1 for quality in qualities if quality == ProjectionQualityStatus.APPROXIMATED),
        preserved_only_count=sum(1 for quality in qualities if quality == ProjectionQualityStatus.PRESERVED_ONLY),
    )


def _entry_changed(current: Any, original: Any | None) -> bool:
    """Return True when the editable CX record differs from the original snapshot projection."""

    if original is None:
        return True
    return current.model_dump(mode="json", exclude={"projection"}) != original.model_dump(
        mode="json",
        exclude={"projection"},
    )


class CxAgentMapper:
    """Pure mapping logic for CX snapshots and AgentLab workspace configs."""

    def cx_to_workspace(self, snapshot: CxAgentSnapshot) -> ImportedAgentSpec:
        """Convert a CX snapshot into an imported AgentLab workspace spec."""

        config = self.to_agentlab(snapshot)
        root_prompt = config.get("prompts", {}).get("root", snapshot.agent.description)
        tools = [
            {
                "name": _slug(webhook.display_name or webhook.name.split("/")[-1]),
                "description": webhook.generic_web_service.get("uri", ""),
                "source": "webhook",
            }
            for webhook in snapshot.webhooks
        ]
        for tool in snapshot.tools:
            tools.append(
                {
                    "name": _slug(tool.display_name or tool.name.split("/")[-1]),
                    "description": tool.spec.get("description", ""),
                    "source": "tool",
                }
            )
        handoffs = [
            {"target": rule["specialist"], "keywords": rule.get("keywords", [])}
            for rule in config.get("routing", {}).get("rules", [])
        ]

        return ImportedAgentSpec(
            adapter="cx_studio",
            source=snapshot.agent.name,
            agent_name=snapshot.agent.display_name or snapshot.agent.name.split("/")[-1],
            platform="dialogflow-cx",
            system_prompts=[root_prompt] if root_prompt else [],
            tools=tools,
            handoffs=handoffs,
            config=config,
            starter_evals=self.extract_test_cases(snapshot),
            adapter_config={
                "type": "dialogflow-cx",
                "agent_name": snapshot.agent.name,
                "fetched_at": snapshot.fetched_at,
            },
            metadata={"model": self._extract_model(snapshot.agent.generative_settings)},
        )

    def to_agentlab(self, snapshot: CxAgentSnapshot) -> dict[str, Any]:
        """Convert a CX snapshot to an AgentLab-compatible config dictionary."""

        try:
            prompts = self._map_prompts(snapshot)
            tools = self._map_tools(snapshot.webhooks, snapshot.tools)
            routing = self._map_routing(snapshot.flows, snapshot.intents)
            cx_workspace = self.build_cx_workspace(snapshot)

            flows = self._map_flows(snapshot)

            config: dict[str, Any] = {
                "prompts": prompts,
                "tools": tools,
                "routing": routing,
                "flows": flows,
                "cx": cx_workspace.model_dump(mode="json"),
                "_cx": {
                    "version": 1,
                    "agent": {
                        "name": snapshot.agent.name,
                        "display_name": snapshot.agent.display_name,
                        "description": snapshot.agent.description,
                    },
                    "snapshot": snapshot.model_dump(),
                    "entity_types": [entity.model_dump() for entity in snapshot.entity_types],
                    "webhooks": [webhook.model_dump() for webhook in snapshot.webhooks],
                    "playbooks": [playbook.model_dump() for playbook in snapshot.playbooks],
                    "flows": [flow.model_dump() for flow in snapshot.flows],
                    "transition_route_groups": [
                        route_group.model_dump() for route_group in snapshot.transition_route_groups
                    ],
                    "intents": [intent.model_dump() for intent in snapshot.intents],
                    "generators": [generator.model_dump() for generator in snapshot.generators],
                },
            }

            model = self._extract_model(snapshot.agent.generative_settings)
            if model:
                config["model"] = model

            return config
        except Exception as exc:  # pragma: no cover - guarded by tests
            raise CxMappingError(f"Failed to map CX snapshot to AgentLab config: {exc}") from exc

    def workspace_to_cx(
        self,
        config: dict[str, Any],
        base_snapshot: CxAgentSnapshot,
    ) -> CxAgentSnapshot:
        """Overlay a workspace config back onto a base CX snapshot."""

        try:
            result = copy.deepcopy(base_snapshot)
            prompts = config.get("prompts", {})
            tools = config.get("tools", {})
            original_workspace = self.build_cx_workspace(base_snapshot)

            self._apply_prompts(result, prompts)
            self._apply_webhooks(result.webhooks, tools)

            if "model" in config:
                result.agent.generative_settings = copy.deepcopy(result.agent.generative_settings)
                llm_settings = result.agent.generative_settings.setdefault("llmModelSettings", {})
                llm_settings["model"] = config["model"]

            if isinstance(config.get("cx"), dict):
                self._apply_cx_workspace(
                    snapshot=result,
                    original_workspace=original_workspace,
                    cx_payload=config["cx"],
                )

            return result
        except Exception as exc:  # pragma: no cover - guarded by tests
            raise CxMappingError(f"Failed to map AgentLab workspace back to CX: {exc}") from exc

    def to_cx(self, config: dict[str, Any], base_snapshot: CxAgentSnapshot) -> CxAgentSnapshot:
        """Compatibility alias for existing importer/exporter code."""

        return self.workspace_to_cx(config, base_snapshot)

    def extract_test_cases(self, snapshot: CxAgentSnapshot) -> list[dict[str, Any]]:
        """Convert CX test cases into AgentLab starter eval cases."""

        cases: list[dict[str, Any]] = []
        for index, test_case in enumerate(snapshot.test_cases, start=1):
            user_message = self._extract_user_message(test_case.conversation_turns)
            cases.append(
                {
                    "id": f"cx_import_{index:03d}",
                    "category": "imported_cx",
                    "input": user_message or "Imported CX test case",
                    "user_message": user_message or "Imported CX test case",
                    "expected_output": test_case.expected_output,
                    "tags": list(test_case.tags),
                    "expected_specialist": self._infer_expected_specialist(snapshot),
                    "expected_behavior": "answer",
                    "expected_keywords": keyword_candidates(jsonable_string(test_case.expected_output)),
                    "metadata": {
                        "cx_name": test_case.name,
                        "cx_display_name": test_case.display_name,
                    },
                }
            )
        return cases

    def build_cx_workspace(self, snapshot: CxAgentSnapshot) -> CxEditableWorkspace:
        """Build the additive CX-native editable contract for a real CX snapshot."""

        playbooks = {
            _slug(playbook.display_name or _resource_segment(playbook.name)): CxEditablePlaybook(
                id=_slug(playbook.display_name or _resource_segment(playbook.name)),
                resource_name=playbook.name,
                display_name=playbook.display_name or _resource_segment(playbook.name),
                goal=playbook.goal,
                instructions=(
                    list(playbook.instructions)
                    if playbook.instructions
                    else ([playbook.instruction_text] if playbook.instruction_text else [])
                ),
                input_parameters=copy.deepcopy(playbook.input_parameter_definitions),
                output_parameters=copy.deepcopy(playbook.output_parameter_definitions),
                handlers=copy.deepcopy(playbook.handlers),
                referenced_tools=list(playbook.referenced_tools),
                referenced_playbooks=list(playbook.referenced_playbooks),
                referenced_flows=list(playbook.referenced_flows),
                code_block=copy.deepcopy(playbook.code_block),
                llm_model_settings=copy.deepcopy(playbook.llm_model_settings),
                projection=_projection(
                    source_platform="cx_studio",
                    source_refs=[playbook.name],
                    quality=ProjectionQualityStatus.FAITHFUL,
                    rationale=["Imported directly from a CX playbook resource."],
                ),
            )
            for playbook in snapshot.playbooks
        }

        transition_route_groups = {
            _slug(route_group.display_name or _resource_segment(route_group.name)): CxEditableTransitionRouteGroup(
                id=_slug(route_group.display_name or _resource_segment(route_group.name)),
                resource_name=route_group.name,
                display_name=route_group.display_name or _resource_segment(route_group.name),
                transition_routes=copy.deepcopy(route_group.transition_routes),
                projection=_projection(
                    source_platform="cx_studio",
                    source_refs=[route_group.name],
                    quality=ProjectionQualityStatus.FAITHFUL,
                    rationale=["Imported directly from a CX transition route group resource."],
                ),
            )
            for route_group in snapshot.transition_route_groups
        }

        flows: dict[str, CxEditableFlow] = {}
        for flow in snapshot.flows:
            flow_key = _slug(flow.display_name or _resource_segment(flow.name))
            pages: dict[str, CxEditablePage] = {}
            for page in flow.pages:
                page_key = _slug(page.display_name or _resource_segment(page.name))
                pages[page_key] = CxEditablePage(
                    id=page_key,
                    resource_name=page.name,
                    display_name=page.display_name or _resource_segment(page.name),
                    entry_fulfillment=copy.deepcopy(page.entry_fulfillment),
                    form=copy.deepcopy(page.form),
                    transition_routes=copy.deepcopy(page.transition_routes),
                    event_handlers=copy.deepcopy(page.event_handlers),
                    route_group_ids=[_slug(_resource_segment(route_group)) for route_group in page.transition_route_groups],
                    projection=_projection(
                        source_platform="cx_studio",
                        source_refs=[page.name],
                        quality=ProjectionQualityStatus.FAITHFUL,
                        rationale=["Imported directly from a CX page resource."],
                    ),
                )

            flows[flow_key] = CxEditableFlow(
                id=flow_key,
                resource_name=flow.name,
                display_name=flow.display_name or _resource_segment(flow.name),
                description=flow.description,
                transition_routes=copy.deepcopy(flow.transition_routes),
                event_handlers=copy.deepcopy(flow.event_handlers),
                route_group_ids=[_slug(_resource_segment(route_group)) for route_group in flow.transition_route_groups],
                pages=pages,
                projection=_projection(
                    source_platform="cx_studio",
                    source_refs=[flow.name],
                    quality=ProjectionQualityStatus.FAITHFUL,
                    rationale=["Imported directly from a CX flow resource."],
                ),
            )

        intents = {
            _slug(intent.display_name or _resource_segment(intent.name)): CxEditableIntent(
                id=_slug(intent.display_name or _resource_segment(intent.name)),
                resource_name=intent.name,
                display_name=intent.display_name or _resource_segment(intent.name),
                description=intent.description,
                training_phrases=copy.deepcopy(intent.training_phrases),
                parameters=copy.deepcopy(intent.parameters),
                labels=dict(intent.labels),
                projection=_projection(
                    source_platform="cx_studio",
                    source_refs=[intent.name],
                    quality=ProjectionQualityStatus.FAITHFUL,
                    rationale=["Imported directly from a CX intent resource."],
                ),
            )
            for intent in snapshot.intents
        }

        entity_types = {
            _slug(entity_type.display_name or _resource_segment(entity_type.name)): CxEditableEntityType(
                id=_slug(entity_type.display_name or _resource_segment(entity_type.name)),
                resource_name=entity_type.name,
                display_name=entity_type.display_name or _resource_segment(entity_type.name),
                kind=entity_type.kind,
                auto_expansion_mode=entity_type.auto_expansion_mode,
                entities=copy.deepcopy(entity_type.entities),
                excluded_phrases=list(entity_type.excluded_phrases),
                projection=_projection(
                    source_platform="cx_studio",
                    source_refs=[entity_type.name],
                    quality=ProjectionQualityStatus.FAITHFUL,
                    rationale=["Imported directly from a CX entity type resource."],
                ),
            )
            for entity_type in snapshot.entity_types
        }

        generators = {
            _slug(generator.display_name or _resource_segment(generator.name)): CxEditableGenerator(
                id=_slug(generator.display_name or _resource_segment(generator.name)),
                resource_name=generator.name,
                display_name=generator.display_name or _resource_segment(generator.name),
                prompt_text=generator.prompt_text,
                placeholders=copy.deepcopy(generator.placeholders),
                llm_model_settings=copy.deepcopy(generator.llm_model_settings),
                projection=_projection(
                    source_platform="cx_studio",
                    source_refs=[generator.name],
                    quality=ProjectionQualityStatus.FAITHFUL,
                    rationale=["Imported directly from a CX generator resource."],
                ),
            )
            for generator in snapshot.generators
        }

        webhooks = {
            _slug(webhook.display_name or _resource_segment(webhook.name)): CxEditableWebhook(
                id=_slug(webhook.display_name or _resource_segment(webhook.name)),
                resource_name=webhook.name,
                display_name=webhook.display_name or _resource_segment(webhook.name),
                url=str(webhook.generic_web_service.get("uri", "")),
                headers=dict(webhook.generic_web_service.get("requestHeaders", {})),
                timeout_ms=webhook.timeout_seconds * 1000,
                disabled=webhook.disabled,
                projection=_projection(
                    source_platform="cx_studio",
                    source_refs=[webhook.name],
                    quality=ProjectionQualityStatus.FAITHFUL,
                    rationale=["Imported directly from a CX webhook resource."],
                ),
            )
            for webhook in snapshot.webhooks
        }

        workspace = CxEditableWorkspace(
            source_platform="cx_studio",
            target_platform="cx_agent_studio",
            playbooks=playbooks,
            flows=flows,
            transition_route_groups=transition_route_groups,
            intents=intents,
            entity_types=entity_types,
            generators=generators,
            webhooks=webhooks,
            preserved={
                "app_tools": [tool.model_dump(mode="json") for tool in snapshot.tools],
                "test_cases": [test_case.model_dump(mode="json") for test_case in snapshot.test_cases],
                "environments": [environment.model_dump(mode="json") for environment in snapshot.environments],
                "speech_settings": [
                    {
                        "speech_to_text_settings": copy.deepcopy(snapshot.agent.speech_to_text_settings),
                        "text_to_speech_settings": copy.deepcopy(snapshot.agent.text_to_speech_settings),
                    }
                ],
            },
        )
        workspace.projection_summary = _projection_summary(
            playbooks,
            flows,
            transition_route_groups,
            intents,
            entity_types,
            generators,
            webhooks,
        )
        return workspace

    def _apply_cx_workspace(
        self,
        *,
        snapshot: CxAgentSnapshot,
        original_workspace: CxEditableWorkspace,
        cx_payload: dict[str, Any],
    ) -> None:
        """Apply the CX-native editable contract onto a snapshot in-place."""

        workspace = CxEditableWorkspace.model_validate(cx_payload)
        self._apply_cx_playbooks(snapshot, workspace, original_workspace)
        self._apply_cx_route_groups(snapshot, workspace, original_workspace)
        self._apply_cx_flows(snapshot, workspace, original_workspace)
        self._apply_cx_intents(snapshot, workspace, original_workspace)
        self._apply_cx_entity_types(snapshot, workspace, original_workspace)
        self._apply_cx_generators(snapshot, workspace, original_workspace)
        self._apply_cx_webhook_contract(snapshot.webhooks, workspace.webhooks, original_workspace.webhooks, snapshot.agent.name)

    def _map_prompts(self, snapshot: CxAgentSnapshot) -> dict[str, str]:
        """Build prompt text from playbooks, agent description, and flow descriptions."""

        prompts: dict[str, str] = {}
        if snapshot.playbooks:
            first_playbook = snapshot.playbooks[0]
            prompts["root"] = first_playbook.instruction_text or snapshot.agent.description
            for playbook in snapshot.playbooks[1:]:
                prompts[_slug(playbook.display_name or playbook.name.split("/")[-1])] = playbook.instruction_text
        elif snapshot.agent.description:
            prompts["root"] = snapshot.agent.description
        elif snapshot.flows:
            prompts["root"] = snapshot.flows[0].description or snapshot.flows[0].display_name
        else:
            prompts["root"] = f"Imported from Dialogflow CX agent {snapshot.agent.display_name or snapshot.agent.name}."
        return prompts

    def _map_tools(self, webhooks: list[CxWebhook], tools: list[CxTool]) -> dict[str, Any]:
        """Map Dialogflow CX webhooks and tools into AgentLab tool entries."""

        config_tools: dict[str, Any] = {}
        for webhook in webhooks:
            key = _slug(webhook.display_name or webhook.name.split("/")[-1])
            config_tools[key] = {
                "enabled": not webhook.disabled,
                "timeout_ms": webhook.timeout_seconds * 1000,
                "url": webhook.generic_web_service.get("uri", ""),
                "headers": webhook.generic_web_service.get("requestHeaders", {}),
                "_cx_webhook_name": webhook.name,
                "_cx_type": "webhook",
            }
        for tool in tools:
            key = _slug(tool.display_name or tool.name.split("/")[-1])
            config_tools[key] = {
                "enabled": True,
                "timeout_ms": int(tool.spec.get("timeout_ms", 5000)),
                "description": str(tool.spec.get("description", "")),
                "_cx_tool_name": tool.name,
                "_cx_type": tool.tool_type or "tool",
            }
        return config_tools

    def _map_routing(
        self,
        flows: list[CxFlow],
        intents: list[CxIntent],
    ) -> dict[str, Any]:
        """Derive routing rules from flow transition routes and intent phrases."""

        intent_by_name = {intent.name: intent for intent in intents}
        page_names: dict[str, str] = {}
        for flow in flows:
            for page in flow.pages:
                page_names[page.name] = page.display_name

        rules: list[dict[str, Any]] = []
        for flow in flows:
            for route in flow.transition_routes:
                intent = intent_by_name.get(route.get("intent", ""))
                keywords = self._extract_training_phrases(intent) if intent else []
                target = route.get("targetPage") or route.get("targetFlow") or flow.display_name
                specialist = _slug(page_names.get(target, str(target).split("/")[-1]))
                if not specialist:
                    specialist = _slug(flow.display_name)
                rules.append(
                    {
                        "specialist": specialist,
                        "keywords": keywords or keyword_candidates(str(target)),
                        "patterns": [route.get("condition", "")] if route.get("condition") else [],
                    }
                )

        if not rules:
            for intent in intents:
                rules.append(
                    {
                        "specialist": _slug(intent.display_name or intent.name.split("/")[-1]),
                        "keywords": self._extract_training_phrases(intent),
                        "patterns": [],
                    }
                )

        return {"rules": rules}

    def _map_flows(self, snapshot: CxAgentSnapshot) -> list[dict[str, Any]]:
        """Project CX flows and pages into IR-compatible flow structures."""

        intent_by_name = {intent.name: intent for intent in snapshot.intents}
        flows: list[dict[str, Any]] = []

        for flow in snapshot.flows:
            flow_name = _slug(flow.display_name or _resource_segment(flow.name))

            flow_transitions: list[dict[str, Any]] = []
            for route in flow.transition_routes:
                intent = intent_by_name.get(route.get("intent", ""))
                target_raw = route.get("targetPage") or route.get("targetFlow") or ""
                target = _slug(_resource_segment(str(target_raw))) if target_raw else ""
                fulfillment = ""
                fulfillment_block = route.get("triggerFulfillment", {})
                if isinstance(fulfillment_block, dict):
                    messages = fulfillment_block.get("messages", [])
                    if messages and isinstance(messages, list):
                        text_block = messages[0].get("text", {}) if isinstance(messages[0], dict) else {}
                        texts = text_block.get("text", []) if isinstance(text_block, dict) else []
                        if texts:
                            fulfillment = str(texts[0])

                flow_transitions.append({
                    "target": target,
                    "condition": str(route.get("condition", "")),
                    "intent": intent.display_name if intent else "",
                    "fulfillment_message": fulfillment,
                    "metadata": {"cx_route": route},
                })

            flow_event_handlers: list[dict[str, Any]] = []
            for handler in flow.event_handlers:
                target_raw = handler.get("targetPage") or handler.get("targetFlow") or ""
                target = _slug(_resource_segment(str(target_raw))) if target_raw else ""
                flow_event_handlers.append({
                    "event": str(handler.get("event", "")),
                    "action": "route" if target else "fulfill",
                    "target": target,
                    "fulfillment_message": self._extract_fulfillment_text(handler.get("triggerFulfillment")),
                })

            states: list[dict[str, Any]] = []
            for page in flow.pages:
                page_name = _slug(page.display_name or _resource_segment(page.name))

                page_transitions: list[dict[str, Any]] = []
                for route in page.transition_routes:
                    intent = intent_by_name.get(route.get("intent", ""))
                    target_raw = route.get("targetPage") or route.get("targetFlow") or ""
                    target = _slug(_resource_segment(str(target_raw))) if target_raw else ""
                    page_transitions.append({
                        "target": target,
                        "condition": str(route.get("condition", "")),
                        "intent": intent.display_name if intent else "",
                        "fulfillment_message": self._extract_fulfillment_text(
                            route.get("triggerFulfillment")
                        ),
                    })

                page_event_handlers: list[dict[str, Any]] = []
                for handler in page.event_handlers:
                    target_raw = handler.get("targetPage") or handler.get("targetFlow") or ""
                    target = _slug(_resource_segment(str(target_raw))) if target_raw else ""
                    page_event_handlers.append({
                        "event": str(handler.get("event", "")),
                        "action": "route" if target else "fulfill",
                        "target": target,
                        "fulfillment_message": self._extract_fulfillment_text(
                            handler.get("triggerFulfillment")
                        ),
                    })

                form_params: list[dict[str, Any]] = []
                form = page.form if isinstance(page.form, dict) else {}
                for param in form.get("parameters", []):
                    if isinstance(param, dict):
                        form_params.append(param)

                states.append({
                    "name": page_name,
                    "display_name": page.display_name or _resource_segment(page.name),
                    "entry_fulfillment": self._extract_fulfillment_text(page.entry_fulfillment),
                    "form_parameters": form_params,
                    "transitions": page_transitions,
                    "event_handlers": page_event_handlers,
                    "metadata": {"cx_page_name": page.name},
                })

            flows.append({
                "name": flow_name,
                "display_name": flow.display_name or _resource_segment(flow.name),
                "description": flow.description,
                "states": states,
                "transitions": flow_transitions,
                "event_handlers": flow_event_handlers,
                "metadata": {"cx_flow_name": flow.name},
            })

        return flows

    @staticmethod
    def _extract_fulfillment_text(fulfillment: Any) -> str:
        """Extract the first text message from a CX fulfillment block."""
        if not isinstance(fulfillment, dict):
            return ""
        messages = fulfillment.get("messages", [])
        if not messages or not isinstance(messages, list):
            return ""
        first = messages[0] if messages else {}
        if not isinstance(first, dict):
            return ""
        text_block = first.get("text", {})
        if not isinstance(text_block, dict):
            return ""
        texts = text_block.get("text", [])
        if texts and isinstance(texts, list):
            return str(texts[0])
        return ""

    def _apply_prompts(self, snapshot: CxAgentSnapshot, prompts: dict[str, Any]) -> None:
        """Apply prompt edits back to playbooks or agent descriptions."""

        root_prompt = str(prompts.get("root", "")).strip()
        if root_prompt:
            if snapshot.playbooks:
                if root_prompt != snapshot.playbooks[0].instruction_text:
                    snapshot.playbooks[0].instruction = root_prompt
                    snapshot.playbooks[0].instructions = [
                        line for line in root_prompt.splitlines() if line.strip()
                    ]
            elif snapshot.agent.description:
                snapshot.agent.description = root_prompt
            elif snapshot.flows:
                snapshot.flows[0].description = root_prompt

        if len(snapshot.playbooks) > 1:
            by_key = {
                _slug(playbook.display_name or playbook.name.split("/")[-1]): playbook
                for playbook in snapshot.playbooks[1:]
            }
            for key, value in prompts.items():
                if key == "root" or key not in by_key:
                    continue
                prompt_text = str(value).strip()
                playbook = by_key[key]
                if prompt_text == playbook.instruction_text:
                    continue
                playbook.instruction = prompt_text
                playbook.instructions = [line for line in prompt_text.splitlines() if line.strip()]

    def _apply_webhooks(self, webhooks: list[CxWebhook], tools: dict[str, Any]) -> None:
        """Apply tool edits back to matching webhooks."""

        index = {
            webhook.name: webhook
            for webhook in webhooks
        }
        keyed = {
            _slug(webhook.display_name or webhook.name.split("/")[-1]): webhook
            for webhook in webhooks
        }

        for key, value in tools.items():
            if not isinstance(value, dict):
                continue
            webhook = None
            if value.get("_cx_webhook_name"):
                webhook = index.get(str(value["_cx_webhook_name"]))
            if webhook is None:
                webhook = keyed.get(key)
            if webhook is None:
                continue

            if "enabled" in value:
                webhook.disabled = not bool(value["enabled"])
            if "timeout_ms" in value:
                webhook.timeout_seconds = max(int(value["timeout_ms"]) // 1000, 1)
            if "url" in value:
                webhook.generic_web_service = copy.deepcopy(webhook.generic_web_service)
                webhook.generic_web_service["uri"] = str(value["url"])
            if "headers" in value and isinstance(value["headers"], dict):
                webhook.generic_web_service = copy.deepcopy(webhook.generic_web_service)
                webhook.generic_web_service["requestHeaders"] = dict(value["headers"])

    def _apply_cx_playbooks(
        self,
        snapshot: CxAgentSnapshot,
        workspace: CxEditableWorkspace,
        original_workspace: CxEditableWorkspace,
    ) -> None:
        """Apply typed CX-native playbook edits."""

        by_name = {playbook.name: playbook for playbook in snapshot.playbooks}
        by_key = {
            _slug(playbook.display_name or _resource_segment(playbook.name)): playbook
            for playbook in snapshot.playbooks
        }

        for key, editable in workspace.playbooks.items():
            if not _entry_changed(editable, original_workspace.playbooks.get(key)):
                continue

            resource_name = editable.resource_name or f"{snapshot.agent.name}/playbooks/{key}"
            playbook = by_name.get(resource_name) or by_key.get(key)
            if playbook is None:
                playbook = CxPlaybook(name=resource_name, display_name=editable.display_name or key)
                snapshot.playbooks.append(playbook)
                by_name[resource_name] = playbook
                by_key[key] = playbook

            playbook.display_name = editable.display_name or playbook.display_name
            playbook.goal = editable.goal
            playbook.instructions = [line for line in editable.instructions if line]
            playbook.instruction = "\n".join(playbook.instructions)
            playbook.input_parameter_definitions = copy.deepcopy(editable.input_parameters)
            playbook.output_parameter_definitions = copy.deepcopy(editable.output_parameters)
            playbook.handlers = copy.deepcopy(editable.handlers)
            playbook.referenced_tools = list(editable.referenced_tools)
            playbook.referenced_playbooks = list(editable.referenced_playbooks)
            playbook.referenced_flows = list(editable.referenced_flows)
            playbook.code_block = copy.deepcopy(editable.code_block)
            playbook.llm_model_settings = copy.deepcopy(editable.llm_model_settings)

    def _apply_cx_route_groups(
        self,
        snapshot: CxAgentSnapshot,
        workspace: CxEditableWorkspace,
        original_workspace: CxEditableWorkspace,
    ) -> None:
        """Apply typed CX-native transition route group edits."""

        by_name = {route_group.name: route_group for route_group in snapshot.transition_route_groups}
        by_key = {
            _slug(route_group.display_name or _resource_segment(route_group.name)): route_group
            for route_group in snapshot.transition_route_groups
        }

        for key, editable in workspace.transition_route_groups.items():
            if not _entry_changed(editable, original_workspace.transition_route_groups.get(key)):
                continue

            resource_name = editable.resource_name or f"{snapshot.agent.name}/transitionRouteGroups/{key}"
            route_group = by_name.get(resource_name) or by_key.get(key)
            if route_group is None:
                route_group = CxTransitionRouteGroup(name=resource_name, display_name=editable.display_name or key)
                snapshot.transition_route_groups.append(route_group)
                by_name[resource_name] = route_group
                by_key[key] = route_group

            route_group.display_name = editable.display_name or route_group.display_name
            route_group.transition_routes = copy.deepcopy(editable.transition_routes)

    def _apply_cx_flows(
        self,
        snapshot: CxAgentSnapshot,
        workspace: CxEditableWorkspace,
        original_workspace: CxEditableWorkspace,
    ) -> None:
        """Apply typed CX-native flow and page edits."""

        by_name = {flow.name: flow for flow in snapshot.flows}
        by_key = {
            _slug(flow.display_name or _resource_segment(flow.name)): flow
            for flow in snapshot.flows
        }

        for key, editable in workspace.flows.items():
            original_flow = original_workspace.flows.get(key)
            flow_changed = _entry_changed(editable, original_flow)
            page_originals = original_flow.pages if original_flow is not None else {}
            page_changes = {
                page_key: page
                for page_key, page in editable.pages.items()
                if _entry_changed(page, page_originals.get(page_key))
            }
            if not flow_changed and not page_changes:
                continue

            resource_name = editable.resource_name or f"{snapshot.agent.name}/flows/{key}"
            flow = by_name.get(resource_name) or by_key.get(key)
            if flow is None:
                flow = CxFlow(name=resource_name, display_name=editable.display_name or key)
                snapshot.flows.append(flow)
                by_name[resource_name] = flow
                by_key[key] = flow

            if flow_changed:
                flow.display_name = editable.display_name or flow.display_name
                flow.description = editable.description
                flow.transition_routes = copy.deepcopy(editable.transition_routes)
                flow.event_handlers = copy.deepcopy(editable.event_handlers)
                flow.transition_route_groups = self._resolve_route_group_refs(
                    editable.route_group_ids,
                    workspace.transition_route_groups,
                    snapshot.agent.name,
                )

            page_by_name = {page.name: page for page in flow.pages}
            page_by_key = {
                _slug(page.display_name or _resource_segment(page.name)): page
                for page in flow.pages
            }
            for page_key, page_editable in page_changes.items():
                page_resource_name = page_editable.resource_name or f"{flow.name}/pages/{page_key}"
                page = page_by_name.get(page_resource_name) or page_by_key.get(page_key)
                if page is None:
                    page = CxPage(name=page_resource_name, display_name=page_editable.display_name or page_key)
                    flow.pages.append(page)
                    page_by_name[page_resource_name] = page
                    page_by_key[page_key] = page

                page.display_name = page_editable.display_name or page.display_name
                page.entry_fulfillment = copy.deepcopy(page_editable.entry_fulfillment)
                page.form = copy.deepcopy(page_editable.form)
                page.transition_routes = copy.deepcopy(page_editable.transition_routes)
                page.event_handlers = copy.deepcopy(page_editable.event_handlers)
                page.transition_route_groups = self._resolve_route_group_refs(
                    page_editable.route_group_ids,
                    workspace.transition_route_groups,
                    snapshot.agent.name,
                )

    def _apply_cx_intents(
        self,
        snapshot: CxAgentSnapshot,
        workspace: CxEditableWorkspace,
        original_workspace: CxEditableWorkspace,
    ) -> None:
        """Apply typed CX-native intent edits."""

        by_name = {intent.name: intent for intent in snapshot.intents}
        by_key = {
            _slug(intent.display_name or _resource_segment(intent.name)): intent
            for intent in snapshot.intents
        }

        for key, editable in workspace.intents.items():
            if not _entry_changed(editable, original_workspace.intents.get(key)):
                continue

            resource_name = editable.resource_name or f"{snapshot.agent.name}/intents/{key}"
            intent = by_name.get(resource_name) or by_key.get(key)
            if intent is None:
                intent = CxIntent(name=resource_name, display_name=editable.display_name or key)
                snapshot.intents.append(intent)
                by_name[resource_name] = intent
                by_key[key] = intent

            intent.display_name = editable.display_name or intent.display_name
            intent.description = editable.description
            intent.training_phrases = copy.deepcopy(editable.training_phrases)
            intent.parameters = copy.deepcopy(editable.parameters)
            intent.labels = dict(editable.labels)

    def _apply_cx_entity_types(
        self,
        snapshot: CxAgentSnapshot,
        workspace: CxEditableWorkspace,
        original_workspace: CxEditableWorkspace,
    ) -> None:
        """Apply typed CX-native entity-type edits."""

        by_name = {entity_type.name: entity_type for entity_type in snapshot.entity_types}
        by_key = {
            _slug(entity_type.display_name or _resource_segment(entity_type.name)): entity_type
            for entity_type in snapshot.entity_types
        }

        for key, editable in workspace.entity_types.items():
            if not _entry_changed(editable, original_workspace.entity_types.get(key)):
                continue

            resource_name = editable.resource_name or f"{snapshot.agent.name}/entityTypes/{key}"
            entity_type = by_name.get(resource_name) or by_key.get(key)
            if entity_type is None:
                entity_type = CxEntityType(name=resource_name, display_name=editable.display_name or key)
                snapshot.entity_types.append(entity_type)
                by_name[resource_name] = entity_type
                by_key[key] = entity_type

            entity_type.display_name = editable.display_name or entity_type.display_name
            entity_type.kind = editable.kind
            entity_type.auto_expansion_mode = editable.auto_expansion_mode
            entity_type.entities = copy.deepcopy(editable.entities)
            entity_type.excluded_phrases = list(editable.excluded_phrases)

    def _apply_cx_generators(
        self,
        snapshot: CxAgentSnapshot,
        workspace: CxEditableWorkspace,
        original_workspace: CxEditableWorkspace,
    ) -> None:
        """Apply typed CX-native generator edits."""

        by_name = {generator.name: generator for generator in snapshot.generators}
        by_key = {
            _slug(generator.display_name or _resource_segment(generator.name)): generator
            for generator in snapshot.generators
        }

        for key, editable in workspace.generators.items():
            if not _entry_changed(editable, original_workspace.generators.get(key)):
                continue

            resource_name = editable.resource_name or f"{snapshot.agent.name}/generators/{key}"
            generator = by_name.get(resource_name) or by_key.get(key)
            if generator is None:
                generator = CxGenerator(name=resource_name, display_name=editable.display_name or key)
                snapshot.generators.append(generator)
                by_name[resource_name] = generator
                by_key[key] = generator

            generator.display_name = editable.display_name or generator.display_name
            generator.prompt_text = editable.prompt_text
            generator.placeholders = copy.deepcopy(editable.placeholders)
            generator.llm_model_settings = copy.deepcopy(editable.llm_model_settings)

    def _apply_cx_webhook_contract(
        self,
        webhooks: list[CxWebhook],
        editable_webhooks: dict[str, CxEditableWebhook],
        original_webhooks: dict[str, CxEditableWebhook],
        agent_name: str,
    ) -> None:
        """Apply typed CX-native webhook edits."""

        by_name = {webhook.name: webhook for webhook in webhooks}
        by_key = {
            _slug(webhook.display_name or _resource_segment(webhook.name)): webhook
            for webhook in webhooks
        }

        for key, editable in editable_webhooks.items():
            if not _entry_changed(editable, original_webhooks.get(key)):
                continue

            resource_name = editable.resource_name or f"{agent_name}/webhooks/{key}"
            webhook = by_name.get(resource_name) or by_key.get(key)
            if webhook is None:
                webhook = CxWebhook(name=resource_name, display_name=editable.display_name or key)
                webhooks.append(webhook)
                by_name[resource_name] = webhook
                by_key[key] = webhook

            webhook.display_name = editable.display_name or webhook.display_name
            webhook.disabled = editable.disabled
            webhook.timeout_seconds = max(int(editable.timeout_ms) // 1000, 1)
            webhook.generic_web_service = copy.deepcopy(webhook.generic_web_service)
            webhook.generic_web_service["uri"] = editable.url
            webhook.generic_web_service["requestHeaders"] = dict(editable.headers)

    @staticmethod
    def _resolve_route_group_refs(
        route_group_ids: list[str],
        editable_route_groups: dict[str, CxEditableTransitionRouteGroup],
        agent_name: str,
    ) -> list[str]:
        """Resolve route-group ids in the editable contract back to resource names."""

        refs: list[str] = []
        for route_group_id in route_group_ids:
            if route_group_id in editable_route_groups:
                resource_name = editable_route_groups[route_group_id].resource_name
                if resource_name:
                    refs.append(resource_name)
                    continue
            if "/" in route_group_id:
                refs.append(route_group_id)
            else:
                refs.append(f"{agent_name}/transitionRouteGroups/{route_group_id}")
        return refs

    @staticmethod
    def _extract_model(generative_settings: dict[str, Any]) -> str | None:
        """Extract the configured model string from generative settings."""

        llm_settings = generative_settings.get("llmModelSettings")
        if isinstance(llm_settings, dict):
            model = llm_settings.get("model")
            if isinstance(model, str) and model:
                return model
        llm_settings = generative_settings.get("llm")
        if isinstance(llm_settings, dict):
            model = llm_settings.get("model")
            if isinstance(model, str) and model:
                return model
        return None

    @staticmethod
    def _extract_training_phrases(intent: CxIntent | None) -> list[str]:
        """Flatten training phrase parts into a keyword list."""

        if intent is None:
            return []
        phrases: list[str] = []
        for phrase in intent.training_phrases:
            parts = phrase.get("parts", [])
            text = "".join(str(part.get("text", "")) for part in parts).strip()
            if text:
                phrases.append(text)
        return phrases

    @staticmethod
    def _extract_user_message(conversation_turns: list[dict[str, Any]]) -> str:
        """Extract the last user utterance from a test case."""

        for turn in reversed(conversation_turns):
            user_input = turn.get("userInput", {})
            input_block = user_input.get("input", {})
            text_block = input_block.get("text", {})
            text = text_block.get("text")
            if isinstance(text, str) and text:
                return text
        return ""

    @staticmethod
    def _infer_expected_specialist(snapshot: CxAgentSnapshot) -> str:
        """Infer a reasonable expected specialist label for imported evals."""

        if snapshot.playbooks:
            return _slug(snapshot.playbooks[0].display_name or "root")
        if snapshot.flows:
            return _slug(snapshot.flows[0].display_name or "flow")
        return "support"


def jsonable_string(value: Any) -> str:
    """Serialize a value to a stable string for keyword extraction."""

    if isinstance(value, str):
        return value
    return str(value)
