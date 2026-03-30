"""Tests for optimization experiment logging and history views."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import runner as runner_module
from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a Click CLI runner for command tests."""
    return CliRunner()


def _report(*, needs_optimization: bool, failure_buckets: dict[str, int] | None = None) -> SimpleNamespace:
    """Build a minimal observer report for optimize command tests."""
    return SimpleNamespace(
        needs_optimization=needs_optimization,
        failure_buckets=failure_buckets or {},
        metrics=SimpleNamespace(to_dict=lambda: {"success_rate": 0.75}),
    )


def _patch_optimize_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reports: list[object],
    outcomes: list[dict[str, object]],
) -> None:
    """Patch optimize dependencies so CLI tests can drive deterministic cycle outcomes."""
    state = SimpleNamespace(
        reports=list(reports),
        outcomes=list(outcomes),
    )

    class FakeConversationStore:
        """Minimal conversation store stub for optimize tests."""

        def __init__(self, db_path: str) -> None:
            self.db_path = db_path

        def get_failures(self, limit: int = 25) -> list[object]:
            return []

    class FakeObserver:
        """Observer stub that returns pre-seeded reports or raises an injected error."""

        def __init__(self, store: FakeConversationStore) -> None:
            self.store = store

        def observe(self) -> object:
            next_item = state.reports.pop(0)
            if isinstance(next_item, BaseException):
                raise next_item
            return next_item

    class FakeMemory:
        """Memory stub whose latest attempt is controlled by the fake optimizer."""

        def __init__(self, db_path: str) -> None:
            self.db_path = db_path
            self.latest_attempt: object | None = None

        def recent(self, limit: int = 1) -> list[object]:
            if self.latest_attempt is None or limit <= 0:
                return []
            return [self.latest_attempt]

    class FakeOptimizer:
        """Optimizer stub that writes the seeded attempt into fake memory."""

        def __init__(self, eval_runner, memory: FakeMemory, **_: object) -> None:
            self.eval_runner = eval_runner
            self.memory = memory

        def optimize(
            self,
            report: object,
            current_config: dict[str, object],
            failure_samples: list[dict[str, object]] | None = None,
        ) -> tuple[dict[str, object] | None, str]:
            del report, current_config, failure_samples
            outcome = state.outcomes.pop(0)
            if "exception" in outcome:
                raise outcome["exception"]  # type: ignore[misc]

            self.memory.latest_attempt = SimpleNamespace(
                change_description=outcome.get("description"),
                score_before=outcome.get("score_before"),
                score_after=outcome.get("score_after"),
                significance_p_value=outcome.get("p_value"),
            )
            return (
                outcome.get("new_config"),  # type: ignore[return-value]
                str(outcome.get("status", "REJECTED (rejected_no_improvement): no gain")),
            )

    class FakeEvalRunner:
        """Eval runner stub that produces a minimal deployable composite score."""

        def run(self, config: dict[str, object] | None = None) -> SimpleNamespace:
            composite = 0.0
            if isinstance(config, dict):
                composite = float(config.get("composite", 0.0))
            return SimpleNamespace(
                quality=composite,
                safety=1.0,
                tool_use_accuracy=1.0,
                latency=1.0,
                cost=1.0,
                composite=composite,
                confidence_intervals={},
                total_tokens=0,
                estimated_cost_usd=0.0,
                warnings=[],
            )

    class FakeDeployer:
        """Deployer stub used to avoid touching real config state."""

        def __init__(self, configs_dir: str, store: FakeConversationStore) -> None:
            self.configs_dir = configs_dir
            self.store = store
            self.version_manager = SimpleNamespace()

        def get_active_config(self) -> dict[str, object]:
            return {"model": "baseline"}

        def deploy(self, config: dict[str, object], score: dict[str, object]) -> str:
            del config, score
            return "deployed"

    runtime = SimpleNamespace(
        eval=SimpleNamespace(
            significance_alpha=0.05,
            significance_min_effect_size=0.0,
            significance_iterations=32,
        ),
        optimizer=SimpleNamespace(skill_autolearn_enabled=False),
    )

    monkeypatch.setattr(runner_module, "ConversationStore", FakeConversationStore)
    monkeypatch.setattr(runner_module, "Observer", FakeObserver)
    monkeypatch.setattr(runner_module, "OptimizationMemory", FakeMemory)
    monkeypatch.setattr(runner_module, "Optimizer", FakeOptimizer)
    monkeypatch.setattr(runner_module, "Deployer", FakeDeployer)
    monkeypatch.setattr(runner_module, "_ensure_active_config", lambda deployer: {"model": "baseline"})
    monkeypatch.setattr(
        runner_module,
        "_build_runtime_components",
        lambda: (
            runtime,
            FakeEvalRunner(),
            SimpleNamespace(use_mock=False, llm_router=None),
            None,
            None,
            None,
        ),
    )
    monkeypatch.setattr(runner_module, "_warn_mock_modes", lambda **_: None)
    monkeypatch.setattr(runner_module, "_print_cli_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module, "_print_next_actions", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module, "_generate_recommendations", lambda *args, **kwargs: [])


def _read_tsv_rows(log_path: Path) -> list[list[str]]:
    """Read a TSV file into a header row plus data rows."""
    return [line.split("\t") for line in log_path.read_text(encoding="utf-8").strip().splitlines()]


def _seed_experiment_log(log_path: Path) -> None:
    """Write a representative experiment log for CLI viewing tests."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                "cycle\ttimestamp\tscore_before\tscore_after\tdelta\tstatus\tdescription",
                "1\t2026-03-29T12:00:00Z\t0.70\t0.80\t0.10\tkeep\tImprove routing prompts",
                "2\t2026-03-29T12:05:00Z\t0.80\t0.78\t-0.02\tdiscard\tAggressive tool retries",
                "3\t2026-03-29T12:10:00Z\t\t\t\tskip\tSystem healthy",
                "4\t2026-03-29T12:15:00Z\t0.78\t\t\tcrash\tOptimizer timed out",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_optimize_creates_experiment_log_tsv_on_first_run(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first optimize run should create the TSV log with a header and one data row."""
    monkeypatch.chdir(tmp_path)
    _patch_optimize_runtime(
        monkeypatch,
        reports=[_report(needs_optimization=True, failure_buckets={"routing_error": 2})],
        outcomes=[
            {
                "status": "ACCEPTED: improved composite",
                "description": "Improve routing prompts",
                "score_before": 0.74,
                "score_after": 0.81,
                "new_config": {"composite": 0.81},
            }
        ],
    )

    result = runner.invoke(cli, ["optimize", "--cycles", "1", "--json"])

    assert result.exit_code == 0, result.output
    log_path = tmp_path / ".autoagent" / "experiment_log.tsv"
    assert log_path.exists()

    rows = _read_tsv_rows(log_path)
    assert rows[0] == [
        "cycle",
        "timestamp",
        "score_before",
        "score_after",
        "delta",
        "status",
        "description",
    ]
    assert len(rows) == 2
    assert rows[1][0] == "1"
    assert float(rows[1][2]) == pytest.approx(0.74)
    assert float(rows[1][3]) == pytest.approx(0.81)
    assert float(rows[1][4]) == pytest.approx(0.07)
    assert rows[1][5] == "keep"
    assert rows[1][6] == "Improve routing prompts"


def test_optimize_appends_experiment_log_rows_across_multiple_runs(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subsequent optimize runs should append rows and continue the experiment counter."""
    monkeypatch.chdir(tmp_path)

    _patch_optimize_runtime(
        monkeypatch,
        reports=[_report(needs_optimization=True, failure_buckets={"routing_error": 1})],
        outcomes=[
            {
                "status": "ACCEPTED: improved composite",
                "description": "Improve routing prompts",
                "score_before": 0.70,
                "score_after": 0.75,
                "new_config": {"composite": 0.75},
            }
        ],
    )
    first_result = runner.invoke(cli, ["optimize", "--cycles", "1", "--json"])
    assert first_result.exit_code == 0, first_result.output

    _patch_optimize_runtime(
        monkeypatch,
        reports=[_report(needs_optimization=True, failure_buckets={"latency": 1})],
        outcomes=[
            {
                "status": "REJECTED (rejected_no_improvement): no gain",
                "description": "Increase tool timeout",
                "score_before": 0.75,
                "score_after": 0.74,
                "new_config": None,
            }
        ],
    )
    second_result = runner.invoke(cli, ["optimize", "--cycles", "1", "--json"])
    assert second_result.exit_code == 0, second_result.output

    rows = _read_tsv_rows(tmp_path / ".autoagent" / "experiment_log.tsv")
    assert len(rows) == 3
    assert rows[1][0] == "1"
    assert rows[2][0] == "2"
    assert rows[2][5] == "discard"
    assert rows[2][6] == "Increase tool timeout"


def test_optimize_continuous_catches_keyboard_interrupt_and_prints_summary(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continuous optimize should stop cleanly on Ctrl+C after reporting a run summary."""
    monkeypatch.chdir(tmp_path)
    _patch_optimize_runtime(
        monkeypatch,
        reports=[
            _report(needs_optimization=True, failure_buckets={"routing_error": 2}),
            KeyboardInterrupt(),
        ],
        outcomes=[
            {
                "status": "ACCEPTED: improved composite",
                "description": "Improve routing prompts",
                "score_before": 0.70,
                "score_after": 0.82,
                "new_config": {"composite": 0.82},
            }
        ],
    )

    result = runner.invoke(cli, ["optimize", "--continuous"])

    assert result.exit_code == 0, result.output
    assert "Starting continuous optimization. Press Ctrl+C to stop." in result.output
    assert "Cycle 1 | Best: 0.82 | Last: keep (+0.12) | Press Ctrl+C to stop" in result.output
    assert "Ran 1 experiments: 1 kept, 0 discarded, 0 skipped. Best score: 0.82" in result.output
    assert "Experiment log saved to .autoagent/experiment_log.tsv" in result.output

    rows = _read_tsv_rows(tmp_path / ".autoagent" / "experiment_log.tsv")
    assert len(rows) == 2
    assert rows[1][5] == "keep"


def test_experiment_log_pretty_prints_entries_with_statuses(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The log command should render a readable aligned table with colored statuses."""
    monkeypatch.chdir(tmp_path)
    _seed_experiment_log(tmp_path / ".autoagent" / "experiment_log.tsv")

    result = runner.invoke(cli, ["experiment", "log"], color=True)

    assert result.exit_code == 0, result.output
    assert "cycle" in result.output
    assert "Improve routing prompts" in result.output
    assert "Aggressive tool retries" in result.output
    assert "\x1b[" in result.output
    assert "keep" in result.output
    assert "discard" in result.output
    assert "skip" in result.output
    assert "crash" in result.output


def test_experiment_log_tail_shows_only_last_entries(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tail option should limit output to the most recent rows."""
    monkeypatch.chdir(tmp_path)
    _seed_experiment_log(tmp_path / ".autoagent" / "experiment_log.tsv")

    result = runner.invoke(cli, ["experiment", "log", "--tail", "2"])

    assert result.exit_code == 0, result.output
    assert "Improve routing prompts" not in result.output
    assert "Aggressive tool retries" not in result.output
    assert "System healthy" in result.output
    assert "Optimizer timed out" in result.output


def test_experiment_log_outputs_json_array(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The JSON flag should return the experiment history as a JSON array."""
    monkeypatch.chdir(tmp_path)
    _seed_experiment_log(tmp_path / ".autoagent" / "experiment_log.tsv")

    result = runner.invoke(cli, ["experiment", "log", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert [entry["cycle"] for entry in payload] == [1, 2, 3, 4]
    assert payload[0]["status"] == "keep"
    assert payload[-1]["status"] == "crash"


def test_experiment_log_summary_reports_best_and_latest_scores(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The summary view should compress the experiment history into a single line."""
    monkeypatch.chdir(tmp_path)
    _seed_experiment_log(tmp_path / ".autoagent" / "experiment_log.tsv")

    result = runner.invoke(cli, ["experiment", "log", "--summary"])

    assert result.exit_code == 0, result.output
    assert (
        "4 experiments: 1 kept, 1 discarded, 1 skipped, 1 crashed. "
        "Best: 0.80 (cycle 1, +0.10 from first). Latest: 0.78 (cycle 2)"
    ) in result.output


def test_experiment_log_empty_state_suggests_continuous_optimize(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If no log exists yet, the command should explain how to create one."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["experiment", "log"])

    assert result.exit_code == 0, result.output
    assert "No experiments yet. Run: autoagent optimize --continuous" in result.output
