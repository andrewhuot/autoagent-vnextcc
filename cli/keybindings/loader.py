"""Keybindings JSON loader and merge logic.

The loader is intentionally agnostic of prompt_toolkit: it produces a
:class:`BindingSet` that any input layer (prompt_toolkit today,
Textual tomorrow) can consume. This keeps the persistence surface
stable even if the runtime binding framework changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable


class KeyBindingMode(str, Enum):
    """Editor-mode family the bindings target."""

    DEFAULT = "default"
    """Emacs-style bindings — the workbench default."""

    VIM = "vim"
    """Full modal vim bindings. Enables modal-state tracking in a
    future prompt_toolkit wiring."""


@dataclass(frozen=True)
class KeyBinding:
    """One declarative binding record.

    The binding is immutable so it can be cached and shared across
    sessions without risk of an in-memory mutation drifting the config.
    """

    keys: tuple[str, ...]
    """Canonical sequence of key tokens. A single-key binding stores a
    tuple of length one; chords use length ≥ 2."""

    command: str
    """Logical action name. The REPL maps actions to runtime handlers."""

    when: str = ""
    """Optional context guard (``"prompt"``, ``"transcript"``, ...). Empty
    string means "always active"."""


@dataclass
class BindingSet:
    """Parsed keybinding configuration.

    The ``mode`` tells the input layer which family of defaults to apply
    before layering ``bindings`` on top. We keep custom bindings as a
    list so order is meaningful: the last binding for a given
    (keys, when) tuple wins, mirroring how humans read the file."""

    mode: KeyBindingMode = KeyBindingMode.DEFAULT
    bindings: list[KeyBinding] = field(default_factory=list)

    def lookup(self, keys: Iterable[str], *, when: str = "") -> KeyBinding | None:
        """Return the last binding matching ``keys`` and ``when``.

        The scan iterates in reverse so user overrides registered after
        the defaults take precedence with one pass — mirrors how most
        precedence systems (PATH, CSS cascade) resolve."""
        target = tuple(keys)
        for binding in reversed(self.bindings):
            if binding.keys == target and binding.when == when:
                return binding
        return None

    def actions(self) -> set[str]:
        """Return the set of logical command names referenced by bindings.

        Handy for the REPL to validate that every referenced command has
        a registered handler — a typo in ``keybindings.json`` should
        surface at load time, not the moment the user presses the key."""
        return {binding.command for binding in self.bindings}


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


DEFAULT_BINDINGS: tuple[KeyBinding, ...] = (
    KeyBinding(keys=("enter",), command="submit", when="prompt"),
    KeyBinding(keys=("escape",), command="cancel", when="prompt"),
    KeyBinding(keys=("ctrl+c",), command="interrupt", when="prompt"),
    KeyBinding(keys=("ctrl+d",), command="exit", when="prompt"),
    KeyBinding(keys=("ctrl+l",), command="clear-transcript"),
    KeyBinding(keys=("ctrl+r",), command="history-search", when="prompt"),
    KeyBinding(keys=("up",), command="history-previous", when="prompt"),
    KeyBinding(keys=("down",), command="history-next", when="prompt"),
    KeyBinding(keys=("tab",), command="completion-next", when="prompt"),
    KeyBinding(keys=("shift+tab",), command="mode-cycle", when="prompt"),
)
"""Emacs-style defaults layered on top of every :class:`BindingSet`.

Listed as plain data so tests can assert the defaults without spinning
up prompt_toolkit. The set intentionally stays small; anything that
wants to rebind one of these just adds an override with the same keys
and the loader's "last wins" semantics applies."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


DEFAULT_CONFIG_PATH = Path.home() / ".agentlab" / "keybindings.json"


def load_bindings(path: Path | None = None) -> BindingSet:
    """Parse ``path`` (or the default user config) into a :class:`BindingSet`.

    Missing / unreadable files return the defaults — the REPL should work
    without any user config. Malformed JSON raises :class:`ValueError` so
    the workbench can surface "your keybindings file is broken" up front
    rather than silently falling back."""
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return resolve_bindings(mode=KeyBindingMode.DEFAULT, user_bindings=())

    raw = config_path.read_text(encoding="utf-8").strip()
    if not raw:
        return resolve_bindings(mode=KeyBindingMode.DEFAULT, user_bindings=())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid keybindings JSON in {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Keybindings file {config_path} must contain a JSON object.")

    mode_raw = str(data.get("mode", "default")).lower()
    try:
        mode = KeyBindingMode(mode_raw)
    except ValueError as exc:
        raise ValueError(
            f"Unknown keybinding mode {mode_raw!r} in {config_path}."
        ) from exc

    bindings_raw = data.get("bindings", [])
    if not isinstance(bindings_raw, list):
        raise ValueError(
            f"'bindings' in {config_path} must be an array."
        )

    user_bindings = tuple(_coerce_binding(entry, config_path) for entry in bindings_raw)
    return resolve_bindings(mode=mode, user_bindings=user_bindings)


def resolve_bindings(
    *,
    mode: KeyBindingMode,
    user_bindings: Iterable[KeyBinding],
) -> BindingSet:
    """Layer ``user_bindings`` on top of the mode-appropriate defaults."""
    # Vim mode swaps the prompt-move defaults; for Phase 6 we only expose
    # the mode flag so the REPL can branch — the actual vim bindings
    # ship in a follow-up. For now vim mode still gets the default key
    # list; authors who opt in pick up modal handling once we wire it.
    defaults = list(DEFAULT_BINDINGS)
    return BindingSet(mode=mode, bindings=defaults + list(user_bindings))


def _coerce_binding(entry: object, path: Path) -> KeyBinding:
    if not isinstance(entry, dict):
        raise ValueError(
            f"Binding entry in {path} must be an object, got {type(entry).__name__}."
        )
    keys_raw = entry.get("keys")
    command = str(entry.get("command") or "").strip()
    if not command:
        raise ValueError(f"Binding in {path} missing 'command'.")
    when = str(entry.get("when") or "").strip()

    if isinstance(keys_raw, str):
        keys = (_normalise_key(keys_raw),)
    elif isinstance(keys_raw, list) and keys_raw:
        keys = tuple(_normalise_key(str(key)) for key in keys_raw)
    else:
        raise ValueError(
            f"Binding in {path} must supply 'keys' (string or non-empty array)."
        )

    return KeyBinding(keys=keys, command=command, when=when)


def _normalise_key(raw: str) -> str:
    """Lower-case and trim a key token so ``"Ctrl+C"`` and ``"ctrl+c"``
    hash to the same binding."""
    return raw.strip().lower()


__all__ = [
    "BindingSet",
    "DEFAULT_BINDINGS",
    "DEFAULT_CONFIG_PATH",
    "KeyBinding",
    "KeyBindingMode",
    "load_bindings",
    "resolve_bindings",
]
