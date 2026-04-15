"""Translate a :class:`BindingSet` into live prompt_toolkit bindings.

Isolated from :mod:`cli.keybindings.loader` so the data layer stays free
of prompt_toolkit imports — the loader remains safe to use from
non-interactive code paths and tests.

Key design points:

- ``build_prompt_toolkit_bindings`` returns a ``KeyBindings`` instance
  that prompt_toolkit consumes via ``PromptSession(key_bindings=...)``.
- Chord bindings (``("ctrl+k", "ctrl+c")``) use prompt_toolkit's
  native multi-key support: ``KeyBindings.add(key1, key2, handler)``.
- ``translate_key`` maps the loader's lowercase tokens (``"ctrl+c"``,
  ``"shift+tab"``) to prompt_toolkit ``Keys`` / raw character values.
- ``when`` filtering is lightweight today — empty string or ``"prompt"``
  means "always active". Other values are silently skipped so future
  context-specific bindings don't crash current releases.
"""

from __future__ import annotations

from typing import Any

from cli.keybindings.actions import ActionRegistry
from cli.keybindings.loader import BindingSet, KeyBinding

# prompt_toolkit is imported lazily inside functions so importing this
# module from a pure data-layer test never drags in the terminal stack.

# Map of loader tokens -> prompt_toolkit key tokens / Keys members.
# Only populated when prompt_toolkit is importable. The mapping is kept
# string-keyed (loader side) / string-or-Keys-valued (PT side) so the
# translation stays trivial to extend.
_CONTROL_LETTERS = "abcdefghijklmnopqrstuvwxyz"

# Loader `when` values we currently honor. Empty string and "prompt"
# mean "fire on the active prompt"; everything else is a future context.
_LIVE_WHEN_VALUES = frozenset({"", "prompt"})


def translate_key(raw: str) -> Any:
    """Translate a loader key token into a prompt_toolkit key value.

    Returns either a :class:`~prompt_toolkit.keys.Keys` member or a raw
    string (for single literal characters like ``"/"``). Raises
    :class:`ValueError` if the token is not understood — better to fail
    at binding-build time than at key-press time.
    """
    try:
        from prompt_toolkit.keys import Keys
    except ImportError as exc:  # pragma: no cover — hard dep
        raise RuntimeError("prompt_toolkit is required to translate keys.") from exc

    token = raw.strip().lower()
    if not token:
        raise ValueError("Empty key token.")

    # Direct aliases for the most common named keys. Keeping this as a
    # dict is clearer than a cascade of ifs and it's the hot path.
    direct: dict[str, Any] = {
        "enter": Keys.ControlM,
        "return": Keys.ControlM,
        "escape": Keys.Escape,
        "esc": Keys.Escape,
        "tab": Keys.ControlI,
        "shift+tab": Keys.BackTab,
        "s-tab": Keys.BackTab,
        "backtab": Keys.BackTab,
        "backspace": Keys.Backspace,
        "space": " ",
        "up": Keys.Up,
        "down": Keys.Down,
        "left": Keys.Left,
        "right": Keys.Right,
        "home": Keys.Home,
        "end": Keys.End,
        "pageup": Keys.PageUp,
        "pagedown": Keys.PageDown,
        "delete": Keys.Delete,
        "insert": Keys.Insert,
    }
    if token in direct:
        return direct[token]

    if token.startswith(("ctrl+", "c-")):
        letter = token.split("+", 1)[1] if token.startswith("ctrl+") else token.split("-", 1)[1]
        letter = letter.strip().lower()
        if len(letter) == 1 and letter in _CONTROL_LETTERS:
            # prompt_toolkit exposes these as ``Keys.ControlA`` etc.
            return getattr(Keys, f"Control{letter.upper()}")
        raise ValueError(f"Unsupported control key: {raw!r}")

    if token.startswith(("alt+", "meta+")):
        # Alt/meta in prompt_toolkit is expressed as two-key sequences
        # (Keys.Escape, letter). We return a tuple so callers can unpack.
        suffix = token.split("+", 1)[1]
        return (Keys.Escape, suffix)

    if token.startswith("f") and token[1:].isdigit():
        name = f"F{int(token[1:])}"
        attr = getattr(Keys, name, None)
        if attr is not None:
            return attr
        raise ValueError(f"Unsupported function key: {raw!r}")

    if len(token) == 1:
        return token

    raise ValueError(f"Unknown key token: {raw!r}")


def _flatten(keys: tuple[str, ...]) -> list[Any]:
    """Translate a chord tuple into the flat list prompt_toolkit wants.

    A loader key like ``"alt+x"`` expands to two PT keys
    (``Keys.Escape``, ``"x"``), so a chord may yield more entries than
    its length — the output is flat either way.
    """
    out: list[Any] = []
    for raw in keys:
        translated = translate_key(raw)
        if isinstance(translated, tuple):
            out.extend(translated)
        else:
            out.append(translated)
    return out


def build_prompt_toolkit_bindings(
    binding_set: BindingSet,
    actions: ActionRegistry,
) -> Any:
    """Return a ``prompt_toolkit.key_binding.KeyBindings`` built from
    ``binding_set``.

    Bindings whose ``command`` has no registered action are skipped with
    no-ops rather than crashing the whole REPL — the typo-surfacing
    behaviour lives inside the default action stubs, not here, so a
    user's custom action name is free to be defined later.
    """
    try:
        from prompt_toolkit.key_binding import KeyBindings
    except ImportError as exc:  # pragma: no cover — hard dep
        raise RuntimeError("prompt_toolkit is required for runtime bindings.") from exc

    kb = KeyBindings()

    for binding in binding_set.bindings:
        if binding.when not in _LIVE_WHEN_VALUES:
            # Future context guards — document explicitly and skip.
            continue
        try:
            pt_keys = _flatten(binding.keys)
        except ValueError:
            # Unknown key token: skip rather than crash the whole REPL.
            # The loader already validates shape; this is defence in depth.
            continue
        if not pt_keys:
            continue

        handler = actions.get(binding.command)
        if handler is None:
            # Unknown action: skip. The user may register it later.
            continue

        _register(kb, pt_keys, handler)

    return kb


def _register(kb: Any, pt_keys: list[Any], handler: Any) -> None:
    """Attach ``handler`` to ``kb`` under the flat key list ``pt_keys``.

    Kept in a helper so the closure captures a fresh ``handler`` per
    binding — binding the variable in a loop body would let the last
    handler win for all keys.
    """

    def _dispatch(event: Any, _handler: Any = handler) -> None:
        _handler(event)

    kb.add(*pt_keys)(_dispatch)


__all__ = [
    "build_prompt_toolkit_bindings",
    "translate_key",
]
