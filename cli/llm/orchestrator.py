"""Turn-loop orchestrator.

:class:`LLMOrchestrator` composes every Phase 1–6 primitive into a
single ``run_turn()`` call:

1. Appends the user prompt to the session transcript (and fires any
   auto-checkpoint).
2. Calls the model with the full conversation + tool schema.
3. Streams the assistant text through :class:`StreamingMarkdownRenderer`.
4. For each tool_use block, delegates to
   :func:`cli.tools.executor.execute_tool_call` — which consults
   permissions, skill overlays, plan-mode restrictions, and hooks — and
   feeds the tool_result back to the model.
5. Stops when the model emits a plain end_turn response, when we hit
   ``max_tool_loops``, or when a hook denial aborts the turn.

Every intermediate action produces structured output in
:class:`OrchestratorResult` so the REPL, ``--print`` mode, and the API
server can all consume the same record.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from cli.llm.types import (
    AssistantTextBlock,
    AssistantToolUseBlock,
    ModelClient,
    ModelResponse,
    OrchestratorResult,
    TurnMessage,
)
from cli.permissions import PermissionManager
from cli.sessions import Session, SessionStore
from cli.tools.base import ToolContext
from cli.tools.executor import ToolExecution, execute_tool_call
from cli.tools.registry import ToolRegistry
from cli.workbench_app.markdown_stream import StreamingMarkdownRenderer


DEFAULT_MAX_TOOL_LOOPS = 12
"""Cap on consecutive tool-use rounds per turn.

The loop terminates when the model stops requesting tools *or* this cap
is hit. 12 is chosen empirically — enough for a reasonable chain of
read/edit/verify calls, low enough that a runaway loop surfaces quickly."""


@dataclass
class LLMOrchestrator:
    """Composes model + tools + permissions + hooks + sessions.

    The orchestrator is intentionally a dataclass rather than a function
    so the REPL can build it once and reuse across turns, and tests can
    swap any collaborator with a stub. All collaborators are optional at
    construction time except the model client and tool registry — a
    workbench without hooks or sessions is still a valid target."""

    model: ModelClient
    tool_registry: ToolRegistry
    permissions: PermissionManager
    workspace_root: Any
    """Absolute path to the workspace root, threaded into
    :class:`ToolContext` for every tool call. Accepts any ``Path`` or
    string the registered tools can resolve against."""

    session: Session | None = None
    session_store: SessionStore | None = None
    hook_registry: Any | None = None
    transcript_manager: Any | None = None
    """Optional :class:`cli.workbench_app.transcript_checkpoint.TranscriptRewindManager`
    — when supplied, an auto-checkpoint is captured after each
    assistant turn so ``/transcript-rewind`` picks them up."""

    system_prompt: str = ""
    max_tool_loops: int = DEFAULT_MAX_TOOL_LOOPS
    dialog_runner: Any | None = None
    """Passed through to :func:`execute_tool_call`. The default (``None``)
    uses the interactive prompt dialog."""

    echo: Callable[[str], None] = print
    """Line sink for streaming assistant output. Tests point this at a
    list; the REPL wires :class:`click.echo`."""

    styler: Any | None = None
    """Optional markdown-stream styler — tests pass a tagger to assert
    mode transitions."""

    # Accumulated conversation across turns (a list to preserve order).
    messages: list[TurnMessage] = field(default_factory=list)

    # ------------------------------------------------------------------ API

    def run_turn(self, user_prompt: str) -> OrchestratorResult:
        """Run one end-to-end user turn.

        Blocks until the model emits a non-tool-use response (or the
        tool-loop cap fires). All side effects — tool calls, session
        writes, checkpoint snapshots — happen synchronously; the returned
        :class:`OrchestratorResult` is the canonical log of what
        occurred."""
        user_message = TurnMessage(role="user", content=user_prompt)
        self.messages.append(user_message)
        if self.session is not None:
            self._append_session_entry(role="user", content=user_prompt)

        renderer = StreamingMarkdownRenderer(echo=self.echo, styler=self.styler)
        executions: list[ToolExecution] = []
        aggregated_usage: dict[str, int] = {}
        stop_reason = "end_turn"
        final_text_parts: list[str] = []

        # ``max_tool_loops`` caps the number of *tool-bearing* iterations.
        # A follow-up non-tool response still counts as one iteration so
        # the model can summarise after the cap is reached — but if the
        # model keeps asking for tools past the limit we hard-stop.
        tool_iterations = 0
        while True:
            response = self.model.complete(
                system_prompt=self.system_prompt,
                messages=list(self.messages),
                tools=self.tool_registry.to_schema(),
            )
            _merge_usage(aggregated_usage, response.usage)

            # Render any text blocks immediately so the user sees prose
            # before the tool_use panel appears.
            for block in response.text_blocks():
                text = block.text or ""
                final_text_parts.append(text)
                renderer.feed(text if text.endswith("\n") else text + "\n")

            tool_uses = response.tool_uses()
            self.messages.append(
                TurnMessage(role="assistant", content=response.blocks)
            )

            if not tool_uses:
                stop_reason = response.stop_reason or "end_turn"
                break

            if tool_iterations >= self.max_tool_loops:
                # Already at the cap — do not execute another tool batch.
                stop_reason = "max_tool_loops"
                break

            tool_iterations += 1

            # Execute tool calls and append a user-side message with the
            # tool_result blocks so the next model call can consume them.
            tool_results: list[dict[str, Any]] = []
            for tool_use in tool_uses:
                execution = self._execute_tool(tool_use)
                executions.append(execution)
                tool_results.append(_result_to_block(tool_use.id, execution))

            self.messages.append(TurnMessage(role="user", content=tool_results))

        renderer.finalize()
        assistant_text = "".join(final_text_parts)

        if self.session is not None and assistant_text:
            self._append_session_entry(role="assistant", content=assistant_text)

        if self.transcript_manager is not None and self.session is not None:
            try:
                self.transcript_manager.maybe_snapshot_after_assistant_turn(self.session)
            except Exception:  # pragma: no cover - best-effort snapshotting
                pass

        if self.hook_registry is not None:
            self._fire_stop_hook(executions)

        return OrchestratorResult(
            assistant_text=assistant_text,
            tool_executions=executions,
            stop_reason=stop_reason,
            usage=aggregated_usage,
            metadata={"loops": tool_iterations},
        )

    # ------------------------------------------------------------------ helpers

    def _execute_tool(self, tool_use: AssistantToolUseBlock) -> ToolExecution:
        context = ToolContext(
            workspace_root=self.workspace_root,
            session_id=self.session.session_id if self.session else None,
            extra=self._build_tool_extra(),
        )
        return execute_tool_call(
            tool_use.name,
            dict(tool_use.input or {}),
            registry=self.tool_registry,
            permissions=self.permissions,
            context=context,
            dialog_runner=self.dialog_runner,
            hook_registry=self.hook_registry,
        )

    def _build_tool_extra(self) -> dict[str, Any]:
        """Stamp the tool context with publishable session state.

        Tools like :class:`AgentSpawnTool` read the background registry
        off ``ToolContext.extra``; orchestrators attach it here so every
        tool call in the turn sees a consistent view."""
        extra: dict[str, Any] = {}
        if self.session is not None:
            extra["session_id"] = self.session.session_id
        return extra

    def _append_session_entry(self, *, role: str, content: str) -> None:
        assert self.session is not None
        if self.session_store is not None:
            self.session_store.append_entry(self.session, role, content)
        else:
            # No store bound — update the in-memory transcript directly so
            # the orchestrator still feeds accurate context to the model.
            from cli.sessions import SessionEntry
            import time

            self.session.transcript.append(
                SessionEntry(role=role, content=content, timestamp=time.time())
            )

    def _fire_stop_hook(self, executions: list[ToolExecution]) -> None:
        """Fire the ``Stop`` lifecycle hook at turn end.

        Best-effort: failures never bubble up — the turn has already
        succeeded, and a broken stop hook must not turn that into a
        user-visible error."""
        try:
            from cli.hooks import HookEvent

            self.hook_registry.fire(
                HookEvent.STOP,
                tool_name="",
                payload={
                    "executions": [execution.tool_name for execution in executions],
                    "session_id": self.session.session_id if self.session else None,
                },
            )
        except Exception:  # pragma: no cover - best-effort hook
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge_usage(acc: dict[str, int], incoming: dict[str, int]) -> None:
    for key, value in (incoming or {}).items():
        try:
            acc[key] = acc.get(key, 0) + int(value)
        except (TypeError, ValueError):
            continue


def _result_to_block(tool_use_id: str, execution: ToolExecution) -> dict[str, Any]:
    """Build the ``tool_result`` block the next model call consumes.

    Claude's API expects ``type: tool_result`` with ``tool_use_id`` and a
    string/content payload. We pack the execution result's ``content``
    directly and flag errors via ``is_error`` so the model sees the
    failure signal the same way Anthropic's API exposes it."""
    result = execution.result
    content = result.content if result is not None else ""
    is_error = bool(result is None or not result.ok)
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": str(content),
        "is_error": is_error,
    }


def synthetic_tool_use_id() -> str:
    """Helper for adapters that don't supply their own ids. Provides a
    stable, URL-safe identifier per tool call."""
    return f"toolu_{uuid.uuid4().hex[:16]}"


__all__ = ["DEFAULT_MAX_TOOL_LOOPS", "LLMOrchestrator", "synthetic_tool_use_id"]
