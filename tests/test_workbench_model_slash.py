"""Tests for cli/workbench_app/model_slash.py — the ``/model`` handler (T14)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from cli.sessions import Session, SessionStore
from cli.workbench_app.commands import CommandRegistry, LocalCommand
from cli.workbench_app.model_slash import (
    _credential_note,
    _format_list,
    _match_model,
    _resolve_root,
    _session_override,
    build_model_command,
)
from cli.workbench_app.slash import DispatchResult, SlashContext, dispatch


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _EchoCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    @property
    def plain(self) -> list[str]:
        return [_strip_ansi(l) for l in self.lines]


def _models(extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    base: list[dict[str, Any]] = [
        {
            "key": "anthropic:claude-opus-4-6",
            "provider": "anthropic",
            "model": "claude-opus-4-6",
            "role": "proposer",
            "api_key_env": "ANTHROPIC_API_KEY",
            "input_cost_per_1k_tokens": 0.0,
            "output_cost_per_1k_tokens": 0.0,
        },
        {
            "key": "openai:gpt-4o",
            "provider": "openai",
            "model": "gpt-4o",
            "role": "evaluator",
            "api_key_env": "OPENAI_API_KEY",
            "input_cost_per_1k_tokens": 0.0,
            "output_cost_per_1k_tokens": 0.0,
        },
    ]
    if extra:
        base.extend(extra)
    return base


def _make_lister(models: list[dict[str, Any]]):
    calls: list[str | Path] = []

    def _lister(root: str | Path) -> list[dict[str, Any]]:
        calls.append(root)
        return list(models)

    _lister.calls = calls  # type: ignore[attr-defined]
    return _lister


def _make_ctx(
    echo: _EchoCapture,
    models: list[dict[str, Any]] | None = None,
    *,
    session: Session | None = None,
    store: SessionStore | None = None,
    workspace: Any | None = None,
    lister_raises: Exception | None = None,
) -> SlashContext:
    registry = CommandRegistry()
    if lister_raises is not None:
        def _lister(_root: str | Path) -> list[dict[str, Any]]:
            raise lister_raises  # type: ignore[misc]

        registry.register(build_model_command(lister=_lister))
    else:
        resolved = _models() if models is None else models
        registry.register(
            build_model_command(lister=_make_lister(resolved))
        )
    return SlashContext(
        echo=echo,
        registry=registry,
        workspace=workspace,
        session=session,
        session_store=store,
    )


@pytest.fixture
def echo() -> _EchoCapture:
    return _EchoCapture()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_resolve_root_without_workspace_returns_cwd_path() -> None:
    assert _resolve_root(None) == Path(".")


def test_resolve_root_reads_workspace_root(tmp_path: Path) -> None:
    class _WS:
        root = tmp_path

    assert _resolve_root(_WS()) == tmp_path


def test_resolve_root_tolerates_workspace_without_root_attribute() -> None:
    class _WS:
        pass

    assert _resolve_root(_WS()) == Path(".")


def test_session_override_none_when_session_missing() -> None:
    assert _session_override(None) is None


def test_session_override_reads_model_from_settings() -> None:
    session = Session(session_id="x")
    session.settings_overrides["model"] = "anthropic:claude-opus-4-6"
    assert _session_override(session) == "anthropic:claude-opus-4-6"


def test_session_override_handles_non_dict_settings() -> None:
    class _S:
        settings_overrides = None

    assert _session_override(_S()) is None


def test_match_model_exact_key() -> None:
    assert _match_model(_models(), "anthropic:claude-opus-4-6")["model"] == (
        "claude-opus-4-6"
    )


def test_match_model_is_case_insensitive() -> None:
    assert _match_model(_models(), "OPENAI:GPT-4O")["key"] == "openai:gpt-4o"


def test_match_model_unique_short_name() -> None:
    assert _match_model(_models(), "gpt-4o")["key"] == "openai:gpt-4o"


def test_match_model_ambiguous_short_returns_none() -> None:
    dup = _models(
        extra=[
            {
                "key": "azure:gpt-4o",
                "provider": "azure",
                "model": "gpt-4o",
                "role": "evaluator",
                "api_key_env": "AZURE_API_KEY",
                "input_cost_per_1k_tokens": 0.0,
                "output_cost_per_1k_tokens": 0.0,
            }
        ]
    )
    assert _match_model(dup, "gpt-4o") is None


def test_match_model_empty_string_returns_none() -> None:
    assert _match_model(_models(), "   ") is None


def test_credential_note_detects_env_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_API_KEY", "abc")
    assert (
        _credential_note({"api_key_env": "FAKE_API_KEY"}) == "key set"
    )


def test_credential_note_reports_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FAKE_MISSING_KEY", raising=False)
    assert _credential_note({"api_key_env": "FAKE_MISSING_KEY"}) == (
        "missing FAKE_MISSING_KEY"
    )


def test_credential_note_without_env_says_no_credentials() -> None:
    assert _credential_note({"api_key_env": ""}) == "no credentials"
    assert _credential_note({"api_key_env": None}) == "no credentials"


def test_format_list_marks_active_model() -> None:
    out = _strip_ansi(
        _format_list(_models(), active_key="openai:gpt-4o")
    )
    lines = [l for l in out.splitlines() if "role=" in l]
    assert lines[0].strip().startswith("○ anthropic:claude-opus-4-6")
    assert lines[1].strip().startswith("● openai:gpt-4o")


def test_format_list_no_active_marker_when_none() -> None:
    out = _strip_ansi(_format_list(_models(), active_key=None))
    for line in out.splitlines():
        if "role=" in line:
            assert "●" not in line


# ---------------------------------------------------------------------------
# build_model_command — surface
# ---------------------------------------------------------------------------


def test_build_model_command_defaults() -> None:
    cmd = build_model_command()
    assert isinstance(cmd, LocalCommand)
    assert cmd.name == "model"
    assert cmd.kind == "local"
    assert cmd.source == "builtin"
    assert cmd.description == "List or switch the active session model"


# ---------------------------------------------------------------------------
# /model — listing mode (no args)
# ---------------------------------------------------------------------------


def test_model_list_no_args_renders_all_models(
    echo: _EchoCapture,
) -> None:
    ctx = _make_ctx(echo)
    result = dispatch(ctx, "/model")

    assert isinstance(result, DispatchResult)
    assert result.handled is True
    assert result.error is None
    plain = "\n".join(echo.plain)
    assert "anthropic:claude-opus-4-6" in plain
    assert "openai:gpt-4o" in plain
    assert "role=proposer" in plain
    assert "role=evaluator" in plain


def test_model_list_meta_says_no_override_when_none(
    echo: _EchoCapture,
) -> None:
    ctx = _make_ctx(echo, session=Session(session_id="s"))
    result = dispatch(ctx, "/model")
    assert any("No session override" in line for line in echo.plain)
    assert any(
        "No session override" in m for m in result.meta_messages
    )


def test_model_list_meta_reports_active_session_override(
    echo: _EchoCapture,
) -> None:
    session = Session(session_id="s")
    session.settings_overrides["model"] = "openai:gpt-4o"
    ctx = _make_ctx(echo, session=session)
    dispatch(ctx, "/model")
    assert any("Session override: openai:gpt-4o" in l for l in echo.plain)


def test_model_list_marks_active_with_dot(
    echo: _EchoCapture,
) -> None:
    session = Session(session_id="s")
    session.settings_overrides["model"] = "openai:gpt-4o"
    ctx = _make_ctx(echo, session=session)
    dispatch(ctx, "/model")
    body_lines = [l for l in echo.plain[0].splitlines() if "role=" in l]
    active_line = next(l for l in body_lines if "openai:gpt-4o" in l)
    other_line = next(l for l in body_lines if "anthropic" in l)
    assert "●" in active_line
    assert "●" not in other_line


def test_model_list_empty_models_message(echo: _EchoCapture) -> None:
    ctx = _make_ctx(echo, models=[])
    result = dispatch(ctx, "/model")
    assert "No models configured" in (result.output or "")


def test_model_list_surfaces_lister_errors(echo: _EchoCapture) -> None:
    ctx = _make_ctx(echo, lister_raises=FileNotFoundError("agentlab.yaml missing"))
    result = dispatch(ctx, "/model")
    assert "Could not load models" in (result.output or "")
    assert "agentlab.yaml missing" in (result.output or "")


# ---------------------------------------------------------------------------
# /model <key> — switching mode
# ---------------------------------------------------------------------------


def test_model_set_by_full_key_persists_to_session(
    echo: _EchoCapture, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="demo")
    ctx = _make_ctx(echo, session=session, store=store)

    result = dispatch(ctx, "/model openai:gpt-4o")

    assert result.handled is True
    assert session.settings_overrides["model"] == "openai:gpt-4o"
    # Reload from disk to confirm persistence.
    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert reloaded.settings_overrides["model"] == "openai:gpt-4o"
    assert "Session model → openai:gpt-4o" in _strip_ansi(result.output or "")


def test_model_set_by_short_name(
    echo: _EchoCapture, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create()
    ctx = _make_ctx(echo, session=session, store=store)

    result = dispatch(ctx, "/model gpt-4o")

    assert session.settings_overrides["model"] == "openai:gpt-4o"
    assert "Session model → openai:gpt-4o" in _strip_ansi(result.output or "")


def test_model_set_unknown_key_reports_error(
    echo: _EchoCapture, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create()
    ctx = _make_ctx(echo, session=session, store=store)

    result = dispatch(ctx, "/model totally-fake")

    assert result.handled is True
    assert "Unknown model: totally-fake" in _strip_ansi(result.output or "")
    assert "model" not in session.settings_overrides
    # Sanity: disk not mutated with bogus value.
    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert "model" not in reloaded.settings_overrides


def test_model_set_without_session_warns(echo: _EchoCapture) -> None:
    ctx = _make_ctx(echo, session=None, store=None)
    result = dispatch(ctx, "/model gpt-4o")
    assert "No active session" in _strip_ansi(result.output or "")


def test_model_set_without_store_still_updates_in_memory(
    echo: _EchoCapture,
) -> None:
    session = Session(session_id="s")
    ctx = _make_ctx(echo, session=session, store=None)
    result = dispatch(ctx, "/model gpt-4o")
    assert session.settings_overrides["model"] == "openai:gpt-4o"
    assert any(
        "Not persisted" in m for m in result.meta_messages
    )


def test_model_set_handles_store_save_failure(
    echo: _EchoCapture,
) -> None:
    session = Session(session_id="s")

    class _BrokenStore:
        def save(self, _session: Session) -> Path:
            raise OSError("disk full")

    ctx = _make_ctx(echo, session=session, store=_BrokenStore())
    result = dispatch(ctx, "/model gpt-4o")
    # In-memory mutation still visible so later dispatches see the override.
    assert session.settings_overrides["model"] == "openai:gpt-4o"
    assert "not persisted" in _strip_ansi(result.output or "").lower()
    assert "disk full" in _strip_ansi(result.output or "")


def test_model_set_meta_mentions_reset_hint(
    echo: _EchoCapture, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create()
    ctx = _make_ctx(echo, session=session, store=store)
    result = dispatch(ctx, "/model gpt-4o")
    assert any("/model reset" in m for m in result.meta_messages)


# ---------------------------------------------------------------------------
# /model reset|clear — drop the override
# ---------------------------------------------------------------------------


def test_model_reset_clears_override_and_persists(
    echo: _EchoCapture, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create()
    session.settings_overrides["model"] = "openai:gpt-4o"
    store.save(session)
    ctx = _make_ctx(echo, session=session, store=store)

    result = dispatch(ctx, "/model reset")

    assert "model" not in session.settings_overrides
    assert "Cleared session model override" in _strip_ansi(result.output or "")
    assert "openai:gpt-4o" in _strip_ansi(result.output or "")
    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert "model" not in reloaded.settings_overrides


def test_model_reset_alias_clear_also_works(
    echo: _EchoCapture, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create()
    session.settings_overrides["model"] = "openai:gpt-4o"
    ctx = _make_ctx(echo, session=session, store=store)

    dispatch(ctx, "/model clear")
    assert "model" not in session.settings_overrides


def test_model_reset_when_none_set_is_idempotent(
    echo: _EchoCapture,
) -> None:
    session = Session(session_id="s")
    ctx = _make_ctx(echo, session=session)
    result = dispatch(ctx, "/model reset")
    assert "No session model override" in _strip_ansi(result.output or "")


def test_model_reset_without_session_is_noop(echo: _EchoCapture) -> None:
    ctx = _make_ctx(echo, session=None)
    result = dispatch(ctx, "/model reset")
    assert "No session model override" in _strip_ansi(result.output or "")


def test_model_reset_tolerates_store_save_failure(
    echo: _EchoCapture,
) -> None:
    """Persistence is best-effort on reset — in-memory pop always wins."""
    session = Session(session_id="s")
    session.settings_overrides["model"] = "openai:gpt-4o"

    class _BrokenStore:
        def save(self, _session: Session) -> Path:
            raise OSError("disk full")

    ctx = _make_ctx(echo, session=session, store=_BrokenStore())
    result = dispatch(ctx, "/model reset")
    assert "model" not in session.settings_overrides
    assert "Cleared" in _strip_ansi(result.output or "")


# ---------------------------------------------------------------------------
# Default registry wiring (T14 adds /model as a built-in)
# ---------------------------------------------------------------------------


def test_default_builtin_registry_includes_model_command() -> None:
    from cli.workbench_app.slash import build_builtin_registry

    registry = build_builtin_registry()
    assert "model" in registry.names()
    cmd = registry.get("/model")
    assert isinstance(cmd, LocalCommand)


def test_default_builtin_registry_without_streaming_still_includes_model() -> None:
    from cli.workbench_app.slash import build_builtin_registry

    registry = build_builtin_registry(include_streaming=False)
    assert "model" in registry.names()
