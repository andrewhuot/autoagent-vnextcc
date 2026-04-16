"""agentlab deploy emits a deployment lineage event when --attempt-id is set."""
from __future__ import annotations

import pytest

from optimizer.improvement_lineage import (
    EVENT_DEPLOYMENT,
    ImprovementLineageStore,
)


@pytest.fixture
def lineage_db(tmp_path, monkeypatch):
    db_path = tmp_path / "lineage.db"
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(db_path))
    return db_path


def test_emit_deploy_lineage_writes_event(lineage_db):
    from runner import _emit_deploy_lineage
    _emit_deploy_lineage(
        attempt_id="a1b2c3d4",
        deployment_id="dep-1",
        version=7,
        strategy="canary",
    )
    store = ImprovementLineageStore(db_path=str(lineage_db))
    events = [e for e in store.recent(100) if e.event_type == EVENT_DEPLOYMENT]
    assert len(events) == 1
    assert events[0].attempt_id == "a1b2c3d4"
    assert events[0].version == 7
    assert events[0].payload["deployment_id"] == "dep-1"
    assert events[0].payload["strategy"] == "canary"


def test_emit_deploy_lineage_skips_without_attempt_id(lineage_db):
    from runner import _emit_deploy_lineage
    _emit_deploy_lineage(
        attempt_id=None,
        deployment_id="dep-1",
        version=7,
        strategy="canary",
    )
    store = ImprovementLineageStore(db_path=str(lineage_db))
    # Lineage file will be created (store ctor creates it), but no deployment events:
    events = [e for e in store.recent(100) if e.event_type == EVENT_DEPLOYMENT]
    assert events == []


def test_emit_deploy_lineage_swallows_errors(tmp_path, monkeypatch):
    """If the lineage store raises, deploy is not blocked."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(blocker / "sub" / "l.db"))
    from runner import _emit_deploy_lineage
    # Must not raise:
    _emit_deploy_lineage(
        attempt_id="a1b2c3d4",
        deployment_id="dep-1",
        version=7,
        strategy="canary",
    )


def test_emit_deploy_lineage_skips_when_env_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", "")
    from runner import _emit_deploy_lineage
    _emit_deploy_lineage(
        attempt_id="a1b2c3d4",
        deployment_id="dep-1",
        version=7,
        strategy="canary",
    )
    # No assertion needed — passes if no exception.
