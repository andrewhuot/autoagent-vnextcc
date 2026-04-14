"""Tests for cli/workbench_app/slash.py — dispatch + ported handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import click
import pytest

from cli.sessions import Session, SessionEntry, SessionStore
from cli.workbench_app.commands import (
    CommandRegistry,
    LocalCommand,
    LocalJSXCommand,
    OnDoneResult,
    PromptCommand,
    on_done,
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
    # T09 adds ``/eval``, T10 adds ``/optimize``, T11 adds ``/save`` (ported)
    # and ``/build`` (streaming), T12 adds ``/deploy`` (streaming) to the
    # default registry. Tests that want just the ported built-ins construct
    # the registry with ``include_streaming=False`` — see
    # ``test_builtin_registry_without_streaming``.
    expected = {
        "help",
        "status",
        "config",
        "memory",
        "doctor",
        "review",
        "mcp",
        "save",
        "compact",
        "resume",
        "exit",
        "eval",
        "optimize",
        "build",
        "deploy",
        "skills",
        "model",
        "clear",
        "new",
    }
    assert set(registry.names()) == expected


def test_builtin_registry_without_streaming() -> None:
    registry = build_builtin_registry(include_streaming=False)
    assert "eval" not in registry.names()
    assert "optimize" not in registry.names()
    assert "build" not in registry.names()
    assert "deploy" not in registry.names()
    assert "skills" not in registry.names()
    assert "save" in registry.names()  # /save is ported, not streaming
    assert "help" in registry.names()
    assert "model" in registry.names()  # T14 /model is inline, not streaming
    assert "clear" in registry.names()  # T15 /clear is inline
    assert "new" in registry.names()  # T15 /new is inline


def test_builtin_registry_help_table_has_descriptions(
    registry: CommandRegistry,
) -> None:
    table = registry.help_table()
    assert table["/help"] == "Show available slash commands"
    assert table["/exit"] == "Exit the shell"


def test_builtin_registry_accepts_extra_commands() -> None:
    extra = LocalCommand(
        name="custom",
        description="Run custom",
        handler=lambda *_a, **_k: "custom ran",
    )
    registry = build_builtin_registry(extra=[extra])
    assert registry.get("/custom") is extra
    # 11 ported built-ins (incl. /save T11) + /clear + /new (T15) + /model
    # (T14) + /eval (T09) + /optimize (T10) + /build (T11) + /deploy (T12)
    # + /skills (T13) + /custom (extra) = 20
    assert len(registry) == 20


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


def test_save_handler_delegates_to_workbench_save(
    ctx: SlashContext, invoker: _FakeClickInvoker
) -> None:
    dispatch(ctx, "/save")
    assert invoker.calls == ["workbench save"]


def test_save_handler_forwards_args(
    ctx: SlashContext, invoker: _FakeClickInvoker
) -> None:
    dispatch(ctx, "/save --project-id p1 --split train")
    assert invoker.calls == ["workbench save --project-id p1 --split train"]


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
    assert "not persisted" in click.unstyle(result.output or "")


def test_resume_handler_with_only_current_session(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="active")
    ctx = SlashContext(
        echo=echo, registry=registry, session=session, session_store=store
    )
    result = dispatch(ctx, "/resume")
    assert click.unstyle(result.output or "") == "  No previous session to resume."


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
    assert result.raw_result is not None
    assert "Resumed previous session" in click.unstyle(result.raw_result)
    plain_meta = [click.unstyle(m) for m in result.meta_messages]
    assert any("older" in m for m in plain_meta)
    assert any("ship it" in m for m in plain_meta)
    assert any("Entries restored: 1" in m for m in plain_meta)
    # Session pointer swapped to the resumed session.
    assert ctx.session is not current
    assert ctx.session is not None
    assert ctx.session.session_id == older.session_id


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
# LocalJSXCommand dispatch — T13 wires screens into dispatch
# ---------------------------------------------------------------------------


def test_dispatch_localjsx_command_runs_screen(
    echo: _EchoCapture,
) -> None:
    from cli.workbench_app.screens.base import ScreenResult as _ScreenResult

    class _Screen:
        calls: list[tuple] = []

        def __init__(self, ctx, *args):
            type(self).calls.append((ctx, args))

        def run(self) -> _ScreenResult:
            return _ScreenResult(
                action="done",
                value="payload",
                meta_messages=("one.", "two."),
            )

    jsx = LocalJSXCommand(
        name="showcase", description="Demo screen", screen_factory=_Screen
    )
    registry = build_builtin_registry(extra=[jsx])
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/showcase arg1")
    assert result.handled is True
    assert result.error is None
    assert result.command is jsx
    assert result.display == "system"
    assert result.meta_messages == ("one.", "two.")
    assert result.raw_result == "payload"
    # Factory received the SlashContext + remaining args.
    assert len(_Screen.calls) == 1
    assert _Screen.calls[0][1] == ("arg1",)
    # Meta messages echoed as dim lines (styling intact).
    plain_lines = [click.unstyle(line) for line in echo.lines]
    assert "one." in plain_lines
    assert "two." in plain_lines


def test_dispatch_localjsx_command_handles_factory_errors(
    echo: _EchoCapture,
) -> None:
    def _boom(ctx, *args):
        raise RuntimeError("screen exploded")

    jsx = LocalJSXCommand(
        name="broken", description="x", screen_factory=_boom
    )
    registry = build_builtin_registry(extra=[jsx])
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/broken")
    assert result.handled is True
    assert result.error == "screen exploded"
    assert any("Error running /broken" in line for line in echo.lines)




# ---------------------------------------------------------------------------
# T05b — onDone return protocol (display modes / should_query / meta messages)
# ---------------------------------------------------------------------------


def _register(registry: CommandRegistry, name: str, handler) -> None:
    registry.register(LocalCommand(name=name, description=name, handler=handler))


def test_on_done_helper_defaults_to_user_display() -> None:
    result = on_done("hello")
    assert isinstance(result, OnDoneResult)
    assert result.result == "hello"
    assert result.display == "user"
    assert result.should_query is False
    assert result.meta_messages == ()


def test_on_done_helper_normalizes_meta_messages_to_tuple() -> None:
    result = on_done("ok", meta_messages=["a", "b"])
    assert result.meta_messages == ("a", "b")
    # Frozen dataclass — tuple makes it hashable and immutable.
    assert hash(result) == hash(result)


def test_dispatch_user_display_echoes_plain_text(
    echo: _EchoCapture,
) -> None:
    registry = build_builtin_registry()
    _register(registry, "user_ping", lambda *_a, **_k: on_done("pong", display="user"))
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/user_ping")

    assert result.display == "user"
    assert result.output == "pong"
    assert result.raw_result == "pong"
    assert echo.lines == ["pong"]


def test_dispatch_system_display_emits_dim_line(
    echo: _EchoCapture,
) -> None:
    registry = build_builtin_registry()
    _register(
        registry, "sys_note", lambda *_a, **_k: on_done("loaded 3 configs", display="system")
    )
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/sys_note")

    assert result.display == "system"
    assert result.raw_result == "loaded 3 configs"
    # Raw text is preserved; the echoed line is dim-styled.
    expected = click.style("loaded 3 configs", dim=True)
    assert echo.lines == [expected]
    assert result.output == expected


def test_dispatch_skip_display_writes_nothing_to_transcript(
    echo: _EchoCapture,
) -> None:
    registry = build_builtin_registry()
    _register(
        registry,
        "silent",
        lambda *_a, **_k: on_done("private state", display="skip"),
    )
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/silent")

    assert result.display == "skip"
    # raw_result still carries the value so callers/loggers can use it.
    assert result.raw_result == "private state"
    assert result.output is None
    assert echo.lines == []


def test_dispatch_skip_display_still_emits_meta_messages(
    echo: _EchoCapture,
) -> None:
    registry = build_builtin_registry()
    _register(
        registry,
        "with_meta",
        lambda *_a, **_k: on_done(
            None, display="skip", meta_messages=["session restored", "2 pending"]
        ),
    )
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/with_meta")

    assert result.output is None
    assert result.meta_messages == ("session restored", "2 pending")
    assert echo.lines == [
        click.style("session restored", dim=True),
        click.style("2 pending", dim=True),
    ]


def test_dispatch_should_query_flag_is_surfaced(
    echo: _EchoCapture,
) -> None:
    registry = build_builtin_registry()
    _register(
        registry,
        "ask",
        lambda *_a, **_k: on_done(
            "explain this traceback", display="user", should_query=True
        ),
    )
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/ask")

    assert result.should_query is True
    assert result.raw_result == "explain this traceback"


def test_dispatch_bare_string_return_is_user_display(
    echo: _EchoCapture,
) -> None:
    """Legacy handlers returning str remain valid — normalized to display='user'."""
    registry = build_builtin_registry()
    _register(registry, "legacy", lambda *_a, **_k: "legacy output")
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/legacy")

    assert result.display == "user"
    assert result.should_query is False
    assert result.meta_messages == ()
    assert result.raw_result == "legacy output"
    assert echo.lines == ["legacy output"]


def test_dispatch_bare_none_return_is_skip_display(
    echo: _EchoCapture,
) -> None:
    registry = build_builtin_registry()
    _register(registry, "noop", lambda *_a, **_k: None)
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/noop")

    assert result.display == "skip"
    assert result.output is None
    assert result.raw_result is None
    assert echo.lines == []


def test_dispatch_rejects_unsupported_return_type(
    echo: _EchoCapture,
) -> None:
    registry = build_builtin_registry()
    _register(registry, "bad", lambda *_a, **_k: 42)  # type: ignore[arg-type]
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/bad")

    # The TypeError from normalization is caught by the generic error path
    # so the loop stays alive and the user sees a useful message.
    assert result.handled is True
    assert result.error is not None
    assert "unsupported type" in result.error
    assert result.display == "system"


def test_dispatch_meta_messages_follow_user_result(
    echo: _EchoCapture,
) -> None:
    registry = build_builtin_registry()
    _register(
        registry,
        "report",
        lambda *_a, **_k: on_done(
            "headline",
            display="user",
            meta_messages=["footnote one", "footnote two"],
        ),
    )
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/report")

    assert echo.lines == [
        "headline",
        click.style("footnote one", dim=True),
        click.style("footnote two", dim=True),
    ]
    assert result.output == "headline"
    assert result.meta_messages == ("footnote one", "footnote two")


def test_dispatch_handler_exception_surfaces_as_system_line(
    echo: _EchoCapture,
) -> None:
    """Handler errors are routed through the system display so the loop stays alive."""

    def _boom(*_a, **_k):
        raise RuntimeError("oops")

    registry = build_builtin_registry()
    _register(registry, "boom2", _boom)
    ctx = SlashContext(echo=echo, registry=registry)
    result = dispatch(ctx, "/boom2")

    assert result.error == "oops"
    assert result.display == "system"
    assert "Error running /boom2" in (result.output or "")


def test_help_handler_goes_through_on_done(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    """The /help handler was ported to return on_done() explicitly (T05b)."""
    result = dispatch(ctx, "/help")
    assert result.display == "user"
    assert result.should_query is False
    assert result.meta_messages == ()
    assert result.raw_result is not None
    assert "/help" in result.raw_result


# ---------------------------------------------------------------------------
# T15 — /clear and /new
# ---------------------------------------------------------------------------


def test_clear_handler_without_transcript_is_a_noop(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    result = dispatch(ctx, "/clear")
    assert result.handled is True
    assert result.display == "system"
    assert result.raw_result is not None
    assert "No transcript bound" in result.raw_result
    # System display → dim-styled line; only the main line, no meta.
    assert echo.lines == [click.style(result.raw_result, dim=True)]


def test_clear_handler_wipes_transcript_entries(
    echo: _EchoCapture, registry: CommandRegistry
) -> None:
    from cli.workbench_app.transcript import Transcript

    transcript = Transcript(echo=lambda _line: None, color=False)
    transcript.append_user("hello")
    transcript.append_assistant("hi there")
    transcript.append_system("note")
    assert len(transcript) == 3

    ctx = SlashContext(echo=echo, registry=registry, transcript=transcript)
    result = dispatch(ctx, "/clear")

    assert result.handled is True
    assert result.display == "system"
    assert len(transcript) == 0
    assert "Transcript cleared" in (result.raw_result or "")
    assert result.meta_messages == ("Removed 3 entries; session kept.",)
    # Main line + one meta line, both dim-styled.
    assert echo.lines[0] == click.style(result.raw_result, dim=True)
    assert click.unstyle(echo.lines[1]) == "Removed 3 entries; session kept."


def test_clear_handler_uses_singular_noun_for_one_entry(
    echo: _EchoCapture, registry: CommandRegistry
) -> None:
    from cli.workbench_app.transcript import Transcript

    transcript = Transcript(echo=lambda _line: None, color=False)
    transcript.append_user("only line")

    ctx = SlashContext(echo=echo, registry=registry, transcript=transcript)
    result = dispatch(ctx, "/clear")

    assert result.meta_messages == ("Removed 1 entry; session kept.",)


def test_clear_handler_keeps_session_intact(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    from cli.workbench_app.transcript import Transcript

    store = SessionStore(tmp_path)
    session = store.create(title="keep-me")
    store.append_entry(session, "user", "persisted line")
    transcript = Transcript(echo=lambda _line: None, color=False)
    transcript.append_user("in-memory line")

    ctx = SlashContext(
        echo=echo,
        registry=registry,
        session=session,
        session_store=store,
        transcript=transcript,
    )
    dispatch(ctx, "/clear")

    # Session pointer unchanged and on-disk transcript untouched.
    assert ctx.session is session
    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert len(reloaded.transcript) == 1
    assert reloaded.transcript[0].content == "persisted line"
    # In-memory transcript wiped.
    assert len(transcript) == 0


def test_new_handler_without_store_reports_and_keeps_session(
    echo: _EchoCapture, registry: CommandRegistry
) -> None:
    prior = Session(session_id="abc", title="before")
    ctx = SlashContext(echo=echo, registry=registry, session=prior)
    result = dispatch(ctx, "/new")

    assert result.handled is True
    assert result.display == "system"
    assert "not persisted" in (result.raw_result or "")
    # Session pointer untouched.
    assert ctx.session is prior


def test_new_handler_creates_session_and_swaps_on_context(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    previous = store.create(title="old")

    ctx = SlashContext(
        echo=echo,
        registry=registry,
        session=previous,
        session_store=store,
    )
    result = dispatch(ctx, "/new")

    assert result.handled is True
    assert result.display == "system"
    assert ctx.session is not previous
    assert ctx.session is not None
    assert ctx.session.session_id != previous.session_id
    # New session persisted to disk.
    assert store.get(ctx.session.session_id) is not None
    # Default-title session still surfaces the auto-generated title meta.
    plain_meta = [click.unstyle(line) for line in echo.lines[1:]]
    assert any(f"Previous session: {previous.session_id}" == m for m in plain_meta)
    assert any(f"New session: {ctx.session.session_id}" == m for m in plain_meta)


def test_new_handler_accepts_title_from_positional_args(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    ctx = SlashContext(echo=echo, registry=registry, session_store=store)

    dispatch(ctx, "/new regression sweep")

    assert ctx.session is not None
    assert ctx.session.title == "regression sweep"
    plain_meta = [click.unstyle(line) for line in echo.lines[1:]]
    assert any("Title: regression sweep" == m for m in plain_meta)


def test_new_handler_clears_transcript_when_bound(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    from cli.workbench_app.transcript import Transcript

    store = SessionStore(tmp_path)
    previous = store.create(title="keep-on-disk")
    transcript = Transcript(echo=lambda _line: None, color=False)
    transcript.append_user("line one")
    transcript.append_user("line two")

    ctx = SlashContext(
        echo=echo,
        registry=registry,
        session=previous,
        session_store=store,
        transcript=transcript,
    )
    dispatch(ctx, "/new")

    assert len(transcript) == 0
    # Prior session file still exists on disk.
    assert store.get(previous.session_id) is not None


def test_new_handler_surfaces_store_failure_as_system_line(
    echo: _EchoCapture, registry: CommandRegistry
) -> None:
    class _BrokenStore:
        def create(self, title: str = "") -> Session:
            raise RuntimeError("disk full")

    ctx = SlashContext(
        echo=echo, registry=registry, session_store=_BrokenStore()  # type: ignore[arg-type]
    )
    result = dispatch(ctx, "/new")

    assert result.handled is True
    assert result.display == "system"
    assert "disk full" in (result.raw_result or "")
    assert ctx.session is None


def test_new_handler_omits_previous_meta_when_no_session_bound(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    ctx = SlashContext(echo=echo, registry=registry, session_store=store)

    dispatch(ctx, "/new")

    plain_meta = [click.unstyle(line) for line in echo.lines[1:]]
    # No "Previous session" line when ctx.session started as None.
    assert not any(line.startswith("Previous session:") for line in plain_meta)
    assert any(line.startswith("New session:") for line in plain_meta)


# ---------------------------------------------------------------------------
# T17 — session persistence + /resume restoration
# ---------------------------------------------------------------------------


def test_dispatch_persists_slash_command_to_history(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="persist-me")
    ctx = SlashContext(
        echo=echo, registry=registry, session=session, session_store=store
    )

    dispatch(ctx, "/help")
    dispatch(ctx, "/status extra arg")

    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert reloaded.command_history[-2:] == ["/help", "/status extra arg"]


def test_dispatch_skips_history_when_store_or_session_unbound(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    # No store bound → no crash, no mutation on the in-memory session.
    session = Session(session_id="x", title="")
    ctx = SlashContext(echo=echo, registry=registry, session=session)
    dispatch(ctx, "/help")
    assert session.command_history == []


def test_dispatch_does_not_record_non_slash_lines(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="quiet")
    ctx = SlashContext(
        echo=echo, registry=registry, session=session, session_store=store
    )
    result = dispatch(ctx, "just some free text")
    assert result.handled is False
    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert reloaded.command_history == []


def test_dispatch_swallows_store_failure_on_command_append(
    echo: _EchoCapture, registry: CommandRegistry
) -> None:
    class _BadStore:
        def append_command(self, session: Session, command: str) -> None:
            raise RuntimeError("disk full")

    session = Session(session_id="abc", title="")
    ctx = SlashContext(
        echo=echo,
        registry=registry,
        session=session,
        session_store=_BadStore(),  # type: ignore[arg-type]
    )
    # Must not raise — persistence is best-effort.
    result = dispatch(ctx, "/help")
    assert result.handled is True


def test_resume_handler_swaps_session_and_restores_transcript(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    from cli.workbench_app.transcript import Transcript

    store = SessionStore(tmp_path)
    older = store.create(title="older")
    older.active_goal = "finish T17"
    older.transcript.extend(
        [
            SessionEntry(role="user", content="hello", timestamp=1.0),
            SessionEntry(role="assistant", content="hi", timestamp=2.0),
            SessionEntry(role="tool", content="  running…", timestamp=3.0),
        ]
    )
    store.save(older)
    current = store.create(title="current")
    older.updated_at = current.updated_at + 1
    store.save(older)

    transcript = Transcript(echo=lambda _line: None, color=False)
    transcript.append_user("throwaway line")

    ctx = SlashContext(
        echo=echo,
        registry=registry,
        session=current,
        session_store=store,
        transcript=transcript,
    )

    result = dispatch(ctx, "/resume")
    assert result.display == "system"
    # Session pointer swapped.
    assert ctx.session is not None
    assert ctx.session.session_id == older.session_id
    # Transcript restored (throwaway line was wiped, 3 entries restored).
    assert len(transcript) == 3
    assert transcript.entries[0].role == "user"
    assert transcript.entries[0].content == "hello"
    assert transcript.entries[2].role == "tool"
    # Transcript rebound to resumed session so future appends persist to it.
    assert transcript.bound_session is ctx.session


def test_resume_handler_accepts_explicit_session_id(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    first = store.create(title="first")
    second = store.create(title="second")
    # second is latest; resuming "first" by id should win.
    ctx = SlashContext(echo=echo, registry=registry, session_store=store)

    result = dispatch(ctx, f"/resume {first.session_id}")
    assert result.display == "system"
    assert ctx.session is not None
    assert ctx.session.session_id == first.session_id
    # Sanity: default /resume would have picked second.
    assert second.session_id != first.session_id


def test_resume_handler_reports_unknown_session_id(
    echo: _EchoCapture, registry: CommandRegistry, tmp_path: Path
) -> None:
    store = SessionStore(tmp_path)
    store.create(title="existing")
    ctx = SlashContext(echo=echo, registry=registry, session_store=store)

    result = dispatch(ctx, "/resume nope-missing")
    assert result.display == "system"
    assert "nope-missing" in click.unstyle(result.raw_result or "")


def test_transcript_bind_session_persists_appends(tmp_path: Path) -> None:
    from cli.workbench_app.transcript import Transcript

    store = SessionStore(tmp_path)
    session = store.create(title="wired")
    transcript = Transcript(echo=lambda _line: None, color=False)
    transcript.bind_session(session, store)

    transcript.append_user("line one")
    transcript.append_assistant("line two")

    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert len(reloaded.transcript) == 2
    assert reloaded.transcript[0].role == "user"
    assert reloaded.transcript[0].content == "line one"
    assert reloaded.transcript[1].role == "assistant"


def test_transcript_bind_session_detach_stops_persisting(tmp_path: Path) -> None:
    from cli.workbench_app.transcript import Transcript

    store = SessionStore(tmp_path)
    session = store.create(title="detach")
    transcript = Transcript(echo=lambda _line: None, color=False)
    transcript.bind_session(session, store)
    transcript.append_user("first")
    transcript.bind_session(None, None)
    transcript.append_user("after-detach")

    reloaded = store.get(session.session_id)
    assert reloaded is not None
    contents = [entry.content for entry in reloaded.transcript]
    assert "first" in contents
    assert "after-detach" not in contents


def test_transcript_clear_keeps_on_disk_session(tmp_path: Path) -> None:
    from cli.workbench_app.transcript import Transcript

    store = SessionStore(tmp_path)
    session = store.create(title="kept")
    transcript = Transcript(echo=lambda _line: None, color=False)
    transcript.bind_session(session, store)
    transcript.append_user("keep me")
    transcript.clear()
    assert len(transcript) == 0

    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert len(reloaded.transcript) == 1


def test_transcript_restore_normalizes_unknown_roles(tmp_path: Path) -> None:
    from cli.workbench_app.transcript import Transcript

    store = SessionStore(tmp_path)
    session = store.create(title="legacy")
    session.transcript.append(
        SessionEntry(role="weird-role", content="what", timestamp=1.0)
    )
    store.save(session)

    transcript = Transcript(echo=lambda _line: None, color=False)
    transcript.restore_from_session(session)
    assert len(transcript) == 1
    # Fallback role is "system" for unknown legacy tags.
    assert transcript.entries[0].role == "system"
