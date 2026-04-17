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

from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ThinkingDelta,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
    UsageDelta,
    collect_stream,
    events_from_model_response,
)
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
        executions: list[ToolExecution] = []
        aggregated_usage: dict[str, int] = {}
        stop_reason = "end_turn"
        hook_messages: list[str] = []

        before_query = self._fire_turn_hook(
            "before_query",
            {
                "prompt": user_prompt,
                "session_id": self.session.session_id if self.session else None,
            },
        )
        if before_query is not None:
            hook_messages.extend(before_query.messages)
            if before_query.verdict.value == "deny":
                stop_reason = "hook_deny"
                assistant_text = "\n".join(before_query.messages)
                session_outcome = self._fire_session_end_hook(
                    stop_reason=stop_reason,
                    assistant_text=assistant_text,
                    executions=executions,
                )
                if session_outcome is not None:
                    hook_messages.extend(session_outcome.messages)
                return OrchestratorResult(
                    assistant_text=assistant_text,
                    tool_executions=[],
                    stop_reason=stop_reason,
                    usage=aggregated_usage,
                    metadata={"loops": 0, "hook_messages": list(hook_messages)},
                )

        user_message = TurnMessage(role="user", content=user_prompt)
        self.messages.append(user_message)
        if self.session is not None:
            self._append_session_entry(role="user", content=user_prompt)

        renderer = StreamingMarkdownRenderer(echo=self.echo, styler=self.styler)
        final_text_parts: list[str] = []

        # ``max_tool_loops`` caps the number of *tool-bearing* iterations.
        # A follow-up non-tool response still counts as one iteration so
        # the model can summarise after the cap is reached — but if the
        # model keeps asking for tools past the limit we hard-stop.
        tool_iterations = 0
        while True:
            response = self._run_model_turn(renderer, final_text_parts)
            _merge_usage(aggregated_usage, response.usage)

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
            post_fragments: list[str] = []
            for tool_use in tool_uses:
                execution = self._execute_tool(tool_use)
                executions.append(execution)
                tool_results.append(_result_to_block(tool_use.id, execution))
                post_fragments.extend(self._post_tool_prompt_fragments(tool_use.name))

            # Append the post-tool-use prompt fragments as a text block at
            # the end of the tool_result message. This keeps them tied to
            # the tools that triggered them and lets the model take them
            # into account on its next turn.
            if post_fragments:
                tool_results.append(
                    {"type": "text", "text": _render_fragment_block(post_fragments)}
                )

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
            after_query = self._fire_turn_hook(
                "after_query",
                self._turn_lifecycle_payload(
                    stop_reason=stop_reason,
                    assistant_text=assistant_text,
                    executions=executions,
                ),
            )
            if after_query is not None:
                hook_messages.extend(after_query.messages)
            session_outcome = self._fire_session_end_hook(
                stop_reason=stop_reason,
                assistant_text=assistant_text,
                executions=executions,
            )
            if session_outcome is not None:
                hook_messages.extend(session_outcome.messages)

        return OrchestratorResult(
            assistant_text=assistant_text,
            tool_executions=executions,
            stop_reason=stop_reason,
            usage=aggregated_usage,
            metadata=_result_metadata(tool_iterations, hook_messages),
        )

    # ------------------------------------------------------------------ helpers

    def _run_model_turn(
        self,
        renderer: StreamingMarkdownRenderer,
        final_text_parts: list[str],
    ) -> ModelResponse:
        """Call the model and render its output live.

        Uses ``stream()`` when the client implements it — text chunks land
        in the renderer as they arrive so the user sees the model
        thinking. Clients that expose only ``complete()`` still route
        through :func:`events_from_model_response` so the renderer path
        is identical, just non-incremental."""
        tools_schema = self.tool_registry.to_schema()
        effective_system_prompt = self._compose_system_prompt()
        stream_method = getattr(self.model, "stream", None)

        if callable(stream_method):
            events_iter = stream_method(
                system_prompt=effective_system_prompt,
                messages=list(self.messages),
                tools=tools_schema,
            )
        else:
            response = self.model.complete(
                system_prompt=effective_system_prompt,
                messages=list(self.messages),
                tools=tools_schema,
            )
            events_iter = events_from_model_response(response)

        # Fork the event stream: one consumer drives the renderer live,
        # the other collects the final ModelResponse for bookkeeping.
        # Materialising to a list is fine — events are tiny dataclasses
        # and fork-splitting an iterator would add complexity for a gain
        # that doesn't matter at this scale.
        collected_events: list[Any] = []
        pending_text = ""
        for event in events_iter:
            collected_events.append(event)
            if isinstance(event, TextDelta):
                text = event.text or ""
                pending_text += text
                final_text_parts.append(text)
                # Feed the renderer without forcing newlines — the
                # markdown streamer buffers partial lines correctly.
                renderer.feed(text)
            elif isinstance(event, ThinkingDelta):
                # Thinking surfaces only on a dedicated indicator in the
                # transcript chrome; the main stream stays focused on
                # user-visible prose.
                continue
            # Tool-use deltas never render as text — they land in the
            # collected ModelResponse via collect_stream.

        # Ensure any trailing partial line flushes on end-of-turn; the
        # renderer will add one itself at finalize(), but we mimic that
        # here so the collected text ends on a clean boundary.
        if pending_text and not pending_text.endswith("\n"):
            renderer.feed("\n")
            final_text_parts.append("\n")

        return collect_stream(collected_events)

    def _compose_system_prompt(self) -> str:
        """Layer hook-supplied prompt fragments on top of the base prompt.

        Fragments fire at ``PreToolUse`` with an empty tool_name because
        they apply to the upcoming turn as a whole — a future revision
        could narrow by the set of available tools, but in practice
        session-level guidance is the common case. ``Stop`` fragments
        are read separately and woven into post-turn telemetry rather
        than leaking into the next model call."""
        if self.hook_registry is None:
            return self.system_prompt

        fragments_for = getattr(self.hook_registry, "prompt_fragments_for", None)
        if not callable(fragments_for):
            return self.system_prompt

        try:
            from cli.hooks import HookEvent

            fragments = fragments_for(HookEvent.PRE_TOOL_USE)
        except Exception:  # pragma: no cover - hooks must never crash turns
            return self.system_prompt
        if not fragments:
            return self.system_prompt

        appendix = "\n\n".join(fragments)
        base = self.system_prompt.rstrip()
        return (
            f"{base}\n\n## Hook Guidance\n\n{appendix}"
            if base
            else f"## Hook Guidance\n\n{appendix}"
        )

    def _post_tool_prompt_fragments(self, tool_name: str) -> list[str]:
        """Return post-tool-use prompt fragments for ``tool_name``.

        Keeping this in a helper means the main loop stays readable and
        tests can stub the hook registry's output without patching the
        loop itself."""
        if self.hook_registry is None:
            return []

        fragments_for = getattr(self.hook_registry, "prompt_fragments_for", None)
        if not callable(fragments_for):
            return []
        try:
            from cli.hooks import HookEvent

            return fragments_for(HookEvent.POST_TOOL_USE, tool_name=tool_name) or []
        except Exception:  # pragma: no cover - hooks must never crash turns
            return []

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

        Tools like :class:`AgentSpawnTool`, :class:`SkillTool`, and
        :class:`ExitPlanModeTool` read the relevant registries off
        ``ToolContext.extra``; the orchestrator composes the payload
        from a ``_tool_extra_seed`` (set by
        :func:`cli.workbench_app.orchestrator_runtime.build_workbench_runtime`)
        plus any session-local values. Seeds let one wiring site
        centralise publication without every orchestrator caller
        copy-pasting the same dict."""
        seed = getattr(self, "_tool_extra_seed", None)
        extra: dict[str, Any] = dict(seed or {})
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

    def _turn_lifecycle_payload(
        self,
        *,
        stop_reason: str,
        assistant_text: str,
        executions: list[ToolExecution],
    ) -> dict[str, Any]:
        """Build the shared payload for turn-completion lifecycle hooks."""
        execution_names = [execution.tool_name for execution in executions]
        return {
            "stop_reason": stop_reason,
            "assistant_text": assistant_text,
            "executions": execution_names,
            "execution_names": execution_names,
            "session_id": self.session.session_id if self.session else None,
        }

    def _fire_turn_hook(self, event_name: str, payload: dict[str, Any]):
        """Fire a turn-level hook by symbolic name, swallowing hook failures."""
        if self.hook_registry is None:
            return None
        try:
            from cli.hooks import HookEvent

            event = {
                "before_query": HookEvent.BEFORE_QUERY,
                "after_query": HookEvent.AFTER_QUERY,
            }[event_name]
            return self.hook_registry.fire(event, tool_name="", payload=payload)
        except Exception:  # pragma: no cover - hooks must never crash the loop
            return None

    def _fire_session_end_hook(
        self,
        *,
        stop_reason: str,
        assistant_text: str,
        executions: list[ToolExecution],
    ):
        """Fire ``SessionEnd`` plus legacy ``Stop`` hooks when registered.

        ``Stop`` remains a compatibility shim only: fake registries that do
        not expose registered definitions will see the new ``SessionEnd``
        event without an extra legacy call."""
        if self.hook_registry is None:
            return None
        payload = self._turn_lifecycle_payload(
            stop_reason=stop_reason,
            assistant_text=assistant_text,
            executions=executions,
        )
        try:
            from cli.hooks import HookEvent

            outcome = self.hook_registry.fire(
                HookEvent.SESSION_END,
                tool_name="",
                payload=payload,
            )
            if self._has_registered_hooks(HookEvent.STOP):
                self.hook_registry.fire(HookEvent.STOP, tool_name="", payload=payload)
            return outcome
        except Exception:  # pragma: no cover - best-effort hook
            return None

    def _has_registered_hooks(self, event: Any) -> bool:
        """Return whether ``hook_registry`` appears to have hooks for ``event``."""
        registry = self.hook_registry
        hooks_for = getattr(registry, "hooks_for", None)
        if callable(hooks_for):
            try:
                return bool(hooks_for(event, tool_name=""))
            except Exception:
                return False
        definitions = getattr(registry, "definitions", None)
        if isinstance(definitions, dict):
            try:
                return bool(definitions.get(event))
            except Exception:
                return False
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge_usage(acc: dict[str, int], incoming: dict[str, int]) -> None:
    for key, value in (incoming or {}).items():
        try:
            acc[key] = acc.get(key, 0) + int(value)
        except (TypeError, ValueError):
            continue


def _result_metadata(tool_iterations: int, hook_messages: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {"loops": tool_iterations}
    if hook_messages:
        metadata["hook_messages"] = list(hook_messages)
    return metadata


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


def _render_fragment_block(fragments: list[str]) -> str:
    """Format a group of post-tool-use fragments as a visible text block.

    We wrap with a clear header so the model can see these are hook
    guidance rather than tool output — otherwise the model could infer
    the text is part of the tool_result payload and hallucinate semantics
    that aren't there."""
    body = "\n\n".join(fragments)
    return f"Hook post-tool-use guidance:\n\n{body}"


__all__ = ["DEFAULT_MAX_TOOL_LOOPS", "LLMOrchestrator", "synthetic_tool_use_id"]
