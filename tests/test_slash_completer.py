"""Chunk 5 acceptance tests — fuzzy slash autocomplete + argument hints.

Companion to :mod:`tests.test_workbench_completer`. That file exercises the
broader completer contract (prefix match, alias match, hidden commands, async
path, file-ref completions). This file pins the two behaviours the Chunk-5
refactor is meant to guarantee against regressions:

1. **Typo-tolerant fuzzy ranking.** ``/buld`` must surface ``/build`` even
   though ``"buld"`` is neither a prefix nor a substring of ``"build"``. The
   completer's ``difflib`` branch is the last line of defence that stops a
   two-character typo from killing the popup.
2. **Menu rows carry description + argument hint.** Claude Code's palette is
   discoverable because the description (and argument shape) is always one
   glance away. The renderer wraps every :class:`SlashCompletion` into a
   prompt_toolkit ``Completion`` whose ``display_meta`` shows both.
"""

from __future__ import annotations

from prompt_toolkit.completion import CompleteEvent, Completion
from prompt_toolkit.document import Document

from cli.workbench_app.commands import CommandRegistry, LocalCommand
from cli.workbench_app.completer import (
    SlashCommandCompleter,
    iter_completions,
)
from cli.workbench_app.slash import build_builtin_registry


def _noop_handler(_ctx, *_args):  # type: ignore[no-untyped-def]
    return None


def _render_meta(completion: Completion) -> str:
    """Flatten ``Completion.display_meta`` (a ``FormattedText`` tuple list)."""
    return "".join(fragment for _style, fragment, *_ in completion.display_meta)


def _render_display(completion: Completion) -> str:
    return "".join(fragment for _style, fragment, *_ in completion.display)


def _get_completions(
    completer: SlashCommandCompleter, text: str
) -> list[Completion]:
    document = Document(text=text, cursor_position=len(text))
    return list(completer.get_completions(document, CompleteEvent()))


# ---------------------------------------------------------------------------
# Fuzzy typo matching — the core UX promise of Chunk 5.
# ---------------------------------------------------------------------------


def test_typo_buld_fuzzy_matches_build_in_real_registry() -> None:
    """``/buld`` is the canonical typo for ``/build`` (dropped 'i').

    ``"buld" not in "build"`` as a substring, so score 4 is skipped. The
    subsequence branch (score 8) and the ``difflib`` branch (score 7) are
    the safety nets — either one alone is enough to keep the match."""
    registry = build_builtin_registry()
    names = [c.name for c in iter_completions(registry, "/buld")]
    assert "build" in names
    # Fuzzy rank should land ``build`` at the top for this typo.
    assert names[0] == "build"


def test_typo_depoloy_fuzzy_matches_deploy() -> None:
    registry = build_builtin_registry()
    names = [c.name for c in iter_completions(registry, "/depoloy")]
    assert names and names[0] == "deploy"


def test_fuzzy_matches_extend_beyond_prefix_for_real_typos() -> None:
    """``/evl`` (dropped 'a') should still surface ``/eval``."""
    registry = build_builtin_registry()
    names = [c.name for c in iter_completions(registry, "/evl")]
    assert "eval" in names
    assert names[0] == "eval"


def test_fuzzy_tolerates_double_letter_typo() -> None:
    """``/plann`` (extra 'n') should still surface ``/plan``."""
    registry = build_builtin_registry()
    names = [c.name for c in iter_completions(registry, "/plann")]
    assert "plan" in names


def test_fuzzy_rejects_garbage_that_does_not_resemble_any_command() -> None:
    """Four consecutive z's should match nothing — fuzzy is not a free-for-all."""
    registry = build_builtin_registry()
    assert list(iter_completions(registry, "/zzzz")) == []


# ---------------------------------------------------------------------------
# Menu rows carry description + argument hint.
# ---------------------------------------------------------------------------


def test_completion_menu_row_includes_description() -> None:
    """The description is the operator-facing one-liner that makes the menu
    scannable — dropping it would regress to an opaque name list."""
    registry = CommandRegistry()
    registry.register(
        LocalCommand(
            name="build",
            description="Build or change an agent",
            handler=_noop_handler,
            argument_hint="[request]",
        )
    )
    completer = SlashCommandCompleter(registry)
    completions = _get_completions(completer, "/buil")
    assert len(completions) == 1
    assert "Build or change an agent" in _render_meta(completions[0])


def test_completion_menu_row_includes_argument_hint() -> None:
    """``LocalCommand.argument_hint`` tells the operator what to type next
    (e.g. ``[request]``, ``<session_id>``). It must reach the menu row so
    users don't need to run ``/help`` to remember the command shape."""
    registry = CommandRegistry()
    registry.register(
        LocalCommand(
            name="resume",
            description="Resume a previous session",
            handler=_noop_handler,
            argument_hint="[session_id]",
        )
    )
    completer = SlashCommandCompleter(registry)
    completions = _get_completions(completer, "/res")
    assert len(completions) == 1
    meta = _render_meta(completions[0])
    assert "Resume a previous session" in meta
    assert "[session_id]" in meta


def test_completion_display_shows_slash_prefix() -> None:
    """The main label in the menu is ``/name`` — the leading slash is the
    visual anchor the user already typed. Missing it would make the menu
    look like ordinary text completions."""
    registry = CommandRegistry()
    registry.register(
        LocalCommand(
            name="deploy",
            description="Ship a candidate",
            handler=_noop_handler,
        )
    )
    completer = SlashCommandCompleter(registry)
    completions = _get_completions(completer, "/dep")
    assert len(completions) == 1
    assert _render_display(completions[0]) == "/deploy"


def test_builtin_registry_fuzzy_and_meta_end_to_end() -> None:
    """Integration check: the real CLI registry surfaces both fuzzy typos
    and their description + argument-hint metadata in a single popup."""
    registry = build_builtin_registry()
    completer = SlashCommandCompleter(registry)
    completions = _get_completions(completer, "/buld")
    assert completions, "fuzzy typo /buld should surface at least one row"
    top = completions[0]
    assert _render_display(top) == "/build"
    meta = _render_meta(top)
    # The real /build command's description mentions agents; argument hint
    # is ``[request]``. Both must reach the user.
    assert "agent" in meta.lower()
    assert "[request]" in meta
