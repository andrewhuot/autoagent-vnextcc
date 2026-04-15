"""Vim-modal keybinding layer.

When a user opts in with ``"mode": "vim"`` in ``keybindings.json``, the
REPL switches prompt_toolkit into ``EditingMode.VI`` — which already
provides h/j/k/l motions, w/b word motions, 0/$ line motions, i/a/o
insert transitions, dd/yy/p/u commands, and visual-mode selection. This
module exists to:

1. Export :data:`VIM_BINDINGS` for any *additional* ad-hoc bindings we
   want to layer on top of prompt_toolkit's native vi emulation (right
   now: an empty tuple, leaving built-in behaviour intact).
2. Provide :func:`apply_vim_mode` which the REPL calls to translate a
   :class:`~cli.keybindings.loader.BindingSet` with
   :class:`KeyBindingMode.VIM` into the prompt_toolkit ``EditingMode``
   flag the session should be launched with.

Rationale: prompt_toolkit's vi implementation already covers every
motion and command the spec lists, so reinventing them would only add
drift. Layer overrides only when behaviour actually has to diverge from
the built-in.
"""

from __future__ import annotations

from typing import Any

from cli.keybindings.loader import BindingSet, KeyBinding, KeyBindingMode

# Deliberately empty: prompt_toolkit's built-in VI mode supplies h/j/k/l,
# w/b, 0/$, i/a/A, o, dd, yy, p, u, Esc, visual h/j/k/l/y out of the box.
# Add entries here only when we need to *deviate* from that default.
VIM_BINDINGS: tuple[KeyBinding, ...] = ()
"""Ad-hoc vim-layer bindings layered on top of prompt_toolkit's native VI
emulation. Empty today — extend when a specific command needs to differ
from the stock behaviour (e.g. ``:w`` to submit instead of Enter)."""


def vim_editing_mode() -> Any:
    """Return ``prompt_toolkit.enums.EditingMode.VI``.

    Isolated behind a helper so tests and callers don't have to import
    prompt_toolkit themselves. Raises :class:`RuntimeError` if the
    library isn't installed, which should never happen in practice
    since it's a hard dependency.
    """
    try:
        from prompt_toolkit.enums import EditingMode
    except ImportError as exc:  # pragma: no cover — hard dep
        raise RuntimeError("prompt_toolkit is required for vim mode.") from exc
    return EditingMode.VI


def editing_mode_for(binding_set: BindingSet) -> Any:
    """Return the prompt_toolkit ``EditingMode`` matching ``binding_set.mode``.

    ``KeyBindingMode.VIM`` → ``EditingMode.VI``; everything else →
    ``EditingMode.EMACS`` (prompt_toolkit's Emacs-style default).
    """
    try:
        from prompt_toolkit.enums import EditingMode
    except ImportError as exc:  # pragma: no cover — hard dep
        raise RuntimeError("prompt_toolkit is required for editing-mode lookup.") from exc
    if binding_set.mode == KeyBindingMode.VIM:
        return EditingMode.VI
    return EditingMode.EMACS


def apply_vim_overlay(binding_set: BindingSet) -> BindingSet:
    """Return ``binding_set`` with :data:`VIM_BINDINGS` appended when in VIM mode.

    No-op when ``mode`` is not VIM so default callers don't see drift.
    Today this is effectively still a no-op because :data:`VIM_BINDINGS`
    is empty, but callers wire through this helper so adding bindings
    later is a one-line change.
    """
    if binding_set.mode != KeyBindingMode.VIM or not VIM_BINDINGS:
        return binding_set
    return BindingSet(
        mode=binding_set.mode,
        bindings=list(binding_set.bindings) + list(VIM_BINDINGS),
    )


__all__ = [
    "VIM_BINDINGS",
    "apply_vim_overlay",
    "editing_mode_for",
    "vim_editing_mode",
]
