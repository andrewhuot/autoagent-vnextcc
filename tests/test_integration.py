"""Integration test for observe -> optimize -> deploy -> canary promotion loop."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from deployer import Deployer
from evals.scorer import CompositeScore
from logger.store import ConversationStore
from observer import Observer
from optimizer import Optimizer
from optimizer.memory import OptimizationMemory
from optimizer.proposer import Proposal

from tests.helpers import build_record


class MockLoopEvalRunner:
    """Deterministic eval runner that rewards configs with quality_boost enabled."""

    def run(self, config: dict | None = None) -> CompositeScore:
        improved = bool(config and config.get("quality_boost"))
        if improved:
            return CompositeScore(
                quality=0.86,
                safety=1.0,
                latency=0.84,
                cost=0.84,
                composite=0.89,
                safety_failures=0,
                total_cases=55,
                passed_cases=53,
            )
        return CompositeScore(
            quality=0.72,
            safety=1.0,
            latency=0.72,
            cost=0.72,
            composite=0.79,
            safety_failures=0,
            total_cases=55,
            passed_cases=45,
        )


class MockLoopProposer:
    """Mock LLM proposer that emits a single targeted config improvement."""

    def propose(
        self,
        current_config: dict,
        health_metrics: dict,
        failure_samples: list[dict],
        failure_buckets: dict[str, int],
        past_attempts: list[dict],
    ) -> Proposal:
        candidate = deepcopy(current_config)
        candidate["quality_boost"] = True
        candidate["prompts"]["root"] = candidate["prompts"]["root"] + " Be thorough and verify answers."
        return Proposal(
            change_description="Enable quality boost and strengthen root instruction",
            config_section="prompts",
            new_config=candidate,
            reasoning="Improve unhelpful response failures",
        )


def _seed_conversation_history(store: ConversationStore) -> None:
    """Seed baseline and degraded records so observer requests optimization."""
    # Baseline traffic for v001 (intentionally weak success so canary has room to win).
    for _ in range(8):
        store.log(build_record(config_version="v001", outcome="success", specialist_used="orders"))
    for _ in range(12):
        store.log(
            build_record(
                config_version="v001",
                outcome="fail",
                agent_response="No",
                specialist_used="support",
            )
        )

    # Additional recent degraded traffic to trigger observer optimization request.
    for _ in range(12):
        store.log(
            build_record(
                user_message="Please write code",
                agent_response="ok",
                outcome="fail",
                latency_ms=3900.0,
                tool_calls=[{"tool": "faq", "status": "error"}],
                safety_flags=["hack"],
                specialist_used="support",
                config_version="v001",
            )
        )


def _seed_canary_success_traffic(store: ConversationStore) -> None:
    """Seed canary conversations so promotion criteria are satisfied."""
    for _ in range(9):
        store.log(build_record(config_version="v002", outcome="success", specialist_used="orders"))
    for _ in range(1):
        store.log(
            build_record(
                config_version="v002",
                outcome="fail",
                agent_response="No",
                specialist_used="support",
            )
        )


def test_full_loop_observe_optimize_deploy_promote(
    base_config: dict,
    tmp_path: Path,
) -> None:
    """System should complete one full self-healing cycle with mocked LLM/evals."""
    store = ConversationStore(str(tmp_path / "conversations.db"))
    memory = OptimizationMemory(str(tmp_path / "optimizer_memory.db"))
    deployer = Deployer(configs_dir=str(tmp_path / "configs"), store=store)

    # Bootstrap an active baseline config version.
    deployer.version_manager.save_version(base_config, scores={"composite": 0.79}, status="active")

    _seed_conversation_history(store)

    observer = Observer(store)
    health_report = observer.observe(window=100)
    assert health_report.needs_optimization is True

    optimizer = Optimizer(
        eval_runner=MockLoopEvalRunner(),
        memory=memory,
        proposer=MockLoopProposer(),
    )
    current_config = deployer.get_active_config()
    assert current_config is not None

    new_config, status = optimizer.optimize(health_report, current_config)
    assert new_config is not None
    assert status.startswith("ACCEPTED")

    score = MockLoopEvalRunner().run(new_config)
    deploy_result = deployer.deploy(
        new_config,
        {
            "quality": score.quality,
            "safety": score.safety,
            "latency": score.latency,
            "cost": score.cost,
            "composite": score.composite,
        },
    )
    assert "canary" in deploy_result.lower()

    _seed_canary_success_traffic(store)
    canary_result = deployer.check_and_act()

    assert "promoted" in canary_result.lower()
    assert deployer.status()["active_version"] == 2
    assert deployer.status()["canary_version"] is None

    recent_attempt = memory.recent(limit=1)[0]
    assert recent_attempt.status == "accepted"
