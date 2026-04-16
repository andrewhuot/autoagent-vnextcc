"""Tests for default Workbench chat runtime resolution."""

from __future__ import annotations

from types import SimpleNamespace

from cli.workbench_app import app as app_module


def test_maybe_build_orchestrator_uses_credentialed_workspace_model(
    monkeypatch, tmp_path
) -> None:
    """A usable workspace model should attach chat without an env opt-in."""
    monkeypatch.delenv("AGENTLAB_LLM_ORCHESTRATOR", raising=False)
    monkeypatch.delenv("AGENTLAB_CLASSIC_COORDINATOR", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "cli.model.list_available_models",
        lambda _root: [
            {
                "key": "anthropic:claude-sonnet-4-5",
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "api_key_env": "ANTHROPIC_API_KEY",
            }
        ],
    )

    calls: dict[str, object] = {}

    def fake_create_model_client(**kwargs):
        calls["model_kwargs"] = kwargs
        return "model-client"

    def fake_build_workbench_runtime(**kwargs):
        calls["runtime_kwargs"] = kwargs
        return "runtime-bundle"

    monkeypatch.setattr("cli.llm.providers.create_model_client", fake_create_model_client)
    monkeypatch.setattr(
        "cli.workbench_app.orchestrator_runtime.build_workbench_runtime",
        fake_build_workbench_runtime,
    )

    workspace = SimpleNamespace(root=tmp_path)
    result = app_module._maybe_build_orchestrator(
        workspace,
        session=None,
        store=None,
        echo=lambda _line: None,
    )

    assert result == "runtime-bundle"
    assert calls["model_kwargs"] == {
        "model": "claude-sonnet-4-5",
        "api_key": "test-key",
        "echo_fallback_on_missing_keys": False,
    }
    assert calls["runtime_kwargs"]["model"] == "model-client"
    assert calls["runtime_kwargs"]["active_model"] == "claude-sonnet-4-5"


def test_maybe_build_orchestrator_skips_uncredentialed_model_without_echo_fallback(
    monkeypatch, tmp_path
) -> None:
    """Missing keys should leave chat unconfigured instead of building EchoModel."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENTLAB_CLASSIC_COORDINATOR", raising=False)
    monkeypatch.setattr(
        "cli.model.list_available_models",
        lambda _root: [
            {
                "key": "anthropic:claude-sonnet-4-5",
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "api_key_env": "ANTHROPIC_API_KEY",
            }
        ],
    )

    def fail_create_model_client(**_kwargs):
        raise AssertionError("missing keys must not build an echo fallback")

    monkeypatch.setattr("cli.llm.providers.create_model_client", fail_create_model_client)

    workspace = SimpleNamespace(root=tmp_path)
    result = app_module._maybe_build_orchestrator(
        workspace,
        session=None,
        store=None,
        echo=lambda _line: None,
    )

    assert result is None
