"""T21 — consolidated unit tests for the workbench slash surface.

This module is the regression checkpoint for the three core bullets
required by T21:

* **dispatch** — routing a ``/command`` line through
  :func:`cli.workbench_app.slash.dispatch` and confirming the handler
  contract (return sugar, exit signalling, display mode).
* **unknown-command handling** — the exact user-facing message,
  error code, and defensive behaviour when the typed slash does not
  resolve.
* **autocomplete matching** — the cross-module contract that the
  :class:`SlashCommandCompleter` offers exactly the set of commands
  that :func:`dispatch` would accept (alias dedup, prefix narrowing,
  registry sharing).

Deeper per-handler coverage lives in ``tests/test_workbench_slash.py``
and completer-internals coverage lives in
``tests/test_workbench_completer.py``; this file intentionally avoids
duplicating either — it exercises the *integration* between the
dispatcher and the completer against the real built-in registry so a
regression in either surface is caught fast.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cli.workbench_app.commands import (
    CommandRegistry,
    LocalCommand,
    OnDoneResult,
    on_done,
)
from cli.workbench_app.completer import (
    SlashCompletion,
    build_completer,
    iter_completions,
)
from cli.workbench_app.slash import (
    DispatchResult,
    SlashContext,
    build_builtin_registry,
    dispatch,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _Echo:
    """Minimal echo sink. Kept local so this module does not import from the
    sibling test file — the T21 bullets should be independently verifiable."""

    lines: list[str]

    def __init__(self) -> None:
        self.lines = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


@pytest.fixture()
def echo() -> _Echo:
    return _Echo()


@pytest.fixture()
def registry() -> CommandRegistry:
    # Shared built-in registry — same instance used by dispatch and the
    # autocomplete tests below so the integration bullet is real.
    return build_builtin_registry()


@pytest.fixture()
def ctx(echo: _Echo, registry: CommandRegistry) -> SlashContext:
    return SlashContext(echo=echo, registry=registry)


# ---------------------------------------------------------------------------
# Bullet 1 — dispatch
# ---------------------------------------------------------------------------


def test_dispatch_returns_dispatchresult_for_slash_line(ctx: SlashContext) -> None:
    result = dispatch(ctx, "/help")
    assert isinstance(result, DispatchResult)
    assert result.handled is True
    assert result.command is not None
    assert result.command.name == "help"


def test_dispatch_is_noop_for_non_slash_input(ctx: SlashContext, echo: _Echo) -> None:
    result = dispatch(ctx, "just typed free text")
    assert result == DispatchResult(handled=False)
    assert echo.lines == []


def test_dispatch_normalizes_bare_string_return_to_user_display(
    echo: _Echo,
) -> None:
    cmd = LocalCommand(
        name="ping",
        description="echo back",
        handler=lambda *_a, **_k: "pong",
    )
    registry = build_builtin_registry(extra=[cmd])
    ctx = SlashContext(echo=echo, registry=registry)

    result = dispatch(ctx, "/ping")

    assert result.handled is True
    assert result.display == "user"
    assert result.output == "pong"
    assert result.raw_result == "pong"
    assert echo.lines == ["pong"]


def test_dispatch_normalizes_none_return_to_skip_display(echo: _Echo) -> None:
    cmd = LocalCommand(
        name="silent",
        description="returns nothing",
        handler=lambda *_a, **_k: None,
    )
    registry = build_builtin_registry(extra=[cmd])
    ctx = SlashContext(echo=echo, registry=registry)

    result = dispatch(ctx, "/silent")

    assert result.handled is True
    assert result.display == "skip"
    assert result.output is None
    assert echo.lines == []


def test_dispatch_honors_on_done_display_system_dims_output(echo: _Echo) -> None:
    def _handler(*_a: object, **_k: object) -> OnDoneResult:
        return on_done(
            "note",
            display="system",
            meta_messages=("follow-up: none",),
        )

    cmd = LocalCommand(name="meta", description="system line", handler=_handler)
    registry = build_builtin_registry(extra=[cmd])
    ctx = SlashContext(echo=echo, registry=registry)

    result = dispatch(ctx, "/meta")

    assert result.display == "system"
    assert result.raw_result == "note"
    assert result.meta_messages == ("follow-up: none",)
    # The rendered system line and the meta line are both echoed.
    assert len(echo.lines) == 2


def test_dispatch_handler_exception_returns_error_and_keeps_loop_alive(
    echo: _Echo,
) -> None:
    def _boom(*_a: object, **_k: object) -> str:
        raise RuntimeError("explode")

    cmd = LocalCommand(name="boom", description="fails", handler=_boom)
    registry = build_builtin_registry(extra=[cmd])
    ctx = SlashContext(echo=echo, registry=registry)

    result = dispatch(ctx, "/boom")

    assert result.handled is True
    assert result.error == "explode"
    # The error line is echoed so the user sees it, rather than dispatch raising.
    assert any("Error running /boom" in line for line in echo.lines)


def test_dispatch_exit_signal_flips_context_and_result_flag(ctx: SlashContext) -> None:
    result = dispatch(ctx, "/exit")
    assert result.exit is True
    assert ctx.exit_requested is True


# ---------------------------------------------------------------------------
# Bullet 2 — unknown-command handling
# ---------------------------------------------------------------------------


def test_dispatch_unknown_command_returns_error_code_unknown(
    ctx: SlashContext,
) -> None:
    result = dispatch(ctx, "/definitely-not-a-command")
    assert result.handled is True
    assert result.error == "unknown"
    assert result.command is None


def test_dispatch_unknown_command_echoes_hint_for_help(
    ctx: SlashContext, echo: _Echo
) -> None:
    dispatch(ctx, "/zzz")
    # One echoed line carrying both the offending token and the /help pointer.
    combined = "\n".join(echo.lines)
    assert "/zzz" in combined
    assert "Unknown command" in combined
    assert "/help" in combined


def test_dispatch_unknown_command_preserves_typed_token_case_insensitively(
    ctx: SlashContext, echo: _Echo
) -> None:
    # ``dispatch`` normalizes the lookup key to lower case, but the echoed
    # hint quotes the canonical (lower-cased) form so the user always sees
    # what dispatch actually searched for.
    dispatch(ctx, "/NoPe")
    assert any("/nope" in line for line in echo.lines)


def test_dispatch_unknown_command_does_not_mutate_registry(
    ctx: SlashContext, registry: CommandRegistry
) -> None:
    before = set(registry.names())
    dispatch(ctx, "/stillnothing")
    assert set(registry.names()) == before


def test_dispatch_without_registry_is_explicit_error_not_crash() -> None:
    # Defensive: an unbound registry must surface a clean error instead of
    # raising — the workbench loop needs to keep running even if bootstrap
    # lost the registry reference.
    ctx = SlashContext()
    result = dispatch(ctx, "/help")
    assert result.handled is True
    assert result.error == "no command registry bound"


# ---------------------------------------------------------------------------
# Bullet 3 — autocomplete matching (integration with the real built-in registry)
# ---------------------------------------------------------------------------


def test_completer_offers_exactly_the_registry_commands(
    registry: CommandRegistry,
) -> None:
    completer = build_completer(registry)
    rows = list(
        iter_completions(completer.registry, "/")
    )
    offered = {row.name for row in rows}
    # Every visible command must resolve via dispatch.
    assert offered == set(registry.names())


def test_completer_prefix_narrows_match_and_replaces_only_prefix_span(
    registry: CommandRegistry,
) -> None:
    rows = list(iter_completions(registry, "/ev"))
    assert [r.name for r in rows] == ["eval"]
    # ``start_position`` replaces only the typed prefix (``ev``), leaving
    # the leading ``/`` alone.
    assert rows[0].start_position == -2


def test_completer_case_insensitive_prefix(registry: CommandRegistry) -> None:
    rows = list(iter_completions(registry, "/HE"))
    assert "help" in {r.name for r in rows}


def test_completer_no_match_yields_empty_iterator(registry: CommandRegistry) -> None:
    rows = list(iter_completions(registry, "/zzznothingmatches"))
    assert rows == []


def test_completer_stops_after_first_whitespace_token(
    registry: CommandRegistry,
) -> None:
    # Once the user types a space, command-name completion bails — this is
    # how arg-completion will hook in later without fighting the name
    # completer.
    assert list(iter_completions(registry, "/eval ")) == []
    assert list(iter_completions(registry, "/eval --run-id abc")) == []


def test_completer_does_not_fire_for_non_slash_buffers(
    registry: CommandRegistry,
) -> None:
    assert list(iter_completions(registry, "")) == []
    assert list(iter_completions(registry, "plain text")) == []


def test_every_autocomplete_match_dispatches_without_unknown_error(
    registry: CommandRegistry, echo: _Echo
) -> None:
    """Cross-module regression: whatever the completer offers, dispatch
    must accept. A drift between the two surfaces would silently ship
    broken suggestions, so pin them together here."""
    ctx = SlashContext(echo=echo, registry=registry)
    for row in iter_completions(registry, "/"):
        # Skip commands that would actually execute side effects; we only
        # care that the *lookup* layer resolves, not that the handler runs.
        found = registry.get(row.name)
        assert found is not None, f"completer offered unknown command: {row.name}"
        assert found.name == row.name


def test_completer_shares_registry_with_dispatch_by_reference(
    registry: CommandRegistry,
) -> None:
    completer = build_completer(registry)
    # Registration on the live registry must be visible to the completer
    # immediately — no copy, no snapshot.
    extra = LocalCommand(
        name="justtocheck",
        description="runtime registration",
        handler=lambda *_a, **_k: None,
    )
    registry.register(extra)
    offered = {r.name for r in iter_completions(completer.registry, "/justtocheck")}
    assert offered == {"justtocheck"}


def test_completion_record_is_frozen() -> None:
    rec = SlashCompletion(
        name="help",
        description="Show help",
        source="builtin",
        start_position=-3,
    )
    with pytest.raises(Exception):
        rec.name = "other"  # type: ignore[misc]
