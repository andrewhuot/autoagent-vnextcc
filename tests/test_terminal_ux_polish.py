"""Tests for terminal UX polish: /help categories, /find, /keybindings, footer.

The implementations live in:

* :mod:`cli.workbench_app.slash` — ``/help`` categorization, ``/help <query>``
  fuzzy filter, and the new ``/find`` + ``/keybindings`` handlers.
* :mod:`cli.workbench_app.help_text` — the shared ``?`` shortcut reference.
* :mod:`cli.workbench_app.pt_prompt` — ``render_bottom_toolbar`` session
  label ladder.
* :mod:`cli.workbench_app.tui.widgets.status_footer` — the pure
  ``format_status_line`` / ``format_footer_line`` helpers.

All of these are pure or near-pure so the tests can assert on strings
directly without spinning up prompt_toolkit or Textual.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import click
import pytest

from cli.sessions import Session, SessionStore
from cli.workbench_app.commands import CommandRegistry, LocalCommand
from cli.workbench_app.help_text import render_shortcuts_help
from cli.workbench_app.pt_prompt import render_bottom_toolbar
from cli.workbench_app.slash import (
    SlashContext,
    _category_for,
    _filter_commands,
    _parse_find_scope,
    build_builtin_registry,
    dispatch,
)
from cli.workbench_app.store import (
    CoordinatorStatus,
    FooterSlice,
    StatusBarSlice,
)
from cli.workbench_app.tui.widgets.status_footer import (
    format_footer_line,
    format_status_line,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeWorkspace:
    root: Path
    workspace_label: str = "workspace"

    @property
    def agentlab_dir(self) -> Path:
        return self.root / ".agentlab"


class _EchoCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


@pytest.fixture
def echo() -> _EchoCapture:
    return _EchoCapture()


@pytest.fixture
def registry() -> CommandRegistry:
    return build_builtin_registry()


@pytest.fixture
def ctx_with_store(
    tmp_path: Path, echo: _EchoCapture, registry: CommandRegistry
) -> SlashContext:
    workspace = _FakeWorkspace(root=tmp_path)
    workspace.agentlab_dir.mkdir(parents=True, exist_ok=True)
    store = SessionStore(tmp_path)
    return SlashContext(
        echo=echo,
        registry=registry,
        workspace=workspace,
        session_store=store,
    )


# ---------------------------------------------------------------------------
# /help — categorized output
# ---------------------------------------------------------------------------


def test_help_groups_commands_into_categories(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    """``/help`` should split the builtin block into named categories so
    operators can scan a long command surface quickly."""
    dispatch(ctx_with_store, "/help")
    rendered = click.unstyle("\n".join(echo.lines))
    # Section header still present.
    assert "Slash Commands" in rendered
    # Source header.
    assert "Builtin Commands" in rendered
    # Two categories that must always carry content.
    assert "Session" in rendered
    assert "Help & Meta" in rendered
    # Known commands live under their expected categories (surface check —
    # exact category layout is asserted in the unit tests below).
    assert "/resume" in rendered
    assert "/help" in rendered
    assert "/find" in rendered
    assert "/keybindings" in rendered


def test_help_detail_still_works_for_exact_match(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    dispatch(ctx_with_store, "/help resume")
    rendered = click.unstyle("\n".join(echo.lines))
    assert rendered.strip().startswith("/resume")
    # Kind is a card field, always emitted.
    assert "Kind: local" in rendered


def test_help_treats_partial_token_as_fuzzy_filter(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    """``/help sess`` should fall through to the filter and return matches
    instead of a "No command named" error."""
    dispatch(ctx_with_store, "/help sess")
    rendered = click.unstyle("\n".join(echo.lines))
    assert "Matching 'sess'" in rendered
    assert "/sessions" in rendered
    # Unrelated commands should be absent from the filtered view.
    assert "/doctor" not in rendered


def test_help_fuzzy_filter_shows_no_matches_message(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    dispatch(ctx_with_store, "/help zzz-no-match")
    rendered = click.unstyle("\n".join(echo.lines))
    assert "No commands matched" in rendered


def test_category_for_maps_known_builtins(registry: CommandRegistry) -> None:
    """Spot-check the category resolver for high-traffic commands."""
    lookup = {c.name: c for c in registry.visible()}
    assert _category_for(lookup["resume"]) == "Session"
    assert _category_for(lookup["memory"]) == "Memory & Context"
    assert _category_for(lookup["theme"]) == "Config & Theme"
    assert _category_for(lookup["find"]) == "Help & Meta"
    assert _category_for(lookup["keybindings"]) == "Help & Meta"


def test_filter_commands_prefers_name_matches_over_description(
    registry: CommandRegistry,
) -> None:
    hits = _filter_commands(registry, "resume")
    assert hits, "expected at least one match for 'resume'"
    assert hits[0].name == "resume"


# ---------------------------------------------------------------------------
# /find — scoped fuzzy search
# ---------------------------------------------------------------------------


def test_parse_find_scope_extracts_cmd_prefix() -> None:
    assert _parse_find_scope("cmd:status") == ("cmd", "status")
    assert _parse_find_scope("SESS:abc") == ("sess", "abc")
    assert _parse_find_scope("memory:mine") == ("mem", "mine")
    assert _parse_find_scope("status") == ("all", "status")


def test_find_without_args_renders_help_card(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    dispatch(ctx_with_store, "/find")
    rendered = click.unstyle("\n".join(echo.lines))
    assert "Find — quick-open search" in rendered
    assert "/find <query>" in rendered


def test_find_surfaces_commands_by_name(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    dispatch(ctx_with_store, "/find status")
    rendered = click.unstyle("\n".join(echo.lines))
    assert "Commands" in rendered
    assert "/status" in rendered


def test_find_surfaces_saved_sessions_by_title(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    store = ctx_with_store.session_store
    assert store is not None
    store.create(title="Terminal UX polish work")
    dispatch(ctx_with_store, "/find terminal")
    rendered = click.unstyle("\n".join(echo.lines))
    assert "Sessions" in rendered
    assert "Terminal UX polish work" in rendered


def test_find_surfaces_memory_snippets(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    memory_dir = ctx_with_store.workspace.agentlab_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "project_r6.md").write_text(
        "## R6 notes\nFixture: acceptance slice B calibration\n",
        encoding="utf-8",
    )
    dispatch(ctx_with_store, "/find mem:calibration")
    rendered = click.unstyle("\n".join(echo.lines))
    assert "Memories" in rendered
    assert "project_r6" in rendered


def test_find_reports_no_matches_cleanly(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    dispatch(ctx_with_store, "/find zzz-nothing-here")
    rendered = click.unstyle("\n".join(echo.lines))
    assert "No matches" in rendered


# ---------------------------------------------------------------------------
# /keybindings — inspect + edit
# ---------------------------------------------------------------------------


def test_keybindings_lists_defaults_and_hardwired(
    ctx_with_store: SlashContext, echo: _EchoCapture
) -> None:
    dispatch(ctx_with_store, "/keybindings")
    rendered = click.unstyle("\n".join(echo.lines))
    assert "Keyboard Bindings" in rendered
    assert "Built-in" in rendered
    # A default binding from DEFAULT_BINDINGS.
    assert "submit" in rendered
    # A hard-wired prompt binding.
    assert "mode-cycle" in rendered
    assert "hard-wired" in rendered


def test_keybindings_shows_user_overrides_from_config(
    ctx_with_store: SlashContext,
    echo: _EchoCapture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "keybindings.json"
    config_path.write_text(
        json.dumps(
            {
                "mode": "default",
                "bindings": [
                    {"keys": "ctrl+k", "command": "clear-transcript"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "cli.keybindings.loader.DEFAULT_CONFIG_PATH", config_path
    )
    dispatch(ctx_with_store, "/keybindings")
    rendered = click.unstyle("\n".join(echo.lines))
    assert "User overrides" in rendered
    assert "ctrl+k" in rendered


def test_keybindings_edit_creates_stub_and_launches_editor(
    ctx_with_store: SlashContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "keybindings.json"
    assert not config_path.exists()
    monkeypatch.setattr(
        "cli.keybindings.loader.DEFAULT_CONFIG_PATH", config_path
    )
    launched: list[list[str]] = []

    def _fake_run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        launched.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("cli.workbench_app.slash.subprocess.run", _fake_run)
    monkeypatch.setenv("EDITOR", "fake-editor")

    result = dispatch(ctx_with_store, "/keybindings edit")

    assert config_path.exists()
    assert launched == [["fake-editor", str(config_path)]]
    assert result.handled is True


# ---------------------------------------------------------------------------
# Footer polish — prompt_toolkit toolbar + TUI status lines
# ---------------------------------------------------------------------------


def test_bottom_toolbar_drops_session_label_when_narrow() -> None:
    """When the terminal is too narrow the session label is the first
    segment dropped — the keyboard affordances always win the space
    budget."""
    toolbar = render_bottom_toolbar("default", width=36, session_label="big-name")
    # "big-name" shouldn't fit alongside the shortcuts at width=36.
    assert "big-name" not in toolbar
    assert "Default permissions on" in toolbar
    assert len(toolbar) <= 36


def test_bottom_toolbar_includes_session_label_when_wide() -> None:
    toolbar = render_bottom_toolbar(
        "default", width=120, session_label="r6-fix · a3b1"
    )
    assert "r6-fix" in toolbar
    assert "Default permissions on" in toolbar
    assert "? shortcuts" in toolbar


def test_status_line_includes_session_title_and_tokens() -> None:
    sb = StatusBarSlice(
        workspace_label="my-workspace",
        config_version=4,
        model="opus-4-7",
        provider="anthropic",
        provider_key_present=True,
        pending_reviews=0,
        best_score=None,
        agentlab_version="0.9.1",
        session_title="r6 acceptance",
        tokens_used=4_000,
        context_limit=200_000,
    )
    line = format_status_line(sb)
    assert "my-workspace" in line
    assert "v004" in line
    assert "opus-4-7" in line
    assert "r6 acceptance" in line
    # Token segment is present and includes the commonly-used formatting.
    assert "4,000/200,000 tok" in line


def test_status_line_marks_missing_api_key() -> None:
    sb = StatusBarSlice(
        workspace_label="ws",
        config_version=None,
        model="opus-4-7",
        provider="anthropic",
        provider_key_present=False,
        pending_reviews=0,
        best_score=None,
        agentlab_version="dev",
        session_title=None,
        tokens_used=None,
        context_limit=None,
    )
    line = format_status_line(sb)
    assert "[no key]" in line


def test_footer_line_shows_coordinator_badge() -> None:
    ft = FooterSlice(
        permission_mode="default",
        active_shells=2,
        active_tasks=1,
        coordinator_status=CoordinatorStatus.RUNNING,
    )
    line = format_footer_line(ft)
    assert "default permissions on" in line
    assert "2 shells" in line
    assert "1 task" in line
    assert "running" in line


def test_footer_line_reads_idle_when_nothing_active() -> None:
    ft = FooterSlice(
        permission_mode="plan",
        active_shells=0,
        active_tasks=0,
        coordinator_status=CoordinatorStatus.IDLE,
    )
    line = format_footer_line(ft)
    assert "plan permissions on" in line
    assert "idle" in line


# ---------------------------------------------------------------------------
# Shortcut reference (? / /shortcuts) — surface the new discovery commands
# ---------------------------------------------------------------------------


def test_shortcut_reference_mentions_new_discovery_commands() -> None:
    rendered = click.unstyle(render_shortcuts_help())
    assert "/help" in rendered
    assert "/find" in rendered
    assert "/keybindings" in rendered
    assert "Discover" in rendered
