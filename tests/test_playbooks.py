"""Unit tests for registry.playbooks — Playbook, PlaybookStore, starter seed."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from registry.playbooks import (
    STARTER_PLAYBOOKS,
    Playbook,
    PlaybookStore,
    seed_starter_playbooks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_playbook(name: str = "test-pb", **kw) -> Playbook:
    return Playbook(
        name=name,
        description=kw.get("description", "A test playbook"),
        tags=kw.get("tags", ["test"]),
        skills=kw.get("skills", ["skill_a"]),
        policies=kw.get("policies", []),
    )


@pytest.fixture
def store(tmp_path: Path) -> PlaybookStore:
    db = str(tmp_path / "test_playbooks.db")
    return PlaybookStore(db_path=db)


# ---------------------------------------------------------------------------
# Playbook serialization
# ---------------------------------------------------------------------------


class TestPlaybookSerialization:
    def test_playbook_to_dict(self):
        pb = _make_playbook()
        d = pb.to_dict()
        assert d["name"] == "test-pb"
        assert d["tags"] == ["test"]
        assert d["deprecated"] is False

    def test_playbook_from_dict(self):
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
        pb = Playbook.from_dict(data)
        assert pb.name == "from-dict"
        assert pb.version == 3
        assert pb.created_at == 1000.0

    def test_playbook_roundtrip(self):
        pb = _make_playbook(name="roundtrip", description="round-trip test")
        restored = Playbook.from_dict(pb.to_dict())
        assert restored.name == pb.name
        assert restored.description == pb.description
        assert restored.tags == pb.tags
        assert restored.skills == pb.skills


# ---------------------------------------------------------------------------
# PlaybookStore registration & retrieval
# ---------------------------------------------------------------------------


class TestPlaybookStore:
    def test_playbook_store_register(self, store: PlaybookStore):
        name, version = store.register(_make_playbook())
        assert name == "test-pb"
        assert version == 1

    def test_playbook_store_register_version_increment(self, store: PlaybookStore):
        store.register(_make_playbook())
        _, v2 = store.register(_make_playbook())
        assert v2 == 2

    def test_playbook_store_get_latest(self, store: PlaybookStore):
        store.register(_make_playbook(description="v1"))
        store.register(_make_playbook(description="v2"))
        pb = store.get("test-pb")
        assert pb is not None
        assert pb.version == 2

    def test_playbook_store_get_specific_version(self, store: PlaybookStore):
        store.register(_make_playbook(description="v1"))
        store.register(_make_playbook(description="v2"))
        pb = store.get("test-pb", version=1)
        assert pb is not None
        assert pb.version == 1

    def test_playbook_store_get_not_found(self, store: PlaybookStore):
        assert store.get("nonexistent") is None

    def test_playbook_store_list(self, store: PlaybookStore):
        store.register(_make_playbook(name="alpha"))
        store.register(_make_playbook(name="beta"))
        result = store.list()
        names = [p.name for p in result]
        assert "alpha" in names
        assert "beta" in names

    def test_playbook_store_list_empty(self, store: PlaybookStore):
        assert store.list() == []

    def test_playbook_store_deprecate(self, store: PlaybookStore):
        store.register(_make_playbook(name="dep"))
        ok = store.deprecate("dep", 1)
        assert ok is True
        result = store.list()
        names = [p.name for p in result]
        assert "dep" not in names

    def test_playbook_store_search(self, store: PlaybookStore):
        store.register(_make_playbook(name="fix-retrieval"))
        store.register(_make_playbook(name="fix-latency"))
        store.register(_make_playbook(name="optimize-cost"))
        results = store.search("fix")
        assert len(results) >= 2

    def test_playbook_store_search_no_results(self, store: PlaybookStore):
        store.register(_make_playbook(name="alpha"))
        results = store.search("zzzznotfound")
        assert results == []


# ---------------------------------------------------------------------------
# Starter playbooks seeding
# ---------------------------------------------------------------------------


class TestSeedStarter:
    def test_seed_starter_playbooks(self, store: PlaybookStore):
        count = seed_starter_playbooks(store)
        assert count == len(STARTER_PLAYBOOKS)
        assert count == 7

    def test_seed_starter_playbooks_idempotent(self, store: PlaybookStore):
        first = seed_starter_playbooks(store)
        second = seed_starter_playbooks(store)
        assert first == 7
        assert second == 0  # no duplicates
