"""Tests for :class:`StreamingSpinner` and ``SlashContext.spinner()``.

Chunk 2 of the Claude-Code-UX refactor introduces a thinking indicator that
wraps :class:`cli.progress.PhaseSpinner`. These tests pin down three invariants:

1. Non-TTY runs must be silent no-ops — animation frames would corrupt stream
   JSON, and the spinner should never *consume* echo calls it can't display.
2. Echo calls on a disabled spinner must route to the caller-supplied echo
   (so the transcript / test capture still receives the line).
3. The ``SlashContext.spinner`` factory must build a spinner bound to
   ``ctx.echo`` so handlers can use a single API regardless of TTY mode.
"""

from __future__ import annotations

from cli.workbench_app.slash import SlashContext
from cli.workbench_app.spinner import StreamingSpinner


class _EchoCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


def test_streaming_spinner_composes_label_with_model() -> None:
    """``model · phase`` is the on-screen label when a model is supplied."""
    spin = StreamingSpinner("building", model="gemini-2.5-pro", echo=_EchoCapture())
    assert spin.label == "gemini-2.5-pro · building"


def test_streaming_spinner_collapses_label_without_model() -> None:
    """When no model is known, the label is just the phase."""
    spin = StreamingSpinner("evaluating", echo=_EchoCapture())
    assert spin.label == "evaluating"


def test_streaming_spinner_is_disabled_in_non_tty_context() -> None:
    """pytest captures stdout, so the spinner must detect non-TTY and no-op."""
    spin = StreamingSpinner("building", model="m", echo=_EchoCapture())
    assert spin.enabled is False


def test_streaming_spinner_echo_routes_to_fallback_when_disabled() -> None:
    """Disabled spinner should forward lines to the supplied echo sink."""
    capture = _EchoCapture()
    spin = StreamingSpinner("building", echo=capture)
    with spin:
        spin.echo("hello")
        spin.echo("world")
    assert capture.lines == ["hello", "world"]


def test_streaming_spinner_update_changes_phase_label() -> None:
    """``update(phase)`` swaps the phase segment without losing the model prefix."""
    spin = StreamingSpinner("building", model="opus", echo=_EchoCapture())
    spin.update("parsing envelope")
    assert spin.phase == "parsing envelope"
    assert spin.label == "opus · parsing envelope"


def test_streaming_spinner_context_manager_round_trip() -> None:
    """Enter/exit should not raise on a disabled spinner."""
    spin = StreamingSpinner("building", echo=_EchoCapture())
    with spin as handle:
        assert handle is spin
    # Double-exit is fine too — caller may defensively re-close.


def test_slash_context_spinner_factory_uses_ctx_echo() -> None:
    """``ctx.spinner(...)`` must route echoes through the context's echo sink."""
    capture = _EchoCapture()
    ctx = SlashContext(echo=capture)

    with ctx.spinner("building candidate") as spin:
        spin.echo("streamed line")

    assert capture.lines == ["streamed line"]
    assert spin.phase == "building candidate"


def test_slash_context_spinner_reads_provider_model_from_meta() -> None:
    """The factory prefills ``model`` from ``ctx.meta['provider_model']``.

    This is the hook Chunk 4 will fill with
    :func:`optimizer.providers.describe_default_provider`. Locking the
    contract now keeps that follow-up change trivial.
    """
    ctx = SlashContext(echo=_EchoCapture())
    ctx.meta["provider_model"] = "claude-opus-4-6"

    spin = ctx.spinner("evaluating")

    assert spin.model == "claude-opus-4-6"
    assert spin.label == "claude-opus-4-6 · evaluating"


def test_slash_context_spinner_explicit_model_overrides_meta() -> None:
    """Explicit ``model`` kwarg wins over ``ctx.meta`` defaults."""
    ctx = SlashContext(echo=_EchoCapture())
    ctx.meta["provider_model"] = "fallback-model"

    spin = ctx.spinner("deploying", model="override-model")

    assert spin.model == "override-model"


def test_streaming_spinner_default_echo_is_click_echo(capsys) -> None:
    """With no ``echo=`` kwarg the default should be ``click.echo``."""
    spin = StreamingSpinner("building")
    with spin:
        spin.echo("fell through to click")
    captured = capsys.readouterr()
    assert "fell through to click" in captured.out
