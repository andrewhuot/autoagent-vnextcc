"""Unit tests for registry.runbooks — Runbook, RunbookStore, starter seed."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from registry.runbooks import (
    STARTER_RUNBOOKS,
    Runbook,
    RunbookStore,
    seed_starter_runbooks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runbook(name: str = "test-pb", **kw) -> Runbook:
    return Runbook(
        name=name,
        description=kw.get("description", "A test runbook"),
        tags=kw.get("tags", ["test"]),
        skills=kw.get("skills", ["skill_a"]),
        policies=kw.get("policies", []),
    )


@pytest.fixture
def store(tmp_path: Path) -> RunbookStore:
    db = str(tmp_path / "test_runbooks.db")
    return RunbookStore(db_path=db)


# ---------------------------------------------------------------------------
# Runbook serialization
# ---------------------------------------------------------------------------


class TestRunbookSerialization:
    def test_runbook_to_dict(self):
        pb = _make_runbook()
        d = pb.to_dict()
        assert d["name"] == "test-pb"
        assert d["tags"] == ["test"]
        assert d["deprecated"] is False

    def test_runbook_from_dict(self):
        data = {
            "name": "from-dict",
            "description": "loaded",
            "version": 3,
            "tags": ["a"],
            "skills": [],
            "policies": [],
            "tool_contracts": [],
            "triggers": [],
            "surfaces": [],
            "metadata": {},
            "created_at": 1000.0,
            "deprecated": False,
        }
        pb = Runbook.from_dict(data)
        assert pb.name == "from-dict"
        assert pb.version == 3
        assert pb.created_at == 1000.0

    def test_runbook_roundtrip(self):
        pb = _make_runbook(name="roundtrip", description="round-trip test")
        restored = Runbook.from_dict(pb.to_dict())
        assert restored.name == pb.name
        assert restored.description == pb.description
        assert restored.tags == pb.tags
        assert restored.skills == pb.skills


# ---------------------------------------------------------------------------
# RunbookStore registration & retrieval
# ---------------------------------------------------------------------------


class TestRunbookStore:
    def test_runbook_store_register(self, store: RunbookStore):
        name, version = store.register(_make_runbook())
        assert name == "test-pb"
        assert version == 1

    def test_runbook_store_register_version_increment(self, store: RunbookStore):
        store.register(_make_runbook())
        _, v2 = store.register(_make_runbook())
        assert v2 == 2

    def test_runbook_store_get_latest(self, store: RunbookStore):
        store.register(_make_runbook(description="v1"))
        store.register(_make_runbook(description="v2"))
        pb = store.get("test-pb")
        assert pb is not None
        assert pb.version == 2

    def test_runbook_store_get_specific_version(self, store: RunbookStore):
        store.register(_make_runbook(description="v1"))
        store.register(_make_runbook(description="v2"))
        pb = store.get("test-pb", version=1)
        assert pb is not None
        assert pb.version == 1

    def test_runbook_store_get_not_found(self, store: RunbookStore):
        assert store.get("nonexistent") is None

    def test_runbook_store_list(self, store: RunbookStore):
        store.register(_make_runbook(name="alpha"))
        store.register(_make_runbook(name="beta"))
        result = store.list()
        names = [p.name for p in result]
        assert "alpha" in names
        assert "beta" in names

    def test_runbook_store_list_empty(self, store: RunbookStore):
        assert store.list() == []

    def test_runbook_store_deprecate(self, store: RunbookStore):
        store.register(_make_runbook(name="dep"))
        ok = store.deprecate("dep", 1)
        assert ok is True
        result = store.list()
        names = [p.name for p in result]
        assert "dep" not in names

    def test_runbook_store_search(self, store: RunbookStore):
        store.register(_make_runbook(name="fix-retrieval"))
        store.register(_make_runbook(name="fix-latency"))
        store.register(_make_runbook(name="optimize-cost"))
        results = store.search("fix")
        assert len(results) >= 2

    def test_runbook_store_search_no_results(self, store: RunbookStore):
        store.register(_make_runbook(name="alpha"))
        results = store.search("zzzznotfound")
        assert results == []


# ---------------------------------------------------------------------------
# Starter runbooks seeding
# ---------------------------------------------------------------------------


class TestSeedStarter:
    def test_seed_starter_runbooks(self, store: RunbookStore):
        count = seed_starter_runbooks(store)
        assert count == len(STARTER_RUNBOOKS)
        assert count == 7

    def test_seed_starter_runbooks_idempotent(self, store: RunbookStore):
        first = seed_starter_runbooks(store)
        second = seed_starter_runbooks(store)
        assert first == 7
        assert second == 0  # no duplicates
