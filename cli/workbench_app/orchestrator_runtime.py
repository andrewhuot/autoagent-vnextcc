"""One-stop constructor for the Phase-1→Phase-7 runtime stack.

The REPL, ``agentlab print``, and API callers all want the same wiring:

* :class:`PermissionManager` with optional plan-workflow binding.
* :class:`ToolRegistry` (default built-ins plus optional MCP bridge).
* :class:`SkillRegistry` (workspace + user-home disk loader).
* :class:`TranscriptRewindManager` (session-scoped transcript rewind).
* :class:`BackgroundTaskRegistry` (subagent panel).
* :class:`HookRegistry` (hooks from ``settings.json``).
* :class:`LLMOrchestrator` wrapping all of the above, ready to accept
  :meth:`~LLMOrchestrator.run_turn` calls.

Duplicating this setup at every call site would be a reliability bug
waiting to happen — a missing subsystem would silently disable the
feature at runtime. :func:`build_workbench_runtime` centralises it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from cli.hooks import HookRegistry, load_hook_registry
from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.types import ModelClient
from cli.permissions import PermissionManager, load_workspace_settings
from cli.sessions import Session, SessionStore
from cli.tools.base import ToolError
from cli.tools.registry import ToolRegistry, default_registry
from cli.tools.skill_tool import (
    ORCHESTRATOR_FACTORY_KEY as SKILL_ORCHESTRATOR_FACTORY_KEY,
    SKILL_REGISTRY_KEY,
)
from cli.tools.exit_plan_mode import PLAN_WORKFLOW_KEY
from cli.user_skills.registry import SkillRegistry, default_skill_store
from cli.workbench_app.agentlab_tools import register_agentlab_tools
from cli.workbench_app.background_panel import BackgroundTaskRegistry
from cli.workbench_app.conversation_bridge import ConversationBridge
from cli.workbench_app.conversation_store import ConversationStore
from cli.workbench_app.permission_preset import apply_agentlab_defaults
from cli.workbench_app.plan_mode import PlanStore, PlanWorkflow
from cli.workbench_app.session_state import WorkbenchSession
from cli.workbench_app.system_prompt import build_system_prompt
from cli.workbench_app.tool_registry import build_default_registry as build_prompt_registry
from cli.workbench_app.transcript_checkpoint import (
    TranscriptCheckpointStore,
    TranscriptRewindManager,
)


@dataclass
class WorkbenchRuntime:
    """Bundle of live subsystems plus the orchestrator.

    Callers read the fields to publish meta on :class:`SlashContext` so
    slash handlers see the same live state the orchestrator is using."""

    orchestrator: LLMOrchestrator
    tool_registry: ToolRegistry
    permission_manager: PermissionManager
    hook_registry: HookRegistry
    skill_registry: SkillRegistry
    plan_workflow: PlanWorkflow
    transcript_rewind: TranscriptRewindManager
    background_tasks: BackgroundTaskRegistry
    session: Session
    session_store: SessionStore
    model: ModelClient
    conversation_store: ConversationStore
    conversation_bridge: ConversationBridge
    conversation_id: str

    # R7.C.3 — used by ``_run_orchestrator_turn`` to advance the
    # ``cost_ticker_usd`` after each assistant turn. Both default to
    # ``None`` so callers that don't supply a session/model still build
    # cleanly (legacy tests, headless paths).
    workbench_session: WorkbenchSession | None = None
    model_id: str | None = None

    # Optional extras so callers can hand-inspect warnings (skill-load
    # errors, MCP connection problems, etc.) in diagnostics.
    skill_warnings: list[str] = field(default_factory=list)


def build_workbench_runtime(
    *,
    workspace_root: Path,
    model: ModelClient,
    system_prompt: str = "",
    session: Session | None = None,
    session_store: SessionStore | None = None,
    active_model: str = "claude-sonnet-4-5",
    mcp_client_factory: Any | None = None,
    echo: Callable[[str], None] | None = None,
    workbench_session: WorkbenchSession | None = None,
) -> WorkbenchRuntime:
    """Construct every subsystem and hand back a packaged
    :class:`WorkbenchRuntime`.

    ``mcp_client_factory`` is optional; when supplied the MCP bridge
    registers any workspace-configured servers' tools into the registry.
    A missing factory leaves the registry with only bundled tools — safe
    default for environments where the ``mcp`` SDK isn't installed."""
    settings = load_workspace_settings(workspace_root)

    permission_manager = PermissionManager(root=workspace_root)
    # AgentLab risk-aware preset: routes EvalRun / Deploy:* / ImproveRun /
    # ImproveAccept through the ``ask`` gate even when the default mode
    # would auto-allow them. Workspace settings.json rules still win.
    apply_agentlab_defaults(permission_manager)
    hook_registry = load_hook_registry(settings)

    session_store = session_store or SessionStore(workspace_dir=workspace_root)
    session = session or session_store.create(title="orchestrator session")

    plan_store = PlanStore(root=workspace_root)
    plan_workflow = PlanWorkflow(store=plan_store, session_id=session.session_id)
    permission_manager.bind_plan_workflow(plan_workflow)

    transcript_store = TranscriptCheckpointStore(workspace_dir=workspace_root)
    transcript_rewind = TranscriptRewindManager(
        store=transcript_store,
        session_store=session_store,
    )

    skill_store = default_skill_store(
        workspace_root=workspace_root,
        user_home=Path.home(),
    )
    skill_registry = SkillRegistry(skill_store)

    background_tasks = BackgroundTaskRegistry()

    tool_registry = default_registry()
    # Register the 7 AgentLab in-process command adapters. ``default_registry()``
    # returns a process-wide singleton, so a second runtime build (common in
    # tests, and possible when the REPL rebuilds the runtime mid-session)
    # would otherwise raise ``ToolError`` on the duplicate registration.
    # Skip silently if the tools are already present.
    if not tool_registry.has("EvalRun"):
        try:
            register_agentlab_tools(tool_registry)
        except ToolError:
            # Race-safe: another caller registered the tools between the
            # ``has`` check and the call. Treat as success.
            pass
    if mcp_client_factory is not None:
        _register_mcp_tools(workspace_root, mcp_client_factory, tool_registry)

    # Build the lean R7 system prompt unless the caller supplied an
    # explicit override (back-compat for tests + Phase-C callers).
    effective_system_prompt = system_prompt
    if not system_prompt:
        prompt_registry = build_prompt_registry()
        effective_system_prompt = build_system_prompt(
            workspace_name=workspace_root.name,
            agent_card_path=None,
            registry=prompt_registry,
        )

    # Conversation persistence (R7.B.7): SQLite store at
    # ``<workspace>/.agentlab/conversations.db`` plus a ConversationBridge
    # bound to a freshly seeded conversation row. The bridge is opt-in for
    # callers — ``_run_orchestrator_turn`` only mirrors turns when a
    # bundle with a bridge is threaded through.
    conv_db_path = workspace_root / ".agentlab" / "conversations.db"
    conversation_store = ConversationStore(conv_db_path)
    conversation = conversation_store.create_conversation(
        workspace_root=str(workspace_root),
        model=active_model,
    )
    conversation_bridge = ConversationBridge(
        store=conversation_store,
        conversation_id=conversation.id,
    )

    # Factory the SkillTool uses to spin up a nested orchestrator. We
    # share most state but give the nested turn a clean message list
    # so the inner skill doesn't pollute the outer conversation.
    def _nested_factory(
        *,
        system_prompt: str,
        context_extra: dict[str, Any],
    ) -> LLMOrchestrator:
        nested = LLMOrchestrator(
            model=model,
            tool_registry=tool_registry,
            permissions=permission_manager,
            workspace_root=workspace_root,
            session=None,
            session_store=None,
            hook_registry=hook_registry,
            transcript_manager=None,
            system_prompt=system_prompt,
            echo=echo or (lambda _line: None),
        )
        # Stash the skill recursion depth so nested SkillTool invocations
        # see the updated counter. We attach it on the orchestrator's
        # messages list (unused) via a side-channel field — callers
        # reach it through the tool context, not here.
        nested._context_extra_seed = context_extra  # type: ignore[attr-defined]
        return nested

    orchestrator = LLMOrchestrator(
        model=model,
        tool_registry=tool_registry,
        permissions=permission_manager,
        workspace_root=workspace_root,
        session=session,
        session_store=session_store,
        hook_registry=hook_registry,
        transcript_manager=transcript_rewind,
        system_prompt=effective_system_prompt,
        echo=echo or (lambda _line: None),
    )

    # Publish the subsystem handles on the orchestrator's builder seed
    # so _execute_tool sees them via ToolContext.extra.
    orchestrator._tool_extra_seed = _build_tool_extra_seed(  # type: ignore[attr-defined]
        plan_workflow=plan_workflow,
        skill_registry=skill_registry,
        background_tasks=background_tasks,
        nested_factory=_nested_factory,
        active_model=active_model,
    )

    return WorkbenchRuntime(
        orchestrator=orchestrator,
        tool_registry=tool_registry,
        permission_manager=permission_manager,
        hook_registry=hook_registry,
        skill_registry=skill_registry,
        plan_workflow=plan_workflow,
        transcript_rewind=transcript_rewind,
        background_tasks=background_tasks,
        session=session,
        session_store=session_store,
        model=model,
        conversation_store=conversation_store,
        conversation_bridge=conversation_bridge,
        conversation_id=conversation.id,
        workbench_session=workbench_session,
        model_id=active_model,
        skill_warnings=list(skill_store.warnings),
    )


def _build_tool_extra_seed(
    *,
    plan_workflow: PlanWorkflow,
    skill_registry: SkillRegistry,
    background_tasks: BackgroundTaskRegistry,
    nested_factory: Any,
    active_model: str,
) -> dict[str, Any]:
    """Collate the ToolContext.extra payload every tool call receives."""
    return {
        PLAN_WORKFLOW_KEY: plan_workflow,
        SKILL_REGISTRY_KEY: skill_registry,
        SKILL_ORCHESTRATOR_FACTORY_KEY: nested_factory,
        "background_task_registry": background_tasks,
        "active_model": active_model,
    }


def _register_mcp_tools(
    workspace_root: Path,
    client_factory: Any,
    tool_registry: ToolRegistry,
) -> list[str]:
    """Best-effort MCP tool registration — warnings surface but do not block.

    Lives here rather than at the :class:`WorkbenchRuntime` call site so
    the boot sequence stays linear and failures don't ripple into the
    unrelated subsystem constructors above."""
    from cli.tools.mcp_bridge import McpBridge, load_specs_from_workspace

    bridge = McpBridge(client_factory=client_factory)
    specs = load_specs_from_workspace(workspace_root)
    return bridge.register_all(specs, tool_registry)


__all__ = ["WorkbenchRuntime", "build_workbench_runtime"]
