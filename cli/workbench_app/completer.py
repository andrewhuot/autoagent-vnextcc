"""Slash-command autocomplete for the workbench app (T19).

prompt_toolkit ``Completer`` implementation that turns
:class:`cli.workbench_app.commands.CommandRegistry` entries into the popup
shown when the user types ``/`` at the input prompt. Mirrors Claude Code's
command-palette UX: bare ``/`` opens with the full list grouped by source,
``/ev`` narrows to matching prefixes, each row shows a one-line description
as ``display_meta``.

The completer only fires while the caret is inside the first whitespace
token of the buffer — completing command names, not their arguments. Arg
completion is intentionally out of scope for T19; a future task can extend
this class with per-command argument completers keyed on
:attr:`SlashCommand.paths` globs.

The module is kept free of prompt_toolkit-specific imports at module scope
so the rest of :mod:`cli.workbench_app` (which runs in headless tests) does
not pay an import cost; the prompt_toolkit symbols are imported at class /
function bodies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Iterator

from cli.workbench_app.commands import CommandRegistry, SlashCommand

if TYPE_CHECKING:
    from prompt_toolkit.completion import CompleteEvent, Completion
    from prompt_toolkit.document import Document


@dataclass(frozen=True)
class SlashCompletion:
    """Framework-agnostic completion record.

    Produced by :func:`iter_completions` and consumed by
    :class:`SlashCommandCompleter` (which wraps each record in a
    prompt_toolkit ``Completion``). Kept as a plain dataclass so unit tests
    can assert against the logic without instantiating prompt_toolkit.
    """

    name: str
    description: str
    source: str
    start_position: int
    """Negative offset relative to the cursor, matching prompt_toolkit's
    ``Completion.start_position`` contract (``-len(prefix_typed_so_far)``)."""


def iter_completions(
    registry: CommandRegistry,
    text_before_cursor: str,
) -> Iterator[SlashCompletion]:
    """Yield completions for the slash token under the cursor.

    Returns nothing when the buffer does not begin with ``/`` or the cursor
    is past the first whitespace token (i.e. the user is already typing
    arguments). Matches are returned in the registry's canonical order —
    currently alphabetical by command name.
    """
    if not text_before_cursor.startswith("/"):
        return
    # Only complete while the cursor is inside the command token — once the
    # user types a space we hand off to (future) arg completers.
    if any(ch in text_before_cursor for ch in (" ", "\t")):
        return

    prefix = text_before_cursor[1:]
    matches = registry.match_prefix(prefix)
    # ``start_position`` is negative: the completion replaces the portion of
    # the command token the user has already typed. The leading ``/`` stays
    # in the buffer, so we only replace ``prefix``.
    start_position = -len(prefix)
    for command in matches:
        yield SlashCompletion(
            name=command.name,
            description=command.description,
            source=command.source,
            start_position=start_position,
        )


class SlashCommandCompleter:
    """prompt_toolkit ``Completer`` backed by a :class:`CommandRegistry`.

    Subclassing at runtime (rather than at class definition time) keeps
    ``prompt_toolkit`` out of the module-level import path so non-interactive
    tests can import :mod:`cli.workbench_app.completer` without pulling the
    UI stack. The ``__init_subclass__`` trick is not used here — we just
    import lazily in ``__init__``.
    """

    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> CommandRegistry:
        return self._registry

    def get_completions(
        self,
        document: "Document",
        complete_event: "CompleteEvent",
    ) -> "Iterable[Completion]":
        from prompt_toolkit.completion import Completion

        del complete_event  # unused — every invocation completes unconditionally
        for record in iter_completions(self._registry, document.text_before_cursor):
            yield Completion(
                text=record.name,
                start_position=record.start_position,
                display=f"/{record.name}",
                display_meta=record.description,
            )


def build_completer(registry: CommandRegistry) -> SlashCommandCompleter:
    """Convenience factory mirroring the other ``build_*`` helpers."""
    return SlashCommandCompleter(registry)


__all__ = [
    "SlashCommandCompleter",
    "SlashCompletion",
    "build_completer",
    "iter_completions",
]
