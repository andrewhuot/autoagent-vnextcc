"""Tests for :mod:`cli.workbench_app.completer` (T19 — slash autocomplete popup)."""

from __future__ import annotations

from typing import Callable

import pytest
from prompt_toolkit.completion import CompleteEvent, Completion
from prompt_toolkit.document import Document

from cli.workbench_app.commands import CommandRegistry, LocalCommand, LocalJSXCommand
from cli.workbench_app.completer import (
    SlashCommandCompleter,
    SlashCompletion,
    build_completer,
    iter_completions,
)
from cli.workbench_app.slash import build_builtin_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _noop_handler(_ctx, *_args):  # type: ignore[no-untyped-def]
    return None


def _registry_with(*specs: tuple[str, str, str]) -> CommandRegistry:
    """Small registry helper — each spec is ``(name, description, source)``."""
    registry = CommandRegistry()
    for name, description, source in specs:
        registry.register(
            LocalCommand(
                name=name,
                description=description,
                source=source,  # type: ignore[arg-type]
                handler=_noop_handler,
            )
        )
    return registry


@pytest.fixture()
def registry() -> CommandRegistry:
    return _registry_with(
        ("help", "Show available slash commands", "builtin"),
        ("eval", "Run an evaluation", "builtin"),
        ("exit", "Exit the shell", "builtin"),
        ("expand", "User plugin", "plugin"),
    )


# ---------------------------------------------------------------------------
# iter_completions — pure logic, no prompt_toolkit wrapping.
# ---------------------------------------------------------------------------


def test_iter_completions_returns_nothing_for_plain_text(registry: CommandRegistry) -> None:
    assert list(iter_completions(registry, "hello world")) == []


def test_iter_completions_returns_nothing_for_empty_buffer(registry: CommandRegistry) -> None:
    assert list(iter_completions(registry, "")) == []


def test_iter_completions_returns_all_commands_for_bare_slash(
    registry: CommandRegistry,
) -> None:
    names = [c.name for c in iter_completions(registry, "/")]
    assert names == ["eval", "exit", "expand", "help"]


def test_iter_completions_filters_by_prefix(registry: CommandRegistry) -> None:
    names = [c.name for c in iter_completions(registry, "/ex")]
    assert names == ["exit", "expand"]


def test_iter_completions_filters_single_match(registry: CommandRegistry) -> None:
    names = [c.name for c in iter_completions(registry, "/he")]
    assert names == ["help"]


def test_iter_completions_no_matches_yields_empty(registry: CommandRegistry) -> None:
    assert list(iter_completions(registry, "/zzz")) == []


def test_iter_completions_start_position_covers_typed_prefix(
    registry: CommandRegistry,
) -> None:
    completions = list(iter_completions(registry, "/ex"))
    assert completions
    for c in completions:
        # ``-len("ex")`` — the leading ``/`` stays in the buffer.
        assert c.start_position == -2


def test_iter_completions_start_position_zero_on_bare_slash(
    registry: CommandRegistry,
) -> None:
    completions = list(iter_completions(registry, "/"))
    assert completions
    for c in completions:
        assert c.start_position == 0


def test_iter_completions_carries_metadata(registry: CommandRegistry) -> None:
    completions = {c.name: c for c in iter_completions(registry, "/")}
    assert completions["help"].description == "Show available slash commands"
    assert completions["help"].source == "builtin"
    assert completions["expand"].source == "plugin"
    # ``[builtin]`` is suppressed from display_meta to match Claude Code's
    # palette — it's the overwhelming default and only non-builtin commands
    # get an explicit source tag in the menu.
    assert "[builtin]" not in completions["help"].display_meta
    assert "[plugin]" in completions["expand"].display_meta


def test_iter_completions_stops_once_user_types_argument(
    registry: CommandRegistry,
) -> None:
    """Arg completion is T19-out-of-scope; no completions once a space appears."""
    assert list(iter_completions(registry, "/eval ")) == []
    assert list(iter_completions(registry, "/eval --run-id 42")) == []


def test_iter_completions_case_insensitive_prefix(registry: CommandRegistry) -> None:
    names = [c.name for c in iter_completions(registry, "/EX")]
    assert names == ["exit", "expand"]


def test_iter_completions_returns_generator() -> None:
    """``iter_completions`` is a generator — callers can stop early."""
    registry = _registry_with(("a", "a", "builtin"), ("b", "b", "builtin"))
    gen = iter_completions(registry, "/")
    import types

    assert isinstance(gen, types.GeneratorType)


def test_iter_completions_surfaces_alias_target_once() -> None:
    """Alias + primary name yielding twice would produce duplicate rows — avoid."""
    registry = CommandRegistry()
    registry.register(
        LocalCommand(
            name="resume",
            description="Resume the session",
            handler=_noop_handler,
            aliases=("r",),
        )
    )
    # Typing ``/r`` should offer the single underlying command once, not twice.
    completions = list(iter_completions(registry, "/r"))
    assert [c.name for c in completions] == ["resume"]


def test_iter_completions_matches_alias_description_and_argument_hints() -> None:
    """The palette should help users who remember intent, not exact tokens."""

    registry = CommandRegistry()
    registry.register(
        LocalCommand(
            name="resume",
            description="Continue a previous session",
            handler=_noop_handler,
            aliases=("history",),
            argument_hint="[session_id]",
        )
    )
    registry.register(
        LocalCommand(
            name="doctor",
            description="Run workspace diagnostics",
            handler=_noop_handler,
        )
    )

    assert [c.name for c in iter_completions(registry, "/hist")] == ["resume"]
    assert [c.name for c in iter_completions(registry, "/diag")] == ["doctor"]
    completion = next(iter_completions(registry, "/res"))
    assert completion.argument_hint == "[session_id]"
    assert "[session_id]" in completion.display_meta


def test_iter_completions_hides_hidden_commands_from_broad_popup() -> None:
    registry = CommandRegistry()
    registry.register(
        LocalCommand(name="status", description="Show status", handler=_noop_handler)
    )
    registry.register(
        LocalCommand(
            name="debug-internal",
            description="Internal debug hook",
            handler=_noop_handler,
            hidden=True,
        )
    )

    assert [c.name for c in iter_completions(registry, "/")] == ["status"]
    assert list(iter_completions(registry, "/debug")) == []


# ---------------------------------------------------------------------------
# SlashCommandCompleter — prompt_toolkit integration.
# ---------------------------------------------------------------------------


def _get_completions(
    completer: SlashCommandCompleter, text: str
) -> list[Completion]:
    document = Document(text=text, cursor_position=len(text))
    return list(completer.get_completions(document, CompleteEvent()))


def test_completer_wraps_records_as_prompt_toolkit_completions(
    registry: CommandRegistry,
) -> None:
    completer = SlashCommandCompleter(registry)
    completions = _get_completions(completer, "/")
    assert {c.text for c in completions} == {"eval", "exit", "expand", "help"}


def test_completer_display_includes_slash_prefix(registry: CommandRegistry) -> None:
    completer = SlashCommandCompleter(registry)
    completions = _get_completions(completer, "/he")
    assert len(completions) == 1
    completion = completions[0]
    assert completion.text == "help"
    # ``display`` is the visible label; it should show the slash.
    assert "/help" in completion.display[0][1]


def test_completer_display_meta_shows_description(registry: CommandRegistry) -> None:
    completer = SlashCommandCompleter(registry)
    completions = _get_completions(completer, "/he")
    assert "Show available slash commands" in completions[0].display_meta[0][1]


def test_completer_display_meta_shows_source_only_for_non_builtin(
    registry: CommandRegistry,
) -> None:
    """Builtin commands get no source badge (Claude-Code palette parity) —
    plugins, skills, and user commands keep theirs so the operator can tell
    at a glance which rows come from outside the default set."""
    completer = SlashCommandCompleter(registry)
    help_completions = _get_completions(completer, "/he")
    assert "[builtin]" not in help_completions[0].display_meta[0][1]
    expand_completions = _get_completions(completer, "/expand")
    assert "[plugin]" in expand_completions[0].display_meta[0][1]


def test_completer_start_position_matches_iter_completions(
    registry: CommandRegistry,
) -> None:
    completer = SlashCommandCompleter(registry)
    completions = _get_completions(completer, "/ex")
    assert all(c.start_position == -2 for c in completions)


def test_completer_returns_nothing_for_non_slash_buffer(
    registry: CommandRegistry,
) -> None:
    completer = SlashCommandCompleter(registry)
    assert _get_completions(completer, "hello") == []


@pytest.mark.asyncio
async def test_completer_supports_prompt_toolkit_async_completion_path(
    registry: CommandRegistry,
) -> None:
    """prompt_toolkit uses async completions for while-typing menus."""
    completer = SlashCommandCompleter(registry)
    document = Document(text="/he", cursor_position=3)

    completions = [
        completion
        async for completion in completer.get_completions_async(
            document, CompleteEvent()
        )
    ]

    assert [completion.text for completion in completions] == ["help"]


def test_completer_cursor_mid_buffer_only_uses_text_before_cursor(
    registry: CommandRegistry,
) -> None:
    """``Document.text_before_cursor`` is what drives matching."""
    completer = SlashCommandCompleter(registry)
    # Full text is "/expand foo", cursor sits right after "/ex" — only the
    # text before the cursor should be considered, so we still see matches
    # for "ex" and no space-induced bailout.
    document = Document(text="/expand foo", cursor_position=3)
    completions = list(completer.get_completions(document, CompleteEvent()))
    assert {c.text for c in completions} == {"exit", "expand"}


def test_completer_exposes_registry_property(registry: CommandRegistry) -> None:
    completer = SlashCommandCompleter(registry)
    assert completer.registry is registry


def test_build_completer_returns_slash_command_completer(
    registry: CommandRegistry,
) -> None:
    completer = build_completer(registry)
    assert isinstance(completer, SlashCommandCompleter)
    assert completer.registry is registry


# ---------------------------------------------------------------------------
# Integration with the real built-in registry
# ---------------------------------------------------------------------------


def test_completer_wired_to_builtin_registry_offers_canonical_commands() -> None:
    registry = build_builtin_registry()
    completer = build_completer(registry)
    completions = _get_completions(completer, "/")
    names = {c.text for c in completions}
    # Spot-check a subset — exact set is verified in test_workbench_slash.py.
    for expected in {"help", "status", "eval", "optimize", "build", "deploy", "skills", "exit"}:
        assert expected in names


def test_completer_wired_to_builtin_registry_narrows_on_prefix() -> None:
    registry = build_builtin_registry()
    completer = build_completer(registry)
    completions = _get_completions(completer, "/ev")
    assert [c.text for c in completions] == ["eval"]


# ---------------------------------------------------------------------------
# SlashCompletion dataclass frozen invariant
# ---------------------------------------------------------------------------


def test_slash_completion_is_frozen() -> None:
    rec = SlashCompletion(
        name="help",
        description="Show help",
        source="builtin",
        start_position=-3,
    )
    with pytest.raises(Exception):
        rec.name = "other"  # type: ignore[misc]
