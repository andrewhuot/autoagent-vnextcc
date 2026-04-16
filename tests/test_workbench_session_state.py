"""Tests for :mod:`cli.workbench_app.session_state` (R4.1).

Covers the ``WorkbenchSession`` dataclass contract — default values,
thread-safe accessors, atomic persistence, corruption tolerance, and the
``load_workbench_session`` helper.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from cli.workbench_app.session_state import (
    WorkbenchSession,
    load_workbench_session,
)


def test_session_defaults_empty() -> None:
    s = WorkbenchSession()
    assert s.current_config_path is None
    assert s.last_eval_run_id is None
    assert s.last_attempt_id is None
    assert s.cost_ticker_usd == 0.0


def test_session_update_mutates_fields() -> None:
    s = WorkbenchSession()
    s.update(last_eval_run_id="er_1", current_config_path="c.yaml")
    assert s.last_eval_run_id == "er_1"
    assert s.current_config_path == "c.yaml"


def test_session_update_rejects_private_field() -> None:
    s = WorkbenchSession()
    with pytest.raises(ValueError):
        s.update(_lock=None)


def test_session_concurrent_updates_do_not_corrupt() -> None:
    s = WorkbenchSession()

    def worker() -> None:
        for _ in range(100):
            s.increment_cost(0.01)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert s.cost_ticker_usd == pytest.approx(8.0, abs=1e-6)


def test_session_persists_to_json(tmp_path: Path) -> None:
    path = tmp_path / "ws.json"
    s = WorkbenchSession(_path=path)
    s.update(last_eval_run_id="er_abc")

    assert path.exists()
    reloaded = WorkbenchSession.load(path)
    assert reloaded.last_eval_run_id == "er_abc"


def test_session_atomic_write_does_not_leave_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ws.json"
    s = WorkbenchSession(_path=path)
    s.update(last_eval_run_id="good")
    pre_update_content = path.read_text()

    def boom(src: str, dst: str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        s.update(last_eval_run_id="bad")

    assert path.read_text() == pre_update_content


def test_session_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.json"
    s = WorkbenchSession.load(path)
    assert s.current_config_path is None
    assert s.last_eval_run_id is None
    assert s.last_attempt_id is None
    assert s.cost_ticker_usd == 0.0
    assert s._path == path


def test_session_load_corrupt_json_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.json"
    path.write_text("not json {{{")
    s = WorkbenchSession.load(path)
    assert s.last_eval_run_id is None
    assert s._path == path


def test_session_load_ignores_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "future.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "last_eval_run_id": "er_x",
                "future_field": 42,
                "another_unknown": "abc",
            }
        )
    )
    s = WorkbenchSession.load(path)
    assert s.last_eval_run_id == "er_x"


def test_load_workbench_session_none_root_returns_in_memory() -> None:
    s = load_workbench_session(None)
    assert s._path is None


def test_load_workbench_session_creates_agentlab_dir(tmp_path: Path) -> None:
    s = load_workbench_session(tmp_path)
    assert (tmp_path / ".agentlab").is_dir()
    assert s._path == tmp_path / ".agentlab" / "workbench_session.json"
