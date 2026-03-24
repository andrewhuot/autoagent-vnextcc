"""Unit tests for the replay and shadow harness."""

from __future__ import annotations

import json
import os
import tempfile
import time

from evals.replay import (
    ReplayHarness,
    ReplaySession,
    ReplayStore,
    RecordedToolIO,
    _hash_input,
)
from evals.side_effects import (
    SideEffectClass,
    ToolClassificationRegistry,
)


def _tmp_db() -> str:
    """Return a path to a fresh temp SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


# ---------------------------------------------------------------------------
# _hash_input
# ---------------------------------------------------------------------------


def test_hash_input_deterministic() -> None:
    """Same input should always produce the same hash."""
    data = {"b": 2, "a": 1}
    assert _hash_input(data) == _hash_input({"a": 1, "b": 2})


def test_hash_input_different_for_different_data() -> None:
    assert _hash_input({"x": 1}) != _hash_input({"x": 2})


# ---------------------------------------------------------------------------
# RecordedToolIO dataclass
# ---------------------------------------------------------------------------


def test_recorded_tool_io_defaults() -> None:
    rio = RecordedToolIO(
        tool_name="t",
        input_hash="abc",
        input_data="{}",
        output_data="{}",
        latency_ms=1.0,
    )
    assert rio.error is None


# ---------------------------------------------------------------------------
# ReplayStore — CRUD
# ---------------------------------------------------------------------------


def test_store_save_and_get_session() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)

    session = ReplaySession(
        session_id="s1",
        config_version="v1",
        created_at=time.time(),
        recorded_ios=[
            RecordedToolIO(
                tool_name="catalog",
                input_hash="h1",
                input_data='{"q": "shoes"}',
                output_data='{"items": []}',
                latency_ms=42.0,
                error=None,
            ),
            RecordedToolIO(
                tool_name="faq",
                input_hash="h2",
                input_data='{"topic": "returns"}',
                output_data='{"answer": "30 days"}',
                latency_ms=5.0,
                error=None,
            ),
        ],
    )
    store.save_session(session)

    loaded = store.get_session("s1")
    assert loaded is not None
    assert loaded.session_id == "s1"
    assert loaded.config_version == "v1"
    assert len(loaded.recorded_ios) == 2
    assert loaded.recorded_ios[0].tool_name == "catalog"
    assert loaded.recorded_ios[1].tool_name == "faq"


def test_store_get_session_returns_none_for_missing() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    assert store.get_session("nonexistent") is None


def test_store_save_session_is_idempotent() -> None:
    """Saving the same session twice should replace, not duplicate."""
    db = _tmp_db()
    store = ReplayStore(db_path=db)

    session = ReplaySession(
        session_id="s2",
        config_version="v1",
        created_at=time.time(),
        recorded_ios=[
            RecordedToolIO(
                tool_name="faq",
                input_hash="h1",
                input_data="{}",
                output_data="{}",
                latency_ms=1.0,
            ),
        ],
    )
    store.save_session(session)
    # Save again with different data.
    session.recorded_ios.append(
        RecordedToolIO(
            tool_name="catalog",
            input_hash="h2",
            input_data="{}",
            output_data="{}",
            latency_ms=2.0,
        )
    )
    store.save_session(session)

    loaded = store.get_session("s2")
    assert loaded is not None
    assert len(loaded.recorded_ios) == 2


def test_store_list_sessions() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)

    for i in range(5):
        store.save_session(
            ReplaySession(
                session_id=f"s{i}",
                config_version="v1",
                created_at=float(i),
            )
        )

    sessions = store.list_sessions(limit=3)
    assert len(sessions) == 3
    # Most recent first.
    assert sessions[0].session_id == "s4"


# ---------------------------------------------------------------------------
# ReplayHarness — record_baseline
# ---------------------------------------------------------------------------


def _make_registry() -> ToolClassificationRegistry:
    reg = ToolClassificationRegistry()
    reg.register("catalog", SideEffectClass.read_only_external, "catalog lookup")
    reg.register("faq", SideEffectClass.pure, "faq lookup")
    reg.register("orders_db", SideEffectClass.write_external_reversible, "order writes")
    return reg


def test_record_baseline() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    harness = ReplayHarness(tool_registry=_make_registry(), replay_store=store)

    tool_calls = [
        {"tool_name": "catalog", "input": {"q": "shoes"}, "output": {"items": []}, "latency_ms": 10.0},
        {"tool_name": "faq", "input": {"topic": "returns"}, "output": {"answer": "30 days"}},
    ]
    harness.record_baseline("baseline1", tool_calls, config_version="v2")

    session = store.get_session("baseline1")
    assert session is not None
    assert len(session.recorded_ios) == 2
    assert session.config_version == "v2"
    assert session.recorded_ios[0].latency_ms == 10.0
    assert session.recorded_ios[1].latency_ms == 0.0  # default


# ---------------------------------------------------------------------------
# ReplayHarness — can_fully_replay / get_replay_coverage
# ---------------------------------------------------------------------------


def test_can_fully_replay_all_pure() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    harness = ReplayHarness(tool_registry=_make_registry(), replay_store=store)

    harness.record_baseline(
        "pure_session",
        [
            {"tool_name": "faq", "input": {"t": "a"}, "output": {"a": "b"}},
            {"tool_name": "catalog", "input": {"q": "x"}, "output": {"items": []}},
        ],
        config_version="v1",
    )
    assert harness.can_fully_replay("pure_session") is True


def test_can_fully_replay_with_writes() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    harness = ReplayHarness(tool_registry=_make_registry(), replay_store=store)

    harness.record_baseline(
        "mixed",
        [
            {"tool_name": "faq", "input": {}, "output": {}},
            {"tool_name": "orders_db", "input": {}, "output": {}},
        ],
        config_version="v1",
    )
    assert harness.can_fully_replay("mixed") is False


def test_can_fully_replay_missing_session() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    harness = ReplayHarness(tool_registry=_make_registry(), replay_store=store)
    assert harness.can_fully_replay("nope") is False


def test_get_replay_coverage() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    harness = ReplayHarness(tool_registry=_make_registry(), replay_store=store)

    harness.record_baseline(
        "cov",
        [
            {"tool_name": "faq", "input": {}, "output": {}},
            {"tool_name": "orders_db", "input": {}, "output": {}},
            {"tool_name": "catalog", "input": {}, "output": {}},
        ],
        config_version="v1",
    )
    coverage = harness.get_replay_coverage("cov")
    assert coverage == {"faq": True, "orders_db": False, "catalog": True}


def test_get_replay_coverage_missing_session() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    harness = ReplayHarness(tool_registry=_make_registry(), replay_store=store)
    assert harness.get_replay_coverage("nope") == {}


# ---------------------------------------------------------------------------
# ReplayHarness — create_replay_agent_fn
# ---------------------------------------------------------------------------


def test_replay_agent_fn_replays_pure_tools() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    registry = _make_registry()
    harness = ReplayHarness(tool_registry=registry, replay_store=store)

    faq_input = {"topic": "returns"}
    faq_output = {"answer": "30 days"}

    harness.record_baseline(
        "replay_test",
        [{"tool_name": "faq", "input": faq_input, "output": faq_output}],
        config_version="v1",
    )

    def fake_agent(msg: str, config: dict | None = None) -> dict:
        return {
            "response": "here you go",
            "tool_calls": [
                {"tool": "faq", "input": faq_input, "output": {"answer": "WRONG — live call"}},
            ],
        }

    wrapped = harness.create_replay_agent_fn("replay_test", fake_agent)
    result = wrapped("what is the return policy?")

    assert result["tool_calls"][0]["output"] == faq_output
    assert result["tool_calls"][0]["replayed"] is True


def test_replay_agent_fn_passes_through_write_tools() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    registry = _make_registry()
    harness = ReplayHarness(tool_registry=registry, replay_store=store)

    harness.record_baseline(
        "write_test",
        [{"tool_name": "orders_db", "input": {"action": "cancel"}, "output": {"ok": True}}],
        config_version="v1",
    )

    live_output = {"ok": False, "reason": "already shipped"}

    def fake_agent(msg: str, config: dict | None = None) -> dict:
        return {
            "response": "done",
            "tool_calls": [
                {"tool": "orders_db", "input": {"action": "cancel"}, "output": live_output},
            ],
        }

    wrapped = harness.create_replay_agent_fn("write_test", fake_agent)
    result = wrapped("cancel order")

    # Write tool should NOT be replayed.
    assert result["tool_calls"][0]["output"] == live_output
    assert "replayed" not in result["tool_calls"][0]


def test_replay_agent_fn_falls_back_on_cache_miss() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    registry = _make_registry()
    harness = ReplayHarness(tool_registry=registry, replay_store=store)

    # Record with one input, call with a different input.
    harness.record_baseline(
        "miss_test",
        [{"tool_name": "faq", "input": {"topic": "returns"}, "output": {"answer": "30 days"}}],
        config_version="v1",
    )

    live_output = {"answer": "live answer"}

    def fake_agent(msg: str, config: dict | None = None) -> dict:
        return {
            "response": "ok",
            "tool_calls": [
                {"tool": "faq", "input": {"topic": "shipping"}, "output": live_output},
            ],
        }

    wrapped = harness.create_replay_agent_fn("miss_test", fake_agent)
    result = wrapped("shipping info")

    # Cache miss: should use the live output.
    assert result["tool_calls"][0]["output"] == live_output
    assert "replayed" not in result["tool_calls"][0]


def test_replay_agent_fn_missing_session_returns_real() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    registry = _make_registry()
    harness = ReplayHarness(tool_registry=registry, replay_store=store)

    def fake_agent(msg: str, config: dict | None = None) -> dict:
        return {"response": "real", "tool_calls": []}

    wrapped = harness.create_replay_agent_fn("nonexistent", fake_agent)
    result = wrapped("hi")
    assert result["response"] == "real"


def test_replay_agent_fn_handles_no_tool_calls_key() -> None:
    db = _tmp_db()
    store = ReplayStore(db_path=db)
    registry = _make_registry()
    harness = ReplayHarness(tool_registry=registry, replay_store=store)

    harness.record_baseline("empty_test", [], config_version="v1")

    def fake_agent(msg: str, config: dict | None = None) -> dict:
        return {"response": "no tools needed"}

    wrapped = harness.create_replay_agent_fn("empty_test", fake_agent)
    result = wrapped("hi")
    assert result["response"] == "no tools needed"
