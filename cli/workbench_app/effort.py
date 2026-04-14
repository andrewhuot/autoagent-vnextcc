"""Effort indicator for long-running tool calls.

Port of Claude Code's ``EffortIndicator``: a spinner + elapsed time + optional
token / cost annotation that appears in the footer of a running tool-call
block once it's been running longer than a threshold (default 2s). Quick
tool calls never surface the indicator, so the transcript stays quiet.

This module is intentionally a pure state machine — terminal rendering is
owned by the enclosing view (the transcript pane in T07 and, once prompt_
toolkit lands in T19, the live footer). Tests drive the indicator through
its public API by injecting a :data:`Clock` so no real time elapses.

Typical usage::

    indicator = EffortIndicator()
    indicator.start()
    ... work ...
    snap = indicator.tick()        # None until > threshold
    if snap is not None:
        echo(format_effort(snap))
    ... more work ...
    final = indicator.stop()       # always visible
    echo(format_effort(final))
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Sequence

from cli.workbench_app import theme


__all__ = [
    "DEFAULT_SPINNER_FRAMES",
    "DEFAULT_THRESHOLD_SECONDS",
    "EffortIndicator",
    "EffortSnapshot",
    "format_effort",
    "format_elapsed",
]


Clock = Callable[[], float]
"""Monotonic-style clock returning seconds. Injected for tests."""


DEFAULT_SPINNER_FRAMES: tuple[str, ...] = (
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏",
)
"""Braille-dot spinner frames (same family Claude Code uses)."""


DEFAULT_THRESHOLD_SECONDS = 2.0
"""Default visibility threshold. Tool calls that finish faster stay silent."""


_FINISHED_GLYPH = "✓"


@dataclass(frozen=True)
class EffortSnapshot:
    """Immutable snapshot of the indicator at one point in time.

    ``finished`` distinguishes a running tick from a post-:meth:`stop` snap.
    Renderers use it to swap the spinner for the completion glyph.
    """

    spinner_frame: str
    elapsed_seconds: float
    token_count: int | None = None
    cost_usd: float | None = None
    finished: bool = False


class EffortIndicator:
    """Track elapsed time + spinner + cost metadata for one tool call.

    The indicator is silent until ``threshold_seconds`` have passed; before
    that :meth:`tick` returns ``None`` so callers can poll freely without
    flickering the transcript. After the threshold, each ``tick()`` advances
    the spinner frame and returns a fresh snapshot. :meth:`stop` always
    returns a snapshot regardless of threshold so callers can emit a final
    footer line.
    """

    def __init__(
        self,
        *,
        threshold_seconds: float = DEFAULT_THRESHOLD_SECONDS,
        clock: Clock | None = None,
        frames: Sequence[str] = DEFAULT_SPINNER_FRAMES,
    ) -> None:
        if threshold_seconds < 0:
            raise ValueError("threshold_seconds must be non-negative")
        if not frames:
            raise ValueError("frames must be non-empty")
        self._threshold = threshold_seconds
        self._clock: Clock = clock if clock is not None else time.monotonic
        self._frames: tuple[str, ...] = tuple(frames)
        self._frame_idx = 0
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._token_count: int | None = None
        self._cost_usd: float | None = None

    # ------------------------------------------------------------------ state

    @property
    def started(self) -> bool:
        return self._started_at is not None

    @property
    def stopped(self) -> bool:
        return self._stopped_at is not None

    def start(self) -> None:
        """Begin tracking. A second call is a no-op (keeps the original start).

        Keeping ``start`` idempotent lets the enclosing block call it on every
        inbound event without bookkeeping — the first event wins.
        """
        if self._started_at is None:
            self._started_at = self._clock()

    def set_cost(
        self, *, token_count: int | None = None, cost_usd: float | None = None
    ) -> None:
        """Attach cost metadata. Only fields explicitly passed are updated.

        Passing ``None`` for a field is the same as not passing it — use the
        dedicated :meth:`clear_cost` helper if you need to erase a value.
        """
        if token_count is not None:
            if token_count < 0:
                raise ValueError("token_count must be non-negative")
            self._token_count = token_count
        if cost_usd is not None:
            if cost_usd < 0:
                raise ValueError("cost_usd must be non-negative")
            self._cost_usd = cost_usd

    def clear_cost(self) -> None:
        """Drop any attached token / cost metadata."""
        self._token_count = None
        self._cost_usd = None

    # ------------------------------------------------------------------ read

    def elapsed(self) -> float:
        """Elapsed seconds since :meth:`start`. ``0.0`` before start."""
        if self._started_at is None:
            return 0.0
        end = self._stopped_at if self._stopped_at is not None else self._clock()
        return max(0.0, end - self._started_at)

    def tick(self) -> EffortSnapshot | None:
        """Return the current snapshot, or ``None`` when still under threshold.

        After :meth:`stop`, ``tick()`` returns ``None`` (the caller should
        switch to the :meth:`stop` return value for the final render). The
        spinner frame advances on each visible tick so a driving render loop
        can animate by polling on a fixed interval.
        """
        if self._started_at is None:
            return None
        if self._stopped_at is not None:
            return None
        elapsed = self.elapsed()
        if elapsed < self._threshold:
            return None
        frame = self._frames[self._frame_idx]
        self._frame_idx = (self._frame_idx + 1) % len(self._frames)
        return EffortSnapshot(
            spinner_frame=frame,
            elapsed_seconds=elapsed,
            token_count=self._token_count,
            cost_usd=self._cost_usd,
            finished=False,
        )

    def stop(self) -> EffortSnapshot:
        """Freeze the clock and return the final snapshot.

        Always visible — callers use this for the tool-call footer regardless
        of whether the indicator ever crossed the threshold. Re-calling
        ``stop`` is idempotent (the first stop timestamp wins).
        """
        if self._started_at is None:
            # Caller stopped without starting. Treat as zero-length so
            # rendering doesn't crash; elapsed is 0s.
            now = self._clock()
            self._started_at = now
            self._stopped_at = now
        elif self._stopped_at is None:
            self._stopped_at = self._clock()
        return EffortSnapshot(
            spinner_frame=_FINISHED_GLYPH,
            elapsed_seconds=self.elapsed(),
            token_count=self._token_count,
            cost_usd=self._cost_usd,
            finished=True,
        )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_elapsed(seconds: float) -> str:
    """Format a duration as ``M:SS`` (zero-padded seconds).

    Kept as a standalone helper so the tool-call footer (T08) and other
    status surfaces can share the same time format without dragging in the
    full indicator state machine.
    """
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    secs = int(seconds - minutes * 60)
    return f"{minutes}:{secs:02d}"


def _format_tokens(count: int) -> str:
    if count < 1000:
        return f"{count} tok"
    if count < 1_000_000:
        return f"{count / 1000:.1f}k tok"
    return f"{count / 1_000_000:.1f}M tok"


def _format_cost(cost_usd: float) -> str:
    # Three-decimal USD matches Claude Code's "$0.012" style footers.
    return f"${cost_usd:.3f}"


def format_effort(snapshot: EffortSnapshot, *, color: bool = True) -> str:
    """Render a snapshot as a dim single-line terminal string.

    The returned string has a two-space indent so it nests under a tool-call
    block header without adding its own framing glyph. Pass ``color=False``
    for plain text (used by tests asserting the raw content).
    """
    parts: list[str] = [snapshot.spinner_frame, format_elapsed(snapshot.elapsed_seconds)]
    if snapshot.token_count is not None:
        parts.append(_format_tokens(snapshot.token_count))
    if snapshot.cost_usd is not None:
        parts.append(_format_cost(snapshot.cost_usd))
    line = "  " + " · ".join(parts)
    return theme.meta(line, color=color)
