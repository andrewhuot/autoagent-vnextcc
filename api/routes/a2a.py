"""FastAPI router for A2A (Agent-to-Agent) protocol endpoints.

Exposes:
    GET  /.well-known/agent-card.json     — agent discovery
    POST /api/a2a/tasks/send              — submit a task (JSON-RPC style)
    GET  /api/a2a/tasks/{task_id}         — get task status
    POST /api/a2a/tasks/{task_id}/cancel  — cancel a task
    GET  /api/a2a/agents                  — list registered agents
    POST /api/a2a/discover                — proxy-discover an external agent
"""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from a2a.agent_card import AgentCardGenerator
from a2a.client import A2AClient
from a2a.server import A2AServer
from a2a.task import TaskManager
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, TaskStatus

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["a2a"])

# ---------------------------------------------------------------------------
# Shared singleton helpers (lazily initialised per app instance)
# ---------------------------------------------------------------------------

_card_generator = AgentCardGenerator()
_a2a_client = A2AClient(timeout_seconds=30)


def _get_a2a_server(request: Request) -> A2AServer:
    """Return (or lazily create) the A2AServer stored on app.state."""
    if not hasattr(request.app.state, "a2a_server"):
        # Build from registered agents if available, else empty
        agents: dict[str, dict[str, Any]] = {}
        if hasattr(request.app.state, "agents"):
            agents = dict(request.app.state.agents)
        request.app.state.a2a_server = A2AServer(agents=agents)
    return request.app.state.a2a_server


def _get_base_url(request: Request) -> str:
    """Derive the public base URL from the incoming request."""
    base = os.environ.get("A2A_BASE_URL", "")
    if base:
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class TaskSendRequest(BaseModel):
    """JSON-RPC-style task submission request."""

    jsonrpc: str = "2.0"
    method: str = "tasks/send"
    params: dict[str, Any] = {}
    id: Optional[str] = None


class DiscoverRequest(BaseModel):
    """Request body for proxied external agent discovery."""

    url: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/.well-known/agent-card.json", include_in_schema=True)
async def get_agent_card(request: Request) -> JSONResponse:
    """Serve the agent card for this AutoAgent instance.

    The card is generated from environment / app.state configuration on each
    call so it always reflects the current set of registered agents.
    """
    base_url = _get_base_url(request)

    agent_name = os.environ.get("A2A_AGENT_NAME", "AutoAgent VNextCC")
    agent_description = os.environ.get(
        "A2A_AGENT_DESCRIPTION",
        "AutoAgent VNextCC — CI/CD for AI agents. "
        "Experiment-driven optimization, evaluation, and deployment.",
    )
    agent_version = os.environ.get("A2A_AGENT_VERSION", "1.0")

    # Collect skills from registered agents when available
    skills: list[AgentSkill] = []
    if hasattr(request.app.state, "agents"):
        for name, cfg in request.app.state.agents.items():
            safe_id = name.lower().replace(" ", "_")
            skills.append(
                AgentSkill(
                    id=safe_id,
                    name=name,
                    description=cfg.get("description", f"Invoke the {name} agent."),
                    tags=cfg.get("tags", [safe_id]),
                    examples=cfg.get("examples", []),
                )
            )

    if not skills:
        # Default skills when no agents are registered
        skills = [
            AgentSkill(
                id="optimize",
                name="Optimize Agent",
                description="Run an optimization cycle to improve agent performance.",
                tags=["optimization", "experiments"],
                examples=["Run the next optimization cycle"],
            ),
            AgentSkill(
                id="evaluate",
                name="Evaluate Agent",
                description="Execute an evaluation suite and return graded results.",
                tags=["eval", "grading"],
                examples=["Run the contract_regression eval suite"],
            ),
        ]

    agent_config: dict[str, Any] = {
        "description": agent_description,
        "version": agent_version,
        "capabilities": {
            "streaming": True,
            "push_notifications": False,
            "state_transition_history": True,
        },
        "input_modes": ["text"],
        "output_modes": ["text"],
        "metadata": {"platform": "autoagent-vnextcc"},
    }

    card = _card_generator.generate_card(
        agent_name=agent_name,
        agent_config=agent_config,
        base_url=base_url,
        skills=skills,
    )
    return JSONResponse(content=_card_generator.card_to_json(card))


@router.post("/api/a2a/tasks/send")
async def send_task(body: TaskSendRequest, request: Request) -> JSONResponse:
    """Submit a new task to a registered agent (JSON-RPC ``tasks/send``).

    Request body follows JSON-RPC 2.0::

        {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "params": {
                "message": {"role": "user", "parts": [{"type": "text", "text": "..."}]},
                "agentName": "optional_agent_name",
                "skillId": "optional_skill_id"
            },
            "id": "req-1"
        }
    """
    server = _get_a2a_server(request)
    try:
        task = server.handle_task_send(body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "result": task.to_dict(),
            "id": body.id,
        }
    )


@router.get("/api/a2a/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> JSONResponse:
    """Retrieve the current state of a task by ID."""
    server = _get_a2a_server(request)
    try:
        task = server.handle_task_get(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(content=task.to_dict())


@router.post("/api/a2a/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> JSONResponse:
    """Cancel a task that has not yet reached a terminal state."""
    server = _get_a2a_server(request)
    try:
        task = server.handle_task_cancel(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(content=task.to_dict())


@router.get("/api/a2a/agents")
async def list_agents(request: Request) -> JSONResponse:
    """List the names of all agents registered with this A2A server."""
    server = _get_a2a_server(request)
    return JSONResponse(content={"agents": server.list_agents()})


@router.post("/api/a2a/discover")
async def discover_external_agent(body: DiscoverRequest) -> JSONResponse:
    """Fetch and return the agent card of an external A2A agent.

    Acts as a server-side proxy so browser clients can avoid CORS issues
    when discovering agents on other origins.

    Request body::

        {"url": "https://other-agent.example.com"}
    """
    try:
        card = _a2a_client.discover(body.url)
    except (ConnectionError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to discover agent at {body.url!r}: {exc}",
        ) from exc
    return JSONResponse(content=card.to_dict())
