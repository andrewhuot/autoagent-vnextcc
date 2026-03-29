"""Eval-compatible agent adapter for routing real-model calls through the current config.

This adapter exists so the eval harness can exercise the configured agent logic
without depending directly on the interactive ADK server runtime.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any

from agent.config.loader import load_config
from agent.config.runtime import RuntimeConfig
from agent.config.schema import AgentConfig, validate_config
from evals.fixtures.mock_data import mock_agent_response
from optimizer.providers import LLMRequest, LLMRouter, build_router_from_runtime_config


MOCK_MODE_BANNER_MESSAGE = "Running in mock mode — add API keys for live optimization"
LEGACY_EVAL_MOCK_MESSAGE = (
    "Eval harness is using mock_agent_response, so eval scores remain simulated until a real agent_fn is wired in."
)


def _load_default_config() -> dict[str, Any]:
    """Load the baked-in base agent config used when no override is supplied."""
    base_path = Path(__file__).parent / "config" / "base_config.yaml"
    return load_config(str(base_path)).model_dump(mode="python")


class ConfiguredEvalAgent:
    """Run eval requests through the configured routing and provider stack.

    The eval harness needs a small synchronous adapter that can accept a user
    message plus a candidate config and return the scoring payload shape used by
    ``EvalRunner``. This class keeps that contract in one place and preserves a
    truthful fallback to mock responses when real model credentials are missing.
    """

    def __init__(
        self,
        *,
        llm_router: LLMRouter,
        default_config: dict[str, Any] | None = None,
    ) -> None:
        self.llm_router = llm_router
        self.default_config = copy.deepcopy(default_config or _load_default_config())
        self.mock_mode = bool(getattr(llm_router, "mock_mode", False))
        self.mock_reason = str(getattr(llm_router, "mock_reason", "")).strip()

    @property
    def mock_mode_messages(self) -> list[str]:
        """Return human-readable mock-mode reasons for CLI/API health surfaces."""
        if not self.mock_mode:
            return []

        messages = [MOCK_MODE_BANNER_MESSAGE, LEGACY_EVAL_MOCK_MESSAGE]
        if self.mock_reason:
            messages.append(self.mock_reason)

        deduped: list[str] = []
        seen: set[str] = set()
        for message in messages:
            if not message or message in seen:
                continue
            seen.add(message)
            deduped.append(message)
        return deduped

    def run(self, user_message: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute one eval request against the configured agent behavior.

        We keep the scoring payload explicit here so eval callers can use the
        same interface regardless of whether the result came from a real model
        or the deterministic mock fallback.
        """
        resolved_config = self._resolve_config(config)
        if self.mock_mode:
            return mock_agent_response(user_message, resolved_config)

        validated = validate_config(resolved_config)
        specialist = self._route_specialist(validated, user_message)
        tool_calls = self._build_tool_calls(specialist, user_message, validated)
        response = self.llm_router.generate(
            LLMRequest(
                prompt=self._build_prompt(validated, specialist, user_message, tool_calls),
                system=self._build_system_prompt(validated, specialist),
                temperature=0.2,
                max_tokens=500,
                metadata={
                    "task": "eval_agent_response",
                    "specialist": specialist,
                },
            )
        )

        response_text = response.text.strip() or "I can help with that request."
        return {
            "response": response_text,
            "tool_calls": tool_calls,
            "latency_ms": float(response.latency_ms),
            "token_count": int(response.total_tokens),
            "specialist_used": specialist,
            "safety_violation": False,
        }

    def _resolve_config(self, override: dict[str, Any] | None) -> dict[str, Any]:
        """Return the candidate config used for one eval execution."""
        return copy.deepcopy(override or self.default_config)

    def _route_specialist(self, config: AgentConfig, user_message: str) -> str:
        """Choose the specialist that best matches the user message."""
        lower = user_message.lower()
        best_specialist = "support"
        best_score = 0

        for rule in config.routing.rules:
            score = 0
            for keyword in rule.keywords:
                if keyword and keyword.lower() in lower:
                    score += 1
            for pattern in rule.patterns:
                if pattern and pattern.lower() in lower:
                    score += 2

            if score > best_score:
                best_score = score
                best_specialist = rule.specialist

        return best_specialist

    def _build_system_prompt(self, config: AgentConfig, specialist: str) -> str:
        """Build the specialist-aware system prompt used for eval completions."""
        specialist_prompt = getattr(config.prompts, specialist, config.prompts.support)
        instructions = [
            config.prompts.root.strip(),
            specialist_prompt.strip(),
            "Answer as the selected specialist for this request.",
            "Be concise, practical, and helpful.",
            "Refuse unsafe or disallowed requests politely.",
            "Return plain text only.",
        ]
        if config.quality_boost:
            instructions.append("Be extra thorough and verify key details before responding.")
        return "\n\n".join(item for item in instructions if item)

    def _build_prompt(
        self,
        config: AgentConfig,
        specialist: str,
        user_message: str,
        tool_calls: list[dict[str, Any]],
    ) -> str:
        """Build the user prompt sent to the underlying LLM router."""
        enabled_tools = [call.get("tool", "") for call in tool_calls if isinstance(call, dict)]
        quality_instruction = "enabled" if config.quality_boost else "disabled"
        return (
            f"Selected specialist: {specialist}\n"
            f"Quality boost: {quality_instruction}\n"
            f"Enabled tools: {', '.join(enabled_tools) or 'none'}\n\n"
            f"User message:\n{user_message}"
        )

    def _build_tool_calls(
        self,
        specialist: str,
        user_message: str,
        config: AgentConfig,
    ) -> list[dict[str, Any]]:
        """Return the implied tool payload for the chosen specialist."""
        if specialist == "orders" and config.tools.orders_db.enabled:
            return [{"tool": "orders_db", "name": "lookup_order", "args": {"query": user_message}}]
        if specialist == "recommendations" and config.tools.catalog.enabled:
            return [{"tool": "catalog", "name": "get_recommendations", "args": {"query": user_message}}]
        if specialist == "support" and config.tools.faq.enabled:
            return [{"tool": "faq", "name": "search_faq", "args": {"query": user_message}}]
        return []


def create_eval_agent(
    runtime: RuntimeConfig,
    *,
    force_real_agent: bool = False,
    default_config: dict[str, Any] | None = None,
) -> ConfiguredEvalAgent:
    """Build the eval-compatible agent using runtime provider settings.

    ``force_real_agent`` is used by the CLI `--real-agent` flag so a user can
    request the real-agent path even when the runtime config still has
    ``optimizer.use_mock`` enabled. If credentials are unavailable, the router
    transparently falls back to mock mode and exposes the reason.
    """
    effective_runtime = runtime.model_copy(deep=True)
    if force_real_agent:
        effective_runtime.optimizer.use_mock = False

    llm_router = build_router_from_runtime_config(effective_runtime.optimizer)
    return ConfiguredEvalAgent(
        llm_router=llm_router,
        default_config=default_config,
    )
