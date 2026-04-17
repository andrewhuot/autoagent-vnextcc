"""Tests for the `/eval` case-grid progress widget (R4.7).

The widget renders N eval cases as a colored grid driven by the in-process
progress callback. These tests exercise:

1. The public API (``set_total`` + ``update_case``).
2. A rendering snapshot at 3-of-12 complete (1 passed, 1 failed, 1 running,
   remaining pending). The snapshot is a textual markup string checked against
   a golden — cheap to read and diff in review, stable across Textual versions.
3. Wiring into :mod:`cli.workbench_app.eval_slash`: when ``task_progress``
   events come through the progress bridge, the grid's ``on_progress_event``
   reflects the advance by flipping the oldest pending cell to ``passed`` and
   the current leading edge to ``running``.
"""

from __future__ import annotations

import pytest

from cli.workbench_app.eval_progress_grid import (
    EvalProgressGrid,
    render_grid_markup,
)


# Golden snapshot for set_total(12), 1 passed, 1 failed, 1 running, 9 pending.
# The widget renders one cell per case as a filled block, colored by status,
# laid out in rows. Format:
#   <row>\n<row>\n...
# A row is a space-separated list of Textual-markup cells. The default row
# width is 8 cells; 12 cases therefore spans 2 rows (8 + 4).
GOLDEN_3_OF_12 = (
    "[green]█[/] [red]█[/] [yellow]█[/] [grey50]█[/] [grey50]█[/] [grey50]█[/] [grey50]█[/] [grey50]█[/]\n"
    "[grey50]█[/] [grey50]█[/] [grey50]█[/] [grey50]█[/]"
)


class TestRenderGridMarkup:
    """Pure-function renderer — no Textual runtime needed."""

    def test_empty_grid(self) -> None:
        assert render_grid_markup([], row_width=8) == ""

    def test_all_pending(self) -> None:
        cells = ["pending"] * 4
        rendered = render_grid_markup(cells, row_width=8)
        # 4 pending cells on one row.
        assert rendered == "[grey50]█[/] [grey50]█[/] [grey50]█[/] [grey50]█[/]"

    def test_snapshot_3_of_12(self) -> None:
        """Golden snapshot — 12 cells: passed, failed, running, 9 pending."""
        cells = (
            ["passed", "failed", "running"]
            + ["pending"] * 9
        )
        assert render_grid_markup(cells, row_width=8) == GOLDEN_3_OF_12

    def test_error_renders_same_color_as_failed(self) -> None:
        """``error`` is a distinct status (tooling cares) but paints red."""
        cells = ["failed", "error"]
        rendered = render_grid_markup(cells, row_width=8)
        assert rendered == "[red]█[/] [red]█[/]"

    def test_unknown_status_falls_back_to_pending(self) -> None:
        """Defensive: an unknown status shouldn't crash the render."""
        cells = ["passed", "bogus"]  # type: ignore[list-item]
        rendered = render_grid_markup(cells, row_width=8)
        assert rendered == "[green]█[/] [grey50]█[/]"


class TestEvalProgressGridStateMachine:
    """Widget state without running the Textual app — we only exercise the
    state-management API and then ask the widget for its current markup."""

    def test_set_total_initializes_all_pending(self) -> None:
        grid = EvalProgressGrid()
        grid.set_total(5)
        assert grid.cells == ("pending",) * 5

    def test_update_case_by_id(self) -> None:
        grid = EvalProgressGrid()
        grid.set_total(3)
        grid.update_case("case-0", "running")
        grid.update_case("case-1", "passed")
        grid.update_case("case-2", "failed")
        assert grid.cells == ("running", "passed", "failed")

    def test_update_case_same_id_preserves_slot(self) -> None:
        """A case that transitions pending → running → passed keeps its slot."""
        grid = EvalProgressGrid()
        grid.set_total(3)
        grid.update_case("case-a", "running")
        grid.update_case("case-b", "running")
        grid.update_case("case-a", "passed")
        # Two distinct ids, two distinct slots; the 3rd remains pending.
        assert grid.cells == ("passed", "running", "pending")

    def test_update_case_rejected_when_grid_full(self) -> None:
        """Once ``set_total`` cells are allocated, new ids are dropped (the
        widget is a view, not a queue — surfacing extras would lie)."""
        grid = EvalProgressGrid()
        grid.set_total(2)
        grid.update_case("a", "running")
        grid.update_case("b", "running")
        grid.update_case("c", "running")  # should be ignored, not crash
        assert grid.cells == ("running", "running")

    def test_update_case_invalid_status_raises(self) -> None:
        grid = EvalProgressGrid()
        grid.set_total(1)
        with pytest.raises(ValueError):
            grid.update_case("x", "bogus")  # type: ignore[arg-type]

    def test_render_markup_at_3_of_12(self) -> None:
        grid = EvalProgressGrid()
        grid.set_total(12)
        grid.update_case("a", "passed")
        grid.update_case("b", "failed")
        grid.update_case("c", "running")
        assert grid.render_markup() == GOLDEN_3_OF_12


class TestProgressEventBridge:
    """The grid reacts to the same ``task_progress`` events `eval_slash.py`
    already threads through its summariser."""

    def test_task_started_sets_total(self) -> None:
        grid = EvalProgressGrid()
        grid.on_progress_event({
            "event": "task_started",
            "task_id": "eval-cases",
            "total": 4,
        })
        assert grid.cells == ("pending",) * 4

    def test_task_progress_advances_leading_edge(self) -> None:
        """``task_progress`` with ``current=N`` means N-1 complete, 1 running."""
        grid = EvalProgressGrid()
        grid.on_progress_event({
            "event": "task_started", "task_id": "eval-cases", "total": 4,
        })
        grid.on_progress_event({
            "event": "task_progress", "task_id": "eval-cases",
            "current": 1, "total": 4,
        })
        # current=1 means "1 case complete": cell 0 passed, cell 1 running.
        assert grid.cells == ("passed", "running", "pending", "pending")

        grid.on_progress_event({
            "event": "task_progress", "task_id": "eval-cases",
            "current": 3, "total": 4,
        })
        # current=3 means "3 complete": cells 0-2 passed, cell 3 running.
        assert grid.cells == ("passed", "passed", "passed", "running")

    def test_task_completed_flips_all_remaining_to_passed(self) -> None:
        grid = EvalProgressGrid()
        grid.on_progress_event({
            "event": "task_started", "task_id": "eval-cases", "total": 3,
        })
        grid.on_progress_event({
            "event": "task_completed", "task_id": "eval-cases",
            "current": 3, "total": 3,
        })
        assert grid.cells == ("passed", "passed", "passed")

    def test_ignores_unrelated_task_ids(self) -> None:
        grid = EvalProgressGrid()
        grid.set_total(2)
        grid.on_progress_event({
            "event": "task_progress", "task_id": "build-something",
            "current": 1, "total": 2,
        })
        assert grid.cells == ("pending", "pending")

    def test_explicit_case_event_honored(self) -> None:
        """If future code grows true per-case events, the bridge accepts them."""
        grid = EvalProgressGrid()
        grid.set_total(2)
        grid.on_progress_event({
            "event": "eval_case_started", "case_id": "a",
        })
        grid.on_progress_event({
            "event": "eval_case_complete", "case_id": "a", "status": "failed",
        })
        assert grid.cells == ("failed", "pending")


class TestEvalSlashWiring:
    """Confirm `eval_slash.make_eval_handler` accepts a grid observer and
    forwards every stream event to it."""

    def test_handler_forwards_events_to_grid(self) -> None:
        from cli.workbench_app.eval_slash import make_eval_handler
        from cli.workbench_app.slash import SlashContext

        received: list[dict] = []

        class _FakeGrid:
            def on_progress_event(self, event: dict) -> None:
                received.append(event)

        grid = _FakeGrid()

        def _runner(args):
            yield {"event": "task_started", "task_id": "eval-cases", "total": 2}
            yield {
                "event": "task_progress", "task_id": "eval-cases",
                "current": 1, "total": 2,
            }
            yield {
                "event": "task_completed", "task_id": "eval-cases",
                "current": 2, "total": 2,
            }
            yield {"event": "eval_complete", "run_id": "v001", "config_path": "x"}

        handler = make_eval_handler(runner=_runner, grid_observer=grid)

        class _Spin:
            def update(self, *a, **kw) -> None: ...
            def echo(self, *a, **kw) -> None: ...
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class _Ctx:
            meta: dict = {}
            cancellation = None
            def echo(self, *a, **kw) -> None: ...
            def spinner(self, *a, **kw): return _Spin()

        handler(_Ctx())

        # Every stream event should have hit the grid observer.
        assert [e["event"] for e in received] == [
            "task_started", "task_progress", "task_completed", "eval_complete",
        ]
