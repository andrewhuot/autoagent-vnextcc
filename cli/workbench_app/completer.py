"""Slash-command autocomplete for the workbench app (T19).

prompt_toolkit ``Completer`` implementation that turns
:class:`cli.workbench_app.commands.CommandRegistry` entries into the popup
shown when the user types ``/`` at the input prompt. Mirrors Claude Code's
command-palette UX: bare ``/`` opens with the full list grouped by source,
``/ev`` narrows to matching prefixes, each row shows a one-line description
as ``display_meta``.

The completer fires while the caret is inside the first whitespace token
of the buffer — completing command names, not their arguments. An ``@``
token anywhere in the line opens a workspace-relative file-reference
popup (Claude Code parity): typing ``@src/`` surfaces files under
``src/`` ranked by typed prefix.

The module is kept free of prompt_toolkit-specific imports at module scope
so the rest of :mod:`cli.workbench_app` (which runs in headless tests) does
not pay an import cost; the prompt_toolkit symbols are imported at class /
function bodies.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable, Iterator

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
    display_meta: str = ""
    argument_hint: str | None = None

    def __post_init__(self) -> None:
        """Backfill display metadata for direct test constructors.

        Mirrors :func:`_completion_meta`: source tag is appended only for
        non-builtin commands so direct constructions match what the real
        registry-backed rendering path produces.
        """
        if not self.display_meta:
            meta = self.description
            if self.source and self.source != "builtin":
                meta = f"{meta}  [{self.source}]"
            object.__setattr__(self, "display_meta", meta)


def iter_completions(
    registry: CommandRegistry,
    text_before_cursor: str,
    *,
    skill_registry: Any = None,
) -> Iterator[SlashCompletion]:
    """Yield completions for the slash token under the cursor.

    Returns nothing when the buffer does not begin with ``/`` or the cursor
    is past the first whitespace token (i.e. the user is already typing
    arguments). Matches are ranked by names, aliases, and descriptive text.

    When ``skill_registry`` is supplied, loaded user skills are surfaced as
    virtual ``/slug`` completions so ``/commit`` completes even though the
    skill is dispatched via the ``/skill`` verb under the hood.
    """
    if not text_before_cursor.startswith("/"):
        return
    # Only complete while the cursor is inside the command token — once the
    # user types a space we hand off to (future) arg completers.
    if any(ch in text_before_cursor for ch in (" ", "\t")):
        return

    prefix = text_before_cursor[1:]
    matches = _ranked_matches(registry, prefix)
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
            display_meta=_completion_meta(command),
            argument_hint=command.argument_hint,
        )

    if skill_registry is not None:
        yield from _iter_skill_completions(skill_registry, prefix, start_position, registry)


def _iter_skill_completions(
    skill_registry: Any,
    prefix: str,
    start_position: int,
    command_registry: CommandRegistry,
) -> Iterator[SlashCompletion]:
    """Yield ``/<slug>`` completions for disk-loaded skills.

    We hide skills whose slug already matches a registered command so the
    popup doesn't show two rows for ``/plan`` when the user happens to have
    a ``plan.md`` skill file — the built-in command wins."""
    token = prefix.lstrip("/").lower()
    try:
        skills = skill_registry.list()
    except AttributeError:
        return
    for skill in skills:
        slug = getattr(skill, "slug", "")
        if not slug or command_registry.get(f"/{slug}") is not None:
            continue
        if token and token not in slug.lower() and not _is_subsequence_match(token, slug.lower()):
            continue
        description = getattr(skill, "description", "") or ""
        source = getattr(getattr(skill, "source", None), "value", "skill")
        yield SlashCompletion(
            name=slug,
            description=description,
            source=f"skill:{source}",
            start_position=start_position,
            display_meta=_skill_meta(skill),
        )


def _skill_meta(skill: Any) -> str:
    description = getattr(skill, "description", "") or "(no description)"
    allowed = getattr(skill, "allowed_tools", ()) or ()
    if allowed:
        return f"{description}  tools: {', '.join(allowed)}  [skill]"
    return f"{description}  [skill]"


def _completion_meta(command: SlashCommand) -> str:
    """Render compact metadata for a slash completion row.

    Matches Claude Code's palette: description first, then argument hint if
    the command takes args, then aliases, and finally a ``[source]`` tag
    only for non-builtin commands. Builtin commands are the vast majority,
    so tagging every one of them just clutters the menu.
    """
    parts = [command.description]
    if command.argument_hint:
        parts.append(command.argument_hint)
    if command.aliases:
        aliases = ", ".join(f"/{alias}" for alias in command.aliases)
        parts.append(f"aliases: {aliases}")
    if command.source and command.source != "builtin":
        parts.append(f"[{command.source}]")
    return "  ".join(parts)


def _ranked_matches(registry: CommandRegistry, query: str) -> list[SlashCommand]:
    """Return visible commands ranked by name, alias, and descriptive text."""
    token = query.lstrip("/").lower()
    commands = registry.visible()
    if not token:
        return sorted(commands, key=lambda c: c.name)

    ranked: list[tuple[tuple[int, str], SlashCommand]] = []
    for command in commands:
        score = _score_command(command, token)
        if score is not None:
            ranked.append(((score, command.name), command))
    return [command for _rank, command in sorted(ranked, key=lambda item: item[0])]


def _score_command(command: SlashCommand, token: str) -> int | None:
    """Return a lower-is-better match score, or ``None`` for no match."""
    name = command.name.lower()
    aliases = tuple(alias.lower() for alias in command.aliases)

    if name == token:
        return 0
    if token in aliases:
        return 1
    if name.startswith(token):
        return 2
    if any(alias.startswith(token) for alias in aliases):
        return 3
    if len(token) >= 3 and token in name:
        return 4
    if len(token) >= 3 and any(token in alias for alias in aliases):
        return 5

    searchable_text = " ".join(
        part
        for part in (
            command.description,
            command.argument_hint or "",
            command.when_to_use or "",
            command.source,
        )
        if part
    ).lower()
    if len(token) >= 3 and token in searchable_text:
        return 6

    candidates = (name, *aliases, *searchable_text.split())
    if (
        len(token) >= 3
        and difflib.get_close_matches(token, candidates, n=1, cutoff=0.72)
    ):
        return 7

    # Character-subsequence match ("ppr" matches "plan-approve" because
    # p→p→r appears in order). Requires 3+ char queries to keep two-char
    # tokens like ``/ev`` from surfacing noisy matches (``review`` would
    # subsequence-match ``ev`` otherwise).
    if len(token) >= 3 and _is_subsequence_match(token, name):
        return 8
    if len(token) >= 3 and any(_is_subsequence_match(token, alias) for alias in aliases):
        return 9

    return None


def _is_subsequence_match(token: str, candidate: str) -> bool:
    """Return ``True`` when every character of ``token`` appears in order in
    ``candidate``. Case-insensitive; both inputs are already lowercased
    by :func:`_score_command`."""
    if not token:
        return True
    it = iter(candidate)
    return all(char in it for char in token)


MAX_FILE_COMPLETIONS = 20
"""Cap the file-ref popup so large repos don't drown the terminal."""

_IGNORED_DIR_NAMES = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
    ".idea",
    ".vscode",
})


@dataclass(frozen=True)
class FileReferenceCompletion:
    """Framework-agnostic file-reference completion record."""

    path: str
    start_position: int
    is_dir: bool = False
    display_meta: str = ""


def extract_file_ref_token(text_before_cursor: str) -> str | None:
    """Return the active ``@``-prefixed token under the caret, or ``None``.

    The caret must sit on a token starting with ``@`` that has no embedded
    whitespace. Returns the text *after* the leading ``@``. ``"@"`` alone
    returns ``""`` (the popup should list root-level entries).
    """
    if not text_before_cursor:
        return None
    # Walk backwards to find the start of the current non-whitespace run.
    for offset, ch in enumerate(reversed(text_before_cursor)):
        if ch.isspace():
            start = len(text_before_cursor) - offset
            break
    else:
        start = 0
    token = text_before_cursor[start:]
    if not token.startswith("@"):
        return None
    return token[1:]


def iter_file_completions(
    root: Path | str | None,
    text_before_cursor: str,
    *,
    limit: int = MAX_FILE_COMPLETIONS,
) -> Iterator[FileReferenceCompletion]:
    """Yield workspace-relative file matches for an ``@``-prefixed token.

    Directory matches come first and end in ``/`` so the caret lands
    inside the folder, matching shell-style path completion. Hidden
    entries (starting with ``.``) are surfaced only when the query itself
    begins with ``.``.
    """
    token = extract_file_ref_token(text_before_cursor)
    if token is None:
        return
    base = Path(root) if root is not None else Path.cwd()
    try:
        base = base.resolve()
    except OSError:
        return

    search_dir, query_prefix = _split_query_path(token)
    absolute = base / search_dir if str(search_dir) else base
    try:
        entries = sorted(os.scandir(absolute), key=lambda entry: entry.name.lower())
    except OSError:
        return

    start_position = -(len(token) + 1)
    yielded = 0
    include_hidden = query_prefix.startswith(".")
    for entry in entries:
        name = entry.name
        if not include_hidden and name.startswith("."):
            continue
        if name in _IGNORED_DIR_NAMES:
            continue
        if query_prefix and not name.lower().startswith(query_prefix.lower()):
            continue
        rel = _join_relative(search_dir, name)
        is_dir = entry.is_dir(follow_symlinks=False)
        display = f"@{rel}{'/' if is_dir else ''}"
        yield FileReferenceCompletion(
            path=rel + ("/" if is_dir else ""),
            start_position=start_position,
            is_dir=is_dir,
            display_meta=f"{'dir' if is_dir else 'file'}  {display}",
        )
        yielded += 1
        if yielded >= limit:
            return


def _split_query_path(token: str) -> tuple[str, str]:
    """Return ``(directory_part, prefix_part)`` for an ``@``-token."""
    if not token:
        return "", ""
    if token.endswith("/"):
        return token.rstrip("/"), ""
    if "/" in token:
        head, _, tail = token.rpartition("/")
        return head, tail
    return "", token


def _join_relative(directory: str, name: str) -> str:
    """Compose a workspace-relative display path for a completion row."""
    if directory:
        return f"{directory}/{name}"
    return name


class SlashCommandCompleter:
    """prompt_toolkit ``Completer`` backed by a :class:`CommandRegistry`.

    Subclassing at runtime (rather than at class definition time) keeps
    ``prompt_toolkit`` out of the module-level import path so non-interactive
    tests can import :mod:`cli.workbench_app.completer` without pulling the
    UI stack. The ``__init_subclass__`` trick is not used here — we just
    import lazily in ``__init__``.

    When ``workspace_root`` is bound, the completer also serves workspace-
    relative file-reference completions for ``@``-prefixed tokens.
    """

    def __init__(
        self,
        registry: CommandRegistry,
        *,
        workspace_root: Path | str | None = None,
    ) -> None:
        self._registry = registry
        self._workspace_root = Path(workspace_root) if workspace_root else None

    @property
    def registry(self) -> CommandRegistry:
        return self._registry

    @property
    def workspace_root(self) -> Path | None:
        return self._workspace_root

    def get_completions(
        self,
        document: "Document",
        complete_event: "CompleteEvent",
    ) -> "Iterable[Completion]":
        from prompt_toolkit.completion import Completion

        del complete_event  # unused — every invocation completes unconditionally
        text_before_cursor = document.text_before_cursor

        token = extract_file_ref_token(text_before_cursor)
        if token is not None:
            for file_record in iter_file_completions(
                self._workspace_root, text_before_cursor
            ):
                yield Completion(
                    text=f"@{file_record.path}",
                    start_position=file_record.start_position,
                    display=f"@{file_record.path}",
                    display_meta=file_record.display_meta,
                )
            return

        for record in iter_completions(self._registry, text_before_cursor):
            yield Completion(
                text=record.name,
                start_position=record.start_position,
                display=f"/{record.name}",
                display_meta=record.display_meta,
            )

    async def get_completions_async(
        self,
        document: "Document",
        complete_event: "CompleteEvent",
    ) -> "AsyncIterator[Completion]":
        """Yield completions for prompt_toolkit's while-typing async path."""
        for completion in self.get_completions(document, complete_event):
            yield completion


def build_completer(
    registry: CommandRegistry,
    *,
    workspace_root: Path | str | None = None,
) -> SlashCommandCompleter:
    """Convenience factory mirroring the other ``build_*`` helpers."""
    return SlashCommandCompleter(registry, workspace_root=workspace_root)


__all__ = [
    "FileReferenceCompletion",
    "MAX_FILE_COMPLETIONS",
    "SlashCommandCompleter",
    "SlashCompletion",
    "build_completer",
    "extract_file_ref_token",
    "iter_completions",
    "iter_file_completions",
]
