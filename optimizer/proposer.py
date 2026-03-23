"""LLM-based config change proposer with deterministic mock."""

from __future__ import annotations

import copy
from dataclasses import dataclass


@dataclass
class Proposal:
    change_description: str
    config_section: str  # which section of config was changed
    new_config: dict  # the full modified config
    reasoning: str


class Proposer:
    """Proposes config changes using LLM (or mock)."""

    def __init__(self, use_mock: bool = True) -> None:
        self.use_mock = use_mock

    def propose(
        self,
        current_config: dict,
        health_metrics: dict,
        failure_samples: list[dict],
        failure_buckets: dict[str, int],
        past_attempts: list[dict],
    ) -> Proposal | None:
        if self.use_mock:
            return self._mock_propose(current_config, health_metrics, failure_buckets, past_attempts)
        return self._llm_propose(current_config, health_metrics, failure_samples, failure_buckets, past_attempts)

    @staticmethod
    def _dominant_failure_bucket(failure_buckets: dict[str, int]) -> str | None:
        """Return dominant non-zero failure bucket, or None when no failures exist."""
        non_zero = {bucket: count for bucket, count in failure_buckets.items() if count > 0}
        if not non_zero:
            return None
        return max(non_zero, key=non_zero.get)

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
    ) -> Proposal | None:
        """Real LLM-based proposer (placeholder for Gemini integration)."""
        # Would call Gemini here with a structured prompt containing:
        # - current_config, health_metrics, failure_samples, failure_buckets, past_attempts
        # For now, fall back to mock
        return self._mock_propose(current_config, health_metrics, failure_buckets, past_attempts)
