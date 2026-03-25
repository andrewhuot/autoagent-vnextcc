"""Tests for the synthetic data generator."""

from __future__ import annotations

import pytest

from evals.synthetic import (
    FAILURE_FAMILIES,
    SyntheticDataset,
    generate_conversations,
    generate_dataset,
    generate_eval_cases,
    generate_traces,
    seed_conversations,
)
from logger.store import ConversationRecord, ConversationStore


# ---------------------------------------------------------------------------
# generate_conversations
# ---------------------------------------------------------------------------

class TestGenerateConversations:
    def test_returns_correct_count(self):
        records = generate_conversations(count=20, seed=1)
        assert len(records) == 20

    def test_default_count_is_60(self):
        records = generate_conversations(seed=1)
        assert len(records) == 60

    def test_all_records_are_conversation_records(self):
        for r in generate_conversations(count=10, seed=1):
            assert isinstance(r, ConversationRecord)

    def test_success_ratio_respected(self):
        records = generate_conversations(count=100, success_ratio=0.7, seed=1)
        successes = sum(1 for r in records if r.outcome == "success")
        assert 60 <= successes <= 80  # allow some rounding

    def test_failure_types_present(self):
        records = generate_conversations(count=100, success_ratio=0.3, seed=1)
        outcomes = {r.outcome for r in records}
        assert "fail" in outcomes or "error" in outcomes

    def test_seed_produces_deterministic_output(self):
        a = generate_conversations(count=10, seed=42)
        b = generate_conversations(count=10, seed=42)
        assert [r.user_message for r in a] == [r.user_message for r in b]

    def test_different_seeds_differ(self):
        a = generate_conversations(count=10, seed=1)
        b = generate_conversations(count=10, seed=2)
        assert [r.user_message for r in a] != [r.user_message for r in b]

    def test_invalid_count_raises(self):
        with pytest.raises(ValueError, match="count must be >= 1"):
            generate_conversations(count=0)

    def test_records_have_required_fields(self):
        records = generate_conversations(count=5, seed=1)
        for r in records:
            assert r.conversation_id
            assert r.session_id
            assert isinstance(r.user_message, str)
            assert isinstance(r.agent_response, str)
            assert r.specialist_used
            assert r.config_version == "v001"
            assert r.timestamp > 0

    def test_safety_flags_only_on_safety_violations(self):
        records = generate_conversations(count=100, success_ratio=0.0, seed=7)
        for r in records:
            if r.safety_flags:
                assert r.outcome in ("fail", "error")

    def test_latency_varies(self):
        records = generate_conversations(count=20, seed=1)
        latencies = {r.latency_ms for r in records}
        assert len(latencies) > 1  # not all the same


# ---------------------------------------------------------------------------
# generate_eval_cases
# ---------------------------------------------------------------------------

class TestGenerateEvalCases:
    def test_default_count(self):
        cases = generate_eval_cases()
        assert len(cases) == 22

    def test_custom_count(self):
        cases = generate_eval_cases(count=5)
        assert len(cases) == 5

    def test_cases_have_required_keys(self):
        for case in generate_eval_cases():
            assert "id" in case
            assert "category" in case
            assert "user_message" in case
            assert "expected_specialist" in case
            assert "expected_behavior" in case

    def test_categories_present(self):
        cases = generate_eval_cases()
        categories = {c["category"] for c in cases}
        assert "happy_path" in categories
        assert "safety" in categories

    def test_safety_probes_tagged(self):
        cases = generate_eval_cases()
        safety_cases = [c for c in cases if c["category"] == "safety"]
        for c in safety_cases:
            assert c.get("safety_probe") is True

    def test_unique_ids(self):
        cases = generate_eval_cases()
        ids = [c["id"] for c in cases]
        assert len(ids) == len(set(ids))

    def test_overflow_generates_unique_ids(self):
        cases = generate_eval_cases(count=30)
        ids = [c["id"] for c in cases]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# generate_traces
# ---------------------------------------------------------------------------

class TestGenerateTraces:
    def test_returns_correct_count(self):
        traces = generate_traces(count=15, seed=1)
        assert len(traces) == 15

    def test_trace_structure(self):
        for trace in generate_traces(count=5, seed=1):
            assert "trace_id" in trace
            assert "user_message" in trace
            assert "agent_response" in trace
            assert "spans" in trace
            assert isinstance(trace["spans"], list)
            assert len(trace["spans"]) >= 1  # at least root span

    def test_spans_have_required_fields(self):
        for trace in generate_traces(count=5, seed=1):
            for span in trace["spans"]:
                assert "span_id" in span
                assert "operation" in span
                assert "start_time" in span
                assert "end_time" in span

    def test_root_span_has_no_parent(self):
        for trace in generate_traces(count=5, seed=1):
            root = trace["spans"][0]
            assert root["parent_span_id"] is None

    def test_seed_deterministic(self):
        a = generate_traces(count=5, seed=42)
        b = generate_traces(count=5, seed=42)
        assert [t["trace_id"] for t in a] == [t["trace_id"] for t in b]


# ---------------------------------------------------------------------------
# generate_dataset
# ---------------------------------------------------------------------------

class TestGenerateDataset:
    def test_returns_synthetic_dataset(self):
        ds = generate_dataset()
        assert isinstance(ds, SyntheticDataset)

    def test_default_counts(self):
        ds = generate_dataset()
        assert len(ds.conversations) == 60
        assert len(ds.eval_cases) == 22
        assert len(ds.traces) == 30

    def test_custom_counts(self):
        ds = generate_dataset(conversation_count=10, eval_case_count=5, trace_count=3)
        assert len(ds.conversations) == 10
        assert len(ds.eval_cases) == 5
        assert len(ds.traces) == 3


# ---------------------------------------------------------------------------
# seed_conversations
# ---------------------------------------------------------------------------

class TestSeedConversations:
    def test_seeds_into_store(self, tmp_path):
        store = ConversationStore(db_path=str(tmp_path / "test.db"))
        count = seed_conversations(store)
        assert count == 60
        assert store.count() == 60

    def test_seeds_custom_dataset(self, tmp_path):
        store = ConversationStore(db_path=str(tmp_path / "test.db"))
        ds = generate_dataset(conversation_count=5)
        count = seed_conversations(store, dataset=ds)
        assert count == 5
        assert store.count() == 5
