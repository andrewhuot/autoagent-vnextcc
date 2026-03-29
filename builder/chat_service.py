"""Deterministic mock-mode service for conversational agent building."""

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
from builder.types import now_ts


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "custom_tool"


class BuilderChatService:
    """Manage conversational builder sessions in deterministic mock mode."""

    def __init__(self) -> None:
        """Initialize the in-memory session store."""
        self._sessions: dict[str, BuilderChatSession] = {}

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
        if session is None:
            return None

        config_payload = self._config_payload(session.config)
        format_key = format_name.lower().strip()
        if format_key == "json":
            import json

            content = json.dumps(config_payload, indent=2)
            extension = "json"
        else:
            content = yaml.safe_dump(config_payload, sort_keys=False)
            extension = "yaml"

        safe_name = _slugify(session.config.agent_name)
        return {
            "filename": f"{safe_name}.{extension}",
            "content": content,
            "content_type": "application/json" if extension == "json" else "application/x-yaml",
        }

    def serialize_session(self, session: BuilderChatSession) -> dict[str, Any]:
        """Convert session state to the frontend-facing response shape."""
        return {
            "session_id": session.session_id,
            "mock_mode": True,
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
            session.evals = self._build_eval_draft(session.config)
            return (
                f"Generated {session.evals.case_count} draft evals covering routing, policy compliance, "
                "and customer-tone regression checks."
            )

        if "add a tool" in normalized or "add tool" in normalized:
            tool = self._build_tool(message)
            if not any(existing.name == tool.name for existing in session.config.tools):
                session.config.tools.append(tool)
            return f"Added the `{tool.name}` tool and linked it to the preview config."

        if "add a policy" in normalized or "never reveal" in normalized or "policy" in normalized:
            policy = self._build_policy(message)
            if not any(existing.name == policy.name for existing in session.config.policies):
                session.config.policies.append(policy)
            return f"Added the policy `{policy.name}` to the guardrails section."

        if "empathetic" in normalized or "more empathy" in normalized:
            prompt = session.config.system_prompt
            if "empathetic" not in prompt.lower():
                session.config.system_prompt = (
                    "Lead with calm, empathetic language before moving into verification or action. "
                    + prompt
                ).strip()
            return "Updated the system prompt to make the agent more empathetic and reassuring."

        if "show me what this looks like" in normalized or "show preview" in normalized:
            return "The live preview shows the current draft config, including prompt, tools, routing rules, and policies."

        if not session.config.system_prompt or "build me" in normalized or "create" in normalized:
            session.config = self._build_base_config(message)
            return self._build_base_reply(session.config)

        return (
            "I updated the draft where I could. If you want a more precise change, ask to add a tool, "
            "adjust tone, add a policy, or generate evals."
        )

    def _build_base_config(self, message: str) -> BuilderConfigDraft:
        """Generate a deterministic base config from a high-level prompt."""
        lower = message.lower()
        domain = "airline" if "airline" in lower or "flight" in lower else "customer support"
        agent_name = "Airline Customer Support Agent" if domain == "airline" else "Customer Support Agent"

        routing_rules: list[BuilderRoutingRuleDraft] = []
        if any(term in lower for term in ("booking", "rebook", "change")):
            routing_rules.append(
                BuilderRoutingRuleDraft(
                    name="booking_changes",
                    intent="booking_change",
                    description="Handle itinerary changes, rebooking requests, and seat updates.",
                )
            )
        if any(term in lower for term in ("cancel", "cancellation", "refund")):
            routing_rules.append(
                BuilderRoutingRuleDraft(
                    name="cancellations",
                    intent="cancellation",
                    description="Handle cancellations, refund expectations, and waiver eligibility.",
                )
            )
        if any(term in lower for term in ("flight status", "status", "delay", "departure", "arrival")):
            routing_rules.append(
                BuilderRoutingRuleDraft(
                    name="flight_status",
                    intent="flight_status",
                    description="Handle delay checks, departure changes, and live flight-status questions.",
                )
            )

        if not routing_rules:
            routing_rules.append(
                BuilderRoutingRuleDraft(
                    name="general_support",
                    intent="general_support",
                    description="Handle standard customer-support questions and ask clarifying questions when needed.",
                )
            )

        policies = [
            BuilderPolicyDraft(
                name="verify_customer_context",
                description="Verify the traveler and reservation context before making booking changes.",
            ),
            BuilderPolicyDraft(
                name="escalate_irregular_operations",
                description="Escalate urgent disruption, safety, or compensation exceptions to a human agent.",
            ),
        ]

        system_prompt = (
            f"You are a {domain} support agent. Help customers with "
            + ", ".join(rule.description for rule in routing_rules)
            + " Keep responses clear, action-oriented, and grounded in policy."
        )

        eval_criteria = [
            BuilderEvalCriterionDraft(
                name="correct_routing",
                description="Requests should route to the correct workflow based on customer intent.",
            ),
            BuilderEvalCriterionDraft(
                name="policy_compliance",
                description="The agent should verify account or reservation context before making sensitive changes.",
            ),
            BuilderEvalCriterionDraft(
                name="customer_tone",
                description="Responses should sound calm, concise, and helpful under stress.",
            ),
        ]

        return BuilderConfigDraft(
            agent_name=agent_name,
            system_prompt=system_prompt,
            routing_rules=routing_rules,
            policies=policies,
            eval_criteria=eval_criteria,
            metadata={"source_prompt": message},
        )

    def _build_base_reply(self, config: BuilderConfigDraft) -> str:
        """Return the assistant reply for an initial config draft."""
        intents = ", ".join(rule.intent.replace("_", " ") for rule in config.routing_rules)
        return (
            f"I drafted `{config.agent_name}` with routing for {intents}. "
            "The preview now includes a base system prompt, default guardrails, and eval criteria. "
            "You can ask me to add tools, adjust tone, add policies, or generate evals."
        )

    def _build_tool(self, message: str) -> BuilderToolDraft:
        """Build a deterministic tool definition from a user request."""
        lower = message.lower()
        if "flight status" in lower:
            return BuilderToolDraft(
                name="flight_status_lookup",
                description="Fetch current departure, arrival, delay, and gate information for a flight.",
                when_to_use="Use when a traveler asks where a flight is, whether it is delayed, or when it lands.",
            )
        if "booking" in lower or "reservation" in lower:
            return BuilderToolDraft(
                name="reservation_manager",
                description="Fetch and update booking records for verified travelers.",
                when_to_use="Use when a traveler wants to change, confirm, or review an itinerary.",
            )

        suffix = message.split("for", 1)[-1].strip(" .")
        name = _slugify(suffix)
        return BuilderToolDraft(
            name=name,
            description=f"Handle {suffix}.",
            when_to_use=f"Use when the customer asks about {suffix}.",
        )

    def _build_policy(self, message: str) -> BuilderPolicyDraft:
        """Build a policy draft from a user message."""
        description = message.strip().rstrip(".")
        if "internal codes" in description.lower():
            return BuilderPolicyDraft(
                name="no_internal_codes",
                description="Never reveal internal codes, internal remarks, or back-office annotations to customers.",
            )

        normalized = description.removeprefix("Add a policy that").strip()
        return BuilderPolicyDraft(
            name=_slugify(normalized)[:48],
            description=normalized[:1].upper() + normalized[1:],
        )

    def _build_eval_draft(self, config: BuilderConfigDraft) -> BuilderEvalDraft:
        """Create a plausible mock eval bundle for the current config."""
        scenarios = [
            {
                "name": "booking_change_routing",
                "description": "Verify booking-change requests route to the correct workflow and preserve traveler context.",
            },
            {
                "name": "flight_status_tool_use",
                "description": "Verify live flight-status requests trigger the correct lookup tool when available.",
            },
            {
                "name": "internal_code_guardrail",
                "description": "Verify the agent refuses to reveal internal codes or hidden operational notes.",
            },
        ]
        if "empathetic" in config.system_prompt.lower():
            scenarios.append(
                {
                    "name": "high_stress_tone",
                    "description": "Verify disrupted-travel responses stay calm, empathetic, and action oriented.",
                }
            )
        return BuilderEvalDraft(case_count=len(scenarios), scenarios=scenarios)

    def _config_payload(self, config: BuilderConfigDraft) -> dict[str, Any]:
        """Return the frontend-facing config payload."""
        return {
            "agent_name": config.agent_name,
            "system_prompt": config.system_prompt,
            "tools": [asdict(tool) for tool in config.tools],
            "routing_rules": [asdict(rule) for rule in config.routing_rules],
            "policies": [asdict(policy) for policy in config.policies],
            "eval_criteria": [asdict(criterion) for criterion in config.eval_criteria],
            "metadata": config.metadata,
        }
