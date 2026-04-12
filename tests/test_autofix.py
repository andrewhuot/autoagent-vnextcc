"""Comprehensive tests for the AutoFix Copilot feature."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from optimizer.autofix import AutoFixEngine, AutoFixProposal, AutoFixStore
from optimizer.autofix_proposers import (
    CostOptimizationProposer,
    FailurePatternProposer,
    RegressionProposer,
)
from optimizer.autofix_vertex import VertexPromptOptimizer
from optimizer.mutations import MutationRegistry, create_default_registry
from shared.canonical_patch import ComponentPatchOperation, ComponentReference, TypedPatchBundle


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------


def _make_proposal(
    proposal_id: str = "test123456ab",
    mutation_name: str = "instruction_rewrite",
    surface: str = "instruction",
    status: str = "pending",
    created_at: float | None = None,
    **kwargs: object,
) -> AutoFixProposal:
    """Build a minimal AutoFixProposal for tests."""
    return AutoFixProposal(
        proposal_id=proposal_id,
        mutation_name=mutation_name,
        surface=surface,
        params=kwargs.get("params", {"target": "root", "text": "test prompt"}),  # type: ignore[arg-type]
        expected_lift=kwargs.get("expected_lift", 0.1),  # type: ignore[arg-type]
        risk_class=kwargs.get("risk_class", "low"),  # type: ignore[arg-type]
        affected_eval_slices=kwargs.get("affected_eval_slices", ["default"]),  # type: ignore[arg-type]
        cost_impact_estimate=kwargs.get("cost_impact_estimate", 0.01),  # type: ignore[arg-type]
        diff_preview=kwargs.get("diff_preview", "Rewrite root prompt"),  # type: ignore[arg-type]
        patch_bundle=kwargs.get("patch_bundle"),  # type: ignore[arg-type]
        status=status,
        created_at=created_at or time.time(),
    )


def _support_keyword_patch_bundle(path: str = "/routing_rules/0") -> dict:
    """Build a typed patch bundle that appends one routing keyword."""
    bundle = TypedPatchBundle(
        bundle_id="bundle-support-refund",
        title="Add support refund route keyword",
        operations=[
            ComponentPatchOperation(
                op="append",
                component=ComponentReference(
                    component_id="root:routing_rule:support",
                    component_type="routing_rule",
                    name="support",
                    path=path,
                ),
                field_path="keywords",
                value=["refund"],
                rationale="Refund examples should route to support.",
            )
        ],
        source="autofix-test",
    )
    return bundle.model_dump(mode="python")


@pytest.fixture()
def registry() -> MutationRegistry:
    """Provide a default mutation registry."""
    return create_default_registry()


@pytest.fixture()
def store(tmp_path: Path) -> AutoFixStore:
    """Provide a fresh AutoFixStore backed by a temp DB."""
    return AutoFixStore(db_path=str(tmp_path / "autofix.db"))


@pytest.fixture()
def sample_config() -> dict:
    """Provide a sample agent configuration."""
    return {
        "model": "gpt-4",
        "prompts": {"root": "You are a helpful assistant."},
        "generation_settings": {"temperature": 0.7, "max_tokens": 8192},
    }


@pytest.fixture()
def sample_failures() -> list[dict]:
    """Provide a list of sample eval failures for proposers."""
    return [
        {"error": "hallucination detected", "eval_slice": "accuracy", "message": ""},
        {"error": "hallucination in response", "eval_slice": "accuracy", "message": ""},
        {"error": "hallucination found", "eval_slice": "factual", "message": ""},
        {"error": "timeout exceeded", "eval_slice": "latency", "message": ""},
        {"error": "timeout on tool call", "eval_slice": "latency", "message": ""},
    ]


# ---------------------------------------------------------------------------
# AutoFixProposal tests
# ---------------------------------------------------------------------------


class TestAutoFixProposal:
    """Tests for AutoFixProposal dataclass."""

    def test_create_proposal(self) -> None:
        """Create a proposal with default and explicit values."""
        p = _make_proposal()
        assert p.proposal_id == "test123456ab"
        assert p.mutation_name == "instruction_rewrite"
        assert p.status == "pending"
        assert p.evaluated_at is None
        assert p.eval_result is None
        assert p.applied_at is None

    def test_to_dict(self) -> None:
        """Serialize a proposal to dict."""
        p = _make_proposal(patch_bundle=_support_keyword_patch_bundle())
        d = p.to_dict()
        assert d["proposal_id"] == "test123456ab"
        assert d["mutation_name"] == "instruction_rewrite"
        assert d["params"] == {"target": "root", "text": "test prompt"}
        assert d["patch_bundle"]["bundle_id"] == "bundle-support-refund"
        assert d["status"] == "pending"
        assert isinstance(d["created_at"], float)

    def test_from_dict(self) -> None:
        """Deserialize a proposal from dict."""
        d = {
            "proposal_id": "abc123",
            "mutation_name": "few_shot_edit",
            "surface": "few_shot",
            "params": {"target": "root", "examples": []},
            "expected_lift": 0.2,
            "risk_class": "medium",
            "affected_eval_slices": ["quality"],
            "cost_impact_estimate": 0.05,
            "diff_preview": "Add examples",
            "status": "evaluated",
            "created_at": 1000.0,
            "evaluated_at": 1001.0,
            "eval_result": {"score": 0.85},
            "applied_at": None,
            "patch_bundle": _support_keyword_patch_bundle(),
        }
        p = AutoFixProposal.from_dict(d)
        assert p.proposal_id == "abc123"
        assert p.mutation_name == "few_shot_edit"
        assert p.expected_lift == 0.2
        assert p.eval_result == {"score": 0.85}
        assert p.patch_bundle is not None
        assert p.patch_bundle["bundle_id"] == "bundle-support-refund"
        assert p.evaluated_at == 1001.0

    def test_round_trip(self) -> None:
        """to_dict -> from_dict round-trip preserves all fields."""
        original = _make_proposal(
            proposal_id="rt001",
            expected_lift=0.35,
            risk_class="high",
            affected_eval_slices=["s1", "s2"],
        )
        reconstructed = AutoFixProposal.from_dict(original.to_dict())
        assert reconstructed.proposal_id == original.proposal_id
        assert reconstructed.mutation_name == original.mutation_name
        assert reconstructed.expected_lift == original.expected_lift
        assert reconstructed.risk_class == original.risk_class
        assert reconstructed.affected_eval_slices == original.affected_eval_slices
        assert reconstructed.created_at == original.created_at


# ---------------------------------------------------------------------------
# AutoFixStore tests
# ---------------------------------------------------------------------------


class TestAutoFixStore:
    """Tests for SQLite-backed AutoFixStore."""

    def test_save_and_get(self, store: AutoFixStore) -> None:
        """Save a proposal and retrieve it by ID."""
        p = _make_proposal(proposal_id="save-get-01")
        store.save(p)
        retrieved = store.get("save-get-01")
        assert retrieved is not None
        assert retrieved.proposal_id == "save-get-01"
        assert retrieved.mutation_name == "instruction_rewrite"
        assert retrieved.params == {"target": "root", "text": "test prompt"}

    def test_save_and_get_preserves_patch_bundle(self, store: AutoFixStore) -> None:
        """Patch bundle metadata must survive SQLite persistence for review/apply."""
        p = _make_proposal(
            proposal_id="save-patch-01",
            mutation_name="component_patch",
            surface="routing",
            params={},
            patch_bundle=_support_keyword_patch_bundle(),
        )
        store.save(p)

        retrieved = store.get("save-patch-01")

        assert retrieved is not None
        assert retrieved.patch_bundle is not None
        assert retrieved.patch_bundle["bundle_id"] == "bundle-support-refund"

    def test_get_nonexistent(self, store: AutoFixStore) -> None:
        """Getting a non-existent proposal returns None."""
        assert store.get("does-not-exist") is None

    def test_list_proposals_all(self, store: AutoFixStore) -> None:
        """List all proposals ordered by created_at descending."""
        now = time.time()
        for i in range(3):
            store.save(_make_proposal(proposal_id=f"list-{i}", created_at=now + i))
        proposals = store.list_proposals()
        assert len(proposals) == 3
        assert proposals[0].proposal_id == "list-2"
        assert proposals[2].proposal_id == "list-0"

    def test_list_proposals_with_status_filter(self, store: AutoFixStore) -> None:
        """Filter proposals by status."""
        now = time.time()
        store.save(_make_proposal(proposal_id="p1", status="pending", created_at=now))
        store.save(_make_proposal(proposal_id="p2", status="applied", created_at=now + 1))
        store.save(_make_proposal(proposal_id="p3", status="pending", created_at=now + 2))
        store.save(_make_proposal(proposal_id="p4", status="rejected", created_at=now + 3))

        pending = store.list_proposals(status="pending")
        assert len(pending) == 2
        assert all(p.status == "pending" for p in pending)
        assert pending[0].proposal_id == "p3"

    def test_list_proposals_with_limit(self, store: AutoFixStore) -> None:
        """Limit constrains result count."""
        now = time.time()
        for i in range(5):
            store.save(_make_proposal(proposal_id=f"lim-{i}", created_at=now + i))
        proposals = store.list_proposals(limit=2)
        assert len(proposals) == 2

    def test_update_status(self, store: AutoFixStore) -> None:
        """Update status and optional fields."""
        store.save(_make_proposal(proposal_id="upd-01"))
        store.update_status("upd-01", "applied", applied_at=1234.0)

        p = store.get("upd-01")
        assert p is not None
        assert p.status == "applied"
        assert p.applied_at == 1234.0

    def test_update_status_with_eval_result(self, store: AutoFixStore) -> None:
        """Update status with eval_result dict."""
        store.save(_make_proposal(proposal_id="upd-02"))
        store.update_status(
            "upd-02", "evaluated",
            evaluated_at=5678.0,
            eval_result={"score": 0.9, "passed": True},
        )

        p = store.get("upd-02")
        assert p is not None
        assert p.status == "evaluated"
        assert p.evaluated_at == 5678.0
        assert p.eval_result == {"score": 0.9, "passed": True}

    def test_update_status_invalid(self, store: AutoFixStore) -> None:
        """Invalid status raises ValueError."""
        store.save(_make_proposal(proposal_id="upd-bad"))
        with pytest.raises(ValueError, match="Invalid status"):
            store.update_status("upd-bad", "bogus_status")

    def test_save_with_eval_result(self, store: AutoFixStore) -> None:
        """Save and retrieve proposal that has eval_result set."""
        p = _make_proposal(proposal_id="eval-01")
        p.eval_result = {"accuracy": 0.95}
        p.evaluated_at = 9999.0
        store.save(p)

        retrieved = store.get("eval-01")
        assert retrieved is not None
        assert retrieved.eval_result == {"accuracy": 0.95}
        assert retrieved.evaluated_at == 9999.0


# ---------------------------------------------------------------------------
# AutoFixEngine tests
# ---------------------------------------------------------------------------


class _MockProposer:
    """Simple mock proposer that returns canned proposals."""

    def __init__(self, proposals: list[AutoFixProposal]) -> None:
        self._proposals = proposals

    def propose(
        self, failures: list[dict], current_config: dict
    ) -> list[AutoFixProposal]:
        return self._proposals


class TestAutoFixEngine:
    """Tests for AutoFixEngine."""

    def test_suggest_with_mock_proposers(self, store: AutoFixStore) -> None:
        """Suggest collects proposals from all proposers and stores them."""
        p1 = _make_proposal(proposal_id="sug-01")
        p2 = _make_proposal(proposal_id="sug-02", mutation_name="few_shot_edit", surface="few_shot")
        proposers = [_MockProposer([p1]), _MockProposer([p2])]
        engine = AutoFixEngine(proposers=proposers, mutation_registry=None, store=store)

        results = engine.suggest([], {})
        assert len(results) == 2
        assert results[0].proposal_id == "sug-01"
        assert results[1].proposal_id == "sug-02"

        # Verify persisted
        assert store.get("sug-01") is not None
        assert store.get("sug-02") is not None

    def test_suggest_without_store(self) -> None:
        """Suggest works without a store — just returns proposals."""
        p1 = _make_proposal(proposal_id="no-store-01")
        engine = AutoFixEngine(
            proposers=[_MockProposer([p1])], mutation_registry=None, store=None
        )
        results = engine.suggest([], {})
        assert len(results) == 1

    def test_apply_with_registry(
        self, store: AutoFixStore, registry: MutationRegistry, sample_config: dict
    ) -> None:
        """Apply a proposal via the real mutation registry."""
        p = _make_proposal(
            proposal_id="apply-01",
            mutation_name="instruction_rewrite",
            surface="instruction",
            params={"target": "root", "text": "New improved prompt"},
        )
        store.save(p)

        engine = AutoFixEngine(proposers=[], mutation_registry=registry, store=store)
        new_config, msg = engine.apply("apply-01", sample_config)

        assert new_config["prompts"]["root"] == "New improved prompt"
        assert "apply-01" in msg

        # Verify status updated
        updated = store.get("apply-01")
        assert updated is not None
        assert updated.status == "applied"
        assert updated.applied_at is not None

    def test_apply_model_swap(
        self, store: AutoFixStore, registry: MutationRegistry, sample_config: dict
    ) -> None:
        """Apply a model_swap mutation."""
        p = _make_proposal(
            proposal_id="apply-model",
            mutation_name="model_swap",
            surface="model",
            params={"model": "gpt-3.5-turbo"},
        )
        store.save(p)

        engine = AutoFixEngine(proposers=[], mutation_registry=registry, store=store)
        new_config, _ = engine.apply("apply-model", sample_config)
        assert new_config["model"] == "gpt-3.5-turbo"
        # Original config unchanged
        assert sample_config["model"] == "gpt-4"

    def test_apply_proposal_uses_patch_bundle_without_registry_operator(
        self,
        store: AutoFixStore,
        registry: MutationRegistry,
    ) -> None:
        """Typed patch bundles are the apply authority when present."""
        current_config = {
            "routing": {"rules": [{"specialist": "support", "keywords": ["help"], "patterns": []}]},
            "thresholds": {"max_turns": 9},
        }
        proposal = _make_proposal(
            proposal_id="apply-patch-01",
            mutation_name="component_patch",
            surface="routing",
            params={},
            patch_bundle=_support_keyword_patch_bundle(),
        )
        store.save(proposal)
        engine = AutoFixEngine(proposers=[], mutation_registry=registry, store=store)

        new_config, message = engine.apply("apply-patch-01", current_config)

        assert "component patch bundle" in message.lower()
        assert new_config["routing"]["rules"][0]["keywords"] == ["help", "refund"]
        assert new_config["thresholds"] == {"max_turns": 9}
        assert store.get("apply-patch-01").status == "applied"  # type: ignore[union-attr]

    def test_apply_invalid_patch_bundle_does_not_mark_proposal_applied(
        self,
        store: AutoFixStore,
        registry: MutationRegistry,
    ) -> None:
        """Invalid canonical patch bundles should fail before status mutation."""
        current_config = {
            "routing": {"rules": [{"specialist": "support", "keywords": ["help"], "patterns": []}]},
        }
        proposal = _make_proposal(
            proposal_id="apply-patch-invalid",
            mutation_name="component_patch",
            surface="routing",
            params={},
            patch_bundle=_support_keyword_patch_bundle(path="/routing_rules/99"),
        )
        store.save(proposal)
        engine = AutoFixEngine(proposers=[], mutation_registry=registry, store=store)

        with pytest.raises(ValueError, match="Invalid patch bundle"):
            engine.apply("apply-patch-invalid", current_config)

        assert store.get("apply-patch-invalid").status == "pending"  # type: ignore[union-attr]

    def test_apply_nonexistent_proposal(
        self, store: AutoFixStore, registry: MutationRegistry
    ) -> None:
        """Applying a non-existent proposal raises KeyError."""
        engine = AutoFixEngine(proposers=[], mutation_registry=registry, store=store)
        with pytest.raises(KeyError, match="not found"):
            engine.apply("nonexistent", {})

    def test_apply_without_store(self, registry: MutationRegistry) -> None:
        """Applying without a store raises RuntimeError."""
        engine = AutoFixEngine(proposers=[], mutation_registry=registry, store=None)
        with pytest.raises(RuntimeError, match="AutoFixStore is required"):
            engine.apply("any-id", {})

    def test_reject_pending_proposal(self, store: AutoFixStore) -> None:
        """Reject updates the proposal status so it leaves the approval queue."""
        store.save(_make_proposal(proposal_id="reject-01"))

        engine = AutoFixEngine(proposers=[], mutation_registry=None, store=store)
        message = engine.reject("reject-01")

        assert "reject-01" in message
        updated = store.get("reject-01")
        assert updated is not None
        assert updated.status == "rejected"

    def test_reject_without_store(self) -> None:
        """Rejecting without a store raises RuntimeError."""
        engine = AutoFixEngine(proposers=[], mutation_registry=None, store=None)
        with pytest.raises(RuntimeError, match="AutoFixStore is required"):
            engine.reject("any-id")

    def test_history(self, store: AutoFixStore) -> None:
        """History returns stored proposals."""
        now = time.time()
        for i in range(3):
            store.save(_make_proposal(proposal_id=f"hist-{i}", created_at=now + i))

        engine = AutoFixEngine(proposers=[], mutation_registry=None, store=store)
        history = engine.history(limit=10)
        assert len(history) == 3
        assert history[0].proposal_id == "hist-2"

    def test_history_without_store(self) -> None:
        """History returns empty list when no store."""
        engine = AutoFixEngine(proposers=[], mutation_registry=None, store=None)
        assert engine.history() == []


# ---------------------------------------------------------------------------
# Proposer tests
# ---------------------------------------------------------------------------


class TestFailurePatternProposer:
    """Tests for FailurePatternProposer."""

    def test_empty_failures(self) -> None:
        """No failures produces no proposals."""
        proposer = FailurePatternProposer()
        assert proposer.propose([], {}) == []

    def test_hallucination_cluster(self, sample_failures: list[dict]) -> None:
        """Hallucination cluster triggers instruction_rewrite proposal."""
        proposer = FailurePatternProposer(min_cluster_size=2)
        proposals = proposer.propose(sample_failures, {})
        assert len(proposals) >= 1

        hallucination_proposals = [
            p for p in proposals if "hallucination" in p.diff_preview
        ]
        assert len(hallucination_proposals) == 1
        assert hallucination_proposals[0].mutation_name == "instruction_rewrite"

    def test_timeout_cluster(self, sample_failures: list[dict]) -> None:
        """Timeout cluster triggers few_shot_edit proposal."""
        proposer = FailurePatternProposer(min_cluster_size=2)
        proposals = proposer.propose(sample_failures, {})

        timeout_proposals = [p for p in proposals if "timeout" in p.diff_preview]
        assert len(timeout_proposals) == 1
        assert timeout_proposals[0].mutation_name == "few_shot_edit"

    def test_min_cluster_size(self) -> None:
        """Failures below min_cluster_size are ignored."""
        failures = [{"error": "hallucination detected", "eval_slice": "acc"}]
        proposer = FailurePatternProposer(min_cluster_size=2)
        assert proposer.propose(failures, {}) == []

    def test_expected_lift_capped(self) -> None:
        """Expected lift is capped at 0.5."""
        failures = [
            {"error": "hallucination", "eval_slice": "acc"} for _ in range(20)
        ]
        proposer = FailurePatternProposer(min_cluster_size=1)
        proposals = proposer.propose(failures, {})
        assert all(p.expected_lift <= 0.5 for p in proposals)


class TestRegressionProposer:
    """Tests for RegressionProposer."""

    def test_empty_failures(self) -> None:
        """No failures produces no proposals."""
        proposer = RegressionProposer()
        assert proposer.propose([], {}) == []

    def test_no_regressions(self) -> None:
        """Non-regression failures produce no proposals."""
        failures = [{"error": "some error", "eval_slice": "default"}]
        proposer = RegressionProposer()
        assert proposer.propose(failures, {}) == []

    def test_regression_detected(self) -> None:
        """Regression failures trigger rollback proposals."""
        failures = [
            {"error": "quality drop", "is_regression": True, "surface": "instruction", "eval_slice": "quality"},
            {"error": "format changed", "previously_passing": True, "surface": "instruction", "eval_slice": "format"},
        ]
        proposer = RegressionProposer()
        proposals = proposer.propose(failures, {})
        assert len(proposals) == 1
        assert proposals[0].mutation_name == "instruction_rewrite"
        assert "rollback" in proposals[0].diff_preview.lower()

    def test_multiple_surfaces(self) -> None:
        """Regressions on different surfaces produce separate proposals."""
        failures = [
            {"error": "err1", "is_regression": True, "surface": "instruction"},
            {"error": "err2", "is_regression": True, "surface": "few_shot"},
        ]
        proposer = RegressionProposer()
        proposals = proposer.propose(failures, {})
        assert len(proposals) == 2


class TestCostOptimizationProposer:
    """Tests for CostOptimizationProposer."""

    def test_empty_failures_with_expensive_model(self, sample_config: dict) -> None:
        """Cost proposer works even with empty failures — analyzes config."""
        proposer = CostOptimizationProposer()
        proposals = proposer.propose([], sample_config)
        # Should suggest model swap (gpt-4 -> gpt-3.5-turbo) and max_tokens reduction
        assert len(proposals) >= 1
        model_proposals = [p for p in proposals if p.mutation_name == "model_swap"]
        assert len(model_proposals) == 1
        assert model_proposals[0].params["model"] == "gpt-3.5-turbo"

    def test_max_tokens_reduction(self, sample_config: dict) -> None:
        """Suggests max_tokens reduction when > 4096."""
        proposer = CostOptimizationProposer()
        proposals = proposer.propose([], sample_config)
        token_proposals = [
            p for p in proposals
            if p.mutation_name == "generation_settings" and "max_tokens" in p.params
        ]
        assert len(token_proposals) == 1
        assert token_proposals[0].params["max_tokens"] == 4096

    def test_no_proposals_for_cheap_config(self) -> None:
        """Cheap config with small max_tokens triggers no proposals."""
        config = {
            "model": "gemini-2.0-flash",
            "generation_settings": {"temperature": 0.7, "max_tokens": 2048},
        }
        proposer = CostOptimizationProposer()
        proposals = proposer.propose([], config)
        assert proposals == []

    def test_high_temperature_reduction(self) -> None:
        """Suggests temperature reduction when > 1.0."""
        config = {
            "model": "gemini-2.0-flash",
            "generation_settings": {"temperature": 1.5, "max_tokens": 1024},
        }
        proposer = CostOptimizationProposer()
        proposals = proposer.propose([], config)
        assert len(proposals) == 1
        assert proposals[0].params["temperature"] == 0.7

    def test_empty_config(self) -> None:
        """Empty config produces no proposals."""
        proposer = CostOptimizationProposer()
        assert proposer.propose([], {}) == []


# ---------------------------------------------------------------------------
# Vertex stub tests
# ---------------------------------------------------------------------------


class TestVertexPromptOptimizer:
    """Tests for the Vertex AI stub."""

    def test_not_available(self) -> None:
        """Stub reports not available."""
        v = VertexPromptOptimizer()
        assert v.is_available is False

    def test_default_location(self) -> None:
        """Default location is us-central1."""
        v = VertexPromptOptimizer()
        assert v.location == "us-central1"

    def test_custom_project(self) -> None:
        """Custom project_id is stored."""
        v = VertexPromptOptimizer(project_id="my-project")
        assert v.project_id == "my-project"

    def test_optimize_prompt_raises(self) -> None:
        """optimize_prompt raises NotImplementedError."""
        v = VertexPromptOptimizer()
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            v.optimize_prompt("test prompt", [{"input": "x", "expected": "y"}])
