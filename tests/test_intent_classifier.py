"""Tests for free-text intent detection (keyword + LLM paths)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from builder.coordinator_turn import detect_command_intent
from builder.worker_mode import WorkerMode


@dataclass
class _Response:
    text: str
    provider: str = "mock"
    model: str = "mock-model"
    total_tokens: int = 8


class _StaticRouter:
    """Returns a canned LLM response without touching the network."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def generate(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return _Response(text=self._text)


class _RaisingRouter:
    """Always raises so we can verify the keyword fallback path."""

    def generate(self, request):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider unavailable")


class TestKeywordIntent:
    @pytest.mark.parametrize(
        "message,expected",
        [
            ("Please deploy the canary build", "deploy"),
            ("optimize the prompt", "optimize"),
            ("run the eval suite", "eval"),
            ("attach a build-time skill", "skills"),
            ("create a new agent for support", "build"),
            ("", "build"),
            ("totally unrelated text", "build"),
        ],
    )
    def test_keyword_intent_matches_expected(self, message: str, expected: str) -> None:
        assert detect_command_intent(message) == expected

    def test_no_router_means_keyword_only(self) -> None:
        # Even with WorkerMode.LLM, lack of a router must keep us on keyword path.
        assert (
            detect_command_intent("Please deploy the canary", worker_mode=WorkerMode.LLM)
            == "deploy"
        )


class TestLLMIntent:
    def test_llm_path_only_fires_when_keyword_is_ambiguous(self) -> None:
        router = _StaticRouter('{"intent": "optimize"}')
        # Strong keyword match should NOT call the LLM.
        result = detect_command_intent(
            "deploy the new canary release",
            worker_mode=WorkerMode.LLM,
            router=router,
        )
        assert result == "deploy"
        assert router.calls == 0

    def test_llm_path_overrides_ambiguous_keyword(self) -> None:
        router = _StaticRouter('{"intent": "optimize"}')
        result = detect_command_intent(
            "make it better please",  # only "make" -> keyword build, ambiguous
            worker_mode=WorkerMode.LLM,
            router=router,
        )
        assert router.calls == 1
        assert result == "optimize"

    def test_llm_failure_falls_back_to_keyword(self) -> None:
        router = _RaisingRouter()
        result = detect_command_intent(
            "make something useful",
            worker_mode=WorkerMode.LLM,
            router=router,
        )
        assert result == "build"

    def test_invalid_llm_response_falls_back(self) -> None:
        router = _StaticRouter("not valid json")
        result = detect_command_intent(
            "make it work",
            worker_mode=WorkerMode.LLM,
            router=router,
        )
        assert result == "build"

    def test_llm_returning_unknown_intent_falls_back(self) -> None:
        router = _StaticRouter('{"intent": "frobnicate"}')
        result = detect_command_intent(
            "make it work",
            worker_mode=WorkerMode.LLM,
            router=router,
        )
        assert result == "build"

    def test_llm_response_with_code_fence_is_parsed(self) -> None:
        router = _StaticRouter('```json\n{"intent": "ask"}\n```')
        result = detect_command_intent(
            "what is this agent doing",
            worker_mode=WorkerMode.LLM,
            router=router,
        )
        assert result == "ask"

    def test_deterministic_mode_skips_llm_even_with_router(self) -> None:
        router = _StaticRouter('{"intent": "deploy"}')
        result = detect_command_intent(
            "make something",
            worker_mode=WorkerMode.DETERMINISTIC,
            router=router,
        )
        assert router.calls == 0
        assert result == "build"
