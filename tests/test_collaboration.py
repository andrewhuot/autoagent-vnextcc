"""Tests for collaborative review system."""

from __future__ import annotations

import os
import tempfile

from collaboration.review import ReviewManager
from collaboration.team import TeamManager, TeamMember


def _tmp_db() -> str:
    """Return a path to a fresh temp SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _tmp_json() -> str:
    """Return a path to a fresh temp JSON file."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    return path


# ---------------------------------------------------------------------------
# TeamManager tests
# ---------------------------------------------------------------------------


def test_team_manager_add_and_get_member() -> None:
    """TeamManager should store and retrieve members."""
    team_path = _tmp_json()
    manager = TeamManager(config_path=team_path)

    member = TeamMember(
        user_id="user1",
        name="Alice",
        role="reviewer",
        email="alice@example.com",
    )
    manager.add_member(member)

    retrieved = manager.get_member("user1")
    assert retrieved is not None
    assert retrieved.user_id == "user1"
    assert retrieved.name == "Alice"
    assert retrieved.role == "reviewer"


def test_team_manager_list_members() -> None:
    """TeamManager should list all members."""
    team_path = _tmp_json()
    manager = TeamManager(config_path=team_path)

    manager.add_member(TeamMember(user_id="u1", name="Alice", role="admin"))
    manager.add_member(TeamMember(user_id="u2", name="Bob", role="reviewer"))

    members = manager.list_members()
    assert len(members) == 2


def test_team_manager_remove_member() -> None:
    """TeamManager should remove members."""
    team_path = _tmp_json()
    manager = TeamManager(config_path=team_path)

    manager.add_member(TeamMember(user_id="u1", name="Alice", role="admin"))
    manager.add_member(TeamMember(user_id="u2", name="Bob", role="reviewer"))

    success = manager.remove_member("u2")
    assert success is True

    members = manager.list_members()
    assert len(members) == 1
    assert members[0].user_id == "u1"


def test_team_manager_has_role() -> None:
    """TeamManager should check role hierarchy."""
    team_path = _tmp_json()
    manager = TeamManager(config_path=team_path)

    manager.add_member(TeamMember(user_id="admin", name="Admin", role="admin"))
    manager.add_member(TeamMember(user_id="reviewer", name="Reviewer", role="reviewer"))
    manager.add_member(TeamMember(user_id="viewer", name="Viewer", role="viewer"))

    # Admin has all roles
    assert manager.has_role("admin", "admin") is True
    assert manager.has_role("admin", "reviewer") is True
    assert manager.has_role("admin", "viewer") is True

    # Reviewer has reviewer and viewer roles
    assert manager.has_role("reviewer", "admin") is False
    assert manager.has_role("reviewer", "reviewer") is True
    assert manager.has_role("reviewer", "viewer") is True

    # Viewer only has viewer role
    assert manager.has_role("viewer", "admin") is False
    assert manager.has_role("viewer", "reviewer") is False
    assert manager.has_role("viewer", "viewer") is True


# ---------------------------------------------------------------------------
# ReviewManager tests
# ---------------------------------------------------------------------------


def test_review_manager_request_review() -> None:
    """ReviewManager should create review requests."""
    db_path = _tmp_db()
    manager = ReviewManager(db_path=db_path)

    request_id = manager.request_review(
        change_id="change123",
        reviewers=["alice", "bob"],
        policy="any_one",
    )

    assert request_id.startswith("review_")


def test_review_manager_submit_review() -> None:
    """ReviewManager should accept review submissions."""
    db_path = _tmp_db()
    manager = ReviewManager(db_path=db_path)

    request_id = manager.request_review(
        change_id="change123",
        reviewers=["alice", "bob"],
        policy="any_one",
    )

    success = manager.submit_review(
        request_id=request_id,
        reviewer="alice",
        decision="approve",
        comment="Looks good!",
    )

    assert success is True


def test_review_manager_check_approval_any_one() -> None:
    """ReviewManager should approve with any_one policy."""
    db_path = _tmp_db()
    manager = ReviewManager(db_path=db_path)

    request_id = manager.request_review(
        change_id="change123",
        reviewers=["alice", "bob"],
        policy="any_one",
    )

    # Not approved yet
    assert manager.check_approval(request_id) is False

    # One approval should be enough
    manager.submit_review(
        request_id=request_id,
        reviewer="alice",
        decision="approve",
        comment="LGTM",
    )

    assert manager.check_approval(request_id) is True


def test_review_manager_check_approval_all_reviewers() -> None:
    """ReviewManager should require all reviewers with all_reviewers policy."""
    db_path = _tmp_db()
    manager = ReviewManager(db_path=db_path)

    request_id = manager.request_review(
        change_id="change123",
        reviewers=["alice", "bob"],
        policy="all_reviewers",
    )

    # One approval not enough
    manager.submit_review(
        request_id=request_id,
        reviewer="alice",
        decision="approve",
        comment="LGTM",
    )
    assert manager.check_approval(request_id) is False

    # Both approvals required
    manager.submit_review(
        request_id=request_id,
        reviewer="bob",
        decision="approve",
        comment="Approved",
    )
    assert manager.check_approval(request_id) is True


def test_review_manager_check_approval_majority() -> None:
    """ReviewManager should require majority with majority policy."""
    db_path = _tmp_db()
    manager = ReviewManager(db_path=db_path)

    request_id = manager.request_review(
        change_id="change123",
        reviewers=["alice", "bob", "charlie"],
        policy="majority",
    )

    # One approval not enough
    manager.submit_review(
        request_id=request_id,
        reviewer="alice",
        decision="approve",
        comment="LGTM",
    )
    assert manager.check_approval(request_id) is False

    # Two approvals (majority of 3) should be enough
    manager.submit_review(
        request_id=request_id,
        reviewer="bob",
        decision="approve",
        comment="Approved",
    )
    assert manager.check_approval(request_id) is True


def test_review_manager_rejection_blocks_approval() -> None:
    """ReviewManager should block approval if any rejection exists."""
    db_path = _tmp_db()
    manager = ReviewManager(db_path=db_path)

    request_id = manager.request_review(
        change_id="change123",
        reviewers=["alice", "bob"],
        policy="any_one",
    )

    # Rejection first
    manager.submit_review(
        request_id=request_id,
        reviewer="alice",
        decision="reject",
        comment="Needs work",
    )

    # Even with an approval, should not be approved
    manager.submit_review(
        request_id=request_id,
        reviewer="bob",
        decision="approve",
        comment="Looks good",
    )

    assert manager.check_approval(request_id) is False


def test_review_manager_list_pending() -> None:
    """ReviewManager should list pending reviews."""
    db_path = _tmp_db()
    manager = ReviewManager(db_path=db_path)

    # Create pending reviews
    manager.request_review(
        change_id="change1",
        reviewers=["alice"],
        policy="any_one",
    )
    manager.request_review(
        change_id="change2",
        reviewers=["bob"],
        policy="any_one",
    )

    pending = manager.list_pending()
    assert len(pending) == 2


def test_review_manager_get_review() -> None:
    """ReviewManager should get review details with comments."""
    db_path = _tmp_db()
    manager = ReviewManager(db_path=db_path)

    request_id = manager.request_review(
        change_id="change123",
        reviewers=["alice", "bob"],
        policy="any_one",
    )

    manager.submit_review(
        request_id=request_id,
        reviewer="alice",
        decision="approve",
        comment="Looks good!",
    )

    review = manager.get_review(request_id)
    assert review is not None
    assert review["change_id"] == "change123"
    assert len(review["submissions"]) == 1
    assert review["submissions"][0]["reviewer"] == "alice"
    assert review["submissions"][0]["comment"] == "Looks good!"


def test_review_manager_get_nonexistent_review() -> None:
    """ReviewManager should return None for non-existent reviews."""
    db_path = _tmp_db()
    manager = ReviewManager(db_path=db_path)

    review = manager.get_review("nonexistent")
    assert review is None


def test_team_member_defaults() -> None:
    """TeamMember should have correct defaults."""
    member = TeamMember(
        user_id="test",
        name="Test User",
        role="reviewer",
    )

    assert member.user_id == "test"
    assert member.name == "Test User"
    assert member.role == "reviewer"
    assert member.email is None
