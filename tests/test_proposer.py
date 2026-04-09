"""Unit tests for deterministic proposer fallback behavior."""

from __future__ import annotations

from optimizer.proposer import Proposer


def test_mock_proposer_uses_scoped_routing_failures_to_expand_matching_rule_keywords() -> None:
    """Routing repairs should mine keywords from scoped failures instead of defaulting to canned terms."""
    proposer = Proposer(use_mock=True)
    current_config = {
        "routing": {
            "rules": [
                {"specialist": "support", "keywords": ["help"], "patterns": []},
                {"specialist": "orders", "keywords": ["order"], "patterns": []},
                {"specialist": "recommendations", "keywords": ["suggest"], "patterns": []},
            ]
        }
    }

    proposal = proposer.propose(
        current_config=current_config,
        health_metrics={"success_rate": 0.25},
        failure_samples=[
            {
                "user_message": "Review this PRD and flag missing acceptance criteria for checkout.",
                "error_message": "routing: expected=support got=orders; keywords: missing expected keywords",
            },
            {
                "user_message": "Generate regression evals for refund edge cases.",
                "error_message": "routing: expected=recommendations got=support; keywords: missing expected keywords",
            },
        ],
        failure_buckets={"routing_error": 2},
        past_attempts=[],
    )

    assert proposal is not None
    assert proposal.config_section == "routing"
    assert "scoped eval failures" in proposal.change_description.lower()
    support_keywords = proposal.new_config["routing"]["rules"][0]["keywords"]
    recommendation_keywords = proposal.new_config["routing"]["rules"][2]["keywords"]
    assert "acceptance" in support_keywords
    assert "criteria" in support_keywords
    assert "regression" in recommendation_keywords
    assert "refund" in recommendation_keywords
