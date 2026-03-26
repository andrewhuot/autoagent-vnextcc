"""Review manager for collaborative approval workflows."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ReviewRequest:
    """A review request for a change."""

    request_id: str
    change_id: str
    reviewers: list[str]
    status: str  # pending, in_review, approved, rejected
    created_at: float
    policy: str  # any_one, all_reviewers, majority


@dataclass
class ReviewSubmission:
    """A review submission."""

    request_id: str
    reviewer: str
    decision: str  # approve, reject
    comment: str
    submitted_at: float


class ReviewManager:
    """Manages collaborative review and approval workflows."""

    def __init__(self, db_path: str = ".autoagent/reviews.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_requests (
                    request_id TEXT PRIMARY KEY,
                    change_id TEXT NOT NULL,
                    reviewers TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    policy TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    comment TEXT,
                    submitted_at REAL NOT NULL
                )
            """)
            conn.commit()

    def request_review(
        self, change_id: str, reviewers: list[str], policy: str = "any_one"
    ) -> str:
        """Create a review request."""
        request_id = f"review_{int(time.time() * 1000)}"

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_requests
                (request_id, change_id, reviewers, status, created_at, policy)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    change_id,
                    json.dumps(reviewers),
                    "pending",
                    time.time(),
                    policy,
                ),
            )
            conn.commit()

        return request_id

    def submit_review(
        self, request_id: str, reviewer: str, decision: str, comment: str = ""
    ) -> bool:
        """Submit a review."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_submissions
                (request_id, reviewer, decision, comment, submitted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (request_id, reviewer, decision, comment, time.time()),
            )

            # Update request status
            conn.execute(
                "UPDATE review_requests SET status = 'in_review' WHERE request_id = ?",
                (request_id,),
            )
            conn.commit()

        # Check if approval requirements are met
        approved = self.check_approval(request_id)
        if approved:
            self._update_status(request_id, "approved")

        return True

    def check_approval(self, request_id: str, policy: str | None = None) -> bool:
        """Check if approval requirements are met."""
        with sqlite3.connect(self.db_path) as conn:
            # Get request
            request_row = conn.execute(
                "SELECT reviewers, policy FROM review_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()

            if not request_row:
                return False

            reviewers = json.loads(request_row[0])
            approval_policy = policy or request_row[1]

            # Get submissions
            submissions = conn.execute(
                "SELECT reviewer, decision FROM review_submissions WHERE request_id = ?",
                (request_id,),
            ).fetchall()

        approvals = [s[0] for s in submissions if s[1] == "approve"]
        rejections = [s[0] for s in submissions if s[1] == "reject"]

        if rejections:
            return False  # Any rejection fails

        if approval_policy == "any_one":
            return len(approvals) >= 1
        elif approval_policy == "all_reviewers":
            return len(approvals) == len(reviewers)
        elif approval_policy == "majority":
            return len(approvals) > len(reviewers) / 2

        return False

    def _update_status(self, request_id: str, status: str) -> None:
        """Update request status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE review_requests SET status = ? WHERE request_id = ?",
                (status, request_id),
            )
            conn.commit()

    def list_pending(self) -> list[dict[str, Any]]:
        """List pending reviews."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM review_requests WHERE status IN ('pending', 'in_review')"
            ).fetchall()

        reviews = []
        for row in rows:
            reviews.append(
                {
                    "request_id": row[0],
                    "change_id": row[1],
                    "reviewers": json.loads(row[2]),
                    "status": row[3],
                    "created_at": row[4],
                    "policy": row[5],
                }
            )
        return reviews

    def get_review(self, request_id: str) -> dict[str, Any] | None:
        """Get review details with comments."""
        with sqlite3.connect(self.db_path) as conn:
            request_row = conn.execute(
                "SELECT * FROM review_requests WHERE request_id = ?", (request_id,)
            ).fetchone()

            if not request_row:
                return None

            submissions = conn.execute(
                "SELECT reviewer, decision, comment, submitted_at FROM review_submissions WHERE request_id = ?",
                (request_id,),
            ).fetchall()

        return {
            "request_id": request_row[0],
            "change_id": request_row[1],
            "reviewers": json.loads(request_row[2]),
            "status": request_row[3],
            "created_at": request_row[4],
            "policy": request_row[5],
            "submissions": [
                {
                    "reviewer": s[0],
                    "decision": s[1],
                    "comment": s[2],
                    "submitted_at": s[3],
                }
                for s in submissions
            ],
        }
