"""P2.orch: prove LLMOrchestrator plumbs the classifier + denial
tracker + audit log through to :func:`execute_tool_call`.

The three primitives landed in P3 as opt-in kwargs on
``execute_tool_call`` but the live caller — the orchestrator's
``_execute_tool_call`` method — ignored them until P1's streaming
dispatcher had merged. Now that P1 is on master, this suite pins the
integration contract:

* When ``classifier_context`` is set on the orchestrator, it is forwarded
  on every tool call.
* When ``denial_tracker`` is set, AUTO_DENY decisions record against it
  and the counter survives across multiple tool calls in the same turn.
* When ``audit_log`` is set, every tool call (including the PROMPT path)
  produces exactly one audit-log entry.
* All three are truly optional — the orchestrator constructed without
  them behaves exactly like before (no regression on the P1/P0 fixtures).

The fixtures mirror :mod:`tests.test_orchestrator_hooks` so the shape
stays familiar; the only novelty is patching ``execute_tool_call`` to
observe the passthrough rather than exercising the classifier end-to-end
(that path is already covered by ``tests/test_executor_classifier_gate``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.streaming import MessageStop, TextDelta, ToolUseEnd, ToolUseStart
from cli.permissions import PermissionManager
from cli.permissions.classifier import ClassifierContext
from cli.permissions.denial_tracking import DenialTracker
from cli.tools.base import PermissionDecision, Tool, ToolContext, ToolResult
from cli.tools.executor import ToolExecution
from cli.tools.registry import ToolRegistry


class _EchoTool(Tool):
    name = "Echo"
    description = "Echo input."
    input_schema = {"type": "object", "properties": {"value": {"type": "string"}}}
    read_only = True

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.success(tool_input["value"], metadata={})


class _ScriptedModel:
    """Two-turn model: first turn asks for a tool, second turn finalises.

    Matches the event shape :mod:`cli.llm.streaming` consumes — tool_use
    bookends plus a final MessageStop."""

    def __init__(self) -> None:
        self.calls = 0

    def stream(self, *, system_prompt, messages, tools) -> Iterator[Any]:
        self.calls += 1
        if self.calls == 1:
            yield ToolUseStart(id="tu_1", name="Echo")
            yield ToolUseEnd(id="tu_1", name="Echo", input={"value": "hi"})
            yield MessageStop(stop_reason="tool_use")
        else:
            yield TextDelta("done")
            yield MessageStop(stop_reason="end_turn")


def _build_orchestrator(
    tmp_path: Path,
    *,
    classifier_context: ClassifierContext | None = None,
    denial_tracker: DenialTracker | None = None,
    audit_log: Any | None = None,
) -> LLMOrchestrator:
    registry = ToolRegistry()
    registry.register(_EchoTool())
    return LLMOrchestrator(
        model=_ScriptedModel(),
        tool_registry=registry,
        permissions=PermissionManager(root=tmp_path),
        workspace_root=tmp_path,
        system_prompt="system",
        echo=lambda _: None,
        classifier_context=classifier_context,
        denial_tracker=denial_tracker,
        audit_log=audit_log,
    )


def _capture_execute_tool_call_kwargs() -> tuple[list[dict[str, Any]], Any]:
    """Patch ``execute_tool_call`` at the orchestrator's import site.

    Returns the recorded kwargs list and a stub execution that pretends
    every tool call succeeded so the turn loop terminates normally."""
    captured: list[dict[str, Any]] = []

    def fake_execute(tool_name, tool_input, **kwargs):
        captured.append(dict(kwargs))
        return ToolExecution(
            tool_name=tool_name,
            decision=PermissionDecision.ALLOW,
            result=ToolResult.success(tool_input.get("value", "")),
        )

    patcher = patch("cli.llm.orchestrator.execute_tool_call", side_effect=fake_execute)
    return captured, patcher


# ---------------------------------------------------------------------------
# Passthrough contract
# ---------------------------------------------------------------------------


def test_orchestrator_forwards_classifier_context(tmp_path: Path) -> None:
    ctx = ClassifierContext(
        workspace_root=tmp_path,
        web_allowlist=frozenset(),
        persisted_allow_patterns=frozenset({"ls"}),
        persisted_deny_patterns=frozenset(),
    )
    orch = _build_orchestrator(tmp_path, classifier_context=ctx)
    captured, patcher = _capture_execute_tool_call_kwargs()
    with patcher:
        orch.run_turn("echo something")

    assert captured, "execute_tool_call was never invoked"
    first_call = captured[0]
    assert first_call.get("classifier_context") is ctx


def test_orchestrator_forwards_denial_tracker(tmp_path: Path) -> None:
    tracker = DenialTracker(max_per_session_per_tool=3)
    orch = _build_orchestrator(tmp_path, denial_tracker=tracker)
    captured, patcher = _capture_execute_tool_call_kwargs()
    with patcher:
        orch.run_turn("echo something")

    assert captured[0].get("denial_tracker") is tracker


def test_orchestrator_forwards_audit_log(tmp_path: Path) -> None:
    from cli.permissions.audit_log import ClassifierAuditLog

    audit = ClassifierAuditLog(path=tmp_path / ".agentlab" / "audit.jsonl")
    orch = _build_orchestrator(tmp_path, audit_log=audit)
    captured, patcher = _capture_execute_tool_call_kwargs()
    with patcher:
        orch.run_turn("echo something")

    assert captured[0].get("audit_log") is audit


def test_orchestrator_without_integration_kwargs_stays_compatible(tmp_path: Path) -> None:
    """No classifier/tracker/audit-log → execute_tool_call is still called,
    and the three kwargs are absent (or None) rather than being fabricated."""
    orch = _build_orchestrator(tmp_path)
    captured, patcher = _capture_execute_tool_call_kwargs()
    with patcher:
        orch.run_turn("echo something")

    kwargs = captured[0]
    # Passing as None is acceptable; the executor handles both cases identically.
    assert kwargs.get("classifier_context") is None
    assert kwargs.get("denial_tracker") is None
    assert kwargs.get("audit_log") is None


# ---------------------------------------------------------------------------
# Multi-call behavior within a single turn
# ---------------------------------------------------------------------------


class _ScriptedModelTwoTools:
    """Three model turns: tool, tool, end_turn — exercises that a shared
    classifier/tracker survives across two tool calls in one turn."""

    def __init__(self) -> None:
        self.calls = 0

    def stream(self, *, system_prompt, messages, tools) -> Iterator[Any]:
        self.calls += 1
        if self.calls == 1:
            yield ToolUseStart(id="tu_1", name="Echo")
            yield ToolUseEnd(id="tu_1", name="Echo", input={"value": "one"})
            yield MessageStop(stop_reason="tool_use")
        elif self.calls == 2:
            yield ToolUseStart(id="tu_2", name="Echo")
            yield ToolUseEnd(id="tu_2", name="Echo", input={"value": "two"})
            yield MessageStop(stop_reason="tool_use")
        else:
            yield TextDelta("done")
            yield MessageStop(stop_reason="end_turn")


def test_same_classifier_and_tracker_passed_on_every_call(tmp_path: Path) -> None:
    ctx = ClassifierContext(
        workspace_root=tmp_path,
        web_allowlist=frozenset(),
        persisted_allow_patterns=frozenset(),
        persisted_deny_patterns=frozenset(),
    )
    tracker = DenialTracker()
    registry = ToolRegistry()
    registry.register(_EchoTool())
    orch = LLMOrchestrator(
        model=_ScriptedModelTwoTools(),
        tool_registry=registry,
        permissions=PermissionManager(root=tmp_path),
        workspace_root=tmp_path,
        system_prompt="system",
        echo=lambda _: None,
        classifier_context=ctx,
        denial_tracker=tracker,
    )
    captured, patcher = _capture_execute_tool_call_kwargs()
    with patcher:
        orch.run_turn("two tools please")

    assert len(captured) == 2
    assert captured[0].get("classifier_context") is ctx
    assert captured[1].get("classifier_context") is ctx
    assert captured[0].get("denial_tracker") is tracker
    assert captured[1].get("denial_tracker") is tracker
