"""Tests for the unified review surface (api/routes/reviews.py).

Covers: aggregation from both stores, approve/reject dispatch,
stats computation, and edge cases (empty stores, missing stores).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.models import PendingReview, UnifiedReviewItem
from api.routes.reviews import (
    _change_card_to_unified,
    _pending_review_to_unified,
    _render_hunks_as_diff,
    router,
)
from optimizer.change_card import (
    ChangeCardStore,
    ConfidenceInfo,
    DiffHunk,
    ProposedChangeCard,
)
from optimizer.pending_reviews import PendingReviewStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pending_review(
    attempt_id: str = "opt-001",
    score_before: float = 0.72,
    score_after: float = 0.85,
) -> PendingReview:
    return PendingReview(
        attempt_id=attempt_id,
        proposed_config={"instructions": "Be concise"},
        current_config={"instructions": "Be helpful"},
        config_diff="--- a\n+++ b\n-Be helpful\n+Be concise",
        score_before=score_before,
        score_after=score_after,
        change_description="Rewrite root prompt for conciseness",
        reasoning="Eval showed quality improvement with shorter instructions",
        created_at=datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc),
        strategy="adaptive",
        selected_operator_family="instruction_rewrite",
        governance_notes=["Reviewed by safety gate"],
        deploy_scores={"composite": 0.85},
        deploy_strategy="immediate",
    )


def _make_change_card(
    card_id: str = "cc-001",
    status: str = "pending",
) -> ProposedChangeCard:
    return ProposedChangeCard(
        card_id=card_id,
        title="Improve routing accuracy",
        why="Routing failures reduced by 40% with updated rules",
        diff_hunks=[
            DiffHunk(
                hunk_id="h1",
                surface="routing.rules",
                old_value="route to fallback",
                new_value="route to specialist",
                status="pending",
            ),
        ],
        metrics_before={"quality": 0.7, "safety": 0.9},
        metrics_after={"quality": 0.85, "safety": 0.92},
        confidence=ConfidenceInfo(p_value=0.02, effect_size=0.15, judge_agreement=0.88),
        risk_class="low",
        status=status,
        created_at=time.time(),
    )


def _create_test_app(
    pending_store: PendingReviewStore | None = None,
    change_card_store: ChangeCardStore | None = None,
    deployer: MagicMock | None = None,
    optimization_memory: MagicMock | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    if pending_store is not None:
        app.state.pending_review_store = pending_store
    if change_card_store is not None:
        app.state.change_card_store = change_card_store
    if deployer is not None:
        app.state.deployer = deployer
    if optimization_memory is not None:
        app.state.optimization_memory = optimization_memory

    return app


# ---------------------------------------------------------------------------
# Unit tests — conversion helpers
# ---------------------------------------------------------------------------


class TestPendingReviewToUnified:
    def test_basic_conversion(self) -> None:
        review = _make_pending_review()
        unified = _pending_review_to_unified(review)

        assert unified.id == "opt-001"
        assert unified.source == "optimizer"
        assert unified.status == "pending"
        assert unified.title == "Rewrite root prompt for conciseness"
        assert unified.description == "Eval showed quality improvement with shorter instructions"
        assert unified.score_before == 0.72
        assert unified.score_after == 0.85
        assert abs(unified.score_delta - 0.13) < 0.001
        assert unified.strategy == "adaptive"
        assert unified.operator_family == "instruction_rewrite"
        assert unified.has_detailed_audit is False

    def test_dict_input(self) -> None:
        review = _make_pending_review()
        data = review.model_dump(mode="python")
        unified = _pending_review_to_unified(data)
        assert unified.id == "opt-001"
        assert unified.source == "optimizer"


class TestChangeCardToUnified:
    def test_basic_conversion(self) -> None:
        card = _make_change_card()
        unified = _change_card_to_unified(card)

        assert unified.id == "cc-001"
        assert unified.source == "change_card"
        assert unified.status == "pending"
        assert unified.title == "Improve routing accuracy"
        assert unified.risk_class == "low"
        assert unified.has_detailed_audit is True
        # Composite score = mean of metrics
        assert abs(unified.score_before - 0.8) < 0.01  # (0.7+0.9)/2
        assert abs(unified.score_after - 0.885) < 0.01  # (0.85+0.92)/2

    def test_applied_status_maps_to_approved(self) -> None:
        card = _make_change_card(status="applied")
        unified = _change_card_to_unified(card)
        assert unified.status == "approved"

    def test_diff_rendering(self) -> None:
        card = _make_change_card()
        unified = _change_card_to_unified(card)
        assert "routing.rules" in unified.diff_summary
        assert "+route to specialist" in unified.diff_summary
        assert "-route to fallback" in unified.diff_summary


class TestRenderHunksAsDiff:
    def test_renders_hunks(self) -> None:
        hunks = [
            {"surface": "prompts.root", "old_value": "hello", "new_value": "goodbye"},
        ]
        result = _render_hunks_as_diff(hunks)
        assert "--- prompts.root" in result
        assert "-hello" in result
        assert "+goodbye" in result

    def test_empty_hunks(self) -> None:
        assert _render_hunks_as_diff([]) == ""


# ---------------------------------------------------------------------------
# Integration tests — API endpoints
# ---------------------------------------------------------------------------


class TestListPendingEndpoint:
    def test_aggregates_both_stores(self, tmp_path: Path) -> None:
        pr_store = PendingReviewStore(store_dir=str(tmp_path / "pending"))
        pr_store.save_review(_make_pending_review("opt-1"))

        cc_store = ChangeCardStore(db_path=str(tmp_path / "cards.db"))
        cc_store.save(_make_change_card("cc-1"))

        app = _create_test_app(pending_store=pr_store, change_card_store=cc_store)
        client = TestClient(app)

        resp = client.get("/api/reviews/pending")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        sources = {item["source"] for item in items}
        assert sources == {"optimizer", "change_card"}

    def test_empty_stores(self, tmp_path: Path) -> None:
        pr_store = PendingReviewStore(store_dir=str(tmp_path / "pending"))
        cc_store = ChangeCardStore(db_path=str(tmp_path / "cards.db"))

        app = _create_test_app(pending_store=pr_store, change_card_store=cc_store)
        client = TestClient(app)

        resp = client.get("/api/reviews/pending")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_missing_stores_graceful(self) -> None:
        app = _create_test_app()
        client = TestClient(app)

        resp = client.get("/api/reviews/pending")
        assert resp.status_code == 200
        assert resp.json() == []


class TestStatsEndpoint:
    def test_counts_both_stores(self, tmp_path: Path) -> None:
        pr_store = PendingReviewStore(store_dir=str(tmp_path / "pending"))
        pr_store.save_review(_make_pending_review("opt-1"))
        pr_store.save_review(_make_pending_review("opt-2"))

        cc_store = ChangeCardStore(db_path=str(tmp_path / "cards.db"))
        cc_store.save(_make_change_card("cc-1", status="pending"))
        cc_store.save(_make_change_card("cc-2", status="applied"))
        cc_store.save(_make_change_card("cc-3", status="rejected"))

        app = _create_test_app(pending_store=pr_store, change_card_store=cc_store)
        client = TestClient(app)

        resp = client.get("/api/reviews/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_pending"] == 3  # 2 optimizer + 1 change card
        assert stats["optimizer_pending"] == 2
        assert stats["change_card_pending"] == 1
        assert stats["total_approved"] == 1
        assert stats["total_rejected"] == 1


class TestApproveEndpoint:
    def test_approve_optimizer_proposal(self, tmp_path: Path) -> None:
        pr_store = PendingReviewStore(store_dir=str(tmp_path / "pending"))
        pr_store.save_review(_make_pending_review("opt-1"))

        deployer = MagicMock()
        deployer.deploy.return_value = "Deployed v002"

        memory = MagicMock()
        memory.get_all.return_value = []

        app = _create_test_app(
            pending_store=pr_store,
            deployer=deployer,
            optimization_memory=memory,
        )
        client = TestClient(app)

        resp = client.post(
            "/api/reviews/opt-1/approve",
            json={"source": "optimizer"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["source"] == "optimizer"
        assert body["deploy_message"] == "Deployed v002"

        # Verify review was removed from store
        assert pr_store.get_review("opt-1") is None

    def test_approve_deploy_failure_keeps_review(self, tmp_path: Path) -> None:
        """If deploy raises, the review must NOT be deleted so the operator can retry."""
        pr_store = PendingReviewStore(store_dir=str(tmp_path / "pending"))
        pr_store.save_review(_make_pending_review("opt-1"))

        deployer = MagicMock()
        deployer.deploy.side_effect = RuntimeError("deploy crashed")

        app = _create_test_app(pending_store=pr_store, deployer=deployer)
        client = TestClient(app)

        resp = client.post(
            "/api/reviews/opt-1/approve",
            json={"source": "optimizer"},
        )
        assert resp.status_code == 502
        assert "deploy failed" in resp.json()["detail"].lower()

        # Review must still exist in the store
        assert pr_store.get_review("opt-1") is not None

    def test_approve_change_card(self, tmp_path: Path) -> None:
        cc_store = ChangeCardStore(db_path=str(tmp_path / "cards.db"))
        cc_store.save(_make_change_card("cc-1"))

        app = _create_test_app(change_card_store=cc_store)
        client = TestClient(app)

        resp = client.post(
            "/api/reviews/cc-1/approve",
            json={"source": "change_card"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "applied"
        assert body["source"] == "change_card"

        # Verify card status was updated
        card = cc_store.get("cc-1")
        assert card is not None
        assert card.status == "applied"

    def test_approve_missing_body(self, tmp_path: Path) -> None:
        app = _create_test_app()
        client = TestClient(app)

        resp = client.post("/api/reviews/opt-1/approve")
        assert resp.status_code == 422 or resp.status_code == 400

    def test_approve_invalid_source(self, tmp_path: Path) -> None:
        app = _create_test_app()
        client = TestClient(app)

        resp = client.post(
            "/api/reviews/opt-1/approve",
            json={"source": "unknown"},
        )
        assert resp.status_code == 422  # Pydantic rejects invalid Literal value

    def test_approve_not_found(self, tmp_path: Path) -> None:
        pr_store = PendingReviewStore(store_dir=str(tmp_path / "pending"))
        app = _create_test_app(pending_store=pr_store)
        client = TestClient(app)

        resp = client.post(
            "/api/reviews/nonexistent/approve",
            json={"source": "optimizer"},
        )
        assert resp.status_code == 404


class TestRejectEndpoint:
    def test_reject_optimizer_proposal(self, tmp_path: Path) -> None:
        pr_store = PendingReviewStore(store_dir=str(tmp_path / "pending"))
        pr_store.save_review(_make_pending_review("opt-1"))

        memory = MagicMock()
        memory.get_all.return_value = []

        app = _create_test_app(
            pending_store=pr_store,
            optimization_memory=memory,
        )
        client = TestClient(app)

        resp = client.post(
            "/api/reviews/opt-1/reject",
            json={"source": "optimizer", "reason": "Not aligned with goals"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"

        # Verify review was removed
        assert pr_store.get_review("opt-1") is None

    def test_reject_change_card_with_reason(self, tmp_path: Path) -> None:
        cc_store = ChangeCardStore(db_path=str(tmp_path / "cards.db"))
        cc_store.save(_make_change_card("cc-1"))

        app = _create_test_app(change_card_store=cc_store)
        client = TestClient(app)

        resp = client.post(
            "/api/reviews/cc-1/reject",
            json={"source": "change_card", "reason": "Insufficient evidence"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        assert "Insufficient evidence" in body["message"]

        card = cc_store.get("cc-1")
        assert card is not None
        assert card.status == "rejected"

    def test_reject_already_applied_card(self, tmp_path: Path) -> None:
        cc_store = ChangeCardStore(db_path=str(tmp_path / "cards.db"))
        card = _make_change_card("cc-1", status="applied")
        cc_store.save(card)

        app = _create_test_app(change_card_store=cc_store)
        client = TestClient(app)

        resp = client.post(
            "/api/reviews/cc-1/reject",
            json={"source": "change_card"},
        )
        assert resp.status_code == 400


class TestListAllEndpoint:
    def test_returns_all_statuses(self, tmp_path: Path) -> None:
        cc_store = ChangeCardStore(db_path=str(tmp_path / "cards.db"))
        cc_store.save(_make_change_card("cc-1", status="pending"))
        cc_store.save(_make_change_card("cc-2", status="applied"))
        cc_store.save(_make_change_card("cc-3", status="rejected"))

        app = _create_test_app(change_card_store=cc_store)
        client = TestClient(app)

        resp = client.get("/api/reviews/all")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 3

    def test_filters_by_status(self, tmp_path: Path) -> None:
        cc_store = ChangeCardStore(db_path=str(tmp_path / "cards.db"))
        cc_store.save(_make_change_card("cc-1", status="pending"))
        cc_store.save(_make_change_card("cc-2", status="applied"))

        app = _create_test_app(change_card_store=cc_store)
        client = TestClient(app)

        resp = client.get("/api/reviews/all?status=pending")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["status"] == "pending"
