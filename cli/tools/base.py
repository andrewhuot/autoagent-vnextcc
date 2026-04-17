"""Abstract base class for workbench tools.

Each tool is a concrete subclass of :class:`Tool` that declares a JSON schema
for its input and implements :meth:`Tool.run`. Tools are invoked by the LLM
loop through :class:`~cli.tools.registry.ToolRegistry`, which resolves the
permission decision via :class:`~cli.permissions.PermissionManager` before
handing the call to :meth:`Tool.run`.

Design notes:

* Tools are *stateless*. Any per-call resources (workspace root, cancel token)
  travel on :class:`ToolContext`.
* Tools must never raise on user-caused failure; they return a
  :class:`ToolResult` with ``ok=False`` so the LLM can react. Raise
  :class:`ToolError` only for programmer errors (invalid schema, unreachable
  state).
* :meth:`Tool.permission_action` returns the action string consumed by the
  existing permission matcher — tools that write to the workspace must build a
  distinctive string (e.g. ``"tool:FileEdit:<relpath>"``) so rules in
  ``settings.json`` can target individual paths.
* :meth:`Tool.render_preview` returns the short string shown in the permission
  dialog — concise, human-readable, no ANSI codes (the dialog adds its own
  styling).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class PermissionDecision(str, Enum):
    """Resolved permission verdict for a single tool invocation."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ToolError(Exception):
    """Raised for programmer errors (invalid schema, registry misuse)."""


@dataclass
class ToolContext:
    """Per-invocation context supplied by the workbench loop.

    The context is built once per user turn and reused across tool calls in
    that turn. Tests construct it directly with a temp-dir ``workspace_root``
    and no cancellation so each test path is deterministic.
    """

    workspace_root: Path
    """Absolute path to the workspace root. All workspace-scoped tools must
    refuse paths that resolve outside this directory."""

    session_id: str | None = None
    """Identifier for the enclosing session, used by tools that persist
    state (checkpoints, pastes)."""

    cancel_check: Any | None = None
    """Optional callable or cancellation token polled by long-running tools.
    ``None`` means tools run to completion without cooperative cancellation."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Scratchpad for tool-specific context the workbench wants to thread
    through (e.g. the active PermissionManager so tools can self-check
    sub-actions)."""


@dataclass
class ToolResult:
    """Structured tool output returned to the LLM loop.

    ``content`` is the payload shown to the model — either a plain string
    (default) or a list of content blocks following the Anthropic tool_result
    shape so structured outputs (diffs, tables) can round-trip without
    serialisation loss. ``display`` is an optional override shown to the user
    when it differs from what the model sees (e.g. collapse a 10k-line grep
    into ``[... 12 000 matches ...]`` for the transcript).
    """

    ok: bool
    content: Any
    display: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, content: Any, *, display: str | None = None, **metadata: Any) -> "ToolResult":
        """Shorthand for the happy path."""
        return cls(ok=True, content=content, display=display, metadata=metadata)

    @classmethod
    def failure(cls, message: str, **metadata: Any) -> "ToolResult":
        """Shorthand for a user-facing failure. Non-raising by design."""
        return cls(ok=False, content=message, display=message, metadata=metadata)


class Tool(ABC):
    """Abstract workbench tool.

    Subclasses must set ``name``, ``description`` and ``input_schema`` as class
    attributes and implement :meth:`run`. The base class provides sensible
    defaults for :meth:`permission_action` (``"tool:<Name>"``) and
    :meth:`render_preview` (a JSON dump of the input).
    """

    name: str
    """Stable identifier exposed to the LLM; matches the Claude Code tool name
    where we ported the concept (``FileReadTool`` → ``FileRead``)."""

    description: str
    """One-paragraph description embedded in the tool-use system prompt."""

    input_schema: Mapping[str, Any]
    """JSON Schema for the tool's input object."""

    read_only: bool = False
    """When ``True`` the tool is auto-allowed in plan mode and never triggers a
    permission prompt in default mode. Grep/Glob/FileRead flip this on."""

    is_concurrency_safe: bool = False
    """When ``True`` the dispatcher may run the tool alongside other safe
    calls. Most tools stay serial by default."""

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        """Return the action string consumed by :class:`PermissionManager`.

        Subclasses that write to the workspace override this to include the
        target path so rules like ``"tool:FileEdit:configs/*.yaml"`` match
        through ``fnmatch``.
        """
        return f"tool:{self.name}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        """Return the short preview shown in the permission dialog."""
        return f"{self.name}({tool_input!r})"

    @abstractmethod
    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        """Execute the tool. Implementations must be synchronous and never
        raise for user-caused errors — return ``ToolResult.failure`` instead."""
        raise NotImplementedError

    def to_schema_entry(self) -> dict[str, Any]:
        """Return the tool definition in Anthropic tool-use shape."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }
