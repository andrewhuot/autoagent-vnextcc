"""Tests for the settings API routes that manage API keys and runtime mode."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest
import yaml

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.config.runtime import load_runtime_config
from api.routes import health as health_routes
from api.routes import settings as settings_routes
from api.routes import setup as setup_routes
from cli.workspace import AgentLabWorkspace


class _StubObserver:
    """Minimal observer stub for the health route in settings tests."""

    def observe(self, window: int = 100) -> SimpleNamespace:  # noqa: ARG002
        metrics = SimpleNamespace(
            success_rate=1.0,
            avg_latency_ms=12.5,
            error_rate=0.0,
            safety_violation_rate=0.0,
            avg_cost=0.0,
            total_conversations=0,
        )
        return SimpleNamespace(
            metrics=metrics,
            anomalies=[],
            failure_buckets={},
            needs_optimization=False,
            reason="",
        )


def _seed_workspace(root: Path) -> None:
    workspace = AgentLabWorkspace.create(
        root,
        name="Demo Workspace",
        template="customer-support",
        agent_name="Support Agent",
        platform="Google ADK",
    )
    workspace.ensure_structure()
    workspace.save_metadata()
    (root / "agentlab.yaml").write_text(
        yaml.safe_dump(
            {
                "optimizer": {
                    "use_mock": True,
                    "strategy": "single",
                    "models": [
                        {
                            "provider": "openai",
                            "model": "gpt-4o",
                            "api_key_env": "OPENAI_API_KEY",
                        },
                        {
                            "provider": "anthropic",
                            "model": "claude-sonnet-4-5",
                            "api_key_env": "ANTHROPIC_API_KEY",
                        },
                        {
                            "provider": "google",
                            "model": "gemini-2.5-pro",
                            "api_key_env": "GOOGLE_API_KEY",
                        },
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    _seed_workspace(tmp_path)
    for env_name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env_name, raising=False)

    app = FastAPI()
    app.include_router(setup_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(health_routes.router)
    app.state.observer = _StubObserver()
    app.state.runtime_config = load_runtime_config("agentlab.yaml")
    app.state.proposer = SimpleNamespace(
        use_mock=True,
        mock_reason="Mock mode explicitly enabled by optimizer.use_mock.",
    )
    app.state.eval_runner = SimpleNamespace(
        mock_mode_messages=["Running in mock mode — add API keys for live optimization"]
    )
    return TestClient(app)


def _api_key(payload: dict, env_name: str) -> dict:
    for item in payload["doctor"]["api_keys"]:
        if item["name"] == env_name:
            return item
    raise AssertionError(f"Missing API key entry for {env_name}")


def test_save_keys_persists_workspace_env_and_masks_saved_values(
    client: TestClient,
    tmp_path: Path,
) -> None:
    response = client.post(
        "/api/settings/keys",
        json={"google_api_key": "AIza-test-key-123456"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "API keys saved."

    env_path = tmp_path / ".agentlab" / ".env"
    assert env_path.exists()
    assert "GOOGLE_API_KEY=AIza-test-key-123456" in env_path.read_text(encoding="utf-8")

    overview = client.get("/api/setup/overview")
    assert overview.status_code == 200
    google_key = _api_key(overview.json(), "GOOGLE_API_KEY")
    assert google_key["configured"] is True
    assert google_key["masked_value"] == "AIz...123456"
    assert google_key["source"] == "workspace"


def test_saving_one_key_does_not_clear_existing_saved_keys(
    client: TestClient,
    tmp_path: Path,
) -> None:
    first_response = client.post(
        "/api/settings/keys",
        json={"google_api_key": "AIza-first-key-123456"},
    )
    assert first_response.status_code == 200

    second_response = client.post(
        "/api/settings/keys",
        json={"openai_api_key": "sk-second-key-abcdef"},
    )
    assert second_response.status_code == 200

    env_path = tmp_path / ".agentlab" / ".env"
    env_contents = env_path.read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY=AIza-first-key-123456" in env_contents
    assert "OPENAI_API_KEY=sk-second-key-abcdef" in env_contents


def test_switch_mode_to_live_requires_a_configured_key(client: TestClient) -> None:
    response = client.post("/api/settings/mode", json={"mode": "live"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Add an API key above to enable live mode"


def test_saving_a_key_and_switching_to_live_updates_setup_and_health_immediately(
    client: TestClient,
) -> None:
    save_response = client.post(
        "/api/settings/keys",
        json={"openai_api_key": "sk-live-key-abcdef"},
    )
    assert save_response.status_code == 200

    mode_response = client.post("/api/settings/mode", json={"mode": "live"})
    assert mode_response.status_code == 200
    mode_payload = mode_response.json()
    assert mode_payload["preferred_mode"] == "live"
    assert mode_payload["effective_mode"] == "live"

    overview = client.get("/api/setup/overview")
    assert overview.status_code == 200
    overview_payload = overview.json()
    assert overview_payload["doctor"]["preferred_mode"] == "live"
    assert overview_payload["doctor"]["effective_mode"] == "live"
    assert any(
        provider["provider"] == "openai" and provider["configured"] is True
        for provider in overview_payload["doctor"]["providers"]
    )

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["mock_mode"] is False


def test_test_key_returns_invalid_api_key_for_auth_failures(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_unauthorized(request, timeout=0, context=None):  # noqa: ANN001, ARG001
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise_unauthorized)

    response = client.post(
        "/api/settings/test-key",
        json={"provider": "openai", "api_key": "sk-invalid"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid API key."


def test_test_key_uses_the_provider_client_for_validation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: dict[str, str] = {}

    class _StubHTTPResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, D401
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "id": "chatcmpl-test",
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            ).encode("utf-8")

    def _fake_urlopen(request, timeout=0, context=None):  # noqa: ANN001, ARG001
        captured_headers.update(dict(request.headers))
        return _StubHTTPResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    response = client.post(
        "/api/settings/test-key",
        json={"provider": "openai", "api_key": "sk-valid-abcdef"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["provider"] == "openai"
    assert captured_headers["Authorization"] == "Bearer sk-valid-abcdef"


def test_test_key_treats_rate_limit_as_valid_but_degraded(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_rate_limit(request, timeout=0, context=None):  # noqa: ANN001, ARG001
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise_rate_limit)

    response = client.post(
        "/api/settings/test-key",
        json={"provider": "google", "api_key": "AIza-test-key-123456"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["provider"] == "google"
    assert payload["message"] == "Key accepted, but the provider is currently rate-limiting requests (HTTP 429)."
    assert payload["masked_value"] == "AIz...123456"


def test_test_key_returns_connection_failure_for_url_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_ssl_error(request, timeout=0, context=None):  # noqa: ANN001, ARG001
        raise urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    monkeypatch.setattr("urllib.request.urlopen", _raise_ssl_error)

    response = client.post(
        "/api/settings/test-key",
        json={"provider": "google", "api_key": "AIza-test-key-123456"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Connection test failed: "
        "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>"
    )
