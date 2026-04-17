"""Bridge :class:`OrchestratorResult` turns into the SQLite ConversationStore.

The orchestrator (``cli.llm.orchestrator``) returns one
:class:`~cli.llm.types.OrchestratorResult` per user turn, carrying the
assistant text plus the list of :class:`~cli.tools.executor.ToolExecution`
objects that fired during the turn. The Workbench app needs that history
persisted to SQLite so the resume UI can reconstruct the conversation
across restarts. :class:`ConversationBridge` is the single seam that
performs that mirroring.

Limitation — ``arguments`` is recorded as ``{}``
------------------------------------------------
:class:`~cli.tools.executor.ToolExecution` does not currently carry the
original ``tool_input`` (the argument dict the LLM passed when it
emitted the ``AssistantToolUseBlock``). The bridge therefore writes
``arguments={}`` for every persisted ``tool_call`` row. A future Slice C
task can plumb the original ``tool_input`` through ``ToolExecution``
(small change to ``cli/tools/executor.py``) and update this bridge to
forward it. Tests in ``tests/test_conversation_bridge.py`` lock in the
empty-dict shape so the limitation is discoverable.
"""

from __future__ import annotations

from typing import Any

from cli.tools.rendering import persisted_renderable_payload
from cli.workbench_app.conversation_store import ConversationStore, Message


# Cap for the ``display`` string we stash on each finished tool_call row.
# Keeps the SQLite payload bounded — anything bigger gets truncated with
# a marker so the UI can still render a reasonable preview.
_DISPLAY_CAP = 4000


class ConversationBridge:
    """Mirror :class:`OrchestratorResult` turns into a :class:`ConversationStore`.

    Each user message becomes one ``message`` row; each assistant turn
    becomes one ``message`` row (with the concatenated assistant text)
    plus one ``tool_call`` row per ``ToolExecution`` that fired during
    the turn.

    See module docstring for the ``arguments`` / ``tool_input``
    limitation — for now every persisted tool_call has
    ``arguments == {}``.
    """

    def __init__(self, store: ConversationStore, conversation_id: str) -> None:
        self._store = store
        self._conv_id = conversation_id

    def record_user_turn(self, text: str) -> Message:
        """Append a user message to the underlying conversation."""
        return self._store.append_message(
            conversation_id=self._conv_id,
            role="user",
            content=text,
        )

    def record_assistant_turn(self, result: Any) -> Message:
        """Record one :class:`OrchestratorResult`.

        - One assistant message with ``result.assistant_text`` content
          (coerced to ``""`` when missing/None so the SQL NOT NULL
          constraint is honoured).
        - One ``tool_call`` row per :class:`ToolExecution`. Status is
          ``"succeeded"`` when ``execution.result.ok`` is True,
          ``"failed"`` when False, and ``"failed"`` with a ``denied``
          payload when ``execution.result is None`` (the executor
          returned a denial).
        - The ``result`` column carries the ``ToolResult.display``
          truncated to ``_DISPLAY_CAP`` characters under key ``"display"``.
          When tool metadata includes a structured renderable payload we
          persist it alongside the display fallback under key
          ``"renderable"``.
        - ``arguments`` is ``{}`` — see the module docstring.
        """
        assistant_text = getattr(result, "assistant_text", "") or ""
        msg = self._store.append_message(
            conversation_id=self._conv_id,
            role="assistant",
            content=assistant_text,
        )
        for execution in getattr(result, "tool_executions", []) or []:
            tool_call = self._store.start_tool_call(
                message_id=msg.id,
                tool_name=execution.tool_name,
                arguments={},  # see docstring
            )
            tr = execution.result
            if tr is None:
                status = "failed"
                payload: dict[str, Any] = {
                    "denied": True,
                    "denial_reason": execution.denial_reason,
                }
            elif tr.ok:
                status = "succeeded"
                payload = {"display": _truncate(tr.display, _DISPLAY_CAP)}
            else:
                status = "failed"
                payload = {"display": _truncate(tr.display, _DISPLAY_CAP)}
            if tr is not None and isinstance(tr.metadata, dict):
                renderable = tr.metadata.get("renderable")
                persisted = persisted_renderable_payload(renderable)
                if persisted is not None:
                    payload["renderable"] = persisted
            self._store.finish_tool_call(
                tool_call_id=tool_call.id,
                status=status,
                result=payload,
            )
        return msg


def _truncate(text: str | None, limit: int) -> str | None:
    """Pass-through for ``None`` and short text; mark longer text with
    a truncation suffix that names how many characters were dropped."""
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... truncated {len(text) - limit} chars ...]"


__all__ = ["ConversationBridge"]
