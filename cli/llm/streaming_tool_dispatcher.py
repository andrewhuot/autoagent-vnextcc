"""Streaming dispatcher for tool calls.

The dispatcher sits between streamed ``ToolUse*`` events and the synchronous
tool executor. It starts concurrency-safe tools as soon as they are ready,
preserves declared order for the results, and serializes any tool that needs a
permission prompt so the modal path stays exclusive.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from cli.llm.provider_capabilities import ProviderCapabilities
from cli.llm.streaming import ToolUseDelta, ToolUseEnd, ToolUseStart
from cli.tools.base import PermissionDecision, ToolResult
from cli.tools.executor import ToolExecution
from cli.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ToolExecutionHandle:
    """Handle returned when a streamed tool call is registered.

    The handle exists for future integration work; the current tests only
    need the dispatcher to retain the submitted work internally.
    """

    tool_use_id: str
    future: Future[ToolExecution] | None


@dataclass
class OrderedToolCall:
    """One streamed tool call plus its execution state."""

    tool_use_id: str
    name: str
    input_fragments: list[str] = field(default_factory=list)
    input_data: dict[str, Any] = field(default_factory=dict)
    exclusive: bool = False
    started: bool = False
    future: Future[ToolExecution] | None = None
    execution: ToolExecution | None = None


class StreamingToolDispatcher:
    """Dispatch streamed tool calls with order-preserving concurrency."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        executor: Callable[[str, dict[str, Any]], ToolExecution],
        capabilities: ProviderCapabilities,
        max_concurrency: int = 4,
    ) -> None:
        """Build a dispatcher around a synchronous executor callable.

        ``executor`` is intentionally duck-typed: the orchestrator can bind
        ``execute_tool_call`` with partial arguments now and a later layer can
        attach a ``requires_permission_prompt`` preflight hook for modal tools.
        """
        self._registry = registry
        self._executor = executor
        self._capabilities = capabilities
        self._max_concurrency = max(1, int(max_concurrency))
        workers = 1 if not capabilities.parallel_tool_calls else self._max_concurrency
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers))
        self._records: list[OrderedToolCall] = []
        self._records_by_id: dict[str, OrderedToolCall] = {}
        self._lock = threading.RLock()
        self._state_changed = threading.Condition(self._lock)
        self._active_count = 0
        self._cancelled = False

    def on_tool_use_start(self, event: ToolUseStart) -> None:
        """Record the streamed tool start so later deltas land on the right call."""
        with self._lock:
            self._get_or_create_record(event.id, event.name)

    def on_tool_use_delta(self, event: ToolUseDelta) -> None:
        """Accumulate streamed JSON fragments for a tool call."""
        with self._lock:
            record = self._get_or_create_record(event.id, "")
            record.input_fragments.append(event.input_json)

    def on_tool_use_end(self, event: ToolUseEnd) -> ToolExecutionHandle:
        """Finalize a tool call and submit it when scheduling allows."""
        with self._lock:
            record = self._get_or_create_record(event.id, event.name)
            record.name = event.name or record.name
            record.input_data = self._resolve_input(record, event.input)
            record.exclusive = self._is_exclusive(record.name, record.input_data)
            self._schedule_ready_locked()
            future = record.future
        return ToolExecutionHandle(tool_use_id=event.id, future=future)

    def results_in_order(self) -> list[ToolExecution]:
        """Wait for all scheduled work and return executions in declaration order."""
        with self._lock:
            self._schedule_ready_locked()
            self._state_changed.wait_for(self._all_done_locked)
            if self._cancelled:
                return []
            return [record.execution for record in self._records if record.execution is not None]

    def cancel_all(self) -> None:
        """Mark the dispatcher terminal and prevent queued work from starting."""
        pool: ThreadPoolExecutor | None = None
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            self._cancel_inflight_locked()
            pool = self._pool
            self._state_changed.notify_all()
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

    def _get_or_create_record(self, tool_use_id: str, name: str) -> OrderedToolCall:
        record = self._records_by_id.get(tool_use_id)
        if record is not None:
            if name and not record.name:
                record.name = name
            return record
        record = OrderedToolCall(tool_use_id=tool_use_id, name=name)
        self._records_by_id[tool_use_id] = record
        self._records.append(record)
        return record

    def _resolve_input(
        self,
        record: OrderedToolCall,
        parsed_input: dict[str, Any],
    ) -> dict[str, Any]:
        if parsed_input:
            return dict(parsed_input)
        joined = "".join(record.input_fragments).strip()
        if not joined:
            return {}
        try:
            value = json.loads(joined)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _is_exclusive(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        if not self._capabilities.parallel_tool_calls:
            return True
        tool = self._tool_for_name(tool_name)
        if tool is None:
            return True
        if not bool(getattr(tool, "is_concurrency_safe", False)):
            return True
        return self._requires_permission_prompt(tool_name, tool_input)

    def _tool_for_name(self, tool_name: str) -> Any | None:
        try:
            return self._registry.get(tool_name)
        except Exception:
            return None

    def _requires_permission_prompt(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        preflight = getattr(self._executor, "requires_permission_prompt", None)
        if not callable(preflight):
            return False
        try:
            return bool(preflight(tool_name, tool_input))
        except Exception:
            return False

    def _schedule_ready_locked(self) -> None:
        if self._cancelled:
            return

        idx = 0
        while idx < len(self._records):
            record = self._records[idx]
            if record.execution is not None:
                idx += 1
                continue
            if record.started:
                if record.exclusive:
                    break
                idx += 1
                continue
            if record.exclusive:
                if self._active_count > 0:
                    break
                self._start_record_locked(record)
                break
            if self._active_count >= self._max_concurrency:
                break
            self._start_record_locked(record)
            idx += 1

    def _start_record_locked(self, record: OrderedToolCall) -> None:
        if self._cancelled or record.started:
            return
        record.started = True
        self._active_count += 1
        try:
            future = self._pool.submit(self._run_record, record)
        except Exception as exc:  # pragma: no cover - defensive
            record.started = False
            self._active_count -= 1
            record.execution = self._failure_execution(record.name, exc)
            self._state_changed.notify_all()
            return
        record.future = future
        future.add_done_callback(lambda fut, current=record: self._finish_record(current, fut))

    def _cancel_inflight_locked(self) -> None:
        cancel_all = getattr(self._executor, "cancel_all", None)
        if callable(cancel_all):
            try:
                cancel_all()
            except Exception:
                pass
        cancel_one = getattr(self._executor, "cancel", None)
        if callable(cancel_one):
            for record in self._records:
                if record.started and record.future is not None and not record.execution:
                    try:
                        cancel_one(record.tool_use_id)
                    except Exception:
                        continue

    def _run_record(self, record: OrderedToolCall) -> ToolExecution:
        if self._cancelled:
            return self._cancelled_execution(record.name)
        try:
            execution = self._executor(record.name, dict(record.input_data))
        except Exception as exc:
            return self._failure_execution(record.name, exc)
        if isinstance(execution, ToolExecution):
            return execution
        return self._failure_execution(
            record.name,
            TypeError(f"Executor returned {type(execution)!r} instead of ToolExecution"),
        )

    def _finish_record(self, record: OrderedToolCall, future: Future[ToolExecution]) -> None:
        with self._lock:
            try:
                execution = future.result()
            except Exception as exc:  # pragma: no cover - executor wrapper already catches
                execution = self._failure_execution(record.name, exc)
            if not self._cancelled:
                record.execution = execution
            self._active_count = max(0, self._active_count - 1)
            self._schedule_ready_locked()
            self._state_changed.notify_all()

    def _all_done_locked(self) -> bool:
        if self._cancelled:
            return True
        if not self._records:
            return True
        return all(record.execution is not None for record in self._records)

    def _failure_execution(self, tool_name: str, exc: Exception) -> ToolExecution:
        return ToolExecution(
            tool_name=tool_name,
            decision=PermissionDecision.ALLOW,
            result=ToolResult.failure(f"{tool_name} crashed: {exc}"),
        )

    def _cancelled_execution(self, tool_name: str) -> ToolExecution:
        return ToolExecution(
            tool_name=tool_name,
            decision=PermissionDecision.DENY,
            result=ToolResult.failure(f"{tool_name} cancelled"),
            denial_reason="cancelled",
        )


__all__ = ["StreamingToolDispatcher", "ToolExecutionHandle"]
