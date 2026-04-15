"""Logical action registry for keybinding dispatch.

Keybindings are declared by logical name (``"submit"``, ``"cancel"``)
rather than by raw keystroke. The REPL registers a callable per name,
decoupling ``keybindings.json`` from the code layout and letting tests
stub handlers independently of prompt_toolkit.

Each default handler raises :class:`NotImplementedError` with a hint —
the REPL wires in real behaviour at runtime. A missing override surfaces
loudly instead of silently swallowing the keystroke.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

ActionHandler = Callable[[Any], None]
"""Handler signature.

Receives the prompt_toolkit ``KeyPressEvent`` (typed loosely as ``Any``
so this module doesn't import prompt_toolkit eagerly). Handlers may call
``event.app.exit()``, ``event.current_buffer.insert_text(...)``, etc.
"""

# Default set of logical action names the REPL is expected to implement.
# The registry seeds every name with a raising stub so typos in
# ``keybindings.json`` trip a clear error the first time the binding
# fires, rather than failing silently.
DEFAULT_ACTION_NAMES: tuple[str, ...] = (
    "submit",
    "cancel",
    "interrupt",
    "exit",
    "clear-transcript",
    "history-previous",
    "history-next",
    "completion-next",
    "mode-cycle",
    "history-search",
)


def _unimplemented(name: str) -> ActionHandler:
    """Return a handler that complains this action is not wired up yet."""

    def _handler(_event: Any) -> None:
        raise NotImplementedError(
            f"Keybinding action {name!r} has no REPL handler registered. "
            "Register one via ActionRegistry.register() before running the prompt."
        )

    _handler.__name__ = f"_unimplemented_{name.replace('-', '_')}"
    return _handler


@dataclass
class ActionRegistry:
    """Mutable mapping of action name -> callable.

    Constructed empty; call :meth:`install_defaults` to seed the
    canonical stubs, then :meth:`register` to replace any of them with
    real handlers. Unknown names resolve to ``None`` via :meth:`get`
    so callers can decide whether to raise or warn.
    """

    handlers: dict[str, ActionHandler] = field(default_factory=dict)

    def install_defaults(self) -> "ActionRegistry":
        """Seed the registry with raising stubs for every canonical action."""
        for name in DEFAULT_ACTION_NAMES:
            self.handlers.setdefault(name, _unimplemented(name))
        return self

    def register(self, name: str, handler: ActionHandler) -> None:
        """Register (or replace) ``handler`` for the logical action ``name``."""
        if not name:
            raise ValueError("Action name must be a non-empty string.")
        self.handlers[name] = handler

    def get(self, name: str) -> ActionHandler | None:
        """Return the handler for ``name`` or ``None`` if unregistered."""
        return self.handlers.get(name)

    def dispatch(self, name: str, event: Any) -> None:
        """Invoke the handler for ``name``.

        Raises :class:`KeyError` if the name was never registered — this
        is distinct from the ``NotImplementedError`` the default stubs
        raise, so callers can tell "typo" from "not wired yet" apart.
        """
        handler = self.handlers.get(name)
        if handler is None:
            raise KeyError(f"No handler registered for action {name!r}.")
        handler(event)


def build_default_registry() -> ActionRegistry:
    """Return a registry pre-populated with raising stubs.

    Callers are expected to replace the stubs for actions they actually
    support. Anything left untouched will raise ``NotImplementedError``
    the first time the matching keybinding fires, which is the wiring
    seam the REPL relies on to surface bugs.
    """
    return ActionRegistry().install_defaults()


__all__ = [
    "ActionHandler",
    "ActionRegistry",
    "DEFAULT_ACTION_NAMES",
    "build_default_registry",
]
