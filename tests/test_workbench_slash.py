"""Tests for cli/workbench_app/slash.py — dispatch + ported handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from cli.sessions import Session, SessionEntry, SessionStore
from cli.workbench_app.commands import (
    CommandRegistry,
    LocalCommand,
    LocalJSXCommand,
    PromptCommand,
)
from cli.workbench_app.slash import (
    DispatchResult,
    SlashContext,
    build_builtin_registry,
    dispatch,
    parse_slash_line,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeConfig:
    version: int = 3
    path: Path = Path("/tmp/config.json")
    config: dict = field(default_factory=lambda: {"model": "opus-4-6"})


@dataclass
class _FakeWorkspace:
    root: Path
    workspace_label: str = "workspace"
    active: _FakeConfig | None = None

    @property
    def agentlab_dir(self) -> Path:
        return self.root / ".agentlab"

    def resolve_active_config(self) -> _FakeConfig | None:
        return self.active

    def summarize_config(self, config: dict) -> str:
        return f"model={config.get('model', '?')}"


class _EchoCapture:
    """Echo sink that records lines and exposes them as a list."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


class _FakeClickInvoker:
    def __init__(self, outputs: dict[str, str] | None = None) -> None:
        self._outputs = outputs or {}
        self.calls: list[str] = []

    def __call__(self, command: str) -> str:
        self.calls.append(command)
        return self._outputs.get(command, f"stub:{command}")


@pytest.fixture
def echo() -> _EchoCapture:
    return _EchoCapture()


@pytest.fixture
def invoker() -> _FakeClickInvoker:
    return _FakeClickInvoker()


@pytest.fixture
def registry() -> CommandRegistry:
    return build_builtin_registry()


@pytest.fixture
def ctx(
    echo: _EchoCapture,
    invoker: _FakeClickInvoker,
    registry: CommandRegistry,
) -> SlashContext:
    return SlashContext(
        echo=echo,
        click_invoker=invoker,
        registry=registry,
    )


# ---------------------------------------------------------------------------
# parse_slash_line
# ---------------------------------------------------------------------------


def test_parse_slash_line_extracts_name_and_args() -> None:
    assert parse_slash_line("/eval --run-id abc") == ("eval", ["--run-id", "abc"])


def test_parse_slash_line_lowercases_name() -> None:
    assert parse_slash_line("/HELP") == ("help", [])


def test_parse_slash_line_returns_none_for_non_slash() -> None:
    assert parse_slash_line("build thing") is None
    assert parse_slash_line("") is None
    assert parse_slash_line("/") is None


def test_parse_slash_line_handles_quoted_args() -> None:
    assert parse_slash_line('/memory add "some note"') == (
        "memory",
        ["add", "some note"],
    )


def test_parse_slash_line_falls_back_on_unbalanced_quotes() -> None:
    # Should not raise — degrades to whitespace split, caller surfaces error.
    name, args = parse_slash_line('/review "open')  # type: ignore[misc]
    assert name == "review"
    assert args == ['"open']


# ---------------------------------------------------------------------------
# build_builtin_registry — the ten ported commands
# ---------------------------------------------------------------------------


def test_builtin_registry_contains_all_ten_commands(registry: CommandRegistry) -> None:
    expected = {
        "help",
        "status",
        "config",
        "memory",
        "doctor",
        "review",
        "mcp",
        "compact",
        "resume",
        "exit",
    }
    assert set(registry.names()) == expected


def test_builtin_registry_help_table_has_descriptions(
    registry: CommandRegistry,
) -> None:
    table = registry.help_table()
    assert table["/help"] == "Show available slash commands"
    assert table["/exit"] == "Exit the shell"


def test_builtin_registry_accepts_extra_commands() -> None:
    extra = LocalCommand(
        name="eval",
        description="Run eval",
        handler=lambda *_a, **_k: "eval ran",
    )
    registry = build_builtin_registry(extra=[extra])
    assert registry.get("/eval") is extra
    assert len(registry) == 11


# ---------------------------------------------------------------------------
# dispatch — generic behavior
# ---------------------------------------------------------------------------


def test_dispatch_returns_not_handled_for_free_text(ctx: SlashContext) -> None:
    result = dispatch(ctx, "build something")
    assert result == DispatchResult(handled=False)


def test_dispatch_unknown_command_surfaces_error(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    result = dispatch(ctx, "/nope")
    assert result.handled is True
    assert result.error == "unknown"
    assert any("Unknown command" in line for line in echo.lines)


def test_dispatch_echoes_handler_output(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    result = dispatch(ctx, "/status")
    assert result.handled is True
    assert result.output == "stub:status"
    assert echo.lines == ["stub:status"]


def test_dispatch_does_not_echo_none(
    echo: _EchoCapture,
) -> None:
    silent = LocalCommand(
        name="ping",
        description="silent",
        handler=lambda *_a, **_k: None,
    )
    registry = build_builtin_registry(extra=[silent])
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/ping")
    assert result.output is None
    assert echo.lines == []


def test_dispatch_rejects_non_local_command(
    echo: _EchoCapture,
) -> None:
    prompt_cmd = PromptCommand(
        name="explain",
        description="Prompt expansion",
        prompt_template="Explain {path}",
    )
    registry = build_builtin_registry(extra=[prompt_cmd])
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/explain")
    assert result.handled is True
    assert result.error == "unsupported-kind"
    assert any("inline dispatch" in line for line in echo.lines)


def test_dispatch_catches_handler_exceptions(
    echo: _EchoCapture,
) -> None:
    def _boom(*_a: object, **_k: object) -> str:
        raise RuntimeError("kaboom")

    exploding = LocalCommand(name="boom", description="x", handler=_boom)
    registry = build_builtin_registry(extra=[exploding])
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/boom")
    assert result.handled is True
    assert result.error == "kaboom"
    assert any("Error running /boom" in line for line in echo.lines)


def test_dispatch_without_registry_returns_error() -> None:
    ctx = SlashContext()
    result = dispatch(ctx, "/help")
    assert result.handled is True
    assert result.error == "no command registry bound"


def test_dispatch_scoped_registry_does_not_leak_onto_ctx(
    echo: _EchoCapture,
) -> None:
    outer = build_builtin_registry()
    scoped = CommandRegistry()
    scoped.register(
        LocalCommand(name="scoped", description="x", handler=lambda *_a, **_k: "ok")
    )
    ctx = SlashContext(echo=echo, registry=outer)
    result = dispatch(ctx, "/scoped", registry=scoped)
    assert result.handled is True
    assert result.output == "ok"
    # Outer registry must be restored after the scoped call.
    assert ctx.registry is outer


# ---------------------------------------------------------------------------
# Individual ported handlers
# ---------------------------------------------------------------------------


def test_help_handler_lists_all_commands(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    result = dispatch(ctx, "/help")
    assert result.handled is True
    assert result.output is not None
    rendered = result.output
    for name in ("/help", "/status", "/exit", "/resume"):
        assert name in rendered
    assert echo.lines == [rendered]


def test_exit_handler_requests_exit(ctx: SlashContext) -> None:
    result = dispatch(ctx, "/exit")
    assert result.handled is True
    assert result.exit is True
    assert ctx.exit_requested is True
    assert result.output == "  Goodbye."


def test_status_handler_delegates_to_click(
    ctx: SlashContext, invoker: _FakeClickInvoker
) -> None:
    dispatch(ctx, "/status")
    assert invoker.calls == ["status"]


def test_memory_handler_runs_memory_show(
    ctx: SlashContext, invoker: _FakeClickInvoker
) -> None:
    dispatch(ctx, "/memory")
    assert invoker.calls == ["memory show"]


def test_doctor_handler_runs_doctor(
    ctx: SlashContext, invoker: _FakeClickInvoker
) -> None:
    dispatch(ctx, "/doctor")
    assert invoker.calls == ["doctor"]


def test_review_handler_runs_review(
    ctx: SlashContext, invoker: _FakeClickInvoker
) -> None:
    dispatch(ctx, "/review")
    assert invoker.calls == ["review"]


def test_mcp_handler_runs_mcp_status(
    ctx: SlashContext, invoker: _FakeClickInvoker
) -> None:
    dispatch(ctx, "/mcp")
    assert invoker.calls == ["mcp status"]


def test_click_invoker_error_surfaces_as_transcript_line(
    echo: _EchoCapture, registry: CommandRegistry
) -> None:
    def _boom(_cmd: str) -> str:
        raise RuntimeError("click died")

    ctx = SlashContext(echo=echo, click_invoker=_boom, registry=registry)
    result = dispatch(ctx, "/status")
    assert result.output is not None
    assert "Error running 'status'" in result.output


def test_config_handler_with_no_workspace(ctx: SlashContext) -> None:
    result = dispatch(ctx, "/config")
    assert result.output == "  No workspace."


def test_config_handler_without_active_config(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    workspace = _FakeWorkspace(root=tmp_path, active=None)
    ctx = SlashContext(echo=echo, registry=registry, workspace=workspace)
    result = dispatch(ctx, "/config")
    assert result.output == "  No active config."


def test_config_handler_reports_active_config(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    workspace = _FakeWorkspace(root=tmp_path, active=_FakeConfig())
    ctx = SlashContext(echo=echo, registry=registry, workspace=workspace)
    result = dispatch(ctx, "/config")
    assert result.output is not None
    assert "v003" in result.output
    assert "model=opus-4-6" in result.output


def test_resume_handler_without_store(
    echo: _EchoCapture, registry: CommandRegistry
) -> None:
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/resume")
    assert "not persisted" in (result.output or "")


def test_resume_handler_with_only_current_session(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="active")
    ctx = SlashContext(
        echo=echo, registry=registry, session=session, session_store=store
    )
    result = dispatch(ctx, "/resume")
    assert result.output == "  No previous session to resume."


def test_resume_handler_loads_older_session(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    older = store.create(title="older")
    older.active_goal = "ship it"
    older.transcript.append(SessionEntry(role="user", content="hi", timestamp=1.0))
    store.save(older)
    # The second create() call becomes "current"; latest() returns the most
    # recently updated which will be the newer one here.
    current = store.create(title="current")
    # Force older to be latest by bumping its updated_at.
    older.updated_at = current.updated_at + 1
    store.save(older)

    ctx = SlashContext(
        echo=echo, registry=registry, session=current, session_store=store
    )
    result = dispatch(ctx, "/resume")
    assert result.output is not None
    assert "older" in result.output
    assert "ship it" in result.output
    assert "Entries: 1" in result.output


def test_compact_handler_without_workspace(ctx: SlashContext) -> None:
    result = dispatch(ctx, "/compact")
    assert result.output == "  No workspace — cannot save session summary."


def test_compact_handler_writes_summary(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    workspace = _FakeWorkspace(root=tmp_path)
    session = Session(
        session_id="abc123",
        title="demo",
        started_at=0.0,
        updated_at=0.0,
        active_goal="ship",
    )
    session.command_history.extend(["/status", "/doctor"])
    session.transcript.append(SessionEntry(role="user", content="hello", timestamp=1.0))
    session.pending_next_actions.append("run /eval")

    ctx = SlashContext(
        echo=echo, registry=registry, workspace=workspace, session=session
    )
    result = dispatch(ctx, "/compact")
    assert result.output is not None

    summary_path = workspace.agentlab_dir / "memory" / "latest_session.md"
    assert summary_path.exists()
    body = summary_path.read_text(encoding="utf-8")
    assert "# Session: demo" in body
    assert "- `/status`" in body
    assert "**user**: hello" in body
    assert "- run /eval" in body


# ---------------------------------------------------------------------------
# Exit signalling flows through DispatchResult.exit
# ---------------------------------------------------------------------------


def test_dispatch_exit_flag_mirrors_ctx_exit(ctx: SlashContext) -> None:
    first = dispatch(ctx, "/status")
    assert first.exit is False
    second = dispatch(ctx, "/exit")
    assert second.exit is True


# ---------------------------------------------------------------------------
# LocalJSXCommand kind is rejected but recognized
# ---------------------------------------------------------------------------


def test_dispatch_localjsx_command_reports_unsupported_kind(
    echo: _EchoCapture,
) -> None:
    class _Screen:
        def run(self) -> int:
            return 0

    jsx = LocalJSXCommand(
        name="skills", description="Browse", screen_factory=_Screen
    )
    registry = build_builtin_registry(extra=[jsx])
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/skills")
    assert result.handled is True
    assert result.error == "unsupported-kind"
    assert result.command is jsx
