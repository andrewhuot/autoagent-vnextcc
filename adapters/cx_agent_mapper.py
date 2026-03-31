"""Bidirectional mapping between Dialogflow CX snapshots and AutoAgent workspaces."""

from __future__ import annotations

import copy
import re
from typing import Any

from adapters.base import ImportedAgentSpec, keyword_candidates
from cx_studio.errors import CxMappingError
from cx_studio.types import (
    CxAgentSnapshot,
    CxEntityType,
    CxFlow,
    CxIntent,
    CxPlaybook,
    CxTool,
    CxWebhook,
)


def _slug(value: str) -> str:
    """Convert a display label into a stable config key."""

    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or "default"


class CxAgentMapper:
    """Pure mapping logic for CX snapshots and AutoAgent workspace configs."""

    def cx_to_workspace(self, snapshot: CxAgentSnapshot) -> ImportedAgentSpec:
        """Convert a CX snapshot into an imported AutoAgent workspace spec."""

        config = self.to_autoagent(snapshot)
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

    def to_autoagent(self, snapshot: CxAgentSnapshot) -> dict[str, Any]:
        """Convert a CX snapshot to an AutoAgent-compatible config dictionary."""

        try:
            prompts = self._map_prompts(snapshot)
            tools = self._map_tools(snapshot.webhooks, snapshot.tools)
            routing = self._map_routing(snapshot.flows, snapshot.intents)

            config: dict[str, Any] = {
                "prompts": prompts,
                "tools": tools,
                "routing": routing,
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
                    "intents": [intent.model_dump() for intent in snapshot.intents],
                },
            }

            model = self._extract_model(snapshot.agent.generative_settings)
            if model:
                config["model"] = model

            return config
        except Exception as exc:  # pragma: no cover - guarded by tests
            raise CxMappingError(f"Failed to map CX snapshot to AutoAgent config: {exc}") from exc

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

            self._apply_prompts(result, prompts)
            self._apply_webhooks(result.webhooks, tools)

            if "model" in config:
                result.agent.generative_settings = copy.deepcopy(result.agent.generative_settings)
                llm_settings = result.agent.generative_settings.setdefault("llmModelSettings", {})
                llm_settings["model"] = config["model"]

            return result
        except Exception as exc:  # pragma: no cover - guarded by tests
            raise CxMappingError(f"Failed to map AutoAgent workspace back to CX: {exc}") from exc

    def to_cx(self, config: dict[str, Any], base_snapshot: CxAgentSnapshot) -> CxAgentSnapshot:
        """Compatibility alias for existing importer/exporter code."""

        return self.workspace_to_cx(config, base_snapshot)

    def extract_test_cases(self, snapshot: CxAgentSnapshot) -> list[dict[str, Any]]:
        """Convert CX test cases into AutoAgent starter eval cases."""

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
        """Map Dialogflow CX webhooks and tools into AutoAgent tool entries."""

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
