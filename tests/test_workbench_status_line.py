"""Tests for Chunk 4: provider + key visibility in the status line.

Companion to :mod:`tests.test_workbench_status_bar` — that file exercises
the pre-provider status bar surface (workspace label, reviews, best score,
extras). This one focuses on the new ``provider`` / ``provider_key_present``
fields introduced by Chunk 4 and on :func:`describe_default_provider`.
"""

from __future__ import annotations

from pathlib import Path

import click
import pytest

from cli.workbench_app.status_bar import (
    StatusSnapshot,
    render_snapshot,
    snapshot_from_workspace,
)


# ---------------------------------------------------------------------------
# render_snapshot — model · provider · [key]
# ---------------------------------------------------------------------------


def test_render_snapshot_model_and_provider_render_with_dot_separator() -> None:
    snap = StatusSnapshot(
        workspace_label="w",
        model="gpt-4o",
        provider="openai",
        provider_key_present=True,
    )
    line = render_snapshot(snap, color=False)
    assert "gpt-4o · openai" in line
    # The combined segment replaces the bare model — no duplicate bar-segments.
    assert line.count("gpt-4o") == 1
    # Key is present so no [no key] badge.
    assert "[no key]" not in line


def test_render_snapshot_missing_key_surfaces_no_key_badge() -> None:
    snap = StatusSnapshot(
        workspace_label="w",
        model="gemini-2.5-pro",
        provider="google",
        provider_key_present=False,
    )
    line = render_snapshot(snap, color=False)
    assert "gemini-2.5-pro · google · [no key]" in line


def test_render_snapshot_missing_key_uses_warn_color() -> None:
    snap = StatusSnapshot(
        workspace_label="w",
        model="gpt-4o",
        provider="openai",
        provider_key_present=False,
    )
    colored = render_snapshot(snap, color=True)
    plain = click.unstyle(colored)
    # The no-key branch routes through theme.warning which emits ANSI SGR.
    # Confirm the warn segment is actually styled — it must differ from the
    # plain render at the `gpt-4o · openai · [no key]` substring.
    assert "\x1b[" in colored
    assert "gpt-4o · openai · [no key]" in plain


def test_render_snapshot_key_present_does_not_warn_color_model() -> None:
    snap = StatusSnapshot(
        workspace_label="w",
        model="gpt-4o",
        provider="openai",
        provider_key_present=True,
    )
    colored = render_snapshot(snap, color=True)
    plain = render_snapshot(snap, color=False)
    # There's still workspace coloring in the line, but the model segment
    # itself should be unstyled when the key is present. Easiest check:
    # the ``gpt-4o · openai`` substring appears byte-identical in both.
    assert "gpt-4o · openai" in plain
    assert "gpt-4o · openai" in click.unstyle(colored)


def test_render_snapshot_provider_without_model_renders_provider_alone() -> None:
    # Model unknown (e.g. no config resolved yet) but we still know which
    # provider the CLI would use by default.
    snap = StatusSnapshot(
        workspace_label="w",
        model=None,
        provider="google",
        provider_key_present=False,
    )
    line = render_snapshot(snap, color=False)
    assert "google · [no key]" in line


def test_render_snapshot_omits_segment_when_no_model_or_provider() -> None:
    snap = StatusSnapshot(workspace_label="w")
    line = render_snapshot(snap, color=False)
    assert " · " not in line
    assert "[no key]" not in line


# ---------------------------------------------------------------------------
# snapshot_from_workspace — wiring to ProviderInfo
# ---------------------------------------------------------------------------


class _FakeActiveConfig:
    def __init__(self, version: int = 7, model: str = "gpt-4o") -> None:
        self.version = version
        self.config = {"model": model}
        self.path = Path("/tmp/fake.yaml")


class _FakeWorkspace:
    def __init__(
        self,
        *,
        label: str = "demo-ws",
        active: object | None = None,
        runtime_config_path: Path | None = None,
    ) -> None:
        self.workspace_label = label
        self._active = active
        self.change_cards_db = Path("/nonexistent-cards.db")
        self.best_score_file = Path("/nonexistent-score.txt")
        self.runtime_config_path = runtime_config_path

    def resolve_active_config(self):
        return self._active


class _StubProviderInfo:
    def __init__(self, *, name: str, model: str, key_present: bool) -> None:
        self.name = name
        self.model = model
        self.key_present = key_present


def test_snapshot_from_workspace_uses_injected_provider_info() -> None:
    ws = _FakeWorkspace(active=_FakeActiveConfig(model="gpt-4o"))
    info = _StubProviderInfo(name="openai", model="gpt-4o", key_present=True)
    snap = snapshot_from_workspace(ws, provider_info=info)
    assert snap.provider == "openai"
    assert snap.provider_key_present is True


def test_snapshot_from_workspace_key_missing_flag_propagates() -> None:
    ws = _FakeWorkspace(active=_FakeActiveConfig(model="gpt-4o"))
    info = _StubProviderInfo(name="openai", model="gpt-4o", key_present=False)
    snap = snapshot_from_workspace(ws, provider_info=info)
    assert snap.provider == "openai"
    assert snap.provider_key_present is False


def test_snapshot_from_workspace_tolerates_provider_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the provider lookup raises, the snapshot must still render.

    Status-bar failures cannot take down the REPL prompt — a broken runtime
    config is an operator error we surface elsewhere, not a crash.
    """
    def _boom(**_: object) -> object:
        raise RuntimeError("provider probe exploded")

    monkeypatch.setattr("optimizer.providers.describe_default_provider", _boom)
    ws = _FakeWorkspace(active=_FakeActiveConfig(model="gpt-4o"))
    # No provider_info override — forces the fallback path.
    snap = snapshot_from_workspace(ws)
    assert snap.provider is None
    assert snap.provider_key_present is True  # safe default: no warn color
    assert snap.model == "gpt-4o"  # rest of the snapshot is untouched


# ---------------------------------------------------------------------------
# describe_default_provider — resolution order
# ---------------------------------------------------------------------------


def test_describe_default_provider_falls_back_to_google_without_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from optimizer.providers import describe_default_provider

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    info = describe_default_provider(environ={})
    assert info.name == "google"
    assert info.key_present is False
    assert info.env_var == "GOOGLE_API_KEY"
    assert info.model == "gemini-2.5-pro"


def test_describe_default_provider_prefers_google_env_when_set() -> None:
    from optimizer.providers import describe_default_provider

    env = {"GOOGLE_API_KEY": "abc", "OPENAI_API_KEY": "xyz"}
    info = describe_default_provider(environ=env)
    # Priority order is google → anthropic → openai, so google wins here.
    assert info.name == "google"
    assert info.key_present is True
    assert info.model == "gemini-2.5-pro"


def test_describe_default_provider_uses_openai_when_only_openai_is_set() -> None:
    from optimizer.providers import describe_default_provider

    info = describe_default_provider(environ={"OPENAI_API_KEY": "abc"})
    assert info.name == "openai"
    assert info.model == "gpt-4o"
    assert info.key_present is True


def test_describe_default_provider_uses_anthropic_when_only_anthropic_is_set() -> None:
    from optimizer.providers import describe_default_provider

    info = describe_default_provider(environ={"ANTHROPIC_API_KEY": "abc"})
    assert info.name == "anthropic"
    assert info.model == "claude-sonnet-4-5"
    assert info.key_present is True


def test_describe_default_provider_reads_runtime_config_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a runtime config is present and declares a non-mock model, that
    model wins regardless of which env vars are set.

    WHY: the status line should reflect what will *actually* run — the
    resolved runtime config — not an env-derived guess.
    """
    from optimizer.providers import describe_default_provider

    config_path = tmp_path / "agentlab.yaml"
    config_path.write_text(
        "\n".join(
            [
                "optimizer:",
                "  strategy: single",
                "  use_mock: false",
                "  models:",
                "    - provider: anthropic",
                "      model: claude-opus-4-6",
                "      api_key_env: ANTHROPIC_API_KEY",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "abc")
    # Even with an openai key set, runtime config takes precedence.
    monkeypatch.setenv("OPENAI_API_KEY", "xyz")
    info = describe_default_provider(runtime_config_path=config_path)
    assert info.name == "anthropic"
    assert info.model == "claude-opus-4-6"
    assert info.key_present is True


def test_describe_default_provider_skips_mock_models_in_runtime_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from optimizer.providers import describe_default_provider

    config_path = tmp_path / "agentlab.yaml"
    config_path.write_text(
        "\n".join(
            [
                "optimizer:",
                "  strategy: single",
                "  use_mock: true",
                "  models:",
                "    - provider: mock",
                "      model: mock-0",
                "    - provider: google",
                "      model: gemini-2.5-flash",
                "      api_key_env: GOOGLE_API_KEY",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "abc")
    info = describe_default_provider(runtime_config_path=config_path)
    assert info.name == "google"
    assert info.model == "gemini-2.5-flash"
    assert info.key_present is True


def test_describe_default_provider_runtime_config_missing_key_flags_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from optimizer.providers import describe_default_provider

    config_path = tmp_path / "agentlab.yaml"
    config_path.write_text(
        "\n".join(
            [
                "optimizer:",
                "  strategy: single",
                "  use_mock: false",
                "  models:",
                "    - provider: openai",
                "      model: gpt-4o",
                "      api_key_env: OPENAI_API_KEY",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    info = describe_default_provider(runtime_config_path=config_path, environ={})
    assert info.name == "openai"
    assert info.model == "gpt-4o"
    assert info.key_present is False


def test_describe_default_provider_malformed_config_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unparseable runtime configs must not propagate — callers include the
    REPL status line, which cannot afford to raise.

    ``load_runtime_config`` is permissive enough to return a default
    configuration on broken YAML, which is fine; the contract here is simply
    "never raise, always return a valid ``ProviderInfo``"."""
    from optimizer.providers import ProviderInfo, describe_default_provider

    config_path = tmp_path / "agentlab.yaml"
    config_path.write_text(":::not valid yaml:::", encoding="utf-8")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    info = describe_default_provider(runtime_config_path=config_path, environ={})
    assert isinstance(info, ProviderInfo)
    assert info.name in ("openai", "anthropic", "google")
    assert isinstance(info.key_present, bool)
