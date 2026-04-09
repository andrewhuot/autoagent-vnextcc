"""Tests for multi-provider LLM routing, retries, and cost accounting."""

from __future__ import annotations

import json
from dataclasses import dataclass

from optimizer.providers import (
    LLMRequest,
    LLMResponse,
    LLMRouter,
    ModelConfig,
    OpenAIProvider,
    RetryPolicy,
)


@dataclass
class _FakeProvider:
    """Minimal provider stub used to validate router behavior."""

    provider_name: str
    model_name: str
    score: float
    failures_before_success: int = 0

    def __post_init__(self) -> None:
        self.calls = 0

    def complete(self, request: LLMRequest, retry_policy: RetryPolicy) -> LLMResponse:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError(f"{self.provider_name}:{self.model_name} temporary failure")
        return LLMResponse(
            provider=self.provider_name,
            model=self.model_name,
            text=f"proposal from {self.provider_name}/{self.model_name}",
            prompt_tokens=120,
            completion_tokens=80,
            total_tokens=200,
            latency_ms=125.0,
            metadata={"proposal_score": self.score},
        )


def test_round_robin_rotates_models() -> None:
    """Round-robin strategy should alternate models between consecutive calls."""
    openai = _FakeProvider("openai", "gpt-4o", score=0.6)
    anthropic = _FakeProvider("anthropic", "claude-sonnet", score=0.7)

    router = LLMRouter(
        strategy="round_robin",
        models=[
            ModelConfig(provider="openai", model="gpt-4o"),
            ModelConfig(provider="anthropic", model="claude-sonnet"),
        ],
        providers={
            ("openai", "gpt-4o"): openai,
            ("anthropic", "claude-sonnet"): anthropic,
        },
    )

    first = router.generate(LLMRequest(prompt="improve routing"))
    second = router.generate(LLMRequest(prompt="improve routing"))

    assert first.provider == "openai"
    assert second.provider == "anthropic"


def test_ensemble_selects_highest_scoring_response() -> None:
    """Ensemble strategy should return the best proposal by score."""
    openai = _FakeProvider("openai", "gpt-5", score=0.61)
    anthropic = _FakeProvider("anthropic", "claude-opus", score=0.84)
    google = _FakeProvider("google", "gemini-2.5-pro", score=0.73)

    router = LLMRouter(
        strategy="ensemble",
        models=[
            ModelConfig(provider="openai", model="gpt-5"),
            ModelConfig(provider="anthropic", model="claude-opus"),
            ModelConfig(provider="google", model="gemini-2.5-pro"),
        ],
        providers={
            ("openai", "gpt-5"): openai,
            ("anthropic", "claude-opus"): anthropic,
            ("google", "gemini-2.5-pro"): google,
        },
    )

    chosen = router.generate(LLMRequest(prompt="propose a fix"))

    assert chosen.provider == "anthropic"
    assert chosen.model == "claude-opus"


def test_router_applies_retry_policy_to_transient_failures() -> None:
    """Router should retry transient provider failures according to retry policy."""
    flaky = _FakeProvider("openai", "gpt-4o", score=0.75, failures_before_success=2)
    router = LLMRouter(
        strategy="single",
        models=[ModelConfig(provider="openai", model="gpt-4o")],
        providers={("openai", "gpt-4o"): flaky},
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.0, max_delay_seconds=0.0, jitter_seconds=0.0),
    )

    response = router.generate(LLMRequest(prompt="improve safety"))

    assert response.provider == "openai"
    assert flaky.calls == 3


def test_single_strategy_falls_back_to_next_model_when_primary_exhausts_retries() -> None:
    """Single strategy should try the next configured model after a primary failure."""
    failing_primary = _FakeProvider("openai", "gpt-4o", score=0.6, failures_before_success=99)
    healthy_secondary = _FakeProvider("google", "gemini-2.5-pro", score=0.8)

    router = LLMRouter(
        strategy="single",
        models=[
            ModelConfig(provider="openai", model="gpt-4o"),
            ModelConfig(provider="google", model="gemini-2.5-pro"),
        ],
        providers={
            ("openai", "gpt-4o"): failing_primary,
            ("google", "gemini-2.5-pro"): healthy_secondary,
        },
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.0, max_delay_seconds=0.0, jitter_seconds=0.0),
    )

    response = router.generate(LLMRequest(prompt="propose a fix"))

    assert response.provider == "google"
    assert response.model == "gemini-2.5-pro"
    assert failing_primary.calls == 2
    assert healthy_secondary.calls == 1


def test_router_tracks_provider_costs() -> None:
    """Router should accumulate token-based costs per provider/model."""
    fake = _FakeProvider("openai", "gpt-4o", score=0.8)
    router = LLMRouter(
        strategy="single",
        models=[
            ModelConfig(
                provider="openai",
                model="gpt-4o",
                input_cost_per_1k_tokens=0.01,
                output_cost_per_1k_tokens=0.03,
            )
        ],
        providers={("openai", "gpt-4o"): fake},
    )

    router.generate(LLMRequest(prompt="one"))
    router.generate(LLMRequest(prompt="two"))

    summary = router.cost_summary()
    assert "openai:gpt-4o" in summary
    assert summary["openai:gpt-4o"]["requests"] == 2
    assert summary["openai:gpt-4o"]["total_cost"] > 0


def test_http_post_uses_shared_ssl_context(monkeypatch) -> None:
    """Provider HTTP POSTs should use the shared SSL context helper."""
    provider = OpenAIProvider(ModelConfig(provider="openai", model="gpt-4o"))
    captured: dict[str, object] = {}
    created_context = object()

    class _StubHTTPResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, D401
            return False

        def read(self) -> bytes:
            return json.dumps({"ok": True}).encode("utf-8")

    def _fake_create_default_context(*args, **kwargs):  # noqa: ANN002, ANN003
        captured["args"] = args
        captured["kwargs"] = kwargs
        return created_context

    def _fake_urlopen(request, timeout=0, context=None):  # noqa: ANN001, ARG001
        captured["context"] = context
        return _StubHTTPResponse()

    monkeypatch.setattr("optimizer.providers.get_ssl_context", _fake_create_default_context)
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    payload = provider._http_post("https://example.com/v1/test", {"hello": "world"}, {"Content-Type": "application/json"})

    assert payload == {"ok": True}
    assert captured["context"] is created_context
