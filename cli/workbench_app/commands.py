"""Three-tier slash-command taxonomy for the workbench app.

Mirrors the Claude Code ``src/types/command.ts`` contract so the port is
unambiguous:

- ``LocalCommand``   — runs inline, returns a result string handed back to the
                       transcript via the ``onDone`` protocol (T05b).
- ``LocalJSXCommand`` — takes over the screen with a full-screen component that
                        owns its key bindings until the user exits (T08b).
- ``PromptCommand``  — expands to a templated user prompt that the model
                       answers on the next turn.

All slash commands registered on the workbench must go through this module.
The actual execution/``onDone`` plumbing lands in T05/T05b; this file is the
typed surface those layers build on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    Mapping,
    Protocol,
    Sequence,
    Union,
    runtime_checkable,
)

CommandSource = Literal["builtin", "plugin", "project", "user"]
"""Origin of a slash command — drives grouping in the autocomplete popup."""

CommandContext = Literal["inline", "fork"]
"""Whether the command shares the active transcript or forks a sub-context."""

CommandEffort = Literal["minimal", "low", "medium", "high"]
"""Hint for the effort indicator + spinner during long-running commands."""

SlashCommandKind = Literal["local", "local-jsx", "prompt"]
"""Discriminator on ``SlashCommand.kind``."""


@runtime_checkable
class Screen(Protocol):
    """Full-screen takeover contract consumed by ``LocalJSXCommand``.

    Implementations block until the user exits and return a value the caller
    surfaces via ``onDone``. Screens own their own key bindings while active
    and must restore the transcript on exit (see T08b).
    """

    def run(self) -> Any:  # pragma: no cover - Protocol
        ...


LocalHandler = Callable[..., Union[str, None, Awaitable[Union[str, None]]]]
"""Signature for ``LocalCommand`` handlers. Return value is rendered per the
``onDone(display=...)`` contract in T05b; ``None`` means ``display='skip'``."""

ScreenFactory = Callable[..., Screen]
"""Factory that constructs the screen to launch for a ``LocalJSXCommand``."""

PromptTemplate = Union[str, Callable[..., str]]
"""Either a static template string or a callable that produces one."""


@dataclass(frozen=True)
class _CommandMeta:
    """Fields shared across every slash-command variant.

    Mirrors the metadata block on the TS ``Command`` type. ``name`` is the
    slash token without the leading ``/``; registrations are case-insensitive
    and stored in canonical lower-case form.
    """

    name: str
    description: str
    source: CommandSource = "builtin"
    paths: tuple[str, ...] = ()
    context: CommandContext = "inline"
    agent: str | None = None
    hooks: tuple[str, ...] = ()
    effort: CommandEffort | None = None
    allowed_tools: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or self.name.startswith("/"):
            raise ValueError(
                "command name must be non-empty and not include the leading '/'"
            )
        if any(" " in part or "\t" in part for part in (self.name, *self.aliases)):
            raise ValueError("command name/alias must not contain whitespace")


@dataclass(frozen=True)
class LocalCommand(_CommandMeta):
    """Inline command; handler returns a string (or ``None``) for the transcript."""

    handler: LocalHandler | None = None
    kind: SlashCommandKind = field(default="local", init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.handler is None:
            raise ValueError(f"LocalCommand {self.name!r} requires a handler")


@dataclass(frozen=True)
class LocalJSXCommand(_CommandMeta):
    """Full-screen takeover command; ``screen_factory`` builds the screen to run."""

    screen_factory: ScreenFactory | None = None
    kind: SlashCommandKind = field(default="local-jsx", init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.screen_factory is None:
            raise ValueError(
                f"LocalJSXCommand {self.name!r} requires a screen_factory"
            )


@dataclass(frozen=True)
class PromptCommand(_CommandMeta):
    """Expands to a templated user prompt that the model answers on the next turn."""

    prompt_template: PromptTemplate | None = None
    kind: SlashCommandKind = field(default="prompt", init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.prompt_template is None:
            raise ValueError(
                f"PromptCommand {self.name!r} requires a prompt_template"
            )

    def render(self, **context: Any) -> str:
        """Render the prompt template with the provided context variables."""
        template = self.prompt_template
        if callable(template):
            rendered = template(**context)
        elif context:
            rendered = template.format(**context)
        else:
            rendered = template  # type: ignore[assignment]
        if not isinstance(rendered, str):
            raise TypeError(
                f"PromptCommand {self.name!r} produced non-string output"
            )
        return rendered


SlashCommand = Union[LocalCommand, LocalJSXCommand, PromptCommand]


def _canonical(name: str) -> str:
    token = name.lstrip("/").strip().lower()
    if not token:
        raise ValueError("slash command name must be non-empty")
    return token


class CommandRegistry:
    """In-memory registry for slash commands.

    Used by the workbench app to register, look up, and enumerate commands.
    Duplicate registrations raise — commands that genuinely need to override
    an earlier entry must call :meth:`replace` explicitly.
    """

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}

    def register(self, command: SlashCommand) -> SlashCommand:
        name = _canonical(command.name)
        if name in self._commands or name in self._aliases:
            raise ValueError(f"slash command {name!r} already registered")
        for alias in command.aliases:
            alias_key = _canonical(alias)
            if alias_key in self._commands or alias_key in self._aliases:
                raise ValueError(
                    f"alias {alias_key!r} for {name!r} conflicts with an existing command"
                )
        self._commands[name] = command
        for alias in command.aliases:
            self._aliases[_canonical(alias)] = name
        return command

    def replace(self, command: SlashCommand) -> SlashCommand:
        """Register or overwrite an existing command with the same name."""
        name = _canonical(command.name)
        self.unregister(name, missing_ok=True)
        return self.register(command)

    def unregister(self, name: str, *, missing_ok: bool = False) -> None:
        key = _canonical(name)
        command = self._commands.pop(key, None)
        if command is None:
            if missing_ok:
                return
            raise KeyError(key)
        for alias in command.aliases:
            self._aliases.pop(_canonical(alias), None)

    def get(self, name: str) -> SlashCommand | None:
        key = _canonical(name)
        if key in self._commands:
            return self._commands[key]
        alias_target = self._aliases.get(key)
        if alias_target is not None:
            return self._commands.get(alias_target)
        return None

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        try:
            return self.get(name) is not None
        except ValueError:
            return False

    def __len__(self) -> int:
        return len(self._commands)

    def __iter__(self):
        return iter(sorted(self._commands.values(), key=lambda c: c.name))

    def names(self) -> list[str]:
        return sorted(self._commands)

    def all(self) -> list[SlashCommand]:
        return list(self)

    def by_source(self, source: CommandSource) -> list[SlashCommand]:
        return [c for c in self if c.source == source]

    def by_kind(self, kind: SlashCommandKind) -> list[SlashCommand]:
        return [c for c in self if c.kind == kind]

    def match_prefix(self, prefix: str) -> list[SlashCommand]:
        """Return commands whose name or alias starts with ``prefix``.

        Used by the autocomplete popup in T19. Accepts an optional leading
        ``/`` for symmetry with what the user actually types.
        """
        token = prefix.lstrip("/").lower()
        matches: dict[str, SlashCommand] = {}
        for name, command in self._commands.items():
            if name.startswith(token):
                matches[name] = command
        for alias, target in self._aliases.items():
            if alias.startswith(token):
                command = self._commands.get(target)
                if command is not None:
                    matches.setdefault(target, command)
        return sorted(matches.values(), key=lambda c: c.name)

    def help_table(self) -> Mapping[str, str]:
        """Return a ``{/name: description}`` mapping for ``/help`` rendering."""
        return {f"/{c.name}": c.description for c in self}


def build_default_registry(
    commands: Sequence[SlashCommand] = (),
) -> CommandRegistry:
    """Construct a registry pre-populated with the provided commands.

    Convenience for tests and future bootstrap code; the workbench app will
    pass the full built-in command list here once T05 ports the handlers.
    """
    registry = CommandRegistry()
    for command in commands:
        registry.register(command)
    return registry


__all__ = [
    "CommandContext",
    "CommandEffort",
    "CommandRegistry",
    "CommandSource",
    "LocalCommand",
    "LocalJSXCommand",
    "LocalHandler",
    "PromptCommand",
    "PromptTemplate",
    "Screen",
    "ScreenFactory",
    "SlashCommand",
    "SlashCommandKind",
    "build_default_registry",
]
