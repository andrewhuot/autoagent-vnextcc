"""LLM-based config change proposer with deterministic mock."""

from __future__ import annotations

import copy
import json
import random
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from shared.canonical_ir_convert import from_config_dict
from shared.canonical_patch import ComponentPatchOperation, TypedPatchBundle, find_component_reference

from .providers import LLMRequest, LLMRouter

if TYPE_CHECKING:
    from .reflection import ReflectionEngine

# Strategy -> mutation-surface mapping. Used by _rank_strategies to look up
# historical effectiveness on the surface a strategy targets. Seed mapping;
# extend as new strategies are registered.
STRATEGY_TO_SURFACE: dict[str, str] = {
    "tighten_prompt": "prompting",
    "add_tool": "tools",
    "refactor": "architecture",
    "expand_card": "agent_card",
}

_ROUTING_STOP_WORDS = {
    "and",
    "about",
    "actual",
    "agent",
    "behavior",
    "check",
    "details",
    "evals",
    "expected",
    "failed",
    "flag",
    "for",
    "generate",
    "got",
    "keywords",
    "missing",
    "probe",
    "recommendations",
    "response",
    "routing",
    "safety",
    "should",
    "support",
    "tool",
    "this",
    "use",
    "orders",
}


def _flatten_component_attributions(failure_samples: list[dict]) -> list[dict]:
    """Collect component-attribution payloads from optimizer failure samples."""
    attributions: list[dict] = []
    for sample in failure_samples:
        raw_attributions = sample.get("component_attributions", [])
        if isinstance(raw_attributions, dict):
            attributions.append(dict(raw_attributions))
        elif isinstance(raw_attributions, list):
            attributions.extend(
                dict(item)
                for item in raw_attributions
                if isinstance(item, dict)
            )
    return attributions


@dataclass
class Proposal:
    change_description: str
    config_section: str  # which section of config was changed
    new_config: dict  # the full modified config
    reasoning: str
    patch_bundle: dict | None = None


class Proposer:
    """Proposes config changes using LLM (or mock)."""

    def __init__(
        self,
        use_mock: bool = False,
        llm_router: LLMRouter | None = None,
        mock_reason: str = "",
    ) -> None:
        self.use_mock = use_mock
        self.llm_router = llm_router
        self.mock_reason = mock_reason

    def propose(
        self,
        current_config: dict,
        health_metrics: dict,
        failure_samples: list[dict],
        failure_buckets: dict[str, int],
        past_attempts: list[dict],
        *,
        optimization_mode: str | None = None,
        objective: str | None = None,
        guardrails: list[str] | None = None,
        project_memory_context: dict[str, list[str]] | None = None,
    ) -> Proposal | None:
        if self.use_mock:
            return self._mock_propose(
                current_config,
                health_metrics,
                failure_buckets,
                past_attempts,
                failure_samples=failure_samples,
            )
        return self._llm_propose(
            current_config, health_metrics, failure_samples, failure_buckets, past_attempts,
            optimization_mode=optimization_mode,
            objective=objective,
            guardrails=guardrails,
            project_memory_context=project_memory_context,
        )

    @staticmethod
    def _dominant_failure_bucket(failure_buckets: dict[str, int]) -> str | None:
        """Return dominant non-zero failure bucket, or None when no failures exist."""
        non_zero = {bucket: count for bucket, count in failure_buckets.items() if count > 0}
        if not non_zero:
            return None
        return max(non_zero, key=non_zero.get)

    def _rank_strategies(
        self,
        available_strategies: list[str],
        reflection_engine: "ReflectionEngine | None",
        epsilon: float = 0.1,
        rng: random.Random | None = None,
    ) -> list[str]:
        """Rank strategies by historical effectiveness with epsilon-greedy exploration.

        With probability ``epsilon``, returns a random shuffle of the input
        (exploration). Otherwise ranks strategies by the ``avg_improvement`` of
        the surface each strategy targets (exploitation), pulled from the
        reflection engine's surface-level effectiveness table.

        Ties break by ``attempts`` (more evidence wins), then by strategy name
        for determinism.

        WHY: Without epsilon exploration, the optimizer will over-pick whichever
        strategy worked in its first successes and starve alternatives - a known
        reflection-feedback-loop failure mode.
        """
        rng = rng or random.Random()
        if reflection_engine is None:
            return list(available_strategies)

        # Epsilon-greedy branch: shuffle and return.
        if rng.random() < epsilon:
            shuffled = list(available_strategies)
            rng.shuffle(shuffled)
            return shuffled

        # Exploitation branch: sort by (avg_improvement, attempts, name) desc.
        def _key(strategy: str) -> tuple[float, int, str]:
            surface = STRATEGY_TO_SURFACE.get(strategy)
            if surface is None:
                # Unknown strategies sort last but stably.
                return (float("-inf"), 0, strategy)
            eff = reflection_engine.read_surface_effectiveness(surface)
            if eff is None:
                return (0.0, 0, strategy)
            return (eff.avg_improvement, eff.attempts, strategy)

        # Stable tie-break on name ascending requires sorting by name first,
        # then by the primary keys reverse (Python sort is stable).
        staged = sorted(available_strategies, key=lambda s: s)
        return sorted(staged, key=_key, reverse=True)

    @staticmethod
    def _append_unique_keywords(existing: list[str], additions: list[str]) -> list[str]:
        """Append keywords while preserving order and avoiding duplicates."""
        seen = set(existing)
        merged = list(existing)
        for keyword in additions:
            if keyword not in seen:
                merged.append(keyword)
                seen.add(keyword)
        return merged

    def _mock_propose(
        self,
        current_config: dict,
        health_metrics: dict,
        failure_buckets: dict[str, int],
        past_attempts: list[dict],
        *,
        failure_samples: list[dict] | None = None,
    ) -> Proposal:
        """Deterministic mock proposer that makes targeted changes based on failure patterns."""
        new_config = copy.deepcopy(current_config)

        # Determine the dominant failure bucket
        dominant = self._dominant_failure_bucket(failure_buckets)

        # Track past config sections to avoid repeating the same change
        past_sections = [
            a.get("config_section", "") for a in (past_attempts[-5:] if past_attempts else [])
        ]

        if dominant == "routing_error" and "routing" not in past_sections:
            # Add more keywords to routing rules to improve routing accuracy
            routing = new_config.setdefault("routing", {})
            rules = routing.setdefault("rules", [])
            dynamic_additions = self._add_keywords_from_routing_failures(
                rules,
                failure_samples or [],
            )
            if dynamic_additions:
                specialist_summaries = [
                    f"{specialist}: {', '.join(keywords)}"
                    for specialist, keywords in dynamic_additions.items()
                ]
                return Proposal(
                    change_description=(
                        "Added routing keywords from scoped eval failures: "
                        + "; ".join(specialist_summaries)
                    ),
                    config_section="routing",
                    new_config=new_config,
                    reasoning=(
                        "Dominant failure bucket is routing_error. "
                        "Expanded runtime routing keywords using the selected eval failure messages."
                    ),
                    patch_bundle=self._routing_patch_bundle(
                        current_config=current_config,
                        dynamic_additions=dynamic_additions,
                        failure_samples=failure_samples or [],
                    ),
                )
            if rules:
                # Enhance existing rules with extra keywords
                for rule in rules:
                    specialist = rule.get("specialist", "")
                    existing = rule.get("keywords", [])
                    if specialist == "orders" and "shipping" not in existing:
                        rule["keywords"] = self._append_unique_keywords(existing, ["shipping"])
                    elif specialist == "support" and "issue" not in existing:
                        rule["keywords"] = self._append_unique_keywords(existing, ["issue"])
                    elif specialist == "recommendations" and "suggest" not in existing:
                        rule["keywords"] = self._append_unique_keywords(existing, ["suggest"])
            else:
                # Create default routing rules
                rules.append({"specialist": "orders", "keywords": ["order", "shipping", "track", "delivery"]})
                rules.append({"specialist": "support", "keywords": ["help", "issue", "problem", "error"]})
                rules.append({"specialist": "recommendations", "keywords": ["recommend", "suggest", "best", "top"]})
                routing["rules"] = rules

            return Proposal(
                change_description="Added routing keywords to improve specialist routing accuracy",
                config_section="routing",
                new_config=new_config,
                reasoning=f"Dominant failure bucket is routing_error. Added keywords to routing rules to improve match rate.",
            )

        elif (dominant == "unhelpful_response" or dominant is None) and "prompts" not in past_sections:
            # Improve system prompts to encourage more thorough responses
            prompts = new_config.setdefault("prompts", {})
            suffix = " Be thorough and detailed in your responses."
            root = prompts.get("root", "You are a helpful customer service agent.")
            if suffix not in root:
                prompts["root"] = root + suffix

            return Proposal(
                change_description="Enhanced root prompt to encourage thorough, detailed responses",
                config_section="prompts",
                new_config=new_config,
                reasoning=f"Dominant failure bucket is unhelpful_response. Appended detail instruction to root prompt.",
            )

        elif dominant == "timeout" and "thresholds" not in past_sections:
            # Reduce max_turns to prevent runaway conversations
            thresholds = new_config.setdefault("thresholds", {})
            current_max_turns = thresholds.get("max_turns", 20)
            new_max_turns = max(4, current_max_turns - 2)
            thresholds["max_turns"] = new_max_turns

            return Proposal(
                change_description=f"Reduced max_turns from {current_max_turns} to {new_max_turns} to prevent timeouts",
                config_section="thresholds",
                new_config=new_config,
                reasoning=f"Dominant failure bucket is timeout. Reduced max_turns to limit conversation length.",
            )

        elif dominant == "tool_failure" and "tools" not in past_sections:
            # Increase tool timeouts to give tools more time
            tools = new_config.setdefault("tools", {})
            for tool_name in ("catalog", "orders_db", "faq"):
                tool_cfg = tools.setdefault(tool_name, {})
                current_timeout = tool_cfg.get("timeout_ms", 5000)
                tool_cfg["timeout_ms"] = current_timeout + 2000

            return Proposal(
                change_description="Increased tool timeout_ms by 2000ms to reduce tool failures",
                config_section="tools",
                new_config=new_config,
                reasoning=f"Dominant failure bucket is tool_failure. Increased tool timeouts to allow more processing time.",
            )

        elif dominant == "safety_violation" and "prompts" not in past_sections:
            # Tighten safety instructions in prompts
            prompts = new_config.setdefault("prompts", {})
            safety_suffix = " Never assist with harmful, illegal, or dangerous requests."
            root = prompts.get("root", "You are a helpful customer service agent.")
            if safety_suffix not in root:
                prompts["root"] = root + safety_suffix

            return Proposal(
                change_description="Added explicit safety refusal instruction to root prompt",
                config_section="prompts",
                new_config=new_config,
                reasoning=f"Dominant failure bucket is safety_violation. Added safety guardrail to root prompt.",
            )

        else:
            # Default: add quality_boost flag and improve the root prompt
            prompts = new_config.setdefault("prompts", {})
            root = prompts.get("root", "You are a helpful customer service agent.")
            quality_suffix = " Always verify your answer before responding."
            if quality_suffix not in root:
                prompts["root"] = root + quality_suffix
            new_config["quality_boost"] = True

            return Proposal(
                change_description="Added quality_boost flag and verification instruction to root prompt",
                config_section="prompts",
                new_config=new_config,
                reasoning=f"No specific dominant failure or past sections overlap. Applied general quality improvement.",
            )

    def _llm_propose(
        self,
        current_config: dict,
        health_metrics: dict,
        failure_samples: list[dict],
        failure_buckets: dict[str, int],
        past_attempts: list[dict],
        *,
        optimization_mode: str | None = None,
        objective: str | None = None,
        guardrails: list[str] | None = None,
        project_memory_context: dict[str, list[str]] | None = None,
    ) -> Proposal | None:
        """Generate a proposal via LLMProposer with Agent Card context.

        Delegates to the full LLMProposer which uses structured prompts,
        the Agent Card representation, failure analysis, and validation.
        Falls back to mock on any error to keep the loop alive.
        """
        if self.llm_router is None:
            return self._mock_propose(current_config, health_metrics, failure_buckets, past_attempts)

        try:
            from agent_card.converter import from_config_dict
            from agent_card.renderer import render_to_markdown
            from optimizer.failure_analyzer import FailureAnalyzer
            from optimizer.llm_proposer import LLMProposer

            # Build Agent Card for rich context
            agent_card = from_config_dict(current_config, name=current_config.get("name", "agent"))
            agent_card_markdown = render_to_markdown(agent_card)

            # Run failure analysis
            analyzer = FailureAnalyzer(llm_router=self.llm_router)
            eval_results = {
                "failure_buckets": failure_buckets,
                "failure_samples": failure_samples,
            }
            analysis = analyzer.analyze(
                eval_results=eval_results,
                agent_card_markdown=agent_card_markdown,
                past_attempts=past_attempts,
            )

            # Build failure analysis dict for the proposer
            failure_analysis_dict = {
                "clusters": [
                    {
                        "id": c.cluster_id,
                        "count": c.count,
                        "summary": c.description,
                        "recommended_surface": c.failure_type,
                    }
                    for c in analysis.clusters
                ],
                "surface_recommendations": {
                    r.surface: r.reasoning
                    for r in analysis.surface_recommendations
                },
                "summary": analysis.summary,
            }

            # Build constraints
            constraints = {}
            if hasattr(self, "_immutable_surfaces") and self._immutable_surfaces:
                constraints["immutable_surfaces"] = list(self._immutable_surfaces)
            if guardrails:
                constraints["guardrails"] = guardrails

            # Generate proposal via LLMProposer
            proposer = LLMProposer(llm_router=self.llm_router)
            proposal = proposer.propose(
                current_config=current_config,
                agent_card_markdown=agent_card_markdown,
                failure_analysis=failure_analysis_dict,
                past_attempts=past_attempts,
                objective=objective,
                constraints=constraints if constraints else None,
            )
            if proposal is not None:
                return proposal

            # LLMProposer returned None (invalid response) — fall back
            return self._mock_propose(
                current_config,
                health_metrics,
                failure_buckets,
                past_attempts,
                failure_samples=failure_samples,
            )
        except Exception:
            # Production-safe fallback keeps loop alive during provider outages.
            return self._mock_propose(
                current_config,
                health_metrics,
                failure_buckets,
                past_attempts,
                failure_samples=failure_samples,
            )

    @classmethod
    def _add_keywords_from_routing_failures(
        cls,
        rules: list[dict],
        failure_samples: list[dict],
    ) -> dict[str, list[str]]:
        """Extract routing repair keywords from scoped failures and apply them in place."""
        if not rules or not failure_samples:
            return {}

        rules_by_specialist: dict[str, dict] = {}
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            specialist = str(rule.get("specialist") or "").strip()
            if not specialist:
                continue
            rule.setdefault("keywords", [])
            rules_by_specialist[specialist] = rule

        additions: dict[str, list[str]] = {}
        for sample in failure_samples:
            error_text = str(sample.get("error_message") or "")
            specialist_match = re.search(r"expected=([a-zA-Z0-9_-]+)", error_text)
            if specialist_match is None:
                continue
            specialist = specialist_match.group(1)
            rule = rules_by_specialist.get(specialist)
            if rule is None:
                continue

            existing = [str(item) for item in rule.get("keywords", []) if str(item).strip()]
            existing_lower = {item.lower() for item in existing}
            candidate_terms = cls._extract_candidate_keywords(
                " ".join(
                    [
                        str(sample.get("user_message") or ""),
                        error_text,
                    ]
                )
            )
            new_terms = [
                term for term in candidate_terms
                if term not in existing_lower
            ][:4]
            if not new_terms:
                continue

            rule["keywords"] = cls._append_unique_keywords(existing, new_terms)
            additions.setdefault(specialist, []).extend(new_terms)

        return additions

    @staticmethod
    def _extract_candidate_keywords(text: str) -> list[str]:
        """Return stable routing-keyword candidates from failure text."""
        keywords: list[str] = []
        seen: set[str] = set()
        for raw in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", text.lower()):
            token = raw.strip("_-")
            if len(token) < 3 or token in _ROUTING_STOP_WORDS or token in seen:
                continue
            seen.add(token)
            keywords.append(token.replace("_", " "))
        return sorted(keywords, key=len, reverse=True)

    @staticmethod
    def _routing_patch_bundle(
        *,
        current_config: dict,
        dynamic_additions: dict[str, list[str]],
        failure_samples: list[dict],
    ) -> dict | None:
        """Build a typed routing patch bundle for mined keyword repairs."""
        agent = from_config_dict(current_config, name="root")
        operations: list[ComponentPatchOperation] = []
        for specialist, keywords in dynamic_additions.items():
            component = find_component_reference(agent, "routing_rule", specialist)
            if component is None:
                continue
            operations.append(
                ComponentPatchOperation(
                    op="append",
                    component=component,
                    field_path="keywords",
                    value=keywords,
                    rationale="Mined routing keywords from scoped eval failures.",
                )
            )
        if not operations:
            return None
        bundle = TypedPatchBundle(
            bundle_id="proposal-routing-keywords",
            title="Route scoped eval failures to expected specialists",
            operations=operations,
            source="optimizer.proposer.mock",
            component_attributions=_flatten_component_attributions(failure_samples),
            metadata={"failure_sample_count": len(failure_samples)},
        )
        return bundle.model_dump(mode="python")

    @staticmethod
    def _extract_json_payload(text: str) -> dict | None:
        """Parse JSON object from full-text LLM response payload."""
        raw = text.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _apply_patch(current_config: dict, patch: dict) -> dict:
        """Apply dot-path patch values onto a config copy."""
        updated = copy.deepcopy(current_config)
        for key, value in patch.items():
            if "." not in key:
                updated[key] = value
                continue
            target = updated
            parts = key.split(".")
            for part in parts[:-1]:
                if part not in target or not isinstance(target[part], dict):
                    target[part] = {}
                target = target[part]
            target[parts[-1]] = value
        return updated
