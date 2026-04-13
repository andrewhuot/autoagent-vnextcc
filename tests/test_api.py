"""Tests for the API layer — verifies models and task manager."""

from __future__ import annotations

import time
from pathlib import Path


from api.models import (
    EvalRunRequest,
    OptimizeRequest,
    DeployRequest,
    DeployStrategy,
    LoopStartRequest,
    HealthResponse,
    HealthMetricsData,
    EvalCaseResult,
    ConfigVersionInfo,
)
from api.tasks import TaskManager, Task


def make_task_manager(tmp_path: Path) -> TaskManager:
    """Create an isolated task manager so persisted history cannot leak between tests."""
    return TaskManager(db_path=str(tmp_path / "tasks.db"))


class TestTaskManager:
    """Test background task manager."""

    def test_create_and_run_task(self, tmp_path: Path):
        tm = make_task_manager(tmp_path)
        task = tm.create_task("eval", lambda t: {"score": 0.85})
        # Give thread time to complete
        time.sleep(0.1)
        updated = tm.get_task(task.task_id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.result == {"score": 0.85}

    def test_task_captures_errors(self, tmp_path: Path):
        tm = make_task_manager(tmp_path)
        task = tm.create_task("eval", lambda t: (_ for _ in ()).throw(ValueError("test error")))
        time.sleep(0.1)
        updated = tm.get_task(task.task_id)
        assert updated is not None
        assert updated.status == "failed"
        assert "test error" in (updated.error or "")

    def test_task_progress_updates(self, tmp_path: Path):
        tm = make_task_manager(tmp_path)

        def work(task: Task):
            task.progress = 50
            task.result = {"halfway": True}
            return task.result

        task = tm.create_task("optimize", work)
        time.sleep(0.1)
        updated = tm.get_task(task.task_id)
        assert updated is not None
        assert updated.progress == 100  # auto-set to 100 on completion
        assert updated.result == {"halfway": True}

    def test_update_task(self, tmp_path: Path):
        tm = make_task_manager(tmp_path)
        task = tm.create_task("eval", lambda t: time.sleep(0.5))
        # Update while running
        tm.update_task(task.task_id, progress=50)
        updated = tm.get_task(task.task_id)
        assert updated is not None
        assert updated.progress == 50

    def test_list_tasks(self, tmp_path: Path):
        tm = make_task_manager(tmp_path)
        tm.create_task("eval", lambda t: None)
        tm.create_task("optimize", lambda t: None)
        time.sleep(0.1)
        tasks = tm.list_tasks()
        assert len(tasks) == 2

    def test_list_tasks_by_type(self, tmp_path: Path):
        tm = make_task_manager(tmp_path)
        tm.create_task("eval", lambda t: None)
        tm.create_task("optimize", lambda t: None)
        tm.create_task("eval", lambda t: None)
        time.sleep(0.1)
        eval_tasks = tm.list_tasks(task_type="eval")
        assert len(eval_tasks) == 2

    def test_get_nonexistent_task(self, tmp_path: Path):
        tm = make_task_manager(tmp_path)
        assert tm.get_task("nonexistent") is None

    def test_task_to_dict(self, tmp_path: Path):
        tm = make_task_manager(tmp_path)
        task = tm.create_task("eval", lambda t: {"done": True})
        time.sleep(0.1)
        d = task.to_dict()
        assert "task_id" in d
        assert "task_type" in d
        assert "status" in d
        assert d["task_type"] == "eval"


class TestRequestModels:
    """Test Pydantic request model validation."""

    def test_eval_run_request_defaults(self):
        req = EvalRunRequest()
        assert req.config_path is None
        assert req.category is None
        assert req.require_live is False

    def test_eval_run_request_with_values(self):
        req = EvalRunRequest(config_path="configs/v001.yaml", category="safety", require_live=True)
        assert req.config_path == "configs/v001.yaml"
        assert req.category == "safety"
        assert req.require_live is True

    def test_optimize_request_defaults(self):
        req = OptimizeRequest()
        assert req.window == 100
        assert req.force is False
        assert req.mode == "standard"

    def test_deploy_request(self):
        req = DeployRequest(strategy=DeployStrategy.canary)
        assert req.strategy == DeployStrategy.canary

    def test_deploy_request_immediate(self):
        req = DeployRequest(version=5, strategy=DeployStrategy.immediate)
        assert req.version == 5
        assert req.strategy == DeployStrategy.immediate

    def test_loop_start_request_defaults(self):
        req = LoopStartRequest()
        assert req.cycles == 5
        assert req.delay == 1.0


class TestResponseModels:
    """Test response model construction."""

    def test_health_response(self):
        resp = HealthResponse(
            metrics=HealthMetricsData(
                success_rate=0.85,
                avg_latency_ms=120.5,
                total_conversations=100,
            ),
            needs_optimization=False,
            mock_mode=True,
            mock_reasons=["Eval harness is using mock_agent_response."],
        )
        assert resp.metrics.success_rate == 0.85
        assert resp.needs_optimization is False
        assert resp.mock_mode is True
        assert resp.mock_reasons == ["Eval harness is using mock_agent_response."]


    def test_eval_case_result(self):
        case = EvalCaseResult(
            case_id="test_1",
            category="happy_path",
            passed=True,
            quality_score=0.95,
            safety_passed=True,
            latency_ms=150.0,
            token_count=200,
        )
        assert case.passed is True
        assert case.quality_score == 0.95

    def test_config_version_info(self):
        info = ConfigVersionInfo(
            version=1,
            config_hash="abc123",
            filename="v001.yaml",
            timestamp=1700000000.0,
            scores={"composite": 0.85},
            status="active",
        )
        assert info.version == 1
        assert info.status == "active"
