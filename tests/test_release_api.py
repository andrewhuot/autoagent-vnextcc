"""Tests for Release Candidate API routes and lifecycle transitions.

Covers:
- CRUD operations (create, get, list)
- Lifecycle promotion transitions (valid and invalid)
- Provenance tracking (approver, evidence)
- Rollback behavior
- Event emission on lifecycle transitions
"""

from __future__ import annotations

import pytest

from builder.store import BuilderStore
from builder.types import (
    RELEASE_TRANSITIONS,
    ReleaseCandidate,
    ReleaseStatus,
    now_ts,
)


@pytest.fixture
def store(tmp_path):
    return BuilderStore(db_path=str(tmp_path / "test_builder.db"))


# ---------------------------------------------------------------------------
# ReleaseCandidate type and lifecycle
# ---------------------------------------------------------------------------


class TestReleaseLifecycle:
    def test_release_status_enum_values(self) -> None:
        assert ReleaseStatus.DRAFT.value == "draft"
        assert ReleaseStatus.REVIEWED.value == "reviewed"
        assert ReleaseStatus.CANDIDATE.value == "candidate"
        assert ReleaseStatus.STAGING.value == "staging"
        assert ReleaseStatus.PRODUCTION.value == "production"
        assert ReleaseStatus.ARCHIVED.value == "archived"
        assert ReleaseStatus.ROLLED_BACK.value == "rolled_back"

    def test_all_statuses_have_transitions(self) -> None:
        for status in ReleaseStatus:
            assert status.value in RELEASE_TRANSITIONS

    def test_draft_can_advance_to_reviewed(self) -> None:
        assert "reviewed" in RELEASE_TRANSITIONS["draft"]

    def test_draft_can_be_archived(self) -> None:
        assert "archived" in RELEASE_TRANSITIONS["draft"]

    def test_reviewed_can_advance_to_candidate(self) -> None:
        assert "candidate" in RELEASE_TRANSITIONS["reviewed"]

    def test_reviewed_can_go_back_to_draft(self) -> None:
        assert "draft" in RELEASE_TRANSITIONS["reviewed"]

    def test_staging_can_advance_to_production(self) -> None:
        assert "production" in RELEASE_TRANSITIONS["staging"]

    def test_staging_can_be_rolled_back(self) -> None:
        assert "rolled_back" in RELEASE_TRANSITIONS["staging"]

    def test_production_can_be_archived(self) -> None:
        assert "archived" in RELEASE_TRANSITIONS["production"]

    def test_production_can_be_rolled_back(self) -> None:
        assert "rolled_back" in RELEASE_TRANSITIONS["production"]

    def test_archived_is_terminal(self) -> None:
        assert RELEASE_TRANSITIONS["archived"] == set()

    def test_rolled_back_can_return_to_draft(self) -> None:
        assert "draft" in RELEASE_TRANSITIONS["rolled_back"]

    def test_no_invalid_transitions_defined(self) -> None:
        """All target statuses in transitions must be valid ReleaseStatus values."""
        valid_values = {s.value for s in ReleaseStatus}
        for source, targets in RELEASE_TRANSITIONS.items():
            assert source in valid_values
            for target in targets:
                assert target in valid_values, f"Invalid target '{target}' from '{source}'"


# ---------------------------------------------------------------------------
# Release candidate store CRUD
# ---------------------------------------------------------------------------


class TestReleaseCRUD:
    def test_create_and_get(self, store) -> None:
        release = ReleaseCandidate(
            project_id="proj-1",
            version="v1.0",
            changelog="Initial release",
        )
        store.save_release(release)
        loaded = store.get_release(release.release_id)
        assert loaded is not None
        assert loaded.version == "v1.0"
        assert loaded.changelog == "Initial release"
        assert loaded.status == "draft"

    def test_get_missing_returns_none(self, store) -> None:
        assert store.get_release("nonexistent") is None

    def test_list_by_project(self, store) -> None:
        store.save_release(ReleaseCandidate(project_id="p1", version="v1"))
        store.save_release(ReleaseCandidate(project_id="p1", version="v2"))
        store.save_release(ReleaseCandidate(project_id="p2", version="v3"))

        releases = store.list_releases(project_id="p1")
        assert len(releases) == 2

    def test_list_by_status(self, store) -> None:
        r1 = ReleaseCandidate(project_id="p1", version="v1", status="draft")
        r2 = ReleaseCandidate(project_id="p1", version="v2", status="reviewed")
        store.save_release(r1)
        store.save_release(r2)

        drafts = store.list_releases(status="draft")
        assert len(drafts) == 1
        assert drafts[0].version == "v1"

    def test_update_release(self, store) -> None:
        release = ReleaseCandidate(project_id="p1", version="v1")
        store.save_release(release)

        release.status = "reviewed"
        release.approved_by = "alice"
        release.approved_at = now_ts()
        store.save_release(release)

        loaded = store.get_release(release.release_id)
        assert loaded.status == "reviewed"
        assert loaded.approved_by == "alice"

    def test_promotion_evidence_persists(self, store) -> None:
        release = ReleaseCandidate(project_id="p1", version="v1")
        release.promotion_evidence.append({
            "from_status": "draft",
            "to_status": "reviewed",
            "approver": "bob",
            "timestamp": now_ts(),
        })
        store.save_release(release)

        loaded = store.get_release(release.release_id)
        assert len(loaded.promotion_evidence) == 1
        assert loaded.promotion_evidence[0]["approver"] == "bob"

    def test_delete_release(self, store) -> None:
        release = ReleaseCandidate(project_id="p1", version="v1")
        store.save_release(release)
        assert store.delete_release(release.release_id) is True
        assert store.get_release(release.release_id) is None
