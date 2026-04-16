"""LLM-driven proposal generation with structured prompts and validation.

Replaces the thin _llm_propose path in proposer.py with a full-featured
proposer that leverages Agent Cards, failure analysis, and past attempts
to generate targeted, validated configuration changes via LLM.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agent_card.converter import from_config_dict
from agent_card.renderer import render_to_markdown
from agent_card.schema import AgentCardModel

from .mutations import MutationRegistry, MutationSurface
from .proposer import Proposal
from .providers import LLMRequest, LLMRouter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid mutation type names (derived from MutationSurface enum)
# ---------------------------------------------------------------------------

_VALID_MUTATION_TYPES: frozenset[str] = frozenset(m.value for m in MutationSurface)

_MUTATION_DESCRIPTIONS: dict[str, str] = {
    "instruction": "Rewrite system prompts that define agent behavior",
    "few_shot": "Add or modify few-shot examples for in-context learning",
    "tool_description": "Modify tool configurations (timeout, description, parameters)",
    "model": "Change the underlying LLM model powering the agent",
    "generation_settings": "Adjust temperature, max_tokens, top_p, top_k",
    "callback": "Modify lifecycle hooks (before/after model, agent, tool calls)",
    "context_caching": "Adjust context caching thresholds and TTL",
    "memory_policy": "Adjust memory preload/writeback policy",
    "routing": "Modify routing rules and keyword mappings for sub-agent dispatch",
    "workflow": "Edit workflow orchestration (step order, parallelism, fallbacks)",
    "skill": "Rewrite a skill's instructions or metadata",
    "policy": "Edit behavioral constraint or operational policy rules",
    "tool_contract": "Edit a tool contract's schema or replay settings",
    "handoff_schema": "Edit handoff schema fields or validation rules between agents",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProposalCandidate:
    """A single proposed change from the LLM."""

    mutation_type: str
    target_agent: str
    target_surface: str
    change_description: str
    reasoning: str
    config_patch: dict[str, Any]
    expected_impact: str
    risk_assessment: str


@dataclass
class ProposalResult:
    """Result of LLM proposal generation."""

    candidates: list[ProposalCandidate]
    analysis_summary: str
    confidence: float
    model_used: str


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert AI agent optimizer. You analyze agent failures and propose \
targeted configuration changes.

You understand that agents are composed of multiple surfaces:
- Instructions: System prompts that define agent behavior
- Tools: External capabilities (APIs, databases) with parameters and timeouts
- Callbacks: Lifecycle hooks (before/after model, agent, tool calls)
- Routing Rules: How messages are dispatched to sub-agents
- Guardrails: Safety and quality gates on input/output
- Policies: Behavioral constraints
- Generation Settings: Temperature, max_tokens, etc.
- Model Selection: Which LLM powers the agent
- Few-Shot Examples: In-context learning demonstrations
- Context Caching: Token caching thresholds and TTL
- Memory Policy: Preload/writeback behavior
- Skills: Reusable capability definitions
- Tool Contracts: Schema and replay settings for tools
- Handoff Schemas: Transfer-of-control field definitions between agents
- Workflows: Step ordering, parallelism, and fallback policies

You know that agents can have sub-agents in a hierarchy, and changes should \
target the specific agent/surface where the failure originates.

RULES:
1. Propose ONE focused, high-leverage change per request.
2. Target the root cause, not symptoms.
3. Prefer low-risk changes (instruction rewrites) over high-risk (model swaps).
4. Never remove safety guardrails.
5. Respect immutable surfaces listed in constraints.
6. Include the complete modified section in your config_patch, not just the delta.
7. The config_patch must be a valid partial config dict that can be deep-merged \
into the current config.
8. If targeting a sub-agent, set target_agent to that sub-agent's name; \
otherwise use "root".

Respond with ONLY a JSON object in the following format (no markdown, no prose):
{
    "proposal": {
        "mutation_type": "<one of the available mutation types>",
        "target_agent": "<root or sub-agent name>",
        "target_surface": "<specific surface being changed>",
        "change_description": "<concise description of the change>",
        "reasoning": "<why this change addresses the root cause>",
        "config_patch": { <partial config dict with the change> },
        "expected_impact": "<high|medium|low>",
        "risk_assessment": "<low|medium|high>"
    },
    "analysis_summary": "<brief summary of the failure analysis>",
    "confidence": <float between 0 and 1>,
    "alternative_proposals": []
}"""


def _build_user_prompt(
    *,
    agent_card_markdown: str,
    failure_analysis: dict[str, Any] | None,
    past_attempts: list[dict[str, Any]] | None,
    objective: str | None,
    constraints: dict[str, Any] | None,
    available_mutations: list[dict[str, str]],
    coverage_signal: list[tuple[str, str, int]] | None = None,
) -> str:
    """Assemble the structured user prompt with all context sections."""
    sections: list[str] = []

    # -- Agent Card --
    sections.append("## Current Agent Definition\n")
    sections.append(agent_card_markdown)
    sections.append("")

    # -- Failure Analysis --
    sections.append("## Failure Analysis\n")
    if failure_analysis:
        clusters = failure_analysis.get("clusters", [])
        if clusters:
            sections.append("### Failure Clusters")
            for cluster in clusters[:10]:
                cluster_id = cluster.get("id", "unknown")
                count = cluster.get("count", 0)
                surface = cluster.get("recommended_surface", "unknown")
                summary = cluster.get("summary", "")
                sections.append(
                    f"- **{cluster_id}** ({count} failures): {summary} "
                    f"[recommended surface: {surface}]"
                )
            sections.append("")

        surface_recs = failure_analysis.get("surface_recommendations", {})
        if surface_recs:
            sections.append("### Surface Recommendations")
            for surface, detail in surface_recs.items():
                sections.append(f"- **{surface}**: {detail}")
            sections.append("")

        summary = failure_analysis.get("summary", "")
        if summary:
            sections.append(f"### Summary\n{summary}\n")
    else:
        sections.append("No failure analysis available.\n")

    # -- Coverage Gaps --
    if coverage_signal:
        sections.append("## Eval Coverage Gaps\n")
        sections.append(
            "These surfaces have under-tested components — prefer proposals that "
            "improve behavior on them:\n"
        )
        for surface, severity, delta in coverage_signal:
            sections.append(
                f"- [{severity.upper()}] {surface}: {delta} cases short of target"
            )
        sections.append("")

    # -- Past Attempts --
    sections.append("## Past Optimization Attempts (most recent first)\n")
    if past_attempts:
        for attempt in past_attempts[:10]:
            desc = attempt.get("change_description", attempt.get("description", "N/A"))
            section = attempt.get("config_section", "N/A")
            outcome = attempt.get("outcome", "unknown")
            score_delta = attempt.get("score_delta", "N/A")
            sections.append(
                f"- [{outcome}] {desc} (section: {section}, "
                f"score delta: {score_delta})"
            )
        sections.append("")
    else:
        sections.append("No previous attempts.\n")

    # -- Objective --
    sections.append("## Optimization Objective\n")
    sections.append(objective or "Maximize overall agent quality and reliability.")
    sections.append("")

    # -- Constraints --
    sections.append("## Constraints\n")
    if constraints:
        immutable = constraints.get("immutable_surfaces", [])
        if immutable:
            sections.append(
                f"**Immutable surfaces (DO NOT modify):** {', '.join(immutable)}"
            )
        max_risk = constraints.get("max_risk")
        if max_risk:
            sections.append(f"**Maximum risk level:** {max_risk}")
        budget = constraints.get("budget")
        if budget:
            sections.append(f"**Budget constraint:** {budget}")
        sections.append("")
    else:
        sections.append("No additional constraints.\n")

    # -- Available Mutations --
    sections.append("## Available Mutation Types\n")
    for mut in available_mutations:
        sections.append(f"- **{mut['type']}**: {mut['description']}")
    sections.append("")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# LLMProposer
# ---------------------------------------------------------------------------


class LLMProposer:
    """Generate intelligent, validated proposals via LLM.

    Uses structured prompts built from the Agent Card, failure analysis,
    and optimization history to produce targeted configuration changes.
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        mutation_registry: MutationRegistry | None = None,
    ) -> None:
        self.llm_router = llm_router
        self.mutation_registry = mutation_registry

    # ----- public API -----

    def propose(
        self,
        current_config: dict[str, Any],
        agent_card_markdown: str,
        failure_analysis: dict[str, Any] | None = None,
        past_attempts: list[dict[str, Any]] | None = None,
        objective: str | None = None,
        constraints: dict[str, Any] | None = None,
        coverage_signal: list[tuple[str, str, int]] | None = None,
    ) -> Proposal | None:
        """Generate an LLM-driven proposal.

        1. Build structured prompt with agent card, failures, history.
        2. Call LLM via the router.
        3. Parse and validate the response.
        4. Convert the best candidate to a ``Proposal``.

        Returns ``None`` when the LLM response is unparseable or invalid.
        """
        # 1. Build prompt
        available_mutations = self._available_mutations(constraints)
        user_prompt = _build_user_prompt(
            agent_card_markdown=agent_card_markdown,
            failure_analysis=failure_analysis,
            past_attempts=past_attempts,
            objective=objective,
            constraints=constraints,
            available_mutations=available_mutations,
            coverage_signal=coverage_signal,
        )

        # 2. Call LLM
        request = LLMRequest(
            system=_SYSTEM_PROMPT,
            prompt=user_prompt,
            temperature=0.4,
            max_tokens=2000,
            metadata={"task": "llm_proposer"},
        )

        try:
            response = self.llm_router.generate(request)
        except Exception:
            logger.exception("LLM call failed in LLMProposer.propose")
            return None

        # 3. Parse
        parsed = self._extract_json(response.text)
        if parsed is None:
            logger.warning("LLMProposer: failed to parse JSON from LLM response")
            return None

        # 4. Validate and convert
        card = self._parse_agent_card(current_config)
        candidate = self._validate_candidate(parsed, card, constraints)
        if candidate is None:
            return None

        # 5. Deep-merge config_patch into current config
        new_config = _deep_merge(
            copy.deepcopy(current_config), candidate.config_patch
        )

        model_used = getattr(response, "model", "unknown")

        return Proposal(
            change_description=candidate.change_description,
            config_section=candidate.target_surface,
            new_config=new_config,
            reasoning=candidate.reasoning,
            patch_bundle=None,
        )

    # ----- prompt helpers -----

    def _available_mutations(
        self, constraints: dict[str, Any] | None
    ) -> list[dict[str, str]]:
        """Return mutation type list, excluding immutable surfaces."""
        immutable: set[str] = set()
        if constraints:
            immutable = set(constraints.get("immutable_surfaces", []))

        result: list[dict[str, str]] = []
        for mt in sorted(_VALID_MUTATION_TYPES):
            if mt in immutable:
                continue
            result.append({
                "type": mt,
                "description": _MUTATION_DESCRIPTIONS.get(mt, ""),
            })
        return result

    # ----- parsing helpers -----

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Parse the first JSON object from raw LLM output."""
        raw = text.strip()
        if not raw:
            return None

        # Try direct parse first
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Try stripping markdown code fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE).strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Regex fallback: extract first { ... }
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        return None

    # ----- validation helpers -----

    @staticmethod
    def _parse_agent_card(config: dict[str, Any]) -> AgentCardModel:
        """Build an AgentCardModel from the current config for validation."""
        return from_config_dict(config, name=config.get("name", "root"))

    @staticmethod
    def _validate_candidate(
        parsed: dict[str, Any],
        card: AgentCardModel,
        constraints: dict[str, Any] | None,
    ) -> ProposalCandidate | None:
        """Extract and validate a ProposalCandidate from parsed LLM JSON."""
        proposal_data = parsed.get("proposal")
        if not isinstance(proposal_data, dict):
            logger.warning("LLMProposer: response missing 'proposal' key")
            return None

        # Required fields
        mutation_type = str(proposal_data.get("mutation_type") or "")
        target_agent = str(proposal_data.get("target_agent") or "root")
        target_surface = str(proposal_data.get("target_surface") or mutation_type)
        change_description = str(proposal_data.get("change_description") or "")
        reasoning = str(proposal_data.get("reasoning") or "")
        config_patch = proposal_data.get("config_patch")
        expected_impact = str(proposal_data.get("expected_impact") or "medium")
        risk_assessment = str(proposal_data.get("risk_assessment") or "medium")

        # Validate mutation_type
        if mutation_type not in _VALID_MUTATION_TYPES:
            logger.warning(
                "LLMProposer: invalid mutation_type %r (valid: %s)",
                mutation_type,
                ", ".join(sorted(_VALID_MUTATION_TYPES)),
            )
            return None

        # Validate config_patch is a dict
        if not isinstance(config_patch, dict):
            logger.warning("LLMProposer: config_patch is not a dict")
            return None

        # Validate change_description is present
        if not change_description:
            logger.warning("LLMProposer: empty change_description")
            return None

        # Validate target_agent exists in card
        known_agents = set(card.all_agent_names())
        if target_agent != "root" and target_agent not in known_agents:
            logger.warning(
                "LLMProposer: target_agent %r not found in agent hierarchy %s",
                target_agent,
                sorted(known_agents),
            )
            return None

        # Validate immutable surface constraints
        if constraints:
            immutable = set(constraints.get("immutable_surfaces", []))
            if mutation_type in immutable:
                logger.warning(
                    "LLMProposer: mutation_type %r targets an immutable surface",
                    mutation_type,
                )
                return None

        # Validate expected_impact / risk_assessment values
        if expected_impact not in ("high", "medium", "low"):
            expected_impact = "medium"
        if risk_assessment not in ("low", "medium", "high"):
            risk_assessment = "medium"

        return ProposalCandidate(
            mutation_type=mutation_type,
            target_agent=target_agent,
            target_surface=target_surface,
            change_description=change_description,
            reasoning=reasoning,
            config_patch=config_patch,
            expected_impact=expected_impact,
            risk_assessment=risk_assessment,
        )


# ---------------------------------------------------------------------------
# Utility: deep merge
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *patch* into *base*, returning the mutated *base*.

    For nested dicts, merging is recursive.  All other types are overwritten.
    """
    for key, value in patch.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
