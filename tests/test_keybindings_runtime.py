"""Tests for the keybindings runtime and vim layer.

The runtime translates loader :class:`~cli.keybindings.loader.BindingSet`
instances into live prompt_toolkit key bindings. These tests exercise
that translation in isolation — no TTY, no :class:`PromptSession` — so
they run fast and deterministically.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cli.keybindings import (
    BindingSet,
    KeyBinding,
    KeyBindingMode,
    resolve_bindings,
)
from cli.keybindings.actions import (
    DEFAULT_ACTION_NAMES,
    ActionRegistry,
    build_default_registry,
)
from cli.keybindings.runtime import (
    build_prompt_toolkit_bindings,
    translate_key,
)
from cli.keybindings.vim import (
    VIM_BINDINGS,
    apply_vim_overlay,
    editing_mode_for,
    vim_editing_mode,
)


# ---------------------------------------------------------------------------
# ActionRegistry
# ---------------------------------------------------------------------------


def test_default_registry_seeds_every_canonical_action() -> None:
    registry = build_default_registry()
    for name in DEFAULT_ACTION_NAMES:
        assert registry.get(name) is not None


def test_default_registry_handlers_raise_not_implemented() -> None:
    """Unwired actions must surface loudly, not silently no-op."""
    registry = build_default_registry()
    for name in DEFAULT_ACTION_NAMES:
        handler = registry.get(name)
        assert handler is not None
        with pytest.raises(NotImplementedError) as excinfo:
            handler(SimpleNamespace())
        assert name in str(excinfo.value)


def test_registry_register_replaces_stub_with_real_handler() -> None:
    registry = build_default_registry()
    calls: list[object] = []
    registry.register("submit", lambda event: calls.append(event))
    event = object()
    registry.dispatch("submit", event)
    assert calls == [event]


def test_registry_dispatch_unknown_action_raises_key_error() -> None:
    registry = ActionRegistry()
    with pytest.raises(KeyError):
        registry.dispatch("not-a-thing", SimpleNamespace())


def test_registry_register_rejects_empty_name() -> None:
    registry = ActionRegistry()
    with pytest.raises(ValueError):
        registry.register("", lambda _event: None)


# ---------------------------------------------------------------------------
# translate_key
# ---------------------------------------------------------------------------


def test_translate_key_maps_ctrl_c_to_keys_control_c() -> None:
    from prompt_toolkit.keys import Keys

    assert translate_key("ctrl+c") is Keys.ControlC
    assert translate_key("Ctrl+C") is Keys.ControlC
    # Short-form aliases should also resolve.
    assert translate_key("c-c") is Keys.ControlC


def test_translate_key_maps_named_keys_to_prompt_toolkit() -> None:
    from prompt_toolkit.keys import Keys

    assert translate_key("enter") is Keys.ControlM
    assert translate_key("escape") is Keys.Escape
    assert translate_key("up") is Keys.Up
    assert translate_key("shift+tab") is Keys.BackTab
    assert translate_key("tab") is Keys.ControlI
    assert translate_key("f5") is Keys.F5


def test_translate_key_returns_literal_character_for_single_char() -> None:
    assert translate_key("/") == "/"
    assert translate_key("a") == "a"


def test_translate_key_expands_alt_to_escape_prefix() -> None:
    from prompt_toolkit.keys import Keys

    result = translate_key("alt+x")
    assert result == (Keys.Escape, "x")


def test_translate_key_rejects_unknown_token() -> None:
    with pytest.raises(ValueError):
        translate_key("ctrl+notaletter")
    with pytest.raises(ValueError):
        translate_key("nonsense-key-name")


# ---------------------------------------------------------------------------
# build_prompt_toolkit_bindings
# ---------------------------------------------------------------------------


def test_build_prompt_toolkit_bindings_wires_chord_to_action() -> None:
    """A two-key chord binding must translate to a multi-key prompt_toolkit
    registration that dispatches the right logical action."""
    from prompt_toolkit.keys import Keys

    fired: list[str] = []
    actions = build_default_registry()
    actions.register("clear-transcript", lambda _event: fired.append("cleared"))

    binding_set = BindingSet(
        mode=KeyBindingMode.DEFAULT,
        bindings=[
            KeyBinding(
                keys=("ctrl+k", "ctrl+c"),
                command="clear-transcript",
                when="prompt",
            ),
        ],
    )
    kb = build_prompt_toolkit_bindings(binding_set, actions)

    # Find the binding we registered — prompt_toolkit stores it on
    # ``kb.bindings`` with ``.keys`` matching what we passed to ``add()``.
    target = None
    for binding in kb.bindings:
        if binding.keys == (Keys.ControlK, Keys.ControlC):
            target = binding
            break
    assert target is not None, (
        f"Expected chord (ControlK, ControlC) in {[b.keys for b in kb.bindings]}"
    )

    # Invoke the handler directly — we don't need a real PT app.
    target.handler(SimpleNamespace())
    assert fired == ["cleared"]


def test_build_prompt_toolkit_bindings_skips_non_prompt_when_values() -> None:
    """A ``when`` context we don't support yet should be silently ignored."""
    actions = build_default_registry()
    actions.register("submit", lambda _event: None)

    binding_set = BindingSet(
        mode=KeyBindingMode.DEFAULT,
        bindings=[
            KeyBinding(keys=("ctrl+s",), command="submit", when="future-context"),
        ],
    )
    kb = build_prompt_toolkit_bindings(binding_set, actions)
    assert len(kb.bindings) == 0


def test_build_prompt_toolkit_bindings_skips_unregistered_actions() -> None:
    """User bindings referencing unknown actions shouldn't crash the REPL."""
    actions = ActionRegistry()  # intentionally empty
    binding_set = BindingSet(
        mode=KeyBindingMode.DEFAULT,
        bindings=[
            KeyBinding(keys=("ctrl+x",), command="custom-unknown", when="prompt"),
        ],
    )
    kb = build_prompt_toolkit_bindings(binding_set, actions)
    assert len(kb.bindings) == 0


def test_build_prompt_toolkit_bindings_preserves_handler_identity_across_iterations() -> None:
    """Closure-over-loop bug guard: each binding must keep its own handler."""
    from prompt_toolkit.keys import Keys

    fired: list[str] = []
    actions = ActionRegistry()
    actions.register("a", lambda _event: fired.append("a"))
    actions.register("b", lambda _event: fired.append("b"))

    binding_set = BindingSet(
        mode=KeyBindingMode.DEFAULT,
        bindings=[
            KeyBinding(keys=("ctrl+a",), command="a", when="prompt"),
            KeyBinding(keys=("ctrl+b",), command="b", when="prompt"),
        ],
    )
    kb = build_prompt_toolkit_bindings(binding_set, actions)

    by_keys = {b.keys: b for b in kb.bindings}
    by_keys[(Keys.ControlA,)].handler(SimpleNamespace())
    by_keys[(Keys.ControlB,)].handler(SimpleNamespace())
    assert fired == ["a", "b"]


# ---------------------------------------------------------------------------
# Vim layer
# ---------------------------------------------------------------------------


def test_vim_editing_mode_returns_prompt_toolkit_vi_enum() -> None:
    from prompt_toolkit.enums import EditingMode

    assert vim_editing_mode() is EditingMode.VI


def test_editing_mode_for_vim_binding_set_is_vi() -> None:
    """The opt-in path must surface VI editing mode readably to the REPL."""
    from prompt_toolkit.enums import EditingMode

    binding_set = resolve_bindings(mode=KeyBindingMode.VIM, user_bindings=())
    assert editing_mode_for(binding_set) is EditingMode.VI


def test_editing_mode_for_default_binding_set_is_emacs() -> None:
    from prompt_toolkit.enums import EditingMode

    binding_set = resolve_bindings(mode=KeyBindingMode.DEFAULT, user_bindings=())
    assert editing_mode_for(binding_set) is EditingMode.EMACS


def test_apply_vim_overlay_is_noop_for_default_mode() -> None:
    binding_set = resolve_bindings(mode=KeyBindingMode.DEFAULT, user_bindings=())
    out = apply_vim_overlay(binding_set)
    assert out is binding_set  # no overlay to add for non-vim users


def test_apply_vim_overlay_is_noop_when_vim_bindings_empty() -> None:
    """Current VIM_BINDINGS is empty; overlay must return the input unchanged."""
    assert VIM_BINDINGS == ()
    binding_set = resolve_bindings(mode=KeyBindingMode.VIM, user_bindings=())
    out = apply_vim_overlay(binding_set)
    assert out is binding_set


# ---------------------------------------------------------------------------
# End-to-end-ish: loader + runtime + registry
# ---------------------------------------------------------------------------


def test_default_binding_set_produces_runtime_bindings_for_all_handled_actions() -> None:
    """Walking the default binding list through the runtime must not explode
    and must skip only the commands we haven't given real handlers."""
    actions = build_default_registry()
    # Replace all stubs with no-op lambdas so the runtime accepts every binding.
    for name in DEFAULT_ACTION_NAMES:
        actions.register(name, lambda _event: None)

    binding_set = resolve_bindings(mode=KeyBindingMode.DEFAULT, user_bindings=())
    kb = build_prompt_toolkit_bindings(binding_set, actions)
    # The default set has ten entries; one (ctrl+l clear-transcript) has
    # ``when=""`` which is live, and all others have ``when="prompt"``.
    # All should register.
    assert len(kb.bindings) == len(binding_set.bindings)
