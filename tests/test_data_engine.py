"""Unit tests for the eval data engine — set management, trace conversion, mode scoring."""

from __future__ import annotations

from pathlib import Path

from evals.data_engine import (
    EvalSetManager,
    EvalSetType,
    EvaluationModeScorer,
    TraceToEvalConverter,
)


def test_eval_set_manager_create_and_list(tmp_path: Path) -> None:
    """Create an eval set and verify it appears in list_sets."""
    manager = EvalSetManager(db_path=str(tmp_path / "eval_sets.db"))
    version = manager.create_set("golden_v1", EvalSetType.golden.value, description="Golden test set")

    assert isinstance(version, str)
    assert len(version) > 0

    sets = manager.list_sets()
    assert len(sets) == 1
    assert sets[0].name == "golden_v1"
    assert sets[0].set_type == EvalSetType.golden.value
    assert sets[0].description == "Golden test set"


def test_eval_set_manager_add_cases(tmp_path: Path) -> None:
    """Add cases to a set and retrieve them."""
    manager = EvalSetManager(db_path=str(tmp_path / "eval_sets.db"))
    manager.create_set("test_set", EvalSetType.challenge.value)

    cases = [
        {"id": "c1", "user_message": "Where is my order?", "expected": "track"},
        {"id": "c2", "user_message": "Return my item", "expected": "return"},
        {"id": "c3", "user_message": "Cancel order", "expected": "cancel"},
    ]
    manager.add_cases("test_set", cases)

    retrieved = manager.get_cases("test_set")
    assert len(retrieved) == 3
    assert retrieved[0]["id"] == "c1"
    assert retrieved[2]["user_message"] == "Cancel order"

    # Verify case_count updated
    meta = manager.get_set("test_set")
    assert meta is not None
    assert meta.case_count == 3


def test_trace_to_eval_converter_basic() -> None:
    """Convert a simple trace (with tool_call event) into an eval case dict."""
    converter = TraceToEvalConverter()
    events = [
        {
            "trace_id": "t-abc",
            "event_type": "tool_call",
            "agent_path": "root/orders",
            "tool_name": "orders_db",
            "tool_input": '{"message": "Where is order 123?"}',
        },
        {
            "trace_id": "t-abc",
            "event_type": "tool_response",
            "agent_path": "root/orders",
            "tool_name": "orders_db",
            "tool_output": '{"status": "shipped"}',
        },
    ]

    case = converter.convert_trace_to_case(events, session_id="sess-99", outcome="fail")

    assert case["source_trace_id"] == "t-abc"
    assert case["source_session_id"] == "sess-99"
    assert case["expected_specialist"] == "orders"
    assert case["expected_tool"] == "orders_db"
    assert "Where is order 123?" in case["user_message"]
    assert case["category"] == EvalSetType.live_failure_queue.value


def test_evaluation_mode_scorer_target_response() -> None:
    """Exact match should score 1.0; partial containment gives partial credit."""
    case = {"reference_answer": "Your order has shipped."}

    # Exact match
    result_exact = {"response": "Your order has shipped."}
    assert EvaluationModeScorer.score_target_response(case, result_exact) == 1.0

    # Substring containment — partial credit
    result_partial = {"response": "Your order has shipped. It arrives tomorrow."}
    score = EvaluationModeScorer.score_target_response(case, result_partial)
    assert 0.0 < score < 1.0

    # No match
    result_none = {"response": "I don't know."}
    assert EvaluationModeScorer.score_target_response(case, result_none) == 0.0


def test_evaluation_mode_scorer_safety() -> None:
    """Safety scoring: refusal for probes, violation detection for normal cases."""
    # Safety probe — agent refuses correctly
    probe_case = {"safety_probe": True}
    result_refused = {"response": "I'm sorry, I cannot help with that request."}
    assert EvaluationModeScorer.score_safety(probe_case, result_refused) == 1.0

    # Safety probe — agent complies (bad)
    result_complied = {"response": "Sure, here is the exploit code."}
    assert EvaluationModeScorer.score_safety(probe_case, result_complied) == 0.0

    # Normal case — no violation
    normal_case = {"safety_probe": False}
    result_clean = {"response": "Here is your order status.", "safety_violation": False}
    assert EvaluationModeScorer.score_safety(normal_case, result_clean) == 1.0

    # Normal case — violation flagged
    result_violation = {"response": "Here is your SSN.", "safety_violation": True}
    assert EvaluationModeScorer.score_safety(normal_case, result_violation) == 0.0


def test_evaluation_mode_scorer_tool_trajectory() -> None:
    """Tool trajectory scoring checks ordered subsequence of expected tools."""
    case_single = {"expected_tool": "catalog"}
    result_match = {"tool_calls": [{"tool": "catalog"}]}
    assert EvaluationModeScorer.score_target_tool_trajectory(case_single, result_match) == 1.0

    # Multiple expected tools in order
    case_multi = {"expected_tool": "catalog, orders_db"}
    result_ordered = {"tool_calls": [{"tool": "catalog"}, {"tool": "faq"}, {"tool": "orders_db"}]}
    assert EvaluationModeScorer.score_target_tool_trajectory(case_multi, result_ordered) == 1.0

    # Wrong order — first tool found, second not after it
    result_wrong_order = {"tool_calls": [{"tool": "orders_db"}, {"tool": "catalog"}]}
    score = EvaluationModeScorer.score_target_tool_trajectory(case_multi, result_wrong_order)
    assert score < 1.0

    # No expected tool → perfect score
    case_none = {"expected_tool": ""}
    assert EvaluationModeScorer.score_target_tool_trajectory(case_none, result_match) == 1.0
