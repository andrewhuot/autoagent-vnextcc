"""Helpers for resuming a Workbench conversation across REPL boots.

The slash handler in :mod:`cli.workbench_app.resume_slash` calls these
to load prior conversation history into a fresh
:class:`~cli.llm.orchestrator.LLMOrchestrator` and to render a hint
when the most recent conversation has interrupted tool calls.

These are intentionally pure helpers: no I/O beyond the
:class:`ConversationStore` argument, no formatting concerns beyond a
single one-line hint, and no orchestrator coupling. The slash handler
and the boot-time hint integration both layer on top.
"""

from __future__ import annotations

from cli.llm.types import TurnMessage
from cli.workbench_app.conversation_store import (
    Conversation,
    ConversationStore,
    ToolCall,
)


# Cap per-tool-result content sent back into orchestrator.messages so
# resuming a long conversation doesn't blow up the context window.
TOOL_RESULT_RESUME_LIMIT = 600


def load_history(
    store: ConversationStore, conversation_id: str
) -> list[TurnMessage]:
    """Return one :class:`TurnMessage` per persisted message in position order.

    Tool calls are summarised inline with the assistant message rather
    than reconstructed as Anthropic content-block objects (which would
    require id-paired ``tool_use``/``tool_result`` blocks). The summary
    is safe to send back to the model — it loses the structured
    invocation but preserves the narrative.
    """
    convo = store.get_conversation(conversation_id)
    out: list[TurnMessage] = []
    for msg in convo.messages:
        if msg.role == "assistant" and msg.tool_calls:
            text = msg.content or ""
            tail_lines = [_summarise_tool_call(tc) for tc in msg.tool_calls]
            text = (text + "\n\n" + "\n".join(tail_lines)).strip()
            out.append(TurnMessage(role="assistant", content=text))
        else:
            out.append(TurnMessage(role=msg.role, content=msg.content))
    return out


def _summarise_tool_call(tc: ToolCall) -> str:
    """One-line tool_call summary for inclusion in resumed history."""
    body = ""
    truncated = False
    if tc.result and isinstance(tc.result, dict):
        display = tc.result.get("display") or tc.result.get("denial_reason") or ""
        if display:
            if len(display) > TOOL_RESULT_RESUME_LIMIT:
                body = display[:TOOL_RESULT_RESUME_LIMIT]
                truncated = True
            else:
                body = display
    line = f"[tool: {tc.tool_name} → {tc.status}] {body}".rstrip()
    if truncated:
        line += " [...]"
    return line


def format_resume_hint(conversation: Conversation) -> str | None:
    """Return a one-line hint when ``conversation`` has interrupted tool calls.

    Returns ``None`` when nothing is interrupted, so callers can write
    ``hint = format_resume_hint(c); if hint: echo(hint)`` without a
    second predicate. Mentions the conversation id explicitly so
    ``/resume <id>`` is discoverable, plus the count of interrupted
    calls so the user knows the scope.
    """
    interrupted = sum(
        1
        for msg in conversation.messages
        for tc in msg.tool_calls
        if tc.status == "interrupted"
    )
    if interrupted == 0:
        return None
    plural = "" if interrupted == 1 else "s"
    return (
        f"Conversation {conversation.id} was interrupted with "
        f"{interrupted} pending tool call{plural}. "
        f"Type /resume {conversation.id} to continue."
    )


__all__ = [
    "TOOL_RESULT_RESUME_LIMIT",
    "format_resume_hint",
    "load_history",
]
