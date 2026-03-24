"""Main FastAPI application for AutoAgent VNextCC API.

Start with: uvicorn api.server:app --reload
"""

from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.routes import autofix, config, context, control, conversations, deploy, eval, events, experiments, health, judges, loop, opportunities, optimize, registry, scorers, traces
from api.tasks import TaskManager
from api.websocket import ConnectionManager


# ---------------------------------------------------------------------------
# Paths (configurable via env vars)
# ---------------------------------------------------------------------------
CONVERSATIONS_DB = os.environ.get("AUTOAGENT_DB", "conversations.db")
CONFIGS_DIR = os.environ.get("AUTOAGENT_CONFIGS", "configs")
OPTIMIZER_MEMORY_DB = os.environ.get("AUTOAGENT_MEMORY_DB", "optimizer_memory.db")
WEB_DIST_DIR = Path(__file__).parent.parent / "web" / "dist"


# ---------------------------------------------------------------------------
# Lifespan — initialize shared stores and managers
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources on startup, clean up on shutdown."""
    from agent.config.runtime import load_runtime_config
    from deployer.canary import Deployer
    from deployer.versioning import ConfigVersionManager
    from evals.runner import EvalRunner
    from logger.structured import configure_structured_logging
    from logger.store import ConversationStore
    from observer import Observer
    from optimizer import Optimizer
    from optimizer.memory import OptimizationMemory
    from optimizer.proposer import Proposer
    from optimizer.providers import build_router_from_runtime_config
    from optimizer.reliability import (
        DeadLetterQueue,
        LoopCheckpointStore,
        LoopWatchdog,
        ResourceMonitor,
    )

    runtime = load_runtime_config()
    startup_epoch = time.time()

    structured_logger = configure_structured_logging(
        log_path=runtime.loop.structured_log_path,
        max_bytes=runtime.loop.log_max_bytes,
        backup_count=runtime.loop.log_backup_count,
    )
    # Core stores
    conversation_store = ConversationStore(db_path=CONVERSATIONS_DB)
    optimization_memory = OptimizationMemory(db_path=OPTIMIZER_MEMORY_DB)
    version_manager = ConfigVersionManager(configs_dir=CONFIGS_DIR)
    dead_letter_queue = DeadLetterQueue(db_path=runtime.loop.dead_letter_db)
    checkpoint_store = LoopCheckpointStore(path=runtime.loop.checkpoint_path)
    loop_watchdog = LoopWatchdog(timeout_seconds=runtime.loop.watchdog_timeout_seconds)
    resource_monitor = ResourceMonitor()

    # High-level components
    observer = Observer(conversation_store)
    eval_runner = EvalRunner(history_db_path=runtime.eval.history_db_path)
    proposer = Proposer(
        use_mock=runtime.optimizer.use_mock,
        llm_router=build_router_from_runtime_config(runtime.optimizer),
    )
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=optimization_memory,
        proposer=proposer,
        significance_alpha=runtime.eval.significance_alpha,
        significance_min_effect_size=runtime.eval.significance_min_effect_size,
        significance_iterations=runtime.eval.significance_iterations,
    )
    deployer = Deployer(configs_dir=CONFIGS_DIR, store=conversation_store)

    # Infrastructure
    task_manager = TaskManager()
    ws_manager = ConnectionManager()

    # Attach to app.state so route handlers can access them
    app.state.conversation_store = conversation_store
    app.state.optimization_memory = optimization_memory
    app.state.version_manager = version_manager
    app.state.observer = observer
    app.state.eval_runner = eval_runner
    app.state.optimizer = optimizer
    app.state.deployer = deployer
    app.state.task_manager = task_manager
    app.state.ws_manager = ws_manager
    app.state.runtime_config = runtime
    app.state.dead_letter_queue = dead_letter_queue
    app.state.checkpoint_store = checkpoint_store
    app.state.loop_watchdog = loop_watchdog
    app.state.resource_monitor = resource_monitor
    app.state.structured_logger = structured_logger
    app.state.started_at = startup_epoch

    # Trace, opportunity, and experiment stores
    from observer.traces import TraceStore
    from observer.opportunities import OpportunityQueue
    from optimizer.experiments import ExperimentStore
    from agent.tracing import TracingMiddleware

    app.state.trace_store = TraceStore(db_path=".autoagent/traces.db")
    app.state.opportunity_queue = OpportunityQueue(db_path=".autoagent/opportunities.db")
    app.state.experiment_store = ExperimentStore(db_path=".autoagent/experiments.db")
    app.state.tracing_middleware = TracingMiddleware(trace_store=app.state.trace_store)

    # Production controls (from R2 simplicity thesis)
    from data.event_log import EventLog
    from optimizer.cost_tracker import CostTracker
    from optimizer.human_control import HumanControlStore

    app.state.control_store = HumanControlStore()
    app.state.event_log = EventLog()
    app.state.cost_tracker = CostTracker(
        db_path=runtime.budget.tracker_db_path,
        per_cycle_budget_dollars=runtime.budget.per_cycle_dollars,
        daily_budget_dollars=runtime.budget.daily_dollars,
        stall_threshold_cycles=runtime.budget.stall_threshold_cycles,
    )

    # AutoFix Copilot
    from optimizer.autofix import AutoFixEngine, AutoFixStore
    from optimizer.autofix_proposers import (
        CostOptimizationProposer,
        FailurePatternProposer,
        RegressionProposer,
    )
    from optimizer.mutations import create_default_registry

    autofix_store = AutoFixStore()
    autofix_registry = create_default_registry()
    autofix_proposers = [
        FailurePatternProposer(),
        RegressionProposer(),
        CostOptimizationProposer(),
    ]
    app.state.autofix_engine = AutoFixEngine(
        proposers=autofix_proposers,
        mutation_registry=autofix_registry,
        eval_runner=eval_runner,
        store=autofix_store,
    )

    # Judge Ops
    from judges.versioning import GraderVersionStore
    from judges.drift_monitor import DriftMonitor
    from judges.human_feedback import HumanFeedbackStore

    app.state.grader_version_store = GraderVersionStore()
    app.state.human_feedback_store = HumanFeedbackStore()
    app.state.drift_monitor = DriftMonitor()

    # Context Workbench
    from context.analyzer import ContextAnalyzer

    app.state.context_analyzer = ContextAnalyzer()

    # Registry store
    from registry.store import RegistryStore
    app.state.registry_store = RegistryStore(
        db_path=os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db"),
    )

    # NL Scorer
    from evals.nl_scorer import NLScorer
    app.state.nl_scorer = NLScorer()

    yield
    # No explicit cleanup needed — SQLite connections are context-managed


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AutoAgent VNextCC",
    description=(
        "Product-grade agent optimization platform — "
        "CLI, API, and web console for iterating ADK agent quality."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS — allow all origins in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
app.include_router(eval.router)
app.include_router(optimize.router)
app.include_router(config.router)
app.include_router(health.router)
app.include_router(conversations.router)
app.include_router(deploy.router)
app.include_router(loop.router)
app.include_router(traces.router)
app.include_router(opportunities.router)
app.include_router(experiments.router)
app.include_router(control.router)
app.include_router(events.router)
app.include_router(autofix.router)
app.include_router(judges.router)
app.include_router(context.router)
app.include_router(registry.router)
app.include_router(scorers.router)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket for real-time progress updates.

    Clients connect and receive JSON messages for:
    - eval_complete: {type, task_id, composite, passed, total}
    - optimize_complete: {type, task_id, accepted, status}
    - loop_cycle: {type, task_id, cycle, total_cycles, success_rate, optimized}
    """
    manager: ConnectionManager = app.state.ws_manager
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except (json.JSONDecodeError, TypeError):
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Background task status endpoints (generic, all task types)
# ---------------------------------------------------------------------------
@app.get("/api/tasks/{task_id}", tags=["tasks"])
async def get_task_status(task_id: str):
    """Get the status of any background task by ID."""
    task = app.state.task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task.to_dict()


@app.get("/api/tasks", tags=["tasks"])
async def list_tasks(task_type: str | None = None):
    """List all background tasks, optionally filtered by type."""
    tasks = app.state.task_manager.list_tasks(task_type=task_type)
    return [t.to_dict() for t in tasks]


# ---------------------------------------------------------------------------
# Static files / SPA catch-all for web frontend
# ---------------------------------------------------------------------------
if WEB_DIST_DIR.is_dir():
    # Mount static assets (JS, CSS, images)
    _assets_dir = WEB_DIST_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_spa_root():
        """Serve the SPA index.html at root."""
        index = WEB_DIST_DIR / "index.html"
        return HTMLResponse(content=index.read_text(encoding="utf-8"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa_catchall(full_path: str):
        """Catch-all for SPA client-side routing."""
        # Don't intercept API, WebSocket, or docs paths
        if full_path.startswith(("api/", "ws")) or full_path in (
            "docs", "redoc", "openapi.json",
        ):
            raise HTTPException(status_code=404)

        # Serve static file if it exists
        static_path = WEB_DIST_DIR / full_path
        if static_path.is_file():
            return FileResponse(str(static_path))

        # Fall back to index.html for client-side routing
        index = WEB_DIST_DIR / "index.html"
        if index.exists():
            return HTMLResponse(content=index.read_text(encoding="utf-8"))

        raise HTTPException(status_code=404)

else:
    @app.get("/", include_in_schema=False)
    async def root():
        return HTMLResponse(
            "<h1>AutoAgent VNextCC API</h1>"
            "<p>API is running. Visit <a href='/docs'>/docs</a> for the OpenAPI explorer.</p>"
            "<p>Frontend not found at web/dist/. Run <code>cd web && npm run build</code>.</p>"
        )
