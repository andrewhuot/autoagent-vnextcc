"""FastAPI server for the ADK agent and status dashboard."""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import create_eval_agent
from agent.config.loader import load_config, load_config_with_canary
from agent.config.runtime import load_runtime_config
from agent.config.schema import validate_config
from agent.dashboard_data import DashboardDataService
from agent.root_agent import create_root_agent
from agent.skill_runtime import SkillRuntime
from core.skills import SkillStore
from deployer import Deployer
from evals import EvalRunner
from logger.middleware import log_conversation
from logger.store import ConversationStore
from optimizer.memory import OptimizationMemory

app = FastAPI(title="AutoAgent VNext", version="0.2.0")

_templates_dir = Path(__file__).parent / "templates"
_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(_templates_dir))
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Global state — initialized on startup
_runner: Runner | None = None
_session_service: InMemorySessionService | None = None
_store: ConversationStore | None = None
_memory: OptimizationMemory | None = None
_deployer: Deployer | None = None
_eval_runner: EvalRunner | None = None
_dashboard: DashboardDataService | None = None
_loaded_config: dict | None = None

_app_name = "autoagent"
_user_id = "default_user"
_app_started_at = time.time()


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    response: str
    session_id: str


def _load_startup_config(configs_dir: str, config_path: str) -> dict:
    """Load config from explicit path, canary config dir, or baked-in default."""
    if config_path:
        return load_config(config_path).model_dump(mode="python")

    if Path(configs_dir).exists():
        return load_config_with_canary(configs_dir).model_dump(mode="python")

    base_path = Path(__file__).parent / "config" / "base_config.yaml"
    return load_config(str(base_path)).model_dump(mode="python")


def _require_dashboard() -> DashboardDataService:
    """Return dashboard service or raise 503 when startup has not completed."""
    if _dashboard is None:
        raise HTTPException(status_code=503, detail="Dashboard service not initialized")
    return _dashboard


def _active_config_version() -> str:
    """Return active config version label for logging metadata."""
    if _deployer is None:
        return "v000"
    active = _deployer.status().get("active_version")
    if active is None:
        return "v000"
    return f"v{active:03d}"


@app.on_event("startup")
async def startup() -> None:
    """Initialize agent runtime, stores, deployment manager, and dashboard service."""
    global _runner, _session_service, _store, _memory, _deployer, _eval_runner, _dashboard, _loaded_config, _app_started_at

    configs_dir = os.environ.get("AUTOAGENT_CONFIGS_DIR", "configs")
    config_path = os.environ.get("AUTOAGENT_CONFIG_PATH", "")
    db_path = os.environ.get("AUTOAGENT_DB_PATH", "conversations.db")
    memory_db_path = os.environ.get("AUTOAGENT_MEMORY_DB_PATH", "optimizer_memory.db")

    _loaded_config = _load_startup_config(configs_dir=configs_dir, config_path=config_path)
    _app_started_at = time.time()
    _store = ConversationStore(db_path=db_path)
    _memory = OptimizationMemory(db_path=memory_db_path)
    _deployer = Deployer(configs_dir=configs_dir, store=_store)
    eval_agent = create_eval_agent(
        load_runtime_config(),
        default_config=_loaded_config,
    )
    _eval_runner = EvalRunner(agent_fn=eval_agent.run)
    _eval_runner.mock_mode_messages = list(eval_agent.mock_mode_messages)

    # Bootstrap active config history when no config has been promoted yet.
    if _deployer.get_active_config() is None and _loaded_config:
        _deployer.version_manager.save_version(
            _loaded_config,
            scores={"composite": 0.0},
            status="active",
        )

    _dashboard = DashboardDataService(
        store=_store,
        memory=_memory,
        deployer=_deployer,
        eval_runner=_eval_runner,
        app_started_at=_app_started_at,
        current_config_provider=lambda: _loaded_config or {},
    )

    # Initialize skill system and apply runtime skills
    skill_store = SkillStore(db_path=".autoagent/core_skills.db")
    skill_runtime = SkillRuntime(store=skill_store)

    # Check if config has skill references and apply them
    config_with_skills = _loaded_config or {}
    skill_refs = config_with_skills.get("metadata", {}).get("skill_refs", [])
    if skill_refs:
        try:
            skills = skill_runtime.load_skills(skill_refs)
            config_with_skills = skill_runtime.apply_to_config(skills, config_with_skills)
        except Exception as e:
            # Log error but continue with config without skills
            print(f"Warning: Failed to load skills: {e}")

    validated = validate_config(config_with_skills)
    agent = create_root_agent(validated)

    _session_service = InMemorySessionService()
    _runner = Runner(
        agent=agent,
        app_name=_app_name,
        session_service=_session_service,
    )


@app.get("/health")
async def health() -> dict:
    """Basic liveness/readiness endpoint."""
    return {
        "status": "ok",
        "agent_loaded": _runner is not None,
        "dashboard_ready": _dashboard is not None,
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Serve the AutoAgent dark-mode dashboard shell."""
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "AutoAgent VNext Dashboard",
        },
    )


@app.get("/api/health")
async def api_health() -> dict:
    """Return current health metrics and trend sparkline data."""
    return _require_dashboard().health_payload()


@app.get("/api/history")
async def api_history() -> dict:
    """Return optimization attempt history and config diffs."""
    return _require_dashboard().history_payload()


@app.get("/api/config")
async def api_config() -> dict:
    """Return active config YAML, version history, and canary status."""
    return _require_dashboard().config_payload()


@app.get("/api/evals")
async def api_evals() -> dict:
    """Return latest eval summary and case-level details."""
    return _require_dashboard().evals_payload()


@app.get("/api/conversations")
async def api_conversations() -> dict:
    """Return recent conversations and expandable transcript details."""
    return _require_dashboard().conversations_payload()


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Run one user message through ADK and return the assistant response."""
    if _runner is None or _session_service is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    session_id = request.session_id or str(uuid.uuid4())

    # Ensure session exists
    session = await _session_service.get_session(
        app_name=_app_name, user_id=_user_id, session_id=session_id
    )
    if session is None:
        await _session_service.create_session(
            app_name=_app_name, user_id=_user_id, session_id=session_id
        )

    # Build user content
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=request.message)],
    )

    start = time.monotonic()
    response_parts: list[str] = []

    try:
        async for event in _runner.run_async(
            user_id=_user_id,
            session_id=session_id,
            new_message=content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        response_parts.append(part.text)
    except Exception as exc:
        if _store is not None:
            log_conversation(
                store=_store,
                session_id=session_id,
                user_message=request.message,
                agent_response="",
                tool_calls=[],
                latency_ms=(time.monotonic() - start) * 1000,
                token_count=0,
                specialist_used="",
                config_version=_active_config_version(),
                error=str(exc),
            )
        raise HTTPException(status_code=500, detail="Agent execution failed") from exc

    response_text = (
        "\n".join(response_parts)
        if response_parts
        else "I'm sorry, I couldn't generate a response."
    )
    latency_ms = (time.monotonic() - start) * 1000
    estimated_tokens = max(1, int(len(response_text.split()) * 1.3))

    if _store is not None:
        log_conversation(
            store=_store,
            session_id=session_id,
            user_message=request.message,
            agent_response=response_text,
            tool_calls=[],
            latency_ms=latency_ms,
            token_count=estimated_tokens,
            specialist_used="",
            config_version=_active_config_version(),
        )

    return ChatResponse(response=response_text, session_id=session_id)
