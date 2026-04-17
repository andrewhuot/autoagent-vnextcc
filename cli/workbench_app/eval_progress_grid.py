"""Case-grid progress widget for `/eval` (R4.7).

Renders N eval cases as a colored grid driven by the in-process
`/eval` progress callback that lives in :mod:`cli.workbench_app.eval_slash`.

### Palette

- ``pending``  — grey50 (Textual named color close to dim grey)
- ``running``  — yellow
- ``passed``   — green
- ``failed``   — red
- ``error``    — red (distinct status kept for tooling; visually identical to ``failed``)

### Event bridge

The eval stack today emits aggregate ``task_started`` / ``task_progress`` /
``task_completed`` events keyed by ``task_id="eval-cases"`` — there is no
per-case event. :meth:`EvalProgressGrid.on_progress_event` interprets the
aggregate ``current`` counter as "N-1 passed, 1 running, rest pending". If
future code grows true per-case events (``eval_case_started`` /
``eval_case_complete``), the bridge honors them as well without needing a
status-mode switch — they update a single cell keyed by ``case_id``.

### Widget host

The grid is a :class:`~textual.widgets.Static` — matching
:mod:`cli.workbench_app.tui.widgets.effort_indicator_widget`'s pattern of
rendering Textual markup into a single reactive widget. It is intentionally
independent of the TUI app tree: callers mount and un-mount it by invoking
:meth:`show` / :meth:`hide` (or by passing it to ``App.compose``); the state
machine and :func:`render_grid_markup` are pure enough to test without a
running Textual app.
"""

from __future__ import annotations

from typing import Iterable, Literal

from textual.widgets import Static


CaseStatus = Literal["pending", "running", "passed", "failed", "error"]
"""Valid per-case status values. ``error`` is kept distinct for tooling,
even though it renders the same color as ``failed``."""


_VALID_STATUSES: frozenset[str] = frozenset(
    {"pending", "running", "passed", "failed", "error"}
)

# Palette — single source of truth for both the pure renderer and the widget.
# Keys must cover every member of :data:`CaseStatus`.
_COLOR_BY_STATUS: dict[str, str] = {
    "pending": "grey50",
    "running": "yellow",
    "passed": "green",
    "failed": "red",
    "error": "red",
}

# Unicode full block — high-contrast, renders in every terminal we support.
_CELL_GLYPH = "█"

DEFAULT_ROW_WIDTH = 8
"""Number of cells per rendered row. 8 keeps a 64-case suite under 8 rows,
and a 12-case suite at a tidy 8+4 split used by the snapshot fixture."""


def render_grid_markup(
    cells: Iterable[str],
    *,
    row_width: int = DEFAULT_ROW_WIDTH,
) -> str:
    """Render an iterable of case statuses as a Textual-markup string.

    Pure function — no Textual runtime required, so tests can diff the output
    without an event loop. Unknown statuses fall back to the ``pending``
    color (grey) rather than raising: a garbled status from an upstream event
    must not take down the status display.
    """
    if row_width <= 0:
        raise ValueError(f"row_width must be positive, got {row_width}")

    cell_markup: list[str] = []
    for status in cells:
        color = _COLOR_BY_STATUS.get(str(status), _COLOR_BY_STATUS["pending"])
        cell_markup.append(f"[{color}]{_CELL_GLYPH}[/]")

    if not cell_markup:
        return ""

    rows: list[str] = []
    for start in range(0, len(cell_markup), row_width):
        rows.append(" ".join(cell_markup[start : start + row_width]))
    return "\n".join(rows)


class EvalProgressGrid(Static):
    """Textual widget rendering N eval cases as a colored grid.

    The widget exposes three inputs:

    - :meth:`set_total` — initialize ``n`` cells in grey/pending state.
    - :meth:`update_case` — update a single cell by stable ``case_id``.
    - :meth:`on_progress_event` — consume dict events straight from the
      :mod:`cli.workbench_app.eval_slash` progress bridge.

    State is held on plain attributes (``_cells``, ``_case_index``) rather
    than a Textual reactive — the widget re-renders eagerly via
    :meth:`_refresh` after every mutation. This keeps the state machine
    usable outside of an app (the tests instantiate the widget without
    ``App.run_test``).
    """

    DEFAULT_CSS = """
    EvalProgressGrid {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        row_width: int = DEFAULT_ROW_WIDTH,
        task_id: str = "eval-cases",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._row_width = row_width
        self._task_id = task_id
        self._cells: list[str] = []
        # Maps case_id -> cell index for stable per-case updates. Cells
        # populated without an explicit id (legacy aggregate progress) use
        # synthetic ``__slot_{i}`` keys so the same ``update_case`` path works.
        self._case_index: dict[str, int] = {}
        self._last_progress_current: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def cells(self) -> tuple[str, ...]:
        """Immutable snapshot of the current cell statuses."""
        return tuple(self._cells)

    def set_total(self, n: int) -> None:
        """Initialize ``n`` cells in the ``pending`` state.

        Calling ``set_total`` is destructive: it resets the grid to fresh
        pending state, clears the case-id index, and forces a re-render.
        Callers that want to *grow* the grid should instead issue
        :meth:`update_case` with a new id — the widget currently disallows
        that (it's a fixed-size view) but the contract is stable.
        """
        if n < 0:
            raise ValueError(f"n must be non-negative, got {n}")
        self._cells = ["pending"] * n
        self._case_index = {}
        self._last_progress_current = 0
        self._refresh()

    def update_case(self, case_id: str, status: CaseStatus) -> None:
        """Update a single cell keyed by ``case_id``.

        If this is a new id and the grid has room (i.e. some slot is still
        without an assigned id), the id takes the next unassigned slot. If
        the grid is full — every slot already bound to an id — the update is
        a no-op: the widget is a view of a fixed-size suite, not a queue, and
        surfacing extras would misrepresent total case count.
        """
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"invalid case status {status!r}; expected one of "
                f"{sorted(_VALID_STATUSES)}"
            )

        idx = self._case_index.get(case_id)
        if idx is None:
            idx = self._allocate_slot(case_id)
            if idx is None:
                # Grid full; drop silently rather than pushing off a real cell.
                return
        self._cells[idx] = status
        self._refresh()

    def on_progress_event(self, event: dict) -> None:
        """Consume one ``task_*`` event from the eval progress bridge.

        Handles four event shapes:

        - ``task_started`` with ``task_id == self._task_id`` — re-initializes
          the grid to ``total`` pending cells.
        - ``task_progress`` with ``task_id == self._task_id`` — interprets
          ``current`` as "N-1 passed, 1 running, rest pending".
        - ``task_completed`` with ``task_id == self._task_id`` — flips every
          remaining cell to ``passed``.
        - ``eval_case_started`` / ``eval_case_complete`` — per-case events.
          If this shape ever exists, :meth:`update_case` is called with the
          ``case_id`` and derived status. ``eval_case_complete`` without an
          explicit ``status`` defaults to ``passed``.

        Events for other task ids are ignored. Events missing required
        fields are ignored silently (no crash — the grid is a display
        ornament, not a validator).
        """
        if not isinstance(event, dict):
            return
        name = str(event.get("event") or "")
        if not name:
            return

        # Per-case events (future-proofing; not currently emitted by eval.py).
        if name == "eval_case_started":
            case_id = event.get("case_id")
            if case_id:
                self.update_case(str(case_id), "running")
            return
        if name == "eval_case_complete":
            case_id = event.get("case_id")
            if not case_id:
                return
            status_raw = str(event.get("status") or "passed")
            status: CaseStatus = (
                status_raw if status_raw in _VALID_STATUSES else "passed"  # type: ignore[assignment]
            )
            self.update_case(str(case_id), status)
            return

        # Aggregate progress events — scoped to the eval-cases task.
        if event.get("task_id") != self._task_id:
            return

        if name == "task_started":
            total = event.get("total")
            if isinstance(total, int) and total >= 0:
                self.set_total(total)
            return

        if name == "task_progress":
            current = event.get("current")
            total = event.get("total")
            if not isinstance(current, int):
                return
            # Grow the grid on the fly if a task_started was missed.
            if isinstance(total, int) and total > len(self._cells):
                # Extend with pending cells; preserve already-set statuses.
                self._cells.extend(["pending"] * (total - len(self._cells)))
            self._apply_aggregate_progress(current)
            return

        if name == "task_completed":
            # Flip all cells to passed. We don't know per-case outcomes from
            # aggregate events — treating completion as success matches how
            # `eval_slash._summarise` counts successful completion.
            for i in range(len(self._cells)):
                if self._cells[i] in ("pending", "running"):
                    self._cells[i] = "passed"
            self._refresh()
            return

    def render_markup(self) -> str:
        """Return the Textual markup the widget would display right now."""
        return render_grid_markup(self._cells, row_width=self._row_width)

    def show(self) -> None:
        """Convenience: un-hide the widget (for transient mounts)."""
        self.display = True

    def hide(self) -> None:
        """Convenience: hide the widget after a run completes."""
        self.display = False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _allocate_slot(self, case_id: str) -> int | None:
        """Bind ``case_id`` to the next unassigned cell, or return None."""
        assigned = set(self._case_index.values())
        for i in range(len(self._cells)):
            if i not in assigned:
                self._case_index[case_id] = i
                return i
        return None

    def _apply_aggregate_progress(self, current: int) -> None:
        """Given an aggregate ``current`` counter, paint cells accordingly.

        Cells ``0..current-1`` go to ``passed`` (unless they already carry a
        terminal status like ``failed``/``error`` from a per-case event).
        Cell ``current`` (if within bounds) goes to ``running``. Remaining
        cells stay pending. Monotonically non-decreasing: if we receive an
        out-of-order smaller ``current``, we ignore it to avoid flicker.
        """
        if current < self._last_progress_current:
            return
        self._last_progress_current = current
        for i in range(len(self._cells)):
            existing = self._cells[i]
            if i < current:
                # Preserve terminal failure statuses set by per-case events.
                if existing in ("failed", "error"):
                    continue
                self._cells[i] = "passed"
            elif i == current:
                if existing in ("failed", "error", "passed"):
                    continue
                self._cells[i] = "running"
            else:
                # Keep whatever's already there — either pending or a status
                # recorded out-of-band by update_case / per-case events.
                if existing == "running":
                    self._cells[i] = "pending"
        self._refresh()

    def _refresh(self) -> None:
        """Re-render the Static. Safe to call before the widget is mounted;
        Textual's :meth:`Static.update` is tolerant outside of an app."""
        try:
            self.update(self.render_markup())
        except Exception:
            # The widget may not be fully initialised (e.g. in unit tests
            # that inspect ``.cells`` without running the app). Swallowing
            # here matches the broader "status widgets never crash the loop"
            # convention used by status_bar and effort_indicator_widget.
            pass


__all__ = [
    "CaseStatus",
    "DEFAULT_ROW_WIDTH",
    "EvalProgressGrid",
    "render_grid_markup",
]
