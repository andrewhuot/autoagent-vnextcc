"""Animated spinner widget wrapping the EffortIndicator state machine.

Drives the braille-dot spinner via Textual's ``set_interval`` timer.
When stalled, the spinner text shifts toward red to signal inactivity,
porting the concept from Claude Code's ``SpinnerGlyph`` color
interpolation.
"""

from __future__ import annotations

from typing import Callable

from textual.widgets import Static

from cli.workbench_app.effort import (
    DEFAULT_SPINNER_FRAMES,
    EffortSnapshot,
    format_effort,
)
from cli.workbench_app.store import AppState, CoordinatorStatus, Store


# Interval between spinner frame advances (seconds).
_TICK_INTERVAL = 0.1


class EffortIndicatorWidget(Static):
    """Animated spinner that appears during active coordinator work.

    Hidden when coordinator is idle. When visible, cycles through braille
    spinner frames and shows elapsed time + optional verb. Stalled state
    shifts color to red.
    """

    DEFAULT_CSS = """
    EffortIndicatorWidget {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, store: Store[AppState], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._store = store
        self._unsub: Callable[[], None] = lambda: None
        self._timer = None
        self._frame_idx = 0
        self._frames = DEFAULT_SPINNER_FRAMES

    def on_mount(self) -> None:
        self._sync_visibility()
        self._unsub = self._store.subscribe(self._on_store_changed)

    def on_unmount(self) -> None:
        self._unsub()
        if self._timer is not None:
            self._timer.stop()

    def _on_store_changed(self) -> None:
        try:
            self.app.call_from_thread(self._sync_visibility)
        except RuntimeError:
            try:
                self.call_later(self._sync_visibility)
            except Exception:
                pass
        except AttributeError:
            pass

    def _sync_visibility(self) -> None:
        """Show/hide the spinner based on coordinator status."""
        state = self._store.get_state()
        is_active = state.coordinator_status == CoordinatorStatus.RUNNING

        if is_active and self._timer is None:
            self.display = True
            self._timer = self.set_interval(_TICK_INTERVAL, self._tick)
        elif not is_active and self._timer is not None:
            self._timer.stop()
            self._timer = None
            self.display = False
            self.update("")

    def _tick(self) -> None:
        """Advance spinner frame and re-render."""
        state = self._store.get_state()
        effort = state.effort

        self._frame_idx = (self._frame_idx + 1) % len(self._frames)
        frame = self._frames[self._frame_idx]

        if effort is not None:
            # Use the effort snapshot for rich rendering.
            text = format_effort(effort)
            if effort.stalled:
                self.update(f"[red]{frame}[/] [red]{text}[/]")
            else:
                self.update(f"[cyan]{frame}[/] {text}")
        else:
            # Simple spinner with coordinator status.
            verb = ""
            workers = state.coordinator_workers
            for w in workers:
                if w.phase.value in ("acting", "gathering_context", "verifying"):
                    verb = f" {w.role.replace('_', ' ').lower()} {w.phase.value.replace('_', ' ')}"
                    break

            self.update(f"[cyan]{frame}[/] working{verb}...")
