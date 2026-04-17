"""Tests for optimizer.canary_scoring.{CanaryRouter, LocalCanaryRouter}."""

from __future__ import annotations

import dataclasses
import inspect
import json
import sqlite3

import pytest

from optimizer.canary_scoring import (
    CanaryPair,
    CanaryRouter,
    LocalCanaryRouter,
)


def test_local_router_creates_schema(tmp_path) -> None:
    db_path = str(tmp_path / "cp.db")
    LocalCanaryRouter(db_path=db_path)

    expected = {
        "pair_id": "TEXT",
        "input_id": "TEXT",
        "baseline_label": "TEXT",
        "candidate_label": "TEXT",
        "baseline_output": "TEXT",
        "candidate_output": "TEXT",
        "metadata_json": "TEXT",
        "recorded_at": "REAL",
    }

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("PRAGMA table_info(canary_pairs)").fetchall()

    assert rows, "canary_pairs table was not created"
    actual = {row[1]: row[2] for row in rows}
    assert actual == expected


def test_local_router_creates_parent_dir(tmp_path) -> None:
    nested = tmp_path / "deeply" / "nested" / "dir" / "cp.db"
    assert not nested.parent.exists()

    LocalCanaryRouter(db_path=str(nested))

    assert nested.parent.is_dir()
    assert nested.exists()


def test_local_router_record_returns_pair_id(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))

    pair_id = router.record_pair(
        input_id="input-1",
        baseline_label="v003",
        candidate_label="v004-canary",
        baseline_output="hello",
        candidate_output="hi there",
    )

    assert isinstance(pair_id, str)
    assert len(pair_id) == 32
    # uuid4().hex is all hex digits.
    int(pair_id, 16)


def test_local_router_record_persists_all_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "optimizer.canary_scoring.time.time", lambda: 1234567.5
    )
    db_path = str(tmp_path / "cp.db")
    router = LocalCanaryRouter(db_path=db_path)

    metadata = {"foo": "bar", "n": 7}
    pair_id = router.record_pair(
        input_id="input-42",
        baseline_label="v003",
        candidate_label="v004-canary",
        baseline_output="baseline-out",
        candidate_output="candidate-out",
        metadata=metadata,
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT pair_id, input_id, baseline_label, candidate_label, "
            "baseline_output, candidate_output, metadata_json, recorded_at "
            "FROM canary_pairs WHERE pair_id = ?",
            (pair_id,),
        ).fetchone()

    assert row is not None
    assert row[0] == pair_id
    assert row[1] == "input-42"
    assert row[2] == "v003"
    assert row[3] == "v004-canary"
    assert row[4] == "baseline-out"
    assert row[5] == "candidate-out"
    assert json.loads(row[6]) == metadata
    assert row[7] == 1234567.5


def test_local_router_list_recent_orders_descending(tmp_path, monkeypatch) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))

    times = iter([100.0, 200.0, 300.0])
    monkeypatch.setattr(
        "optimizer.canary_scoring.time.time", lambda: next(times)
    )

    ids = []
    for i in range(3):
        ids.append(
            router.record_pair(
                input_id=f"input-{i}",
                baseline_label="v003",
                candidate_label="v004",
                baseline_output=f"b{i}",
                candidate_output=f"c{i}",
            )
        )

    # Freeze "now" past everything for the read.
    monkeypatch.setattr("optimizer.canary_scoring.time.time", lambda: 400.0)
    pairs = router.list_recent(baseline_label="v003", candidate_label="v004")

    assert [p.recorded_at for p in pairs] == [300.0, 200.0, 100.0]
    assert [p.pair_id for p in pairs] == [ids[2], ids[1], ids[0]]


def test_local_router_list_recent_filters_by_labels(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))

    # Combo A
    router.record_pair(
        input_id="i1",
        baseline_label="v003",
        candidate_label="v004",
        baseline_output="a",
        candidate_output="b",
    )
    router.record_pair(
        input_id="i2",
        baseline_label="v003",
        candidate_label="v004",
        baseline_output="a",
        candidate_output="b",
    )
    # Combo B
    router.record_pair(
        input_id="i3",
        baseline_label="v005",
        candidate_label="v006",
        baseline_output="a",
        candidate_output="b",
    )

    a = router.list_recent(baseline_label="v003", candidate_label="v004")
    b = router.list_recent(baseline_label="v005", candidate_label="v006")

    assert len(a) == 2
    assert all(
        p.baseline_label == "v003" and p.candidate_label == "v004" for p in a
    )
    assert len(b) == 1
    assert b[0].baseline_label == "v005"
    assert b[0].candidate_label == "v006"


def test_local_router_window_s_filter(tmp_path, monkeypatch) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))

    # Three pairs at t=1000, t=1500, t=1590.
    times = iter([1000.0, 1500.0, 1590.0])
    monkeypatch.setattr(
        "optimizer.canary_scoring.time.time", lambda: next(times)
    )
    for i in range(3):
        router.record_pair(
            input_id=f"i{i}",
            baseline_label="v003",
            candidate_label="v004",
            baseline_output="b",
            candidate_output="c",
        )

    # "Now" is t=1600; window_s=60 keeps anything with recorded_at > 1540.
    monkeypatch.setattr("optimizer.canary_scoring.time.time", lambda: 1600.0)

    pairs = router.list_recent(
        baseline_label="v003", candidate_label="v004", window_s=60
    )
    assert [p.recorded_at for p in pairs] == [1590.0]

    # Wider window catches the t=1500 pair too.
    pairs2 = router.list_recent(
        baseline_label="v003", candidate_label="v004", window_s=200
    )
    assert sorted(p.recorded_at for p in pairs2) == [1500.0, 1590.0]


def test_local_router_count_matches_list_recent_size(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))

    for i in range(7):
        router.record_pair(
            input_id=f"i{i}",
            baseline_label="v003",
            candidate_label="v004",
            baseline_output="b",
            candidate_output="c",
        )
    # Different combo should not affect the count.
    router.record_pair(
        input_id="ix",
        baseline_label="other",
        candidate_label="combo",
        baseline_output="b",
        candidate_output="c",
    )

    n = router.count(baseline_label="v003", candidate_label="v004")
    pairs = router.list_recent(baseline_label="v003", candidate_label="v004")

    assert n == len(pairs) == 7


def test_local_router_metadata_default_empty_dict(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))

    router.record_pair(
        input_id="i1",
        baseline_label="v003",
        candidate_label="v004",
        baseline_output="b",
        candidate_output="c",
    )

    pairs = router.list_recent(baseline_label="v003", candidate_label="v004")
    assert len(pairs) == 1
    assert pairs[0].metadata == {}
    assert pairs[0].metadata is not None


def test_local_router_record_pair_returns_unique_ids(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))

    ids: set[str] = set()
    for i in range(100):
        pid = router.record_pair(
            input_id=f"i{i}",
            baseline_label="v003",
            candidate_label="v004",
            baseline_output="b",
            candidate_output="c",
        )
        ids.add(pid)

    assert len(ids) == 100


def test_canary_pair_dataclass_is_frozen() -> None:
    pair = CanaryPair(
        pair_id="abc",
        input_id="i1",
        baseline_label="v003",
        candidate_label="v004",
        baseline_output="b",
        candidate_output="c",
        metadata={},
        recorded_at=1.0,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        pair.input_id = "x"  # type: ignore[misc]


def test_canary_router_protocol_satisfied_by_local(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))

    # Runtime Protocol check (CanaryRouter is @runtime_checkable).
    assert isinstance(router, CanaryRouter)

    # Lock the contract on parameter names too: signature parity.
    proto_sig = inspect.signature(CanaryRouter.record_pair)
    impl_sig = inspect.signature(LocalCanaryRouter.record_pair)
    assert list(proto_sig.parameters) == list(impl_sig.parameters)
