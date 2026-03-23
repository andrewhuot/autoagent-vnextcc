"""Loop endpoints — start/stop continuous optimization loop, view status."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from api.models import (
    LoopCycleInfo,
    LoopStartRequest,
    LoopStatusResponse,
)
from api.tasks import Task

router = APIRouter(prefix="/api/loop", tags=["loop"])

# Module-level state for the loop
_loop_lock = threading.Lock()
_loop_task_id: str | None = None
_loop_stop_event = threading.Event()
_loop_cycle_history: list[dict] = []
_loop_total_cycles: int = 0
_loop_completed_cycles: int = 0


def _ensure_active_config(deployer: Any) -> dict:
    """Return active config; bootstrap from base if needed."""
    from agent.config.loader import load_config

    current = deployer.get_active_config()
    if current is not None:
        return current
    base_path = Path(__file__).parent.parent.parent / "agent" / "config" / "base_config.yaml"
    if base_path.exists():
        config = load_config(str(base_path)).model_dump()
    else:
        config = {}
    deployer.version_manager.save_version(config, scores={"composite": 0.0}, status="active")
    return config


def _build_failure_samples(store: Any, limit: int = 25) -> list[dict]:
    """Build structured failure samples for optimizer proposal context."""
    samples: list[dict] = []
    for record in store.get_failures(limit=limit):
        samples.append({
            "user_message": record.user_message,
            "agent_response": record.agent_response,
            "outcome": record.outcome,
            "error_message": record.error_message,
            "safety_flags": record.safety_flags,
            "tool_calls": record.tool_calls,
            "specialist_used": record.specialist_used,
            "latency_ms": record.latency_ms,
        })
    return samples


@router.post("/start", response_model=LoopStatusResponse, status_code=202)
async def start_loop(body: LoopStartRequest, request: Request) -> LoopStatusResponse:
    """Start the continuous optimization loop as a background task."""
    global _loop_task_id, _loop_cycle_history, _loop_total_cycles, _loop_completed_cycles

    with _loop_lock:
        if _loop_task_id is not None:
            existing = request.app.state.task_manager.get_task(_loop_task_id)
            if existing and existing.status == "running":
                raise HTTPException(status_code=409, detail="A loop is already running")

    task_manager = request.app.state.task_manager
    ws_manager = request.app.state.ws_manager
    observer = request.app.state.observer
    optimizer = request.app.state.optimizer
    deployer = request.app.state.deployer
    eval_runner = request.app.state.eval_runner
    store = request.app.state.conversation_store

    cycles = body.cycles
    delay = body.delay
    window = body.window

    _loop_stop_event.clear()

    with _loop_lock:
        _loop_cycle_history = []
        _loop_total_cycles = cycles
        _loop_completed_cycles = 0

    def run_loop(task: Task) -> dict:
        import asyncio
        global _loop_completed_cycles

        for cycle_num in range(1, cycles + 1):
            if _loop_stop_event.is_set():
                break

            task.progress = int((cycle_num - 1) / cycles * 100)
            report = observer.observe(window=window)

            cycle_info: dict[str, Any] = {
                "cycle": cycle_num,
                "health_success_rate": report.metrics.success_rate,
                "health_error_rate": report.metrics.error_rate,
                "optimization_run": False,
                "optimization_result": None,
                "deploy_result": None,
                "canary_result": None,
            }

            if report.needs_optimization:
                cycle_info["optimization_run"] = True
                current_config = _ensure_active_config(deployer)
                failure_samples = _build_failure_samples(store)

                new_config, status_msg = optimizer.optimize(
                    report, current_config, failure_samples=failure_samples
                )
                cycle_info["optimization_result"] = status_msg

                if new_config is not None:
                    score = eval_runner.run(config=new_config)
                    scores_dict = {
                        "quality": score.quality,
                        "safety": score.safety,
                        "latency": score.latency,
                        "cost": score.cost,
                        "composite": score.composite,
                    }
                    deploy_result = deployer.deploy(new_config, scores_dict)
                    cycle_info["deploy_result"] = deploy_result

            canary_result = deployer.check_and_act()
            cycle_info["canary_result"] = canary_result

            with _loop_lock:
                _loop_cycle_history.append(cycle_info)
                _loop_completed_cycles = cycle_num

            # Best-effort websocket broadcast
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    ws_manager.broadcast({
                        "type": "loop_cycle",
                        "task_id": task.task_id,
                        "cycle": cycle_num,
                        "total_cycles": cycles,
                        "success_rate": report.metrics.success_rate,
                        "optimized": cycle_info["optimization_run"],
                    })
                )
                loop.close()
            except Exception:
                pass

            if cycle_num < cycles and not _loop_stop_event.is_set():
                # Sleep in small increments so we can respond to stop quickly
                for _ in range(int(delay * 10)):
                    if _loop_stop_event.is_set():
                        break
                    time.sleep(0.1)

        task.progress = 100
        with _loop_lock:
            result = {
                "total_cycles": cycles,
                "completed_cycles": _loop_completed_cycles,
                "stopped_early": _loop_stop_event.is_set(),
                "cycle_history": list(_loop_cycle_history),
            }
        task.result = result
        return result

    task = task_manager.create_task("loop", run_loop)
    with _loop_lock:
        _loop_task_id = task.task_id

    return LoopStatusResponse(
        running=True,
        task_id=task.task_id,
        total_cycles=cycles,
        completed_cycles=0,
        cycle_history=[],
    )


@router.post("/stop", response_model=LoopStatusResponse)
async def stop_loop(request: Request) -> LoopStatusResponse:
    """Stop the currently running optimization loop."""
    global _loop_task_id

    with _loop_lock:
        if _loop_task_id is None:
            raise HTTPException(status_code=400, detail="No loop is running")
        task = request.app.state.task_manager.get_task(_loop_task_id)
        if task is None or task.status != "running":
            raise HTTPException(status_code=400, detail="No active loop to stop")

    _loop_stop_event.set()

    with _loop_lock:
        history = [LoopCycleInfo(**c) for c in _loop_cycle_history]
        return LoopStatusResponse(
            running=False,
            task_id=_loop_task_id,
            total_cycles=_loop_total_cycles,
            completed_cycles=_loop_completed_cycles,
            cycle_history=history,
        )


@router.get("/status", response_model=LoopStatusResponse)
async def get_loop_status(request: Request) -> LoopStatusResponse:
    """Get current loop status and cycle history."""
    with _loop_lock:
        task_id = _loop_task_id
        total = _loop_total_cycles
        completed = _loop_completed_cycles
        history_raw = list(_loop_cycle_history)

    running = False
    if task_id:
        task = request.app.state.task_manager.get_task(task_id)
        if task and task.status == "running":
            running = True

    history = [LoopCycleInfo(**c) for c in history_raw]

    return LoopStatusResponse(
        running=running,
        task_id=task_id,
        total_cycles=total,
        completed_cycles=completed,
        cycle_history=history,
    )
