"""Runtime/provider behavior tests for mock fallback semantics."""

from __future__ import annotations

from optimizer.providers import LLMRequest, build_router_from_runtime_config
from agent.config.runtime import RuntimeConfig


def test_router_falls_back_to_mock_when_required_api_keys_are_missing(monkeypatch) -> None:
    """Router should transparently fall back to mock mode when no usable model credentials exist."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    runtime = RuntimeConfig.model_validate(
        {
            "optimizer": {
                "use_mock": False,
                "strategy": "single",
                "models": [
                    {
                        "provider": "openai",
                        "model": "gpt-test",
                        "api_key_env": "OPENAI_API_KEY",
                    }
                ],
            }
        }
    )

    router = build_router_from_runtime_config(runtime.optimizer)

    assert getattr(router, "mock_mode", False) is True
    assert "OPENAI_API_KEY" in getattr(router, "mock_reason", "")

    response = router.generate(LLMRequest(prompt="hello"))
    assert response.provider == "mock"
    assert response.metadata.get("proposal_score") == 0.5


def test_router_keeps_real_mode_when_mock_is_explicitly_disabled_and_key_exists(monkeypatch) -> None:
    """A model with configured credentials should stay in real mode and avoid fallback."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    runtime = RuntimeConfig.model_validate(
        {
            "optimizer": {
                "use_mock": False,
                "strategy": "single",
                "models": [
                    {
                        "provider": "openai",
                        "model": "gpt-test",
                        "api_key_env": "OPENAI_API_KEY",
                    }
                ],
            }
        }
    )

    router = build_router_from_runtime_config(runtime.optimizer)

    assert getattr(router, "mock_mode", True) is False
    assert getattr(router, "mock_reason", "") == ""

