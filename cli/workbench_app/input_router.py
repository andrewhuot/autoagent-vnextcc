"""Central input routing for the Workbench REPL.

The Workbench loop handles several local syntaxes before a line should
reach either chat or coordinator workflows. Keeping that classification in
one pure module prevents plain text from accidentally falling through to a
workflow runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


EXIT_TOKENS = frozenset({"/exit", "/quit", ":q", "exit", "quit"})


class InputKind(str, Enum):
    """Kinds of input the Workbench loop knows how to execute."""

    EMPTY = "empty"
    EXIT = "exit"
    SHORTCUTS = "shortcuts"
    SHELL = "shell"
    BACKGROUND = "background"
    SLASH = "slash"
    CHAT = "chat"


@dataclass(frozen=True)
class InputRoute:
    """Classified user input with the payload needed by the executor."""

    kind: InputKind
    raw: str
    payload: str
    command_name: str | None = None


def route_user_input(line: str) -> InputRoute:
    """Classify one raw REPL line without executing it.

    Only slash-prefixed input can become a slash command. Plain text is a
    chat prompt, even when it contains workflow-y words like "build" or
    "deploy".
    """
    stripped = line.strip()
    if not stripped:
        return InputRoute(kind=InputKind.EMPTY, raw=line, payload="")

    if stripped.lower() in EXIT_TOKENS:
        return InputRoute(kind=InputKind.EXIT, raw=line, payload=stripped)

    if stripped == "?":
        return InputRoute(kind=InputKind.SHORTCUTS, raw=line, payload=stripped)

    if stripped.startswith("!"):
        return InputRoute(kind=InputKind.SHELL, raw=line, payload=stripped)

    if stripped.startswith("&"):
        return InputRoute(
            kind=InputKind.BACKGROUND,
            raw=line,
            payload=stripped[1:].strip(),
        )

    if stripped.startswith("/"):
        command_name = _slash_command_name(stripped)
        return InputRoute(
            kind=InputKind.SLASH,
            raw=line,
            payload=stripped,
            command_name=command_name,
        )

    return InputRoute(kind=InputKind.CHAT, raw=line, payload=stripped)


def _slash_command_name(line: str) -> str:
    """Return the command token from a slash-prefixed line."""
    token = line.split(maxsplit=1)[0]
    return token.lstrip("/")


__all__ = ["EXIT_TOKENS", "InputKind", "InputRoute", "route_user_input"]
