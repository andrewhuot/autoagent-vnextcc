"""Tests for Phase F.4 tools: WebFetch, WebSearch, TodoWrite.

Mirrors the conventions in ``tests/test_cli_tools.py`` — a tmp workspace
fixture, a ``ToolContext`` fixture, and focused per-tool tests that drive
the ``run`` contract without reaching over the network or disk outside
the workspace.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pytest

from cli.tools.base import ToolContext
from cli.tools.registry import default_registry, reset_default_registry
from cli.tools.todo_write import TodoWriteTool
from cli.tools.web_fetch import WebFetchTool
from cli.tools.web_search import WebSearchTool


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


@pytest.fixture
def context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace)


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


def test_default_registry_includes_phase_f4_tools() -> None:
    reset_default_registry()
    try:
        registry = default_registry()
        names = {tool.name for tool in registry.list()}
        assert {"WebFetch", "WebSearch", "TodoWrite"}.issubset(names)
    finally:
        reset_default_registry()


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for what ``urlopen`` returns; supports the subset
    ``WebFetchTool.run`` uses (``read`` + ``headers.get`` + context manager)."""

    def __init__(self, body: bytes, content_type: str = "text/plain") -> None:
        self._buf = io.BytesIO(body)
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._buf.read()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        self._buf.close()


def test_web_fetch_rejects_non_http_scheme(context: ToolContext) -> None:
    result = WebFetchTool().run({"url": "file:///etc/passwd"}, context)
    assert not result.ok
    assert "http(s)" in result.content


def test_web_fetch_rejects_empty_url(context: ToolContext) -> None:
    result = WebFetchTool().run({"url": ""}, context)
    assert not result.ok


def test_web_fetch_permission_action_scopes_by_host() -> None:
    tool = WebFetchTool()
    assert tool.permission_action({"url": "https://github.com/anthropics"}) == (
        "tool:WebFetch:github.com"
    )


def test_web_fetch_redacts_secrets(
    monkeypatch: pytest.MonkeyPatch, context: ToolContext
) -> None:
    body = (
        b"Config dump:\n"
        b"OPENAI_API_KEY=sk-proj-12345abcdef\n"
        b"Anthropic key sk-ant-api03-ZZZZ-YYYY in the clear.\n"
        b"GitHub token github_pat_ABCDEF123 committed.\n"
    )

    def fake_urlopen(request, timeout: int = 0):  # noqa: ARG001
        return _FakeResponse(body, content_type="text/plain")

    monkeypatch.setattr("cli.tools.web_fetch.urlopen", fake_urlopen)

    result = WebFetchTool().run({"url": "https://example.com/leak"}, context)
    assert result.ok
    assert "sk-proj-12345abcdef" not in result.content
    assert "sk-ant-api03-ZZZZ-YYYY" not in result.content
    assert "github_pat_ABCDEF123" not in result.content
    assert "[REDACTED" in result.content
    assert "OPENAI_API_KEY=[REDACTED]" in result.content


def test_web_fetch_strips_html(
    monkeypatch: pytest.MonkeyPatch, context: ToolContext
) -> None:
    html = (
        b"<html><head><style>h1{color:red}</style>"
        b"<script>alert(1)</script></head>"
        b"<body><h1>Hello</h1><p>World</p></body></html>"
    )

    def fake_urlopen(request, timeout: int = 0):  # noqa: ARG001
        return _FakeResponse(html, content_type="text/html; charset=utf-8")

    monkeypatch.setattr("cli.tools.web_fetch.urlopen", fake_urlopen)

    result = WebFetchTool().run({"url": "https://example.com"}, context)
    assert result.ok
    assert "alert(1)" not in result.content
    assert "color:red" not in result.content
    assert "Hello" in result.content
    assert "World" in result.content


def test_web_fetch_handles_urlopen_failure(
    monkeypatch: pytest.MonkeyPatch, context: ToolContext
) -> None:
    from urllib.error import URLError

    def boom(request, timeout: int = 0):  # noqa: ARG001
        raise URLError("name resolution failed")

    monkeypatch.setattr("cli.tools.web_fetch.urlopen", boom)

    result = WebFetchTool().run({"url": "https://does-not-exist.invalid"}, context)
    assert not result.ok
    assert "Fetch failed" in result.content
    assert "name resolution failed" in result.content


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------


def test_web_search_fallback_when_no_backend(
    monkeypatch: pytest.MonkeyPatch, context: ToolContext
) -> None:
    monkeypatch.delenv("AGENTLAB_SEARCH_BACKEND", raising=False)
    result = WebSearchTool().run({"query": "anthropic claude"}, context)
    assert result.ok
    assert "backend not configured" in result.content
    assert result.metadata["configured"] is False


def test_web_search_uses_injected_backend(context: ToolContext) -> None:
    calls: list[tuple[str, int]] = []

    def backend(query: str, limit: int) -> Iterable[Mapping[str, Any]]:
        calls.append((query, limit))
        return [
            {"title": "Foo", "url": "https://foo.example", "snippet": "foo snippet"},
            {"title": "Bar", "url": "https://bar.example", "snippet": "bar snippet"},
        ]

    context.extra["web_search_backend"] = backend
    result = WebSearchTool().run({"query": "hello", "limit": 2}, context)
    assert result.ok
    assert calls == [("hello", 2)]
    assert "Foo" in result.content
    assert "https://bar.example" in result.content
    assert result.metadata["configured"] is True
    assert len(result.metadata["results"]) == 2


def test_web_search_handles_backend_exception(context: ToolContext) -> None:
    def broken(query: str, limit: int) -> Iterable[Mapping[str, Any]]:
        raise RuntimeError("provider unreachable")

    context.extra["web_search_backend"] = broken
    result = WebSearchTool().run({"query": "hello"}, context)
    assert not result.ok
    assert "provider unreachable" in result.content


def test_web_search_validates_limit(context: ToolContext) -> None:
    result = WebSearchTool().run({"query": "hi", "limit": 99}, context)
    assert not result.ok
    assert "limit" in result.content


def test_web_search_env_backend_stub(
    monkeypatch: pytest.MonkeyPatch, context: ToolContext
) -> None:
    monkeypatch.setenv("AGENTLAB_SEARCH_BACKEND", "stub")
    # Ensure injected wins over env: here none injected so env backend used.
    assert "web_search_backend" not in context.extra
    result = WebSearchTool().run({"query": "stub test", "limit": 3}, context)
    assert result.ok
    assert result.metadata["configured"] is True
    assert len(result.metadata["results"]) == 3


def test_web_search_env_backend_brave_raises(
    monkeypatch: pytest.MonkeyPatch, context: ToolContext
) -> None:
    monkeypatch.setenv("AGENTLAB_SEARCH_BACKEND", "brave")
    result = WebSearchTool().run({"query": "foo"}, context)
    assert not result.ok
    assert "install adapter" in result.content


# ---------------------------------------------------------------------------
# TodoWriteTool
# ---------------------------------------------------------------------------


def _todo_path(workspace: Path) -> Path:
    return workspace / ".agentlab" / "todos.json"


def test_todo_write_creates_file(workspace: Path, context: ToolContext) -> None:
    items = [
        {"content": "draft spec", "status": "pending"},
        {"content": "open pr", "status": "in_progress"},
    ]
    result = TodoWriteTool().run({"items": items}, context)
    assert result.ok
    path = _todo_path(workspace)
    assert path.exists()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored) == 2
    assert {entry["content"] for entry in stored} == {"draft spec", "open pr"}
    # Auto-assigned ids
    assert all(entry.get("id") for entry in stored)
    assert result.metadata["count"] == 2
    assert result.metadata["by_status"]["pending"] == 1
    assert result.metadata["by_status"]["in_progress"] == 1


def test_todo_write_appends_new_items(workspace: Path, context: ToolContext) -> None:
    tool = TodoWriteTool()
    tool.run({"items": [{"content": "first", "status": "pending"}]}, context)
    tool.run({"items": [{"content": "second", "status": "pending"}]}, context)
    stored = json.loads(_todo_path(workspace).read_text(encoding="utf-8"))
    assert [entry["content"] for entry in stored] == ["first", "second"]


def test_todo_write_updates_existing_in_place(
    workspace: Path, context: ToolContext
) -> None:
    tool = TodoWriteTool()
    first = tool.run(
        {"items": [{"content": "write tests", "status": "pending", "id": "task-1"}]},
        context,
    )
    assert first.ok
    second = tool.run(
        {"items": [{"content": "write tests", "status": "completed", "id": "task-1"}]},
        context,
    )
    assert second.ok
    stored = json.loads(_todo_path(workspace).read_text(encoding="utf-8"))
    assert len(stored) == 1
    assert stored[0]["status"] == "completed"
    assert stored[0]["id"] == "task-1"
    assert second.metadata["by_status"]["completed"] == 1


def test_todo_write_validates_item_schema(context: ToolContext) -> None:
    tool = TodoWriteTool()
    missing_content = tool.run({"items": [{"status": "pending"}]}, context)
    assert not missing_content.ok
    assert "content" in missing_content.content

    bad_status = tool.run(
        {"items": [{"content": "x", "status": "done"}]}, context
    )
    assert not bad_status.ok
    assert "status" in bad_status.content

    not_a_list = tool.run({"items": "nope"}, context)
    assert not not_a_list.ok


def test_todo_write_mixes_update_and_append(workspace: Path, context: ToolContext) -> None:
    tool = TodoWriteTool()
    tool.run(
        {
            "items": [
                {"content": "A", "status": "pending", "id": "a"},
                {"content": "B", "status": "pending", "id": "b"},
            ]
        },
        context,
    )
    result = tool.run(
        {
            "items": [
                {"content": "A done", "status": "completed", "id": "a"},
                {"content": "C", "status": "pending"},
            ]
        },
        context,
    )
    assert result.ok
    stored = json.loads(_todo_path(workspace).read_text(encoding="utf-8"))
    assert [entry["content"] for entry in stored] == ["A done", "B", "C"]
    assert stored[0]["status"] == "completed"
    assert result.metadata["count"] == 3
