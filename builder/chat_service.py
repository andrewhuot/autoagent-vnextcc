"""Conversational builder service backed by real generation/refinement helpers."""

from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any

import yaml

from builder.chat_types import (
    BuilderChatMessage,
    BuilderChatSession,
    BuilderConfigDraft,
    BuilderEvalCriterionDraft,
    BuilderEvalDraft,
    BuilderPolicyDraft,
    BuilderRoutingRuleDraft,
    BuilderToolDraft,
)
from builder.workspace_config import generated_config_to_yaml, persist_generated_config, preview_generated_config
from builder.types import now_ts
from optimizer.transcript_intelligence import TranscriptIntelligenceService
from shared.build_artifact_store import BuildArtifactStore


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "custom_tool"


class BuilderChatService:
    """Manage conversational builder sessions with truthful live/mock behavior."""

    def __init__(
        self,
        *,
        studio_service: TranscriptIntelligenceService | None = None,
        build_artifact_store: BuildArtifactStore | None = None,
    ) -> None:
        """Initialize the in-memory session store and shared dependencies."""
        self._sessions: dict[str, BuilderChatSession] = {}
        self._studio_service = studio_service or TranscriptIntelligenceService()
        self._build_artifact_store = build_artifact_store

    def handle_message(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        """Apply one conversational message to a builder session."""
        session = self._get_or_create_session(session_id)
        user_message = BuilderChatMessage(role="user", content=message.strip())
        session.messages.append(user_message)

        assistant_reply = self._apply_message(session, user_message.content)
        session.messages.append(BuilderChatMessage(role="assistant", content=assistant_reply))
        session.updated_at = now_ts()
        self._sessions[session.session_id] = session
        return self.serialize_session(session)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return serialized state for one builder session."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return self.serialize_session(session)

    def export_session(self, session_id: str, format_name: str = "yaml") -> dict[str, str] | None:
        """Serialize one builder config for download."""
        session = self._sessions.get(session_id)
        if session is None or session.generated_config is None:
            return None

        format_key = format_name.lower().strip()
        if format_key == "json":
            import json

            actual_config = yaml.safe_load(generated_config_to_yaml(session.generated_config)) or {}
            content = json.dumps(actual_config, indent=2)
            extension = "json"
        else:
            content = generated_config_to_yaml(
                session.generated_config,
                builder_session_id=session.session_id,
            )
            extension = "yaml"

        safe_name = _slugify(session.config.agent_name)
        return {
            "filename": f"{safe_name}.{extension}",
            "content": content,
            "content_type": "application/json" if extension == "json" else "application/x-yaml",
        }

    def save_session(self, session_id: str) -> dict[str, Any] | None:
        """Persist a builder session into the real workspace/versioning path."""
        session = self._sessions.get(session_id)
        if session is None or session.generated_config is None or self._build_artifact_store is None:
            return None
        saved = persist_generated_config(
            session.generated_config,
            artifact_store=self._build_artifact_store,
            source="builder_chat",
            builder_session_id=session.session_id,
        )
        return saved.to_dict()

    def preview_session(self, session_id: str, message: str) -> dict[str, Any] | None:
        """Run a sample message through the session's current generated config."""
        session = self._sessions.get(session_id)
        if session is None or session.generated_config is None:
            return None
        return preview_generated_config(session.generated_config, message).to_dict()

    def serialize_session(self, session: BuilderChatSession) -> dict[str, Any]:
        """Convert session state to the frontend-facing response shape."""
        return {
            "session_id": session.session_id,
            "mock_mode": session.mock_mode,
            "mock_reason": session.mock_reason,
            "messages": [asdict(message) for message in session.messages],
            "config": self._config_payload(session.config),
            "stats": {
                "tool_count": len(session.config.tools),
                "policy_count": len(session.config.policies),
                "routing_rule_count": len(session.config.routing_rules),
            },
            "evals": asdict(session.evals) if session.evals is not None else None,
            "updated_at": session.updated_at,
        }

    def _get_or_create_session(self, session_id: str | None) -> BuilderChatSession:
        """Return an existing session or create a new one."""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        session = BuilderChatSession()
        session.messages.append(
            BuilderChatMessage(
                role="assistant",
                content=(
                    "Describe the agent you want to build. I will draft the config, "
                    "update it as you refine the requirements, and keep the preview in sync."
                ),
            )
        )
        self._sessions[session.session_id] = session
        return session

    def _apply_message(self, session: BuilderChatSession, message: str) -> str:
        """Mutate the session config in response to one message."""
        normalized = message.lower()

        if "generate eval" in normalized or "run eval" in normalized:
            if session.generated_config is None:
                return "Start by describing the agent you want to build, then I can draft evals for it."
            session.evals = self._build_eval_draft(session.generated_config)
            return (
                f"Generated {session.evals.case_count} draft evals covering routing, policy compliance, "
                "and regression checks for the current build."
            )

        if session.generated_config is None:
            generated = self._studio_service.generate_agent_config(message)
            session.generated_config = generated
            session.config = self._draft_from_generated_config(generated)
            session.mock_mode = not bool(self._studio_service.last_generation_used_llm)
            session.mock_reason = self._mock_reason()
            return self._build_base_reply(session.config)

        refinement = self._studio_service.chat_refine(message, session.generated_config)
        session.generated_config = refinement["config"]
        session.config = self._draft_from_generated_config(refinement["config"])
        session.mock_mode = not bool(self._studio_service.last_refinement_used_llm)
        session.mock_reason = self._mock_reason()
        return str(refinement["response"] or "Updated the draft config.")

    def _mock_reason(self) -> str:
        """Return a stable user-facing reason when the studio is not using a live router."""
        generation_failure = str(
            getattr(self._studio_service, "last_generation_failure_reason", "") or ""
        ).strip()
        refinement_failure = str(
            getattr(self._studio_service, "last_refinement_failure_reason", "") or ""
        ).strip()
        if refinement_failure:
            return refinement_failure
        if generation_failure:
            return generation_failure
        router = getattr(self._studio_service, "_llm_router", None)
        if router is None:
            return "No configured builder LLM router is available."
        return str(getattr(router, "mock_reason", "") or "").strip()

    def _build_base_reply(self, config: BuilderConfigDraft) -> str:
        """Return the assistant reply for an initial config draft."""
        intents = ", ".join(rule.intent.replace("_", " ") for rule in config.routing_rules)
        return (
            f"I drafted `{config.agent_name}` using model `{config.model or 'default'}` with routing for {intents or 'general support'}. "
            "The preview now reflects the live draft config. You can refine tone, policies, tools, routing, or ask for evals."
        )

    def _build_eval_draft(self, generated_config: dict[str, Any]) -> BuilderEvalDraft:
        """Create an eval summary from the current generated config."""
        scenarios: list[dict[str, str]] = []

        for rule in generated_config.get("routing_rules", [])[:3]:
            if not isinstance(rule, dict):
                continue
            scenarios.append(
                {
                    "name": _slugify(str(rule.get("action") or rule.get("condition") or "routing_rule")),
                    "description": str(rule.get("condition") or rule.get("action") or "Validate routing behavior."),
                }
            )

        for policy in generated_config.get("policies", [])[:2]:
            if not isinstance(policy, dict):
                continue
            scenarios.append(
                {
                    "name": _slugify(str(policy.get("name") or "policy_check")),
                    "description": str(policy.get("description") or "Validate policy adherence."),
                }
            )

        if not scenarios:
            scenarios = [
                {
                    "name": "basic_response_quality",
                    "description": "Validate that the built agent answers clearly and safely.",
                }
            ]

        return BuilderEvalDraft(case_count=len(scenarios), scenarios=scenarios)

    def _draft_from_generated_config(self, generated_config: dict[str, Any]) -> BuilderConfigDraft:
        """Convert the studio contract into the builder-chat preview contract."""
        metadata = generated_config.get("metadata") if isinstance(generated_config.get("metadata"), dict) else {}
        return BuilderConfigDraft(
            agent_name=str(metadata.get("agent_name") or "AgentLab"),
            model=str(generated_config.get("model") or ""),
            system_prompt=str(generated_config.get("system_prompt") or ""),
            tools=[
                BuilderToolDraft(
                    name=str(tool.get("name") or "unnamed_tool"),
                    description=str(tool.get("description") or ""),
                    when_to_use=", ".join(tool.get("parameters") or []) or str(tool.get("description") or ""),
                )
                for tool in generated_config.get("tools", [])
                if isinstance(tool, dict)
            ],
            routing_rules=[
                BuilderRoutingRuleDraft(
                    name=_slugify(str(rule.get("action") or rule.get("condition") or "routing_rule")),
                    intent=str(rule.get("action") or "route"),
                    description=str(rule.get("condition") or ""),
                )
                for rule in generated_config.get("routing_rules", [])
                if isinstance(rule, dict)
            ],
            policies=[
                BuilderPolicyDraft(
                    name=str(policy.get("name") or "policy"),
                    description=str(policy.get("description") or ""),
                )
                for policy in generated_config.get("policies", [])
                if isinstance(policy, dict)
            ],
            eval_criteria=[
                BuilderEvalCriterionDraft(
                    name=str(criterion.get("name") or "eval"),
                    description=str(criterion.get("description") or ""),
                )
                for criterion in generated_config.get("eval_criteria", [])
                if isinstance(criterion, dict)
            ],
            metadata=copy_dict(metadata),
        )

    def _config_payload(self, config: BuilderConfigDraft) -> dict[str, Any]:
        """Return the frontend-facing builder preview config payload."""
        return {
            "agent_name": config.agent_name,
            "model": config.model,
            "system_prompt": config.system_prompt,
            "tools": [asdict(tool) for tool in config.tools],
            "routing_rules": [asdict(rule) for rule in config.routing_rules],
            "policies": [asdict(policy) for policy in config.policies],
            "eval_criteria": [asdict(criterion) for criterion in config.eval_criteria],
            "metadata": config.metadata,
        }


def copy_dict(value: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of metadata for dataclass construction."""
    return dict(value)
