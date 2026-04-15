"""Keybindings configuration loader.

Users declare custom key bindings in ``~/.agentlab/keybindings.json``.
This package parses that file into a :class:`BindingSet` that future
prompt_toolkit wiring can consume — today the loader and lookup API are
public so authors can start declaring bindings while the interactive
binding is still being built.

Schema (mirrors Claude Code's ``keybindings.json``):

.. code-block:: json

    {
      "mode": "default",  // "default" | "vim"
      "bindings": [
        { "keys": "ctrl+s", "command": "send", "when": "prompt" },
        { "keys": ["ctrl+k", "ctrl+c"], "command": "clear-transcript" }
      ]
    }

``keys`` accepts a single string or a list (chord). ``command`` is the
logical action name; the REPL maps actions to handlers, decoupling the
user config from the code layout.
"""

from __future__ import annotations

from cli.keybindings.loader import (
    DEFAULT_BINDINGS,
    BindingSet,
    KeyBinding,
    KeyBindingMode,
    load_bindings,
    resolve_bindings,
)

__all__ = [
    "DEFAULT_BINDINGS",
    "BindingSet",
    "KeyBinding",
    "KeyBindingMode",
    "load_bindings",
    "resolve_bindings",
]
