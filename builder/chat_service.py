"""Conversational builder service backed by real generation/refinement helpers.

Chat sessions are persisted to SQLite so they survive server restarts.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import re
import sqlite3
from pathlib import Path
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
    """Manage conversational builder sessions with truthful live/mock behavior.

    Sessions are persisted to a SQLite database so they survive server
    restarts.  On startup, previously-saved sessions are loaded back into
    memory for fast access.
    """

    def __init__(
        self,
        *,
        studio_service: TranscriptIntelligenceService | None = None,
        build_artifact_store: BuildArtifactStore | None = None,
        db_path: str = ".agentlab/builder_chat_sessions.db",
    ) -> None:
        """Initialize the session store and shared dependencies."""
        self._sessions: dict[str, BuilderChatSession] = {}
        self._studio_service = studio_service or TranscriptIntelligenceService()
        self._build_artifact_store = build_artifact_store
        self._db_path = db_path
        self._init_db()
        self._load_persisted_sessions()

    # ------------------------------------------------------------------
    # SQLite persistence
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the chat_sessions table if it does not exist."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload    TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
                ON chat_sessions (updated_at DESC)
            """)

    def _load_persisted_sessions(self) -> None:
        """Load saved sessions from the database on startup."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()

        for row in rows:
            try:
                session = _deserialize_session(row["payload"])
                if session is not None:
                    self._sessions[session.session_id] = session
            except Exception:
                continue

    def _persist_session(self, session: BuilderChatSession) -> None:
        """Write or update a session row in the database."""
        payload = _serialize_session(session)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO chat_sessions (session_id, created_at, updated_at, payload)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       updated_at = excluded.updated_at,
                       payload = excluded.payload
                """,
                (session.session_id, session.created_at, session.updated_at, payload),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_message(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        """Apply one conversational message to a builder session."""
        session = self._get_or_create_session(session_id)
        user_message = BuilderChatMessage(role="user", content=message.strip())
        session.messages.append(user_message)

        assistant_reply = self._apply_message(session, user_message.content)
        session.messages.append(BuilderChatMessage(role="assistant", content=assistant_reply))
        session.updated_at = now_ts()
        self._sessions[session.session_id] = session
        self._persist_session(session)
        return self.serialize_session(session)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return serialized state for one builder session."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return self.serialize_session(session)

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return a summary list of recent chat sessions."""
        sessions = sorted(
            self._sessions.values(),
            key=lambda s: s.updated_at,
            reverse=True,
        )[:limit]
        return [
            {
                "session_id": s.session_id,
                "agent_name": s.config.agent_name,
                "message_count": len(s.messages),
                "mock_mode": s.mock_mode,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in sessions
        ]

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
        self._persist_session(session)
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


# ------------------------------------------------------------------
# Serialization helpers for session persistence
# ------------------------------------------------------------------

def _serialize_session(session: BuilderChatSession) -> str:
    """Serialize a session to JSON for database storage."""
    data = {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": [asdict(m) for m in session.messages],
        "config": asdict(session.config),
        "generated_config": session.generated_config,
        "mock_mode": session.mock_mode,
        "mock_reason": session.mock_reason,
        "evals": asdict(session.evals) if session.evals else None,
    }
    return json.dumps(data, default=str)


def _deserialize_session(raw: str) -> BuilderChatSession | None:
    """Reconstruct a session from its JSON representation."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None

    session = BuilderChatSession.__new__(BuilderChatSession)
    session.session_id = data["session_id"]
    session.created_at = data["created_at"]
    session.updated_at = data["updated_at"]
    session.mock_mode = data.get("mock_mode", True)
    session.mock_reason = data.get("mock_reason", "")
    session.generated_config = data.get("generated_config")

    session.messages = [
        BuilderChatMessage(
            message_id=m.get("message_id", ""),
            role=m.get("role", "assistant"),
            content=m.get("content", ""),
            created_at=m.get("created_at", 0.0),
        )
        for m in data.get("messages", [])
    ]

    cfg = data.get("config", {})
    session.config = BuilderConfigDraft(
        agent_name=cfg.get("agent_name", "Customer Support Agent"),
        model=cfg.get("model", ""),
        system_prompt=cfg.get("system_prompt", ""),
        tools=[
            BuilderToolDraft(name=t["name"], description=t["description"], when_to_use=t.get("when_to_use", ""))
            for t in cfg.get("tools", []) if isinstance(t, dict)
        ],
        routing_rules=[
            BuilderRoutingRuleDraft(name=r["name"], intent=r["intent"], description=r.get("description", ""))
            for r in cfg.get("routing_rules", []) if isinstance(r, dict)
        ],
        policies=[
            BuilderPolicyDraft(name=p["name"], description=p.get("description", ""))
            for p in cfg.get("policies", []) if isinstance(p, dict)
        ],
        eval_criteria=[
            BuilderEvalCriterionDraft(name=e["name"], description=e.get("description", ""))
            for e in cfg.get("eval_criteria", []) if isinstance(e, dict)
        ],
        metadata=cfg.get("metadata", {}),
    )

    evals_data = data.get("evals")
    if evals_data and isinstance(evals_data, dict):
        session.evals = BuilderEvalDraft(
            case_count=evals_data.get("case_count", 0),
            scenarios=evals_data.get("scenarios", []),
        )
    else:
        session.evals = None

    return session


def copy_dict(value: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of metadata for dataclass construction."""
    return dict(value)
