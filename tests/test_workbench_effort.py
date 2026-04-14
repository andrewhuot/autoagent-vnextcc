"""Tests for :mod:`cli.workbench_app.effort` (T18b — effort indicator)."""

from __future__ import annotations

import pytest
import click

from cli.workbench_app.effort import (
    DEFAULT_SPINNER_FRAMES,
    DEFAULT_THRESHOLD_SECONDS,
    EffortIndicator,
    EffortSnapshot,
    format_effort,
    format_elapsed,
)


class _FakeClock:
    """Monotonic clock with a manually advanced cursor."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# EffortIndicator state machine
# ---------------------------------------------------------------------------


def test_indicator_defaults_are_sensible() -> None:
    assert DEFAULT_THRESHOLD_SECONDS == 2.0
    assert len(DEFAULT_SPINNER_FRAMES) == 10


def test_indicator_tick_before_start_returns_none() -> None:
    clock = _FakeClock()
    indicator = EffortIndicator(clock=clock)
    assert indicator.tick() is None
    assert indicator.elapsed() == 0.0
    assert indicator.started is False
    assert indicator.stopped is False


def test_indicator_tick_below_threshold_returns_none() -> None:
    clock = _FakeClock()
    indicator = EffortIndicator(threshold_seconds=2.0, clock=clock)
    indicator.start()
    clock.now = 1.9
    assert indicator.tick() is None
    assert indicator.started is True
    assert indicator.elapsed() == pytest.approx(1.9)


def test_indicator_tick_emits_snapshot_once_visible() -> None:
    clock = _FakeClock()
    indicator = EffortIndicator(threshold_seconds=2.0, clock=clock)
    indicator.start()
    clock.now = 2.0
    snap = indicator.tick()
    assert snap is not None
    assert snap.spinner_frame == DEFAULT_SPINNER_FRAMES[0]
    assert snap.elapsed_seconds == pytest.approx(2.0)
    assert snap.token_count is None
    assert snap.cost_usd is None
    assert snap.finished is False


def test_indicator_spinner_frame_advances_per_tick() -> None:
    clock = _FakeClock()
    indicator = EffortIndicator(threshold_seconds=0.0, clock=clock)
    indicator.start()
    frames = []
    for _ in range(12):
        clock.now += 0.1
        snap = indicator.tick()
        assert snap is not None
        frames.append(snap.spinner_frame)
    # Wraps back to the first frame after len(DEFAULT_SPINNER_FRAMES) ticks.
    assert frames[0] == DEFAULT_SPINNER_FRAMES[0]
    assert frames[10] == DEFAULT_SPINNER_FRAMES[0]
    assert frames[11] == DEFAULT_SPINNER_FRAMES[1]


def test_indicator_start_is_idempotent() -> None:
    clock = _FakeClock()
    indicator = EffortIndicator(clock=clock)
    indicator.start()
    first = indicator._started_at  # type: ignore[attr-defined]
    clock.now = 5.0
    indicator.start()
    assert indicator._started_at == first  # type: ignore[attr-defined]


def test_indicator_stop_returns_final_snapshot_always_visible() -> None:
    clock = _FakeClock()
    indicator = EffortIndicator(threshold_seconds=2.0, clock=clock)
    indicator.start()
    clock.now = 0.5
    snap = indicator.stop()
    assert snap.finished is True
    assert snap.spinner_frame == "✓"
    assert snap.elapsed_seconds == pytest.approx(0.5)
    assert indicator.stopped is True


def test_indicator_stop_without_start_treats_as_zero_length() -> None:
    indicator = EffortIndicator(clock=_FakeClock())
    snap = indicator.stop()
    assert snap.finished is True
    assert snap.elapsed_seconds == pytest.approx(0.0)


def test_indicator_tick_after_stop_returns_none() -> None:
    clock = _FakeClock()
    indicator = EffortIndicator(threshold_seconds=0.0, clock=clock)
    indicator.start()
    clock.now = 1.0
    indicator.stop()
    clock.now = 2.0
    assert indicator.tick() is None


def test_indicator_stop_is_idempotent() -> None:
    clock = _FakeClock()
    indicator = EffortIndicator(clock=clock)
    indicator.start()
    clock.now = 3.0
    first = indicator.stop()
    clock.now = 99.0
    second = indicator.stop()
    assert first.elapsed_seconds == pytest.approx(second.elapsed_seconds)
    assert second.elapsed_seconds == pytest.approx(3.0)


def test_indicator_set_cost_attaches_tokens_and_usd() -> None:
    clock = _FakeClock()
    indicator = EffortIndicator(threshold_seconds=0.0, clock=clock)
    indicator.start()
    indicator.set_cost(token_count=1234, cost_usd=0.012)
    clock.now = 1.0
    snap = indicator.tick()
    assert snap is not None
    assert snap.token_count == 1234
    assert snap.cost_usd == pytest.approx(0.012)


def test_indicator_set_cost_partial_update_keeps_other_field() -> None:
    indicator = EffortIndicator(threshold_seconds=0.0, clock=_FakeClock())
    indicator.start()
    indicator.set_cost(token_count=100, cost_usd=0.01)
    indicator.set_cost(token_count=200)  # cost_usd=None means unchanged
    snap = indicator.tick()
    assert snap is not None
    assert snap.token_count == 200
    assert snap.cost_usd == pytest.approx(0.01)


def test_indicator_clear_cost_drops_metadata() -> None:
    indicator = EffortIndicator(threshold_seconds=0.0, clock=_FakeClock())
    indicator.start()
    indicator.set_cost(token_count=100, cost_usd=0.01)
    indicator.clear_cost()
    snap = indicator.tick()
    assert snap is not None
    assert snap.token_count is None
    assert snap.cost_usd is None


def test_indicator_set_cost_rejects_negatives() -> None:
    indicator = EffortIndicator(clock=_FakeClock())
    with pytest.raises(ValueError):
        indicator.set_cost(token_count=-1)
    with pytest.raises(ValueError):
        indicator.set_cost(cost_usd=-0.01)


def test_indicator_constructor_rejects_bad_args() -> None:
    with pytest.raises(ValueError):
        EffortIndicator(threshold_seconds=-1)
    with pytest.raises(ValueError):
        EffortIndicator(frames=())


def test_indicator_snapshot_is_frozen() -> None:
    snap = EffortSnapshot(spinner_frame="⠋", elapsed_seconds=1.0)
    with pytest.raises(Exception):
        snap.elapsed_seconds = 2.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# format_effort / format_elapsed
# ---------------------------------------------------------------------------


def test_format_elapsed_pads_seconds() -> None:
    assert format_elapsed(0.0) == "0:00"
    assert format_elapsed(4.0) == "0:04"
    assert format_elapsed(59.999) == "0:59"
    assert format_elapsed(60.0) == "1:00"
    assert format_elapsed(65.5) == "1:05"
    assert format_elapsed(3661.0) == "61:01"


def test_format_elapsed_clamps_negatives_to_zero() -> None:
    assert format_elapsed(-5.0) == "0:00"


def test_format_effort_bare_snapshot_shows_frame_and_time() -> None:
    snap = EffortSnapshot(spinner_frame="⠋", elapsed_seconds=3.0)
    out = format_effort(snap, color=False)
    assert out == "  ⠋ · 0:03"


def test_format_effort_finished_snapshot_uses_its_frame() -> None:
    snap = EffortSnapshot(spinner_frame="✓", elapsed_seconds=11.0, finished=True)
    out = format_effort(snap, color=False)
    assert out == "  ✓ · 0:11"


def test_format_effort_includes_tokens_when_present() -> None:
    snap = EffortSnapshot(
        spinner_frame="⠙", elapsed_seconds=11.0, token_count=1234,
    )
    out = format_effort(snap, color=False)
    assert "1.2k tok" in out
    assert "0:11" in out


def test_format_effort_formats_token_scales() -> None:
    def tok(n: int) -> str:
        snap = EffortSnapshot(
            spinner_frame="⠋", elapsed_seconds=0.0, token_count=n,
        )
        return format_effort(snap, color=False)

    assert "999 tok" in tok(999)
    assert "1.0k tok" in tok(1000)
    assert "2.5k tok" in tok(2500)
    assert "1.0M tok" in tok(1_000_000)
    assert "3.2M tok" in tok(3_200_000)


def test_format_effort_includes_cost() -> None:
    snap = EffortSnapshot(
        spinner_frame="⠋", elapsed_seconds=1.0, cost_usd=0.0125,
    )
    out = format_effort(snap, color=False)
    assert "$0.013" in out  # rounded to three decimals


def test_format_effort_colored_by_default_is_dim_and_unstyles_back() -> None:
    snap = EffortSnapshot(spinner_frame="⠋", elapsed_seconds=1.0)
    styled = format_effort(snap)
    plain = format_effort(snap, color=False)
    assert click.unstyle(styled) == plain
    # Dim ANSI code is `\x1b[2m` — presence indicates styling applied.
    assert "\x1b[" in styled
