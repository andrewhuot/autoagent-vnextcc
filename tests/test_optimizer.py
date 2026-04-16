"""Unit tests for optimizer proposal evaluation and gate outcomes."""

from __future__ import annotations

from copy import deepcopy

from evals.scorer import CompositeScore, EvalResult
from observer.metrics import HealthMetrics, HealthReport
from optimizer.adversarial import AdversarialSimulationResult
from optimizer.gates import Gates
from optimizer.loop import Optimizer
from optimizer.memory import OptimizationMemory
from optimizer.proposer import Proposal


class StubProposer:
    """Deterministic proposer used for optimizer tests."""

    def __init__(self, proposal: Proposal | None):
        self.proposal = proposal

    def propose(
        self,
        current_config: dict,
        health_metrics: dict,
        failure_samples: list[dict],
        failure_buckets: dict[str, int],
        past_attempts: list[dict],
        **kwargs,
    ) -> Proposal | None:
        return self.proposal


class SequencedEvalRunner:
    """Return pre-seeded scores on consecutive run calls."""

    def __init__(self, baseline: CompositeScore, candidate: CompositeScore):
        self.baseline = baseline
        self.candidate = candidate
        self.calls = 0

    def run(self, config: dict | None = None) -> CompositeScore:
        self.calls += 1
        return self.baseline if self.calls == 1 else self.candidate


class CapturingProposer:
    """Capture proposer inputs to verify optimizer context plumbing."""

    def __init__(self, proposal: Proposal):
        self.proposal = proposal
        self.captured_past_attempts: list[list[dict]] = []

    def propose(
        self,
        current_config: dict,
        health_metrics: dict,
        failure_samples: list[dict],
        failure_buckets: dict[str, int],
        past_attempts: list[dict],
        **kwargs,
    ) -> Proposal:
        self.captured_past_attempts.append(past_attempts)
        return self.proposal


class RejectingAdversarialSimulator:
    """Always fails simulation to test adversarial reject path."""

    def evaluate_candidate(
        self,
        *,
        baseline_config: dict,
        candidate_config: dict,
    ) -> AdversarialSimulationResult:
        del baseline_config, candidate_config
        return AdversarialSimulationResult(
            baseline_pass_rate=0.80,
            candidate_pass_rate=0.60,
            pass_rate_delta=-0.20,
            passed=False,
            conversations=30,
            details="adversarial_pass_rate 0.800 -> 0.600 (delta=-0.200, allowed_drop=0.050)",
        )


class RecordingAutoLearner:
    """Record auto-learning calls and return a deterministic draft ID."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def learn_from_accepted_attempt(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return "draft-skill-001"


def _health_report() -> HealthReport:
    return HealthReport(
        metrics=HealthMetrics(
            success_rate=0.62,
            avg_latency_ms=420.0,
            error_rate=0.22,
            safety_violation_rate=0.01,
            avg_cost=0.19,
            total_conversations=100,
        ),
        failure_buckets={"routing_error": 7, "tool_failure": 3},
        needs_optimization=True,
        reason="error rate too high",
    )


def _score(
    *,
    quality: float,
    safety: float,
    latency: float,
    cost: float,
    composite: float,
    safety_failures: int = 0,
) -> CompositeScore:
    return CompositeScore(
        quality=quality,
        safety=safety,
        latency=latency,
        cost=cost,
        composite=composite,
        safety_failures=safety_failures,
        total_cases=55,
        passed_cases=50,
    )


def _score_with_case_results(
    *,
    quality: float,
    safety: float,
    latency: float,
    cost: float,
    composite: float,
    case_quality_values: list[float],
) -> CompositeScore:
    """Build score object with explicit per-case results for significance testing."""
    results = [
        EvalResult(
            case_id=f"case_{index:02d}",
            category="regression",
            passed=value >= 0.5,
            quality_score=value,
            safety_passed=True,
            latency_ms=120.0,
            token_count=180,
        )
        for index, value in enumerate(case_quality_values, start=1)
    ]
    return CompositeScore(
        quality=quality,
        safety=safety,
        latency=latency,
        cost=cost,
        composite=composite,
        safety_failures=0,
        total_cases=len(results),
        passed_cases=sum(1 for result in results if result.passed),
        results=results,
    )


def _proposal_with_prompt_change(config: dict) -> Proposal:
    updated = deepcopy(config)
    updated["prompts"]["root"] = updated["prompts"]["root"] + " Please be explicit."
    return Proposal(
        change_description="Strengthen root prompt",
        config_section="prompts",
        new_config=updated,
        reasoning="Improve answer quality",
    )


def test_optimizer_accepts_when_all_gates_pass(tmp_path, base_config: dict) -> None:
    """Optimizer should accept proposal when safety/improvement/regression gates pass."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score(quality=0.70, safety=1.0, latency=0.70, cost=0.70, composite=0.77),
        candidate=_score(quality=0.75, safety=1.0, latency=0.73, cost=0.72, composite=0.81),
    )
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=StubProposer(_proposal_with_prompt_change(base_config)),
        gates=Gates(regression_threshold=0.05),
    )

    new_config, status = optimizer.optimize(_health_report(), base_config)

    assert new_config is not None
    assert status.startswith("ACCEPTED")
    attempts = memory.recent(limit=1)
    assert len(attempts) == 1
    assert attempts[0].status == "accepted"


def test_optimizer_accepts_small_eval_suites_without_significance_rejection(
    tmp_path,
    base_config: dict,
) -> None:
    """Tiny starter eval suites should remain reviewable instead of failing the whole loop."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score_with_case_results(
            quality=0.70,
            safety=0.6667,
            latency=0.9696,
            cost=0.8940,
            composite=0.7747,
            case_quality_values=[0.85, 0.85, 0.40],
        ),
        candidate=_score_with_case_results(
            quality=0.80,
            safety=1.0,
            latency=0.9698,
            cost=0.8998,
            composite=0.8989,
            case_quality_values=[0.85, 0.85, 0.70],
        ),
    )
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=StubProposer(_proposal_with_prompt_change(base_config)),
    )

    new_config, status = optimizer.optimize(_health_report(), base_config)

    assert new_config is not None
    assert status.startswith("ACCEPTED")
    assert "significance advisory only" in status
    attempt = memory.recent(limit=1)[0]
    assert attempt.status == "accepted"
    assert attempt.significance_n == 3


def test_optimizer_rejects_on_safety_failures(tmp_path, base_config: dict) -> None:
    """Safety hard gate must reject candidates with any safety failure."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score(quality=0.70, safety=1.0, latency=0.70, cost=0.70, composite=0.77),
        candidate=_score(
            quality=0.90,
            safety=0.80,
            latency=0.90,
            cost=0.90,
            composite=0.88,
            safety_failures=2,
        ),
    )
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=StubProposer(_proposal_with_prompt_change(base_config)),
    )

    new_config, status = optimizer.optimize(_health_report(), base_config)

    assert new_config is None
    assert "rejected" in status.lower()
    assert "safety" in status.lower() or "constraint" in status.lower()
    recent_status = memory.recent(limit=1)[0].status
    assert recent_status in ("rejected_safety", "rejected_constraints")


def test_optimizer_rejects_when_candidate_not_improved(tmp_path, base_config: dict) -> None:
    """Improvement gate should reject equal-or-worse composite scores."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score(quality=0.72, safety=1.0, latency=0.72, cost=0.72, composite=0.79),
        candidate=_score(quality=0.71, safety=1.0, latency=0.71, cost=0.71, composite=0.78),
    )
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=StubProposer(_proposal_with_prompt_change(base_config)),
    )

    new_config, status = optimizer.optimize(_health_report(), base_config)

    assert new_config is None
    assert "rejected_no_improvement" in status.lower()
    assert memory.recent(limit=1)[0].status == "rejected_no_improvement"


def test_optimizer_rejects_regression_even_if_composite_improves(tmp_path, base_config: dict) -> None:
    """Regression gate should reject candidates that drop an individual metric by >5%."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score(quality=1.00, safety=1.0, latency=0.70, cost=0.70, composite=0.89),
        candidate=_score(quality=0.90, safety=1.0, latency=0.95, cost=0.95, composite=0.92),
    )
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=StubProposer(_proposal_with_prompt_change(base_config)),
        gates=Gates(regression_threshold=0.05),
    )

    new_config, status = optimizer.optimize(_health_report(), base_config)

    assert new_config is None
    assert "rejected_regression" in status.lower()
    assert memory.recent(limit=1)[0].status == "rejected_regression"


def test_optimizer_rejects_invalid_config_without_running_evals(tmp_path, base_config: dict) -> None:
    """Invalid configs should be rejected before the eval runner is executed."""
    invalid = deepcopy(base_config)
    invalid["thresholds"]["max_turns"] = "many"
    proposal = Proposal(
        change_description="Introduce invalid max_turns",
        config_section="thresholds",
        new_config=invalid,
        reasoning="Intentional invalid config for test",
    )

    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score(quality=0.7, safety=1.0, latency=0.7, cost=0.7, composite=0.77),
        candidate=_score(quality=0.8, safety=1.0, latency=0.8, cost=0.8, composite=0.84),
    )
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=StubProposer(proposal),
    )

    new_config, status = optimizer.optimize(_health_report(), base_config)

    assert new_config is None
    assert status.startswith("Invalid config:")
    assert memory.recent(limit=1)[0].status == "rejected_invalid"
    assert eval_runner.calls == 0


def test_optimizer_tracks_config_section_in_past_attempts(tmp_path, base_config: dict) -> None:
    """Past attempts should preserve config section names for proposer de-duplication."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score(quality=0.70, safety=1.0, latency=0.70, cost=0.70, composite=0.77),
        candidate=_score(quality=0.78, safety=1.0, latency=0.74, cost=0.74, composite=0.83),
    )
    proposal = _proposal_with_prompt_change(base_config)
    proposer = CapturingProposer(proposal)
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=proposer,
    )

    optimizer.optimize(_health_report(), base_config)
    optimizer.optimize(_health_report(), base_config)

    assert len(proposer.captured_past_attempts) == 2
    second_call_attempts = proposer.captured_past_attempts[1]
    assert second_call_attempts
    assert second_call_attempts[0]["config_section"] == "prompts"


def test_optimizer_rejects_non_significant_improvement(tmp_path, base_config: dict) -> None:
    """Accepted gate result should still reject when lift lacks statistical significance."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score_with_case_results(
            quality=0.70,
            safety=1.0,
            latency=0.70,
            cost=0.70,
            composite=0.79,
            case_quality_values=[0.60, 0.61, 0.59, 0.60, 0.61, 0.60, 0.59, 0.60],
        ),
        candidate=_score_with_case_results(
            quality=0.705,
            safety=1.0,
            latency=0.705,
            cost=0.705,
            composite=0.792,
            case_quality_values=[0.61, 0.60, 0.60, 0.60, 0.61, 0.60, 0.60, 0.60],
        ),
    )
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=StubProposer(_proposal_with_prompt_change(base_config)),
        significance_alpha=0.05,
        significance_min_effect_size=0.01,
        significance_iterations=1000,
    )

    new_config, status = optimizer.optimize(_health_report(), base_config)

    assert new_config is None
    assert "rejected_not_significant" in status.lower()
    attempt = memory.recent(limit=1)[0]
    assert attempt.status == "rejected_not_significant"
    assert attempt.significance_n > 0


def test_optimizer_rejects_when_adversarial_simulation_regresses(
    tmp_path,
    base_config: dict,
) -> None:
    """Adversarial regression should veto an otherwise accepted candidate."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score(quality=0.70, safety=1.0, latency=0.70, cost=0.70, composite=0.77),
        candidate=_score(quality=0.75, safety=1.0, latency=0.73, cost=0.72, composite=0.81),
    )
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=StubProposer(_proposal_with_prompt_change(base_config)),
        require_statistical_significance=False,
        adversarial_simulator=RejectingAdversarialSimulator(),
    )

    new_config, status = optimizer.optimize(_health_report(), base_config)

    assert new_config is None
    assert "rejected_adversarial" in status.lower()
    assert memory.recent(limit=1)[0].status == "rejected_adversarial"


def test_optimizer_creates_draft_skill_from_accepted_attempt(
    tmp_path,
    base_config: dict,
) -> None:
    """Accepted non-skill mutations should feed the auto-learning loop."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = SequencedEvalRunner(
        baseline=_score(quality=0.70, safety=1.0, latency=0.70, cost=0.70, composite=0.77),
        candidate=_score(quality=0.78, safety=1.0, latency=0.74, cost=0.74, composite=0.83),
    )
    learner = RecordingAutoLearner()
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=StubProposer(_proposal_with_prompt_change(base_config)),
        require_statistical_significance=False,
        skill_autolearner=learner,
        auto_learn_skills=True,
    )

    new_config, status = optimizer.optimize(_health_report(), base_config)

    assert new_config is not None
    assert "ACCEPTED" in status
    assert "draft_skill_created=draft-skill-001" in status
    assert len(learner.calls) == 1
