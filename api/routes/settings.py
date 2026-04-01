"""Settings mutation routes for API-key storage, testing, and mode control."""

from __future__ import annotations

from typing import Literal
import urllib.error

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.runtime_state import refresh_runtime_state
from cli.mode import get_mode_preference, set_mode_preference, summarize_mode_state
from cli.providers import default_api_key_env_for, default_model_for
from cli.workspace_env import (
    collect_provider_api_key_statuses,
    load_workspace_env,
    mask_secret,
    resolve_workspace_env_value,
    write_workspace_env_values,
)
from optimizer.providers import LLMRequest, LLMRouter, ModelConfig, RetryPolicy

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SaveProviderKeysRequest(BaseModel):
    """Request body for saving provider API keys into the workspace env file."""

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None


class SetRuntimeModeRequest(BaseModel):
    """Request body for switching workspace runtime mode."""

    mode: Literal["mock", "auto", "live"]


class TestProviderKeyRequest(BaseModel):
    """Request body for provider key validation."""

    provider: Literal["openai", "anthropic", "google"]
    api_key: str | None = None
    model: str | None = Field(None, min_length=1)


def _mode_payload() -> dict[str, str | bool]:
    """Return the current preferred/effective mode summary."""
    summary = summarize_mode_state("agentlab.yaml")
    return {
        "preferred_mode": summary["preferred_mode"],
        "effective_mode": summary["effective_mode"],
        "mode_source": summary["mode_source"],
        "message": summary["message"],
        "real_provider_configured": summary["real_provider_configured"],
    }


def _provider_model(provider: str, requested_model: str | None) -> str:
    """Return the concrete model used for a provider connectivity test."""
    if requested_model and requested_model.strip():
        return requested_model.strip()

    runtime = summarize_mode_state("agentlab.yaml")["runtime"]
    for model in runtime.optimizer.models:
        if str(model.provider).strip().lower() == provider:
            return str(model.model)
    return default_model_for(provider)


@router.post("/keys")
async def save_provider_keys(body: SaveProviderKeysRequest, request: Request) -> dict:
    """Persist provider keys into `.agentlab/.env` and refresh runtime state."""
    field_to_env = {
        "openai_api_key": "OPENAI_API_KEY",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "google_api_key": "GOOGLE_API_KEY",
    }
    updates = {
        env_name: getattr(body, field_name)
        for field_name, env_name in field_to_env.items()
        if field_name in body.model_fields_set
    }
    write_workspace_env_values(updates)
    load_workspace_env(override=True)
    refresh_runtime_state(request.app)
    return {
        "message": "API keys saved.",
        "api_keys": collect_provider_api_key_statuses(),
        "mode": _mode_payload(),
    }


@router.post("/mode")
async def set_runtime_mode(body: SetRuntimeModeRequest, request: Request) -> dict:
    """Persist the preferred runtime mode and refresh app state immediately."""
    load_workspace_env()
    summary = summarize_mode_state("agentlab.yaml")
    if body.mode == "live" and not summary["real_provider_configured"]:
        raise HTTPException(status_code=400, detail="Add an API key above to enable live mode")

    set_mode_preference(body.mode)
    refresh_runtime_state(request.app)
    return _mode_payload()


@router.post("/test-key")
async def test_provider_key(body: TestProviderKeyRequest) -> dict:
    """Run a lightweight live provider request to validate one key."""
    env_name = default_api_key_env_for(body.provider)
    api_key = (body.api_key or resolve_workspace_env_value(env_name) or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="Enter an API key or save one first.")

    model_name = _provider_model(body.provider, body.model)
    provider = LLMRouter._build_provider(  # type: ignore[attr-defined]
        ModelConfig(
            provider=body.provider,
            model=model_name,
            api_key_env=env_name,
        )
    )

    previous_value = resolve_workspace_env_value(env_name)
    try:
        # Provider adapters resolve credentials from the process environment.
        import os

        os.environ[env_name] = api_key
        provider.complete(
            LLMRequest(
                prompt="Return the single word ok.",
                system="Provider connectivity check.",
                temperature=0.0,
                max_tokens=8,
            ),
            RetryPolicy(max_attempts=1, base_delay_seconds=0.0, max_delay_seconds=0.0, jitter_seconds=0.0),
        )
    except urllib.error.HTTPError as exc:
        if int(getattr(exc, "code", 0) or 0) in {401, 403}:
            raise HTTPException(status_code=400, detail="Invalid API key.")
        raise HTTPException(status_code=400, detail=f"Connection test failed: HTTP {exc.code}")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise HTTPException(status_code=400, detail=f"Connection test failed: {exc}")
    finally:
        import os

        if body.api_key is not None:
            if previous_value:
                os.environ[env_name] = previous_value
            else:
                os.environ.pop(env_name, None)

    return {
        "provider": body.provider,
        "model": model_name,
        "valid": True,
        "message": "Key valid.",
        "masked_value": mask_secret(api_key),
    }
