"""LLM-driven prompt optimization operators.

Originally stubbed for Vertex AI prompt optimizer APIs, these operators now
use the configured LLM router to perform prompt optimization without
requiring Vertex AI credentials.

Each operator targets a specific optimization strategy:
- ZeroShotOptimizer: Rewrites prompts without examples
- FewShotOptimizer: Generates/improves few-shot examples from eval data
- DataDrivenOptimizer: Proposes changes based on eval history analysis
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from optimizer.mutations import (
    MutationOperator,
    MutationRegistry,
    MutationSurface,
    RiskClass,
)


def _get_router() -> Any:
    """Lazily resolve the LLM router to avoid circular imports."""
    from optimizer.providers import LLMRequest, LLMRouter
    return LLMRequest, LLMRouter


def _extract_json(text: str) -> dict | None:
    """Extract a JSON object from LLM response text."""
    raw = text.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
    return None


class ZeroShotOptimizer:
    """Rewrites system prompts using LLM without requiring few-shot examples.

    Takes the current prompt and failure context, asks the LLM to produce
    an improved version that addresses observed failures while preserving
    the agent's core behavior.
    """

    @classmethod
    def create_operator(cls) -> MutationOperator:
        return MutationOperator(
            name="llm_zero_shot_optimize",
            surface=MutationSurface.instruction,
            risk_class=RiskClass.medium,
            preconditions=[
                "LLM router configured with at least one provider",
                "Target prompt exists in config",
            ],
            validator=lambda config: isinstance(config.get("prompts"), dict),
            rollback_strategy="revert to pre-optimization prompt text",
            estimated_eval_cost=0.05,
            supports_autodeploy=False,
            description=(
                "Use LLM to rewrite system prompts without few-shot examples. "
                "Analyzes failures and rewrites prompts to address root causes."
            ),
            apply=cls._apply,
            ready=True,
        )

    @staticmethod
    def _apply(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Rewrite prompts using LLM zero-shot optimization.

        params:
            llm_router: LLMRouter instance
            target_prompt_key: which prompt to rewrite (default: "root")
            failure_context: summary of failures to address
            objective: optimization goal
        """
        LLMRequest, _ = _get_router()
        router = params.get("llm_router")
        if router is None:
            return config

        new_config = copy.deepcopy(config)
        prompts = new_config.get("prompts", {})
        target_key = params.get("target_prompt_key", "root")
        current_prompt = prompts.get(target_key, "")

        if not current_prompt:
            return config

        failure_context = params.get("failure_context", "")
        objective = params.get("objective", "Improve overall quality and accuracy")

        system = (
            "You are an expert prompt engineer. Rewrite the given system prompt to "
            "address the observed failures while preserving the agent's core behavior, "
            "personality, and capabilities. Return ONLY a JSON object with a single "
            "'improved_prompt' field containing the rewritten prompt."
        )

        user_prompt = json.dumps({
            "current_prompt": current_prompt,
            "prompt_key": target_key,
            "failures_to_address": failure_context,
            "optimization_objective": objective,
            "rules": [
                "Preserve the agent's role and persona",
                "Address the specific failure patterns described",
                "Keep the prompt concise but comprehensive",
                "Add constraints or clarifications where failures indicate ambiguity",
                "Do not add unnecessary verbosity",
            ],
        }, indent=2)

        try:
            response = router.generate(LLMRequest(
                prompt=user_prompt,
                system=system,
                temperature=0.3,
                max_tokens=2000,
                metadata={"task": "zero_shot_prompt_optimize", "target": target_key},
            ))
            parsed = _extract_json(response.text)
            if parsed and "improved_prompt" in parsed:
                prompts[target_key] = parsed["improved_prompt"]
                new_config["prompts"] = prompts
                return new_config
        except Exception:
            pass

        return config


class FewShotOptimizer:
    """Generates or improves few-shot examples using LLM.

    Uses eval results and failure patterns to create targeted few-shot
    examples that demonstrate correct behavior for common failure cases.
    """

    @classmethod
    def create_operator(cls) -> MutationOperator:
        return MutationOperator(
            name="llm_few_shot_optimize",
            surface=MutationSurface.few_shot,
            risk_class=RiskClass.medium,
            preconditions=[
                "LLM router configured with at least one provider",
            ],
            validator=lambda config: isinstance(config.get("prompts"), dict),
            rollback_strategy="revert to pre-optimization few-shot examples",
            estimated_eval_cost=0.08,
            supports_autodeploy=False,
            description=(
                "Use LLM to generate or improve few-shot examples based on "
                "eval failures, demonstrating correct behavior for edge cases."
            ),
            apply=cls._apply,
            ready=True,
        )

    @staticmethod
    def _apply(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Generate few-shot examples using LLM.

        params:
            llm_router: LLMRouter instance
            failure_samples: list of failure cases to learn from
            target_specialist: which specialist needs examples
            max_examples: maximum number of examples to generate (default: 3)
        """
        LLMRequest, _ = _get_router()
        router = params.get("llm_router")
        if router is None:
            return config

        new_config = copy.deepcopy(config)
        failure_samples = params.get("failure_samples", [])
        target_specialist = params.get("target_specialist", "root")
        max_examples = params.get("max_examples", 3)

        # Get current prompt context
        prompts = new_config.get("prompts", {})
        specialist_prompt = prompts.get(target_specialist, "")

        system = (
            "You are an expert at creating few-shot examples for AI agents. "
            "Generate examples that demonstrate correct behavior for cases "
            "where the agent is currently failing. Return ONLY a JSON object "
            "with a 'examples' field containing a list of {input, output} pairs."
        )

        user_prompt = json.dumps({
            "specialist": target_specialist,
            "specialist_instructions": specialist_prompt[:500],
            "failure_cases": [
                {
                    "input": s.get("user_message", ""),
                    "expected": s.get("expected_behavior", ""),
                    "actual_error": s.get("error_message", s.get("failure_description", "")),
                }
                for s in failure_samples[:10]
            ],
            "max_examples": max_examples,
            "rules": [
                "Each example should address a specific failure pattern",
                "Inputs should be realistic user messages",
                "Outputs should demonstrate ideal agent behavior",
                "Cover diverse failure types, not just the most common",
            ],
        }, indent=2)

        try:
            response = router.generate(LLMRequest(
                prompt=user_prompt,
                system=system,
                temperature=0.4,
                max_tokens=2000,
                metadata={"task": "few_shot_optimize", "target": target_specialist},
            ))
            parsed = _extract_json(response.text)
            if parsed and "examples" in parsed and isinstance(parsed["examples"], list):
                few_shot = new_config.setdefault("few_shot", {})
                few_shot[target_specialist] = parsed["examples"][:max_examples]
                return new_config
        except Exception:
            pass

        return config


class DataDrivenOptimizer:
    """Proposes config changes based on analysis of eval history.

    Analyzes patterns across multiple eval runs to identify systemic
    issues and propose targeted configuration changes.
    """

    @classmethod
    def create_operator(cls) -> MutationOperator:
        return MutationOperator(
            name="llm_data_driven_optimize",
            surface=MutationSurface.instruction,
            risk_class=RiskClass.high,
            preconditions=[
                "LLM router configured with at least one provider",
                "Sufficient eval history available",
            ],
            validator=lambda config: isinstance(config.get("prompts"), dict),
            rollback_strategy="revert to pre-optimization config snapshot",
            estimated_eval_cost=0.15,
            supports_autodeploy=False,
            description=(
                "Use LLM to analyze eval history and propose data-driven "
                "configuration changes across multiple agent surfaces."
            ),
            apply=cls._apply,
            ready=True,
        )

    @staticmethod
    def _apply(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Propose data-driven changes using LLM analysis.

        params:
            llm_router: LLMRouter instance
            eval_history: list of past eval summaries
            failure_trends: dict of failure type -> count over time
            agent_card_markdown: full Agent Card for context
        """
        LLMRequest, _ = _get_router()
        router = params.get("llm_router")
        if router is None:
            return config

        new_config = copy.deepcopy(config)
        eval_history = params.get("eval_history", [])
        failure_trends = params.get("failure_trends", {})
        agent_card = params.get("agent_card_markdown", "")

        system = (
            "You are an expert AI agent optimizer analyzing evaluation data "
            "to propose targeted configuration improvements. Return ONLY a "
            "JSON object with 'config_patch' (partial config to merge), "
            "'reasoning' (why this change), and 'target_surface' (which "
            "aspect of the agent is being changed)."
        )

        user_prompt = json.dumps({
            "current_config": {
                k: v for k, v in config.items()
                if k in ("prompts", "routing", "tools", "thresholds", "guardrails",
                         "generation", "model")
            },
            "agent_card": agent_card[:3000] if agent_card else "",
            "eval_history_summary": eval_history[:10],
            "failure_trends": failure_trends,
            "available_surfaces": [
                "prompts (system instructions per specialist)",
                "routing (rules, keywords, patterns)",
                "tools (timeouts, descriptions)",
                "thresholds (max_turns, confidence)",
                "guardrails (safety gates)",
                "generation (temperature, max_tokens)",
            ],
            "rules": [
                "Propose ONE focused change based on data patterns",
                "Target the surface with highest impact potential",
                "Include the complete modified section, not just deltas",
                "Preserve existing config structure",
            ],
        }, indent=2)

        try:
            response = router.generate(LLMRequest(
                prompt=user_prompt,
                system=system,
                temperature=0.2,
                max_tokens=2000,
                metadata={"task": "data_driven_optimize"},
            ))
            parsed = _extract_json(response.text)
            if parsed and "config_patch" in parsed and isinstance(parsed["config_patch"], dict):
                for key, value in parsed["config_patch"].items():
                    if isinstance(value, dict) and key in new_config and isinstance(new_config[key], dict):
                        new_config[key].update(value)
                    else:
                        new_config[key] = value
                return new_config
        except Exception:
            pass

        return config


def register_google_operators(registry: MutationRegistry) -> None:
    """Register all LLM-driven optimization operators."""
    registry.register(ZeroShotOptimizer.create_operator())
    registry.register(FewShotOptimizer.create_operator())
    registry.register(DataDrivenOptimizer.create_operator())
