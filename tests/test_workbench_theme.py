"""Unit tests for :mod:`cli.workbench_app.theme`.

The palette is the single source of truth for colour decisions in the
workbench REPL (T18). These tests pin the role → colour mapping so an
accidental change to the defaults requires a conscious test update, and
they verify every helper respects ``color=False`` for ANSI-free output.
"""

from __future__ import annotations

import dataclasses

import click
import pytest

from cli.workbench_app import theme


# ------------------------------------------------------------------ palette

def test_palette_is_frozen() -> None:
    """The palette must be immutable so no caller can repaint it at runtime."""

    with pytest.raises(dataclasses.FrozenInstanceError):
        theme.PALETTE.workspace = "magenta"  # type: ignore[misc]


def test_palette_default_role_colors() -> None:
    """Pin the advertised defaults — plan T18 names each role's colour."""

    assert theme.PALETTE.workspace == "cyan"
    assert theme.PALETTE.user == "cyan"
    assert theme.PALETTE.success == "green"
    assert theme.PALETTE.warning == "yellow"
    assert theme.PALETTE.error == "red"
    assert theme.PALETTE.command_name == "cyan"
    assert theme.PALETTE.assistant is None
    assert theme.PALETTE.plan_mode == "cyan"
    assert theme.PALETTE.accept_mode == "green"
    assert theme.PALETTE.danger_mode == "red"
    # Turquoise-blue accent (xterm 256-colour index) for the Claude-Code-style chevron.
    assert theme.PALETTE.prompt_accent == 45
    # Border roles default to dim chrome (None triggers the dim path).
    assert theme.PALETTE.border is None


# -------------------------------------------------------------------- meta

def test_meta_applies_dim_ansi() -> None:
    styled = theme.meta("tip")
    assert styled != "tip"
    assert click.unstyle(styled) == "tip"


def test_meta_color_false_returns_plain_text() -> None:
    assert theme.meta("tip", color=False) == "tip"


# -------------------------------------------------- workspace / user / cmd

CYAN_CODE = "\x1b[36m"
GREEN_CODE = "\x1b[32m"
YELLOW_CODE = "\x1b[33m"
RED_CODE = "\x1b[31m"
BOLD_CODE = "\x1b[1m"
DIM_CODE = "\x1b[2m"
RESET_CODE = "\x1b[0m"


@pytest.mark.parametrize(
    "helper, bold_default",
    [
        (theme.workspace, True),
        (theme.user, True),
        (theme.command_name, False),
    ],
)
def test_cyan_role_helpers_apply_cyan(helper, bold_default) -> None:
    styled = helper("label")
    assert click.unstyle(styled) == "label"
    assert CYAN_CODE in styled
    assert (BOLD_CODE in styled) is bold_default


def test_workspace_bold_false_strips_bold() -> None:
    styled = theme.workspace("label", bold=False)
    assert CYAN_CODE in styled
    assert BOLD_CODE not in styled
    assert click.unstyle(styled) == "label"


def test_command_name_bold_true_opts_in() -> None:
    styled = theme.command_name("/help", bold=True)
    assert CYAN_CODE in styled
    assert BOLD_CODE in styled
    assert click.unstyle(styled) == "/help"


def test_workspace_color_false_returns_plain() -> None:
    assert theme.workspace("lab", color=False) == "lab"


# ---------------------------------------------------------------- assistant

def test_assistant_without_color_role_returns_verbatim() -> None:
    """Default palette leaves assistant output untouched so pre-styled event
    lines pass through unchanged.
    """

    assert theme.assistant("hello") == "hello"


# ------------------------------------------------------- success / warning

def test_success_default_is_green_without_bold() -> None:
    styled = theme.success("done")
    assert GREEN_CODE in styled
    assert BOLD_CODE not in styled
    assert click.unstyle(styled) == "done"


def test_success_bold_true_adds_bold() -> None:
    styled = theme.success("done", bold=True)
    assert GREEN_CODE in styled
    assert BOLD_CODE in styled
    assert click.unstyle(styled) == "done"


def test_warning_default_is_yellow() -> None:
    styled = theme.warning("watch out")
    assert YELLOW_CODE in styled
    assert BOLD_CODE not in styled
    assert click.unstyle(styled) == "watch out"


def test_warning_color_false_strips_ansi() -> None:
    assert theme.warning("watch out", color=False) == "watch out"


# --------------------------------------------------------------- mode roles

def test_format_mode_renders_permission_symbols_without_color() -> None:
    assert theme.format_mode("default", color=False) == "Default"
    assert theme.format_mode("plan", color=False) == "⏸ Plan Mode"
    assert theme.format_mode("acceptEdits", color=False) == "⏵⏵ Accept edits"
    assert theme.format_mode("bypass", color=False) == "⏵⏵ Bypass"


def test_format_mode_applies_role_colors() -> None:
    plan = theme.format_mode("plan")
    accept = theme.format_mode("acceptEdits")
    bypass = theme.format_mode("bypass")

    assert click.unstyle(plan) == "⏸ Plan Mode"
    assert CYAN_CODE in plan
    assert click.unstyle(accept) == "⏵⏵ Accept edits"
    assert GREEN_CODE in accept
    assert click.unstyle(bypass) == "⏵⏵ Bypass"
    assert RED_CODE in bypass
    assert BOLD_CODE in bypass


def test_mode_helpers_respect_color_false() -> None:
    assert theme.plan_mode("x", color=False) == "x"
    assert theme.accept_mode("x", color=False) == "x"
    assert theme.danger_mode("x", color=False) == "x"


# ----------------------------------------------------------------- error

def test_error_default_is_red_bold() -> None:
    """Errors default to bold because callers shouldn't need to remember."""

    styled = theme.error("boom")
    assert RED_CODE in styled
    assert BOLD_CODE in styled
    assert click.unstyle(styled) == "boom"


def test_error_bold_false_drops_bold() -> None:
    styled = theme.error("boom", bold=False)
    assert RED_CODE in styled
    assert BOLD_CODE not in styled
    assert click.unstyle(styled) == "boom"


def test_error_color_false_plain() -> None:
    assert theme.error("boom", color=False) == "boom"


# ---------------------------------------------------------------- heading

def test_heading_is_bold_only() -> None:
    styled = theme.heading("Slash Commands")
    assert BOLD_CODE in styled
    assert CYAN_CODE not in styled
    assert click.unstyle(styled) == "Slash Commands"


def test_heading_color_false_plain() -> None:
    assert theme.heading("Slash Commands", color=False) == "Slash Commands"


# ---------------------------------------------------------------- stylize

def test_stylize_returns_text_verbatim_when_no_flags() -> None:
    """Bare ``stylize`` with no flags is a no-op — important for the
    ``assistant`` fall-through path and for helpers that pass through a
    palette value of ``None``.
    """

    assert theme.stylize("plain") == "plain"


def test_stylize_color_false_short_circuits() -> None:
    assert theme.stylize("plain", fg="red", bold=True, color=False) == "plain"


# ----------------------------------------------------------------- accent
# The turquoise-blue chevron role emits 256-colour SGR `38;5;45` and stays
# bold by default so the prompt reads as the visual anchor of the input card.

ACCENT_256_CODE = "\x1b[38;5;45"


def test_accent_default_is_turquoise_bold() -> None:
    styled = theme.accent("›")
    assert click.unstyle(styled) == "›"
    assert ACCENT_256_CODE in styled
    assert BOLD_CODE in styled


def test_accent_bold_false_drops_bold() -> None:
    styled = theme.accent("›", bold=False)
    assert ACCENT_256_CODE in styled
    assert BOLD_CODE not in styled


def test_accent_color_false_returns_plain() -> None:
    assert theme.accent("›", color=False) == "›"


# ----------------------------------------------------------------- border
# The border helper paints rounded-box chrome dim-grey by default so it
# recedes behind content. When a call site asks for ``color=False`` the
# text must pass through untouched so tests can assert layout without
# ANSI escapes.


def test_border_default_is_dim() -> None:
    styled = theme.border("╭──╮")
    assert click.unstyle(styled) == "╭──╮"
    assert DIM_CODE in styled


def test_border_color_false_returns_plain() -> None:
    assert theme.border("╭──╮", color=False) == "╭──╮"
