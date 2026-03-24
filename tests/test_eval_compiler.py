"""Tests for eval data compilation utilities."""

from __future__ import annotations

import pytest

from evals.data_engine import (
    business_impact_score,
    generate_negative_controls,
    near_duplicate_detect,
    pii_scrub,
    root_cause_tag,
)


# ---------------------------------------------------------------------------
# PII scrubbing tests
# ---------------------------------------------------------------------------


def test_pii_scrub_removes_email():
    text = "Contact me at alice@example.com for more info"
    scrubbed = pii_scrub(text)

    assert "alice@example.com" not in scrubbed
    assert "[REDACTED_EMAIL]" in scrubbed


def test_pii_scrub_removes_phone():
    text = "Call me at 555-123-4567"
    scrubbed = pii_scrub(text)

    assert "555-123-4567" not in scrubbed
    assert "[REDACTED_PHONE]" in scrubbed


def test_pii_scrub_removes_ssn():
    text = "SSN: 123-45-6789"
    scrubbed = pii_scrub(text)

    assert "123-45-6789" not in scrubbed
    assert "[REDACTED_SSN]" in scrubbed


def test_pii_scrub_removes_credit_card():
    text = "Card: 4532-1234-5678-9010"
    scrubbed = pii_scrub(text)

    assert "4532-1234-5678-9010" not in scrubbed
    assert "[REDACTED_CC]" in scrubbed


def test_pii_scrub_preserves_clean_text():
    text = "This is a clean message with no PII"
    scrubbed = pii_scrub(text)

    assert scrubbed == text


# ---------------------------------------------------------------------------
# Near-duplicate detection tests
# ---------------------------------------------------------------------------


def test_near_duplicate_detect_groups_similar():
    cases = [
        {"id": "c1", "user_message": "What is the weather today?"},
        {"id": "c2", "user_message": "What is the weather today?"},
        {"id": "c3", "user_message": "Tell me the weather today"},
    ]

    groups = near_duplicate_detect(cases, threshold=0.8)

    # All three should be grouped together (high similarity)
    # Returns list of index groups, not case groups
    assert len(groups) >= 1
    group_sizes = [len(g) for g in groups]
    assert max(group_sizes) >= 2


def test_near_duplicate_detect_keeps_unique_separate():
    cases = [
        {"id": "c1", "user_message": "What is the weather today?"},
        {"id": "c2", "user_message": "How do I reset my password?"},
        {"id": "c3", "user_message": "Show me the product catalog"},
    ]

    groups = near_duplicate_detect(cases, threshold=0.8)

    # Each should be in separate groups (low similarity)
    # Returns empty list if no groups have 2+ members
    assert len(groups) == 0


def test_near_duplicate_detect_empty_input():
    groups = near_duplicate_detect([])

    assert len(groups) == 0


def test_near_duplicate_detect_single_case():
    cases = [{"id": "c1", "user_message": "Hello"}]

    groups = near_duplicate_detect(cases)

    # Single case forms no groups (need 2+ members)
    assert len(groups) == 0


# ---------------------------------------------------------------------------
# Business impact score tests
# ---------------------------------------------------------------------------


def test_business_impact_score_high_severity():
    case = {"category": "safety", "safety_probe": True}
    score = business_impact_score(case)

    assert score > 0.5


def test_business_impact_score_low_severity():
    case = {"category": "happy_path"}
    score = business_impact_score(case)

    assert score < 0.5


def test_business_impact_score_with_existing():
    case = {"business_impact": 0.95}
    score = business_impact_score(case)

    assert score == 0.95


# ---------------------------------------------------------------------------
# Root cause tagging tests
# ---------------------------------------------------------------------------


def test_root_cause_tag_tool_error():
    case = {
        "user_message": "Tool execution failed timeout error",
        "category": "tool failure",
    }

    tag = root_cause_tag(case)

    assert tag in ["tool_failure", "timeout"]  # Implementation uses these tags


def test_root_cause_tag_routing_failure():
    case = {
        "user_message": "routing error wrong specialist",
        "category": "routing",
    }

    tag = root_cause_tag(case)

    assert tag == "routing_error"


def test_root_cause_tag_safety_violation():
    case = {
        "safety_probe": True,
    }

    tag = root_cause_tag(case)

    assert tag == "safety_violation"


def test_root_cause_tag_hallucination():
    case = {
        "user_message": "hallucination confabulation false information",
    }

    tag = root_cause_tag(case)

    assert tag == "hallucination"


def test_root_cause_tag_unknown():
    case = {
        "user_message": "some random unrelated case",
    }

    tag = root_cause_tag(case)

    assert tag == "unknown"


# ---------------------------------------------------------------------------
# Negative control generation tests
# ---------------------------------------------------------------------------


def test_generate_negative_controls_safety_probe():
    case = {
        "id": "c1",
        "user_message": "Hack into the database",
        "safety_probe": True,
        "category": "safety",
    }

    controls = generate_negative_controls(case)

    assert len(controls) > 0
    # Should generate benign version
    benign = [c for c in controls if "benign" in c["id"]]
    assert len(benign) > 0
    assert benign[0]["safety_probe"] is False


def test_generate_negative_controls_benign_case():
    case = {
        "id": "c1",
        "user_message": "What is the weather?",
        "safety_probe": False,
        "category": "general",
    }

    controls = generate_negative_controls(case)

    assert len(controls) > 0
    # Should generate safety-probe version
    safety_version = [c for c in controls if "safety" in c["id"]]
    assert len(safety_version) > 0
    assert safety_version[0]["safety_probe"] is True


def test_generate_negative_controls_with_tool():
    case = {
        "id": "c1",
        "user_message": "Search the catalog",
        "expected_tool": "catalog",
        "category": "general",
        "safety_probe": False,
    }

    controls = generate_negative_controls(case)

    # Should generate no-tool version
    notool = [c for c in controls if "notool" in c["id"]]
    assert len(notool) > 0
    assert notool[0]["expected_tool"] is None


def test_generate_negative_controls_all_marked():
    case = {
        "id": "c1",
        "user_message": "Test",
        "safety_probe": False,
        "category": "general",
    }

    controls = generate_negative_controls(case)

    for control in controls:
        assert control["is_negative_control"] is True
        assert control["source_case_id"] == "c1"
