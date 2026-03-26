"""Assistant API routes — conversational AI interface with SSE streaming.

FastAPI endpoints for the AutoAgent Assistant:
- POST /api/assistant/message - Send message, get streaming response (SSE)
- POST /api/assistant/upload - Upload files for processing
- GET /api/assistant/history - Get conversation history
- DELETE /api/assistant/history - Clear conversation
- GET /api/assistant/suggestions - Get contextual suggestions
- POST /api/assistant/action/{action_id} - Execute card action

SSE streaming format:
    event: thinking
    data: {"step": "Analyzing...", "progress": 0.2}

    event: card
    data: {"type": "diagnosis", "data": {...}}

    event: text
    data: {"content": "I found 3 issues..."}

    event: suggestions
    data: {"actions": ["Apply fix", "Show alternatives"]}
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from api.models import (
    AssistantMessageRequest,
    AssistantHistoryItem,
    AssistantHistoryResponse,
    AssistantSuggestionsResponse,
    AssistantActionRequest,
    AssistantActionResponse,
)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


# ---------------------------------------------------------------------------
# Session storage (in-memory for now)
# ---------------------------------------------------------------------------

# Format: {session_id: {"history": [turns], "context": {...}}}
_sessions: dict[str, dict[str, Any]] = {}


def _get_or_create_session(session_id: str | None) -> tuple[str, dict[str, Any]]:
    """Get existing session or create a new one."""
    if session_id and session_id in _sessions:
        return session_id, _sessions[session_id]

    new_id = session_id or str(uuid.uuid4())
    _sessions[new_id] = {
        "history": [],
        "context": {},
        "created_at": asyncio.get_event_loop().time(),
    }
    return new_id, _sessions[new_id]


def _clear_session(session_id: str) -> None:
    """Clear a session from memory."""
    if session_id in _sessions:
        del _sessions[session_id]


# ---------------------------------------------------------------------------
# Mock Orchestrator (placeholder until assistant.orchestrator exists)
# ---------------------------------------------------------------------------

class MockOrchestrator:
    """Mock assistant orchestrator for development.

    Replace with real assistant.orchestrator.AssistantOrchestrator when available.
    """

    async def handle_message(
        self,
        message: str,
        session_context: dict[str, Any],
        app_state: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Process a user message and yield response events.

        Args:
            message: User message text
            session_context: Session conversation context
            app_state: FastAPI app.state with access to stores and services

        Yields:
            Event dictionaries with 'event' and 'data' keys for SSE
        """
        # Simulate thinking
        yield {
            "event": "thinking",
            "data": {"step": "Processing your message...", "progress": 0.1}
        }
        await asyncio.sleep(0.3)

        # Classify intent (mock)
        message_lower = message.lower()

        if "build" in message_lower or "create" in message_lower:
            yield {
                "event": "thinking",
                "data": {"step": "Analyzing requirements...", "progress": 0.3}
            }
            await asyncio.sleep(0.5)

            yield {
                "event": "card",
                "data": {
                    "type": "agent_preview",
                    "data": {
                        "agent_name": "Customer Support Agent",
                        "specialists": 3,
                        "routing_rules": 12,
                        "estimated_coverage": 87.5,
                    }
                }
            }

            yield {
                "event": "text",
                "data": {
                    "content": "I've designed a 3-specialist agent based on your requirements. "
                               "It covers approximately 88% of common customer support scenarios."
                }
            }

        elif "fix" in message_lower or "diagnose" in message_lower or "why" in message_lower:
            yield {
                "event": "thinking",
                "data": {"step": "Running diagnosis...", "progress": 0.3}
            }
            await asyncio.sleep(0.5)

            yield {
                "event": "card",
                "data": {
                    "type": "diagnosis",
                    "data": {
                        "root_cause": "Routing error",
                        "description": "40% of billing questions are routed to tech_support",
                        "impact_score": 0.82,
                        "affected_conversations": 156,
                        "trend": "increasing"
                    }
                }
            }

            yield {
                "event": "text",
                "data": {
                    "content": "I found the issue: billing questions are being misrouted to the tech support team. "
                               "This affects 156 conversations. I can fix this by updating the routing rules."
                }
            }

            yield {
                "event": "card",
                "data": {
                    "type": "diff",
                    "data": {
                        "section": "routing.keywords",
                        "before": "['tech', 'computer', 'login']",
                        "after": "['tech', 'computer', 'login', 'invoice', 'refund', 'payment', 'charge', 'billing']",
                        "risk_level": "low"
                    }
                }
            }

        elif "explore" in message_lower or "show" in message_lower or "what" in message_lower:
            yield {
                "event": "thinking",
                "data": {"step": "Searching conversations...", "progress": 0.3}
            }
            await asyncio.sleep(0.5)

            yield {
                "event": "thinking",
                "data": {"step": "Clustering by root cause...", "progress": 0.6}
            }
            await asyncio.sleep(0.4)

            yield {
                "event": "text",
                "data": {
                    "content": "I analyzed 2,340 recent conversations. Found 3 main failure patterns:"
                }
            }

            for i, (title, count, impact) in enumerate([
                ("Routing errors", 156, 0.82),
                ("Tool timeout issues", 89, 0.64),
                ("Unclear responses", 43, 0.31),
            ], 1):
                yield {
                    "event": "card",
                    "data": {
                        "type": "cluster",
                        "data": {
                            "rank": i,
                            "title": title,
                            "count": count,
                            "impact": impact,
                            "trend": "increasing" if i == 1 else "stable"
                        }
                    }
                }
                await asyncio.sleep(0.2)

        else:
            # General response
            yield {
                "event": "text",
                "data": {
                    "content": "I can help you build, optimize, and debug AI agents. "
                               "Try asking me to: build an agent, diagnose issues, fix problems, or explore conversations."
                }
            }

        # Always end with suggestions
        suggestions = self._get_suggestions(message_lower, session_context)
        yield {
            "event": "suggestions",
            "data": {"actions": suggestions}
        }

    def _get_suggestions(self, message_lower: str, context: dict[str, Any]) -> list[str]:
        """Get contextual suggestions based on message and context."""
        if "build" in message_lower:
            return [
                "Looks good, save it",
                "Add more specialists",
                "Show routing logic",
                "Run baseline eval"
            ]
        elif "fix" in message_lower or "diagnose" in message_lower:
            return [
                "Apply fix",
                "Show alternatives",
                "Explain more",
                "Skip this issue"
            ]
        elif "explore" in message_lower:
            return [
                "Fix the top issue",
                "Show example conversations",
                "Compare to last week",
                "Next cluster"
            ]
        else:
            return [
                "Build a new agent",
                "Optimize my agent",
                "Explore conversations",
                "Show agent health"
            ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/message")
async def send_message(
    request: Request,
    body: AssistantMessageRequest,
) -> StreamingResponse:
    """Send a message to the assistant and receive streaming SSE response.

    The assistant processes the message, classifies intent, routes to appropriate
    modules, and streams back events (thinking, cards, text, suggestions).

    Args:
        request: FastAPI request with app.state access
        body: Message request with text and optional session_id

    Returns:
        StreamingResponse with text/event-stream content type

    SSE Event Types:
        - thinking: Progress updates {"step": str, "progress": float}
        - card: Rich data cards {"type": str, "data": {...}}
        - text: Assistant text response {"content": str}
        - suggestions: Suggested actions {"actions": [str, ...]}
        - error: Error message {"message": str}
    """
    session_id, session_data = _get_or_create_session(body.session_id)

    # Update session context with request context
    session_data["context"].update(body.context)

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for the assistant's response."""
        try:
            # Get orchestrator (mock for now)
            # TODO: Replace with real AssistantOrchestrator when available
            # orchestrator = getattr(request.app.state, "assistant_orchestrator", None)
            # if orchestrator is None:
            #     orchestrator = AssistantOrchestrator(...)
            #     request.app.state.assistant_orchestrator = orchestrator

            orchestrator = MockOrchestrator()

            # Stream events from orchestrator
            events = []
            async for event in orchestrator.handle_message(
                message=body.message,
                session_context=session_data["context"],
                app_state=request.app.state,
            ):
                event_type = event.get("event", "text")
                event_data = event.get("data", {})

                # Store event for history
                events.append(event)

                # Format as SSE
                yield f"event: {event_type}\n"
                yield f"data: {json.dumps(event_data)}\n\n"

            # Store turn in history
            turn = {
                "turn_id": str(uuid.uuid4()),
                "user_message": body.message,
                "assistant_response": events,
                "timestamp": asyncio.get_event_loop().time(),
                "session_id": session_id,
            }
            session_data["history"].append(turn)

        except Exception as exc:
            # Send error event
            error_data = {
                "message": f"Error processing message: {str(exc)}",
                "type": "internal_error"
            }
            yield f"event: error\n"
            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "X-Session-ID": session_id,  # Return session ID in header
        }
    )


@router.post("/upload")
async def upload_files(
    request: Request,
    files: list[UploadFile] = File(...),
    session_id: str | None = Form(None),
    description: str | None = Form(None),
) -> dict[str, Any]:
    """Upload files for assistant processing.

    Supports:
    - Transcripts: CSV, JSON, JSONL, ZIP of text files
    - Documents: PDF, DOCX, TXT (SOPs, playbooks, knowledge bases)
    - Audio: MP3, WAV, M4A (transcribed via Whisper)
    - Agent configs: YAML, JSON (existing agent definitions)

    Args:
        request: FastAPI request
        files: List of uploaded files
        session_id: Optional session ID for conversation continuity
        description: Optional description of the files

    Returns:
        Upload status with file IDs and processing info

    Raises:
        HTTPException: If files are invalid or processing fails
    """
    session_id, session_data = _get_or_create_session(session_id)

    # Validate file types
    allowed_extensions = {
        ".csv", ".json", ".jsonl", ".zip",
        ".pdf", ".docx", ".txt",
        ".mp3", ".wav", ".m4a",
        ".yaml", ".yml"
    }

    uploaded_files = []
    for file in files:
        filename = file.filename or "unknown"
        extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {filename}. Allowed: {', '.join(allowed_extensions)}"
            )

        # Read file content
        content = await file.read()
        file_size = len(content)

        # Limit file size (50MB max)
        max_size = 50 * 1024 * 1024
        if file_size > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {filename} ({file_size} bytes). Max: {max_size} bytes"
            )

        file_id = str(uuid.uuid4())
        uploaded_files.append({
            "file_id": file_id,
            "filename": filename,
            "extension": extension,
            "size_bytes": file_size,
            "content_type": file.content_type,
        })

        # Store in session context for processing
        # TODO: Store files properly (filesystem, S3, etc.)
        if "uploaded_files" not in session_data["context"]:
            session_data["context"]["uploaded_files"] = []
        session_data["context"]["uploaded_files"].append({
            "file_id": file_id,
            "filename": filename,
            "size_bytes": file_size,
            "description": description,
        })

    return {
        "success": True,
        "session_id": session_id,
        "files": uploaded_files,
        "total_files": len(uploaded_files),
        "message": f"Uploaded {len(uploaded_files)} file(s). Use the message endpoint to process them.",
    }


@router.get("/history")
async def get_history(
    request: Request,
    session_id: str,
) -> AssistantHistoryResponse:
    """Get conversation history for a session.

    Args:
        request: FastAPI request
        session_id: Session identifier

    Returns:
        Full conversation history with all turns

    Raises:
        HTTPException: If session not found
    """
    if session_id not in _sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}"
        )

    session_data = _sessions[session_id]
    turns = [
        AssistantHistoryItem(**turn)
        for turn in session_data["history"]
    ]

    return AssistantHistoryResponse(
        session_id=session_id,
        turns=turns,
        total=len(turns),
    )


@router.delete("/history")
async def clear_history(
    request: Request,
    session_id: str,
) -> dict[str, Any]:
    """Clear conversation history for a session.

    Args:
        request: FastAPI request
        session_id: Session identifier

    Returns:
        Success confirmation

    Raises:
        HTTPException: If session not found
    """
    if session_id not in _sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}"
        )

    _clear_session(session_id)

    return {
        "success": True,
        "session_id": session_id,
        "message": "Conversation history cleared",
    }


@router.get("/suggestions")
async def get_suggestions(
    request: Request,
    session_id: str,
) -> AssistantSuggestionsResponse:
    """Get contextual suggestions for the next action.

    Suggestions are based on current conversation state, recent messages,
    and available actions.

    Args:
        request: FastAPI request
        session_id: Session identifier

    Returns:
        List of suggested messages and quick actions

    Raises:
        HTTPException: If session not found
    """
    if session_id not in _sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}"
        )

    session_data = _sessions[session_id]

    # Get suggestions based on recent history and context
    # TODO: Make this smarter based on actual conversation state
    suggestions = [
        "Build a new agent",
        "Optimize my agent",
        "Diagnose issues",
        "Explore conversations",
        "Show agent health",
    ]

    quick_actions = [
        {"label": "Build Agent", "action": "build", "icon": "🏗️"},
        {"label": "Optimize", "action": "optimize", "icon": "🔧"},
        {"label": "Explore", "action": "explore", "icon": "🔍"},
        {"label": "Help", "action": "help", "icon": "❓"},
    ]

    return AssistantSuggestionsResponse(
        session_id=session_id,
        suggestions=suggestions,
        quick_actions=quick_actions,
    )


@router.post("/action/{action_id}")
async def execute_action(
    request: Request,
    action_id: str,
    body: AssistantActionRequest,
) -> AssistantActionResponse:
    """Execute a card action (approve fix, deploy, etc.).

    Card actions are interactive elements in the assistant's rich cards.
    Examples:
    - approve_fix: Apply a proposed configuration change
    - deploy: Deploy a tested change to production
    - rollback: Revert a deployed change
    - show_examples: Display example conversations
    - run_eval: Run evaluation on current config

    Args:
        request: FastAPI request
        action_id: Action identifier (e.g., "approve_fix", "deploy")
        body: Action request with session_id and action-specific data

    Returns:
        Action execution result

    Raises:
        HTTPException: If session not found or action fails
    """
    if body.session_id not in _sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {body.session_id}"
        )

    session_data = _sessions[body.session_id]

    # Route to appropriate handler based on action_id
    # TODO: Implement actual action handlers

    if action_id == "approve_fix":
        # Apply proposed configuration change
        result = {
            "applied": True,
            "description": "Applied routing rule fix",
            "score_before": 0.72,
            "score_after": 0.81,
        }
        message = "Fix applied successfully. Running evaluation..."

    elif action_id == "deploy":
        # Deploy change to production
        result = {
            "deployed": True,
            "version": "v1.2.3",
            "canary_progress": 0.0,
        }
        message = "Deployment started. Monitoring canary rollout..."

    elif action_id == "rollback":
        # Rollback deployed change
        result = {
            "rolled_back": True,
            "reverted_to": "v1.2.2",
        }
        message = "Rolled back to previous version"

    elif action_id == "show_examples":
        # Fetch example conversations
        result = {
            "examples": [
                {"conversation_id": "conv_123", "snippet": "User: I need a refund..."},
                {"conversation_id": "conv_456", "snippet": "User: Where's my order?..."},
            ]
        }
        message = "Showing example conversations"

    elif action_id == "run_eval":
        # Trigger evaluation run
        result = {
            "eval_id": str(uuid.uuid4()),
            "status": "running",
        }
        message = "Started evaluation run"

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action: {action_id}"
        )

    # Record action in session history
    session_data["context"]["last_action"] = {
        "action_id": action_id,
        "timestamp": asyncio.get_event_loop().time(),
        "result": result,
    }

    return AssistantActionResponse(
        success=True,
        action_id=action_id,
        result=result,
        message=message,
    )
