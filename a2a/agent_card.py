"""Agent card generation for A2A protocol discovery.

Generates /.well-known/agent-card.json descriptors that allow external
agents and orchestrators to discover capabilities and skills.
"""

from __future__ import annotations

from typing import Any, Optional

from a2a.types import AgentCapabilities, AgentCard, AgentSkill


# ---------------------------------------------------------------------------
# Built-in archetype definitions
# ---------------------------------------------------------------------------

_ARCHETYPES: dict[str, dict[str, Any]] = {
    "optimizer": {
        "name": "AutoAgent Optimizer",
        "description": (
            "Continuously improves agent configurations through "
            "experiment-driven optimization cycles."
        ),
        "version": "1.0",
        "skills": [
            {
                "id": "run_optimization",
                "name": "Run Optimization Cycle",
                "description": "Execute a full optimization loop iteration.",
                "tags": ["optimization", "experiments", "eval"],
                "examples": ["Run the next optimization cycle"],
            },
            {
                "id": "compare_variants",
                "name": "Compare Variants",
                "description": "Compare two or more candidate agent variants on eval metrics.",
                "tags": ["evaluation", "comparison"],
                "examples": ["Compare variant A vs B on task_success_rate"],
            },
        ],
    },
    "evaluator": {
        "name": "AutoAgent Evaluator",
        "description": "Runs evaluation suites and reports graded results.",
        "version": "1.0",
        "skills": [
            {
                "id": "run_eval",
                "name": "Run Eval Suite",
                "description": "Execute an eval suite and return graded results.",
                "tags": ["eval", "grading", "testing"],
                "examples": ["Run the contract_regression eval suite"],
            },
            {
                "id": "grade_response",
                "name": "Grade Agent Response",
                "description": "Grade a single agent response against expected criteria.",
                "tags": ["grading", "llm_judge"],
                "examples": ["Grade this response for groundedness"],
            },
        ],
    },
    "assistant": {
        "name": "AutoAgent Assistant",
        "description": "General-purpose agent assistant for conversational tasks.",
        "version": "1.0",
        "skills": [
            {
                "id": "answer_question",
                "name": "Answer Question",
                "description": "Answer user questions using available knowledge and tools.",
                "tags": ["qa", "general"],
                "examples": ["What is the current optimization status?"],
            },
        ],
    },
}


class AgentCardGenerator:
    """Generates A2A-compliant agent cards for AutoAgent agents."""

    def generate_card(
        self,
        agent_name: str,
        agent_config: dict[str, Any],
        base_url: str,
        skills: Optional[list[AgentSkill]] = None,
    ) -> AgentCard:
        """Build an AgentCard from an agent name, config dict, and base URL.

        Args:
            agent_name: Human-readable agent name.
            agent_config: Arbitrary config dict from the agent's registry entry.
            base_url: Public base URL where this agent is reachable.
            skills: Optional explicit list of AgentSkill objects. When omitted,
                    skills are inferred from ``agent_config``.

        Returns:
            A fully-populated AgentCard.
        """
        description = agent_config.get(
            "description", f"AutoAgent: {agent_name}"
        )
        version = agent_config.get("version", "1.0")

        caps_cfg = agent_config.get("capabilities", {})
        capabilities = AgentCapabilities(
            streaming=caps_cfg.get("streaming", True),
            push_notifications=caps_cfg.get("push_notifications", False),
            state_transition_history=caps_cfg.get("state_transition_history", True),
        )

        if skills is None:
            skills = self._infer_skills(agent_name, agent_config)

        url = base_url.rstrip("/")

        return AgentCard(
            name=agent_name,
            description=description,
            url=url,
            version=version,
            capabilities=capabilities,
            skills=skills,
            default_input_modes=agent_config.get("input_modes", ["text"]),
            default_output_modes=agent_config.get("output_modes", ["text"]),
            metadata=agent_config.get("metadata", {}),
        )

    def card_to_json(self, card: AgentCard) -> dict[str, Any]:
        """Serialise an AgentCard for serving at /.well-known/agent-card.json."""
        return card.to_dict()

    def generate_from_archetype(
        self, archetype_id: str, base_url: str
    ) -> AgentCard:
        """Create an AgentCard from a built-in archetype template.

        Args:
            archetype_id: One of ``optimizer``, ``evaluator``, ``assistant``.
            base_url: Public base URL for the agent.

        Returns:
            A pre-populated AgentCard.

        Raises:
            ValueError: If ``archetype_id`` is not recognised.
        """
        template = _ARCHETYPES.get(archetype_id)
        if template is None:
            known = ", ".join(sorted(_ARCHETYPES))
            raise ValueError(
                f"Unknown archetype '{archetype_id}'. Known archetypes: {known}"
            )

        skills = [AgentSkill.from_dict(s) for s in template.get("skills", [])]

        return AgentCard(
            name=template["name"],
            description=template["description"],
            url=base_url.rstrip("/"),
            version=template.get("version", "1.0"),
            capabilities=AgentCapabilities(),
            skills=skills,
            default_input_modes=["text"],
            default_output_modes=["text"],
            metadata={"archetype": archetype_id},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _infer_skills(
        self, agent_name: str, agent_config: dict[str, Any]
    ) -> list[AgentSkill]:
        """Derive AgentSkill list from config when none is explicitly given."""
        raw_skills = agent_config.get("skills", [])
        if raw_skills:
            return [
                AgentSkill.from_dict(s) if isinstance(s, dict) else s
                for s in raw_skills
            ]

        # Fallback: single generic skill named after the agent
        safe_id = agent_name.lower().replace(" ", "_")
        return [
            AgentSkill(
                id=safe_id,
                name=agent_name,
                description=agent_config.get(
                    "description", f"Invoke the {agent_name} agent."
                ),
                tags=[safe_id],
                examples=[],
            )
        ]
