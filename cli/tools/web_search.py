"""WebSearchTool — pluggable search dispatch with graceful fallback.

Search is a capability with many possible backends (Brave, Tavily, a local
crawler, a test stub). Rather than bake a single provider into the tool,
we accept an optional callable on :class:`ToolContext.extra` keyed as
``"web_search_backend"``. When none is configured, the tool succeeds with
a friendly message so the LLM can recover by asking the user to configure
one — failing hard would just trigger a retry storm.

Design notes:

* ``read_only`` is True in spirit. Searching third-party indices does not
  mutate workspace state, so we treat it like Glob/Grep in plan mode.
* Backend adapters are NotImplementedError stubs for Brave/Tavily until an
  HTTP adapter lands. The ``stub`` backend returns a deterministic list so
  tests can assert dispatch.
* A backend exception becomes a ToolResult.failure rather than propagating
  — consistent with other tools in this package.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Iterable, Mapping

from cli.tools.base import Tool, ToolContext, ToolResult


SearchBackend = Callable[[str, int], Iterable[Mapping[str, Any]]]

DEFAULT_LIMIT = 5
MIN_LIMIT = 1
MAX_LIMIT = 10

_FALLBACK_MESSAGE = (
    "WebSearch backend not configured. Set AGENTLAB_SEARCH_BACKEND or "
    "register via ToolContext.extra['web_search_backend']."
)


class WebSearchTool(Tool):
    """Dispatch to a configured search backend or fall back gracefully."""

    name = "WebSearch"
    description = (
        "Search the web for a query and return a list of title/url/snippet "
        "entries. Requires a backend configured either via "
        "ToolContext.extra['web_search_backend'] or the AGENTLAB_SEARCH_BACKEND "
        "environment variable (values: stub, brave, tavily)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free-text search query.",
            },
            "limit": {
                "type": "integer",
                "minimum": MIN_LIMIT,
                "maximum": MAX_LIMIT,
                "description": "Maximum results to return (default 5).",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    read_only = True

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return "tool:WebSearch"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        query = str(tool_input.get("query", ""))
        return f"WebSearch {query[:160]}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        query = str(tool_input.get("query") or "").strip()
        if not query:
            return ToolResult.failure("WebSearch requires a 'query'.")
        limit_raw = tool_input.get("limit", DEFAULT_LIMIT)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            return ToolResult.failure("WebSearch 'limit' must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            return ToolResult.failure(
                f"WebSearch 'limit' must be between {MIN_LIMIT} and {MAX_LIMIT}."
            )

        backend = _resolve_backend(context)
        if backend is None:
            # Friendly success so the model can react rather than loop.
            return ToolResult(
                ok=True,
                content=_FALLBACK_MESSAGE,
                metadata={"configured": False, "query": query, "results": []},
            )

        try:
            raw_results = list(backend(query, limit))
        except NotImplementedError as exc:
            return ToolResult.failure(f"WebSearch backend error: {exc}")
        except Exception as exc:  # noqa: BLE001 — tool.run must not raise
            return ToolResult.failure(f"WebSearch backend error: {exc}")

        results = [_normalise(entry) for entry in raw_results[:limit]]
        summary = "\n".join(
            f"{idx + 1}. {entry['title']}\n   {entry['url']}\n   {entry['snippet']}"
            for idx, entry in enumerate(results)
        ) or "(no results)"

        return ToolResult(
            ok=True,
            content=summary,
            metadata={"configured": True, "query": query, "results": results},
        )


def _resolve_backend(context: ToolContext) -> SearchBackend | None:
    injected = context.extra.get("web_search_backend") if context.extra else None
    if callable(injected):
        return injected  # type: ignore[return-value]
    return env_backend()


def env_backend() -> SearchBackend | None:
    """Return a backend callable from the AGENTLAB_SEARCH_BACKEND env var.

    Values:

    * ``stub`` — deterministic fixture used in tests.
    * ``brave`` / ``tavily`` — raise NotImplementedError until an adapter
      ships; the orchestrator surfaces that as a failure result.
    * anything else (or unset) — ``None``.
    """
    raw = (os.environ.get("AGENTLAB_SEARCH_BACKEND") or "").strip().lower()
    if not raw:
        return None
    if raw == "stub":
        return _stub_backend
    if raw == "brave":
        return _brave_backend
    if raw == "tavily":
        return _tavily_backend
    return None


def _stub_backend(query: str, limit: int) -> list[dict[str, str]]:
    return [
        {
            "title": f"Stub result {idx} for {query}",
            "url": f"https://example.com/stub/{idx}",
            "snippet": f"Deterministic stub snippet #{idx} for query '{query}'.",
        }
        for idx in range(1, limit + 1)
    ]


def _brave_backend(query: str, limit: int) -> list[dict[str, str]]:
    raise NotImplementedError("install adapter to use")


def _tavily_backend(query: str, limit: int) -> list[dict[str, str]]:
    raise NotImplementedError("install adapter to use")


def _normalise(entry: Mapping[str, Any]) -> dict[str, str]:
    return {
        "title": str(entry.get("title") or "").strip() or "(untitled)",
        "url": str(entry.get("url") or "").strip(),
        "snippet": str(entry.get("snippet") or "").strip(),
    }
