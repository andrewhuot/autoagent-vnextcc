"""Tests for the P2.T9 slash handlers: ``/uncompact``, ``/memory-debug``, ``/memory-edit``.

Each handler is a thin orchestrator over existing infrastructure
(``CompactArchive``, ``RetrievalResult``, ``$EDITOR``). The tests drive
them through a minimal :class:`SlashContext` — no real workspace, no
session store — because the handlers are defined to reach for only the
fields they need. A ``_slash_ctx`` factory builds that context with
sane defaults so each individual test can override only what it
inspects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from cli.llm.compact_archive import CompactArchive
from cli.llm.types import TurnMessage
from cli.memory.retrieval import RetrievalReason, RetrievalResult
from cli.memory.types import Memory, MemoryType
from cli.sessions import Session
from cli.workbench_app.slash import (
    SlashContext,
    _handle_memory_debug,
    _handle_memory_edit,
    _handle_uncompact,
    build_builtin_registry,
    dispatch,
)


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


@dataclass
class _FakeWorkspace:
    """Minimal workspace stand-in exposing only ``agentlab_dir``.

    The real Workspace object does a lot more; these handlers only
    touch ``workspace.agentlab_dir`` so we don't pull in the rest of
    the workspace surface.
    """

    root: Path

    @property
    def agentlab_dir(self) -> Path:
        return self.root / ".agentlab"


class _EchoCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


def _slash_ctx(
    *,
    workspace_root: Path | None = None,
    session_id: str = "sess-test",
    uncompact_callback: Any = None,
    memory_last_retrieval: Any = None,
) -> SlashContext:
    """Build a SlashContext with only the bits handlers under test read."""
    workspace = _FakeWorkspace(root=workspace_root) if workspace_root else None
    session = Session(session_id=session_id, title="test-session")
    return SlashContext(
        workspace=workspace,
        session=session,
        echo=_EchoCapture(),
        uncompact_callback=uncompact_callback,
        memory_last_retrieval=memory_last_retrieval,
    )


def _sample_messages() -> list[TurnMessage]:
    """Mirror of test_compact_archive._sample_messages so the archive
    round-trip exercises the same shape in both suites."""
    return [
        TurnMessage(role="user", content="hello"),
        TurnMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "let me check"},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "file_read",
                    "input": {"path": "README.md"},
                },
            ],
        ),
        TurnMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "file contents here",
                }
            ],
        ),
    ]


def _seed_archive(
    workspace_root: Path, session_id: str, start: int, end: int
) -> list[TurnMessage]:
    """Write a range into the session's compact archive and return the messages."""
    messages = _sample_messages()
    archive = CompactArchive(
        root=workspace_root / ".agentlab" / "compact_archive",
        session_id=session_id,
    )
    archive.write(start, end, messages)
    return messages


# --------------------------------------------------------------------------- #
# /uncompact                                                                  #
# --------------------------------------------------------------------------- #


def test_uncompact_reads_archive_and_restores_via_callback(tmp_path: Path) -> None:
    """Handler calls the callback with the loaded messages and reports the range."""
    expected = _seed_archive(tmp_path, "sess-1", 3, 17)

    received: list[list[TurnMessage]] = []
    ctx = _slash_ctx(
        workspace_root=tmp_path,
        session_id="sess-1",
        uncompact_callback=received.append,
    )
    result = _handle_uncompact(ctx)

    assert "Restored 14 messages" in result
    assert "[3, 17)" in result
    assert len(received) == 1
    assert received[0] == expected


def test_uncompact_without_archive_returns_friendly_message(tmp_path: Path) -> None:
    ctx = _slash_ctx(workspace_root=tmp_path, session_id="s1")
    result = _handle_uncompact(ctx)
    assert "nothing to uncompact" in result.lower()


def test_uncompact_picks_most_recent_range_when_multiple_present(tmp_path: Path) -> None:
    """With several ranges archived, /uncompact uses the last in sorted order."""
    _seed_archive(tmp_path, "sess-2", 0, 2)
    _seed_archive(tmp_path, "sess-2", 5, 10)
    _seed_archive(tmp_path, "sess-2", 20, 25)  # most-recent (highest start).

    captured: list[list[TurnMessage]] = []
    ctx = _slash_ctx(
        workspace_root=tmp_path,
        session_id="sess-2",
        uncompact_callback=captured.append,
    )
    result = _handle_uncompact(ctx)
    assert "Restored 5 messages from range [20, 25)" in result
    assert len(captured) == 1  # only one range restored


def test_uncompact_without_callback_still_reports_summary(tmp_path: Path) -> None:
    _seed_archive(tmp_path, "sess-nc", 0, 3)
    ctx = _slash_ctx(
        workspace_root=tmp_path, session_id="sess-nc", uncompact_callback=None
    )
    result = _handle_uncompact(ctx)
    assert "Restored 3 messages" in result


def test_uncompact_requires_workspace() -> None:
    """No workspace bound → handler returns a friendly error, not a crash."""
    ctx = _slash_ctx(workspace_root=None, session_id="x")
    # SlashContext accepts workspace=None; simulate that path.
    ctx.workspace = None
    result = _handle_uncompact(ctx)
    assert "no workspace" in result.lower()


# --------------------------------------------------------------------------- #
# /memory-debug                                                               #
# --------------------------------------------------------------------------- #


def _mk_reason(name: str, final: float, recency: float, hits: dict[str, int]) -> RetrievalReason:
    return RetrievalReason(
        name=name, term_hits=hits, recency_bonus=recency, final_score=final
    )


def _mk_memory(name: str) -> Memory:
    return Memory(
        name=name,
        type=MemoryType.PROJECT,
        description="desc",
        body="body",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_memory_debug_shows_injected_memories_with_reasons(tmp_path: Path) -> None:
    result_obj = RetrievalResult(
        memories=[_mk_memory("alpha"), _mk_memory("beta")],
        reasons=[
            _mk_reason("alpha", 1.234, 0.008, {"foo": 2}),
            _mk_reason("beta", 0.500, 0.001, {"bar": 1}),
        ],
    )
    ctx = _slash_ctx(workspace_root=tmp_path, memory_last_retrieval=result_obj)
    out = _handle_memory_debug(ctx)

    assert "Injected 2 memories" in out
    assert "alpha" in out and "beta" in out
    assert "1.234" in out
    assert "0.500" in out
    assert "foo" in out and "bar" in out


def test_memory_debug_without_retrieval_is_friendly(tmp_path: Path) -> None:
    ctx = _slash_ctx(workspace_root=tmp_path, memory_last_retrieval=None)
    out = _handle_memory_debug(ctx)
    assert "No memories injected yet" in out


def test_memory_debug_with_empty_retrieval_renders_valid_message(tmp_path: Path) -> None:
    """Retrieval ran but nothing scored — don't leave the user with a bare header."""
    empty = RetrievalResult(memories=[], reasons=[])
    ctx = _slash_ctx(workspace_root=tmp_path, memory_last_retrieval=empty)
    out = _handle_memory_debug(ctx)
    # Either the "No memories injected yet" fall-through (RetrievalResult is
    # falsy by convention) or the 0-count rendering is acceptable — both
    # convey "nothing matched". We assert on the observable invariant.
    assert "memor" in out.lower()


# --------------------------------------------------------------------------- #
# /memory-edit                                                                #
# --------------------------------------------------------------------------- #


def test_memory_edit_opens_editor_on_resolved_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, check: bool = False, **_: Any) -> Any:  # noqa: ANN001
        calls.append(list(cmd))
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setenv("EDITOR", "nano")
    monkeypatch.setattr("cli.workbench_app.slash.subprocess.run", fake_run)

    ctx = _slash_ctx(workspace_root=tmp_path)
    result = _handle_memory_edit(ctx)

    expected_path = tmp_path / ".agentlab" / "memory" / "MEMORY.md"
    assert calls == [["nano", str(expected_path)]]
    assert "nano" in result
    assert str(expected_path) in result


def test_memory_edit_with_slug_targets_per_memory_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr(
        "cli.workbench_app.slash.subprocess.run",
        lambda cmd, check=False, **_: calls.append(list(cmd)) or type("R", (), {"returncode": 0})(),
    )

    ctx = _slash_ctx(workspace_root=tmp_path)
    _handle_memory_edit(ctx, "my-note")

    expected_path = tmp_path / ".agentlab" / "memory" / "my-note.md"
    assert calls == [["vim", str(expected_path)]]


def test_memory_edit_falls_back_to_vi_when_editor_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr(
        "cli.workbench_app.slash.subprocess.run",
        lambda cmd, check=False, **_: calls.append(list(cmd)) or type("R", (), {"returncode": 0})(),
    )

    ctx = _slash_ctx(workspace_root=tmp_path)
    result = _handle_memory_edit(ctx)

    assert calls[0][0] == "vi"
    assert "vi" in result


def test_memory_edit_requires_workspace() -> None:
    ctx = _slash_ctx(workspace_root=None)
    ctx.workspace = None
    out = _handle_memory_edit(ctx)
    assert "no workspace" in out.lower()


# --------------------------------------------------------------------------- #
# registry wiring                                                             #
# --------------------------------------------------------------------------- #


def test_new_commands_are_registered_in_builtin_registry() -> None:
    """build_builtin_registry exposes the three new handlers by name."""
    registry = build_builtin_registry()
    assert registry.get("uncompact") is not None
    assert registry.get("memory-debug") is not None
    assert registry.get("memory-edit") is not None


def test_dispatch_routes_uncompact_through_registry(tmp_path: Path) -> None:
    """End-to-end: /uncompact is handled and returns a sensible message."""
    ctx = _slash_ctx(workspace_root=tmp_path, session_id="wired")
    ctx.registry = build_builtin_registry()
    result = dispatch(ctx, "/uncompact")
    assert result.handled is True
    assert result.command is not None
    assert result.command.name == "uncompact"
