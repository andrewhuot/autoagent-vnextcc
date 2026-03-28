"""Main FastAPI application for AutoAgent VNextCC API.

Start with: uvicorn api.server:app --reload
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.routes import (
    datasets as datasets_routes,
    outcomes as outcomes_routes,
    a2a as a2a_routes,
    adk as adk_routes,
    agent_skills as agent_skills_routes,
    assistant as assistant_routes,
    autofix as autofix_routes,
    changes as changes_routes,
    cicd as cicd_routes,
    collaboration as collaboration_routes,
    config as config_routes,
    context as context_routes,
    control as control_routes,
    conversations as conversations_routes,
    curriculum as curriculum_routes,
    cx_studio as cx_studio_routes,
    demo as demo_routes,
    deploy as deploy_routes,
    diagnose as diagnose_routes,
    edit as edit_routes,
    eval as eval_routes,
    events as events_routes,
    experiments as experiments_routes,
    health as health_routes,
    impact as impact_routes,
    intelligence as intelligence_routes,
    judges as judges_routes,
    knowledge as knowledge_routes,
    loop as loop_routes,
    memory as memory_routes,
    notifications as notifications_routes,
    opportunities as opportunities_routes,
    optimize as optimize_routes,
    optimize_stream as optimize_stream_routes,
    quickfix as quickfix_routes,
    runbooks as runbooks_routes,
    registry as registry_routes,
    sandbox as sandbox_routes,
    scorers as scorers_routes,
    skills as skills_routes,
    traces as traces_routes,
    what_if as what_if_routes,
)
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
# Demo data seeding helper
# ---------------------------------------------------------------------------
def _seed_demo_data_if_empty(conversation_store) -> None:
    """Seed VP demo data if the conversation store is empty."""
    # Check if conversations DB is empty
    with sqlite3.connect(conversation_store.db_path) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM conversations")
        count = cursor.fetchone()[0]

    if count == 0:
        from evals.vp_demo_data import generate_vp_demo_dataset
        print("🌱 Seeding VP demo data (first boot detected)...")
        dataset = generate_vp_demo_dataset(seed=42)
        for conversation in dataset.conversations:
            conversation_store.log(conversation)
        print(f"✅ Seeded {len(dataset.conversations)} demo conversations")
    else:
        print(f"📊 Found {count} existing conversations, skipping demo seed")


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
    from optimizer.adversarial import AdversarialSimulationConfig, AdversarialSimulator
    from optimizer.memory import OptimizationMemory
    from optimizer.proposer import Proposer
    from optimizer.providers import build_router_from_runtime_config
    from optimizer.reliability import (
        DeadLetterQueue,
        LoopCheckpointStore,
        LoopWatchdog,
        ResourceMonitor,
    )
    from core.skills import SkillStore
    from optimizer.skill_engine import SkillEngine
    from optimizer.skill_autolearner import SkillAutoLearner

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
    eval_runner = EvalRunner(
        history_db_path=runtime.eval.history_db_path,
        cache_enabled=runtime.eval.cache_enabled,
        cache_db_path=runtime.eval.cache_db_path,
        dataset_strict_integrity=runtime.eval.dataset_strict_integrity,
        random_seed=runtime.eval.random_seed,
        token_cost_per_1k=runtime.eval.token_cost_per_1k,
    )
    proposer = Proposer(
        use_mock=runtime.optimizer.use_mock,
        llm_router=build_router_from_runtime_config(runtime.optimizer),
    )

    # Initialize skills system
    skill_store = SkillStore(db_path=".autoagent/core_skills.db")
    skill_engine = SkillEngine(store=skill_store)
    adversarial_simulator = None
    if runtime.optimizer.adversarial_simulation_enabled:
        adversarial_simulator = AdversarialSimulator(
            AdversarialSimulationConfig(
                enabled=True,
                conversations=runtime.optimizer.adversarial_simulation_cases,
                max_allowed_drop=runtime.optimizer.adversarial_simulation_max_drop,
            )
        )
    skill_autolearner = None
    if runtime.optimizer.skill_autolearn_enabled:
        skill_autolearner = SkillAutoLearner(
            store=skill_store,
            min_improvement=runtime.optimizer.skill_autolearn_min_improvement,
        )

    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=optimization_memory,
        proposer=proposer,
        significance_alpha=runtime.eval.significance_alpha,
        significance_min_effect_size=runtime.eval.significance_min_effect_size,
        significance_iterations=runtime.eval.significance_iterations,
        skill_engine=skill_engine,
        use_skills=True,
        skill_selection_strategy="auto",
        skill_max_candidates=5,
        adversarial_simulator=adversarial_simulator,
        skill_autolearner=skill_autolearner,
        auto_learn_skills=runtime.optimizer.skill_autolearn_enabled,
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
    app.state.core_skill_store = skill_store
    app.state.skill_engine = skill_engine
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

    # Runbook store
    from registry.runbooks import RunbookStore, seed_starter_runbooks
    app.state.runbook_store = RunbookStore(
        db_path=os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db"),
    )
    seed_starter_runbooks(app.state.runbook_store)

    # Executable skills store
    from registry.skill_store import SkillStore as ExecutableSkillStore
    from registry.skill_loader import install_builtin_packs
    app.state.skill_store = ExecutableSkillStore(
        db_path=os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db"),
    )
    install_builtin_packs(app.state.skill_store)

    # Change card store
    from optimizer.change_card import ChangeCardStore
    app.state.change_card_store = ChangeCardStore()

    # Project memory
    from core.project_memory import ProjectMemory
    app.state.project_memory = ProjectMemory.load() or ProjectMemory()

    # Agent skill generation store
    from agent_skills.store import AgentSkillStore
    app.state.agent_skill_store = AgentSkillStore()

    # Notification manager
    from notifications.manager import NotificationManager
    app.state.notification_manager = NotificationManager(
        db_path=".autoagent/notifications.db"
    )

    # Auto-seed demo data on first boot if DB is empty
    _seed_demo_data_if_empty(conversation_store)

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
app.include_router(demo_routes.router)
app.include_router(eval_routes.router)
app.include_router(optimize_routes.router)
app.include_router(optimize_stream_routes.router)
app.include_router(quickfix_routes.router)
app.include_router(config_routes.router)
app.include_router(health_routes.router)
app.include_router(conversations_routes.router)
app.include_router(deploy_routes.router)
app.include_router(loop_routes.router)
app.include_router(traces_routes.router)
app.include_router(opportunities_routes.router)
app.include_router(experiments_routes.router)
app.include_router(control_routes.router)
app.include_router(events_routes.router)
app.include_router(autofix_routes.router)
app.include_router(judges_routes.router)
app.include_router(context_routes.router)
app.include_router(intelligence_routes.router)
app.include_router(registry_routes.router)
app.include_router(scorers_routes.router)
app.include_router(changes_routes.router)
app.include_router(runbooks_routes.router)
app.include_router(memory_routes.router)
app.include_router(curriculum_routes.router)
app.include_router(cx_studio_routes.router)
app.include_router(adk_routes.router)
app.include_router(cicd_routes.router)
app.include_router(skills_routes.router)
app.include_router(agent_skills_routes.router)
app.include_router(edit_routes.router)
app.include_router(diagnose_routes.router)
app.include_router(assistant_routes.router)
app.include_router(notifications_routes.router)
app.include_router(sandbox_routes.router)
app.include_router(knowledge_routes.router)
app.include_router(what_if_routes.router)
app.include_router(impact_routes.router)
app.include_router(collaboration_routes.router)
app.include_router(datasets_routes.router)
app.include_router(outcomes_routes.router)
app.include_router(a2a_routes.router)
# Check if a2a_routes has a well-known endpoint and wire it up
# The a2a router registers /.well-known/agent-card.json directly (no prefix)
# so we include the router without an additional prefix to keep the path correct.


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
