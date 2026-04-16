"""R1.11: guard test - no tracked template yaml may force mock mode.

Also asserts bootstrap's runtime-mode resolution stays consistent so future
refactors can't silently flip the default back to use_mock: true.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cli import bootstrap


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "docs" / "templates"

# All env vars that bootstrap._has_api_key inspects. Tests that simulate a
# "no key" environment must clear every one of these; otherwise a CI runner
# that happens to set e.g. GEMINI_API_KEY would cause spurious flips.
_API_KEY_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_API_KEY",
    "GEMINI_API_KEY",
)


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _clear_api_keys(monkeypatch) -> None:
    for var in _API_KEY_VARS:
        monkeypatch.delenv(var, raising=False)


def test_no_tracked_template_forces_use_mock():
    """docs/templates/*.yaml must not bake use_mock: true in."""
    yamls = list(TEMPLATES_DIR.glob("*.yaml"))
    assert yamls, f"No template yamls found at {TEMPLATES_DIR}"
    offenders = []
    for yaml_path in yamls:
        data = _load_yaml(yaml_path)
        optimizer = (data or {}).get("optimizer") or {}
        if optimizer.get("use_mock") is True:
            offenders.append(str(yaml_path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"Template yamls must not set optimizer.use_mock=true: {offenders}. "
        "Live mode is the default; mock is opt-in per workspace."
    )


def test_resolve_runtime_use_mock_explicit_live(monkeypatch):
    # Explicit live always wins regardless of env.
    _clear_api_keys(monkeypatch)
    assert bootstrap._resolve_runtime_use_mock("live") is False


def test_resolve_runtime_use_mock_explicit_mock(monkeypatch):
    _clear_api_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "a" * 40)
    # Explicit mock always wins even if key is present.
    assert bootstrap._resolve_runtime_use_mock("mock") is True


def test_resolve_runtime_use_mock_auto_with_key(monkeypatch):
    _clear_api_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "a" * 40)
    assert bootstrap._resolve_runtime_use_mock("auto") is False


def test_resolve_runtime_use_mock_auto_without_key(monkeypatch):
    _clear_api_keys(monkeypatch)
    assert bootstrap._resolve_runtime_use_mock("auto") is True


def test_resolve_runtime_use_mock_invalid_raises():
    with pytest.raises(ValueError):
        bootstrap._resolve_runtime_use_mock("weird")


def test_write_runtime_config_live_produces_use_mock_false(tmp_path, monkeypatch):
    """In live mode, the produced yaml must have use_mock: false."""
    from cli.workspace import AgentLabWorkspace, infer_workspace_metadata

    _clear_api_keys(monkeypatch)

    # Construct a minimal workspace rooted at tmp_path.
    meta = infer_workspace_metadata(tmp_path)
    workspace = AgentLabWorkspace(root=tmp_path, metadata=meta)

    bootstrap.write_runtime_config(workspace, mode="live")

    config_yaml = workspace.runtime_config_path
    assert config_yaml.exists(), f"Expected {config_yaml} to be written"
    data = _load_yaml(config_yaml)
    optimizer = data.get("optimizer") or {}
    assert optimizer.get("use_mock") is False, (
        f"write_runtime_config(mode='live') should produce use_mock=false, got {optimizer}"
    )


def test_write_runtime_config_auto_with_key_produces_use_mock_false(tmp_path, monkeypatch):
    """In auto mode with a provider key present, use_mock must be false."""
    from cli.workspace import AgentLabWorkspace, infer_workspace_metadata

    _clear_api_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "a" * 40)

    meta = infer_workspace_metadata(tmp_path)
    workspace = AgentLabWorkspace(root=tmp_path, metadata=meta)

    bootstrap.write_runtime_config(workspace, mode="auto")

    config_yaml = workspace.runtime_config_path
    data = _load_yaml(config_yaml)
    optimizer = data.get("optimizer") or {}
    assert optimizer.get("use_mock") is False
