"""Trace-to-eval converter — turn production traces into eval test cases.

Converts raw trace dicts (from :mod:`observer.traces`) into
:class:`~core.types.EvalCase`-compatible dicts that can be loaded by the eval
runner.  Also provides auto-selection of diverse traces for bulk generation.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any


class TraceToEvalConverter:
    """Convert production traces into eval test cases.

    The converter extracts input, expected output, trajectory, and grading
    criteria from a trace dict and assembles them into the EvalCase schema.

    Usage::

        converter = TraceToEvalConverter()
        case = converter.convert(trace, expected_output="order shipped")
        cases = converter.auto_generate_from_production(traces, max_cases=30)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert(
        self,
        trace: dict[str, Any],
        expected_output: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Convert a single trace dict into an EvalCase-compatible dict.

        Args:
            trace: Raw trace dict (from the observer layer or a log file).
            expected_output: Override for the expected output.  When ``None``
                the converter attempts to infer it from the trace.
            tags: Optional list of tag strings added to ``metadata.tags``.

        Returns:
            An EvalCase-compatible dict ready for the eval runner.
        """
        trace_id = str(
            trace.get("trace_id") or trace.get("id") or uuid.uuid4().hex[:12]
        )
        case_id = f"trace_{trace_id}"

        task = self._extract_input(trace)
        inferred_output = expected_output or self._extract_expected_output(trace)
        trajectory = self._extract_trajectory(trace)
        grading = self._generate_grading_criteria(trace)

        return {
            "case_id": case_id,
            "task": task,
            "category": str(trace.get("category") or "trace_derived"),
            "suite_type": "discovery",
            "expected_end_state": {"response": inferred_output} if inferred_output else None,
            "diagnostic_trace_features": {
                "source_trace_id": trace_id,
                "trajectory": trajectory,
                "latency_ms": trace.get("latency_ms") or trace.get("total_latency_ms"),
                "tool_count": len(trajectory),
            },
            "expected_specialist": trace.get("specialist_used") or trace.get("agent_path"),
            "expected_behavior": grading.get("expected_behavior", "answer"),
            "expected_keywords": grading.get("expected_keywords", []),
            "expected_tool": grading.get("expected_tool"),
            "reference_answer": inferred_output or "",
            "split": "tuning",
            "metadata": {
                "source": "trace_converter",
                "source_trace_id": trace_id,
                "grading_criteria": grading,
                "tags": list(tags or []),
            },
        }

    def convert_batch(self, traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert a list of traces to EvalCase dicts."""
        return [self.convert(trace) for trace in traces]

    def auto_generate_from_production(
        self,
        traces: list[dict[str, Any]],
        max_cases: int = 50,
    ) -> list[dict[str, Any]]:
        """Auto-select diverse traces and convert them to eval cases.

        Selection strategy:
        1. Deduplicate by input fingerprint (one case per unique user message).
        2. Prefer traces that cover different agent paths / specialists.
        3. Include at least one error trace per specialist when available.
        4. Cap at *max_cases* total.

        Args:
            traces: All available production traces.
            max_cases: Maximum number of eval cases to generate.

        Returns:
            A list of at most *max_cases* EvalCase-compatible dicts.
        """
        if not traces:
            return []

        max_cases = max(1, int(max_cases))

        # --- Deduplication by input fingerprint ---
        seen_fingerprints: set[str] = set()
        deduplicated: list[dict[str, Any]] = []
        for trace in traces:
            fp = self._input_fingerprint(trace)
            if fp not in seen_fingerprints:
                seen_fingerprints.add(fp)
                deduplicated.append(trace)

        # --- Stratified selection by specialist / agent path ---
        by_specialist: dict[str, list[dict[str, Any]]] = {}
        for trace in deduplicated:
            specialist = str(
                trace.get("specialist_used")
                or trace.get("agent_path")
                or "unknown"
            )
            by_specialist.setdefault(specialist, []).append(trace)

        selected: list[dict[str, Any]] = []

        # Round-robin across specialists to get diversity
        specialist_keys = sorted(by_specialist.keys())
        max_rounds = (max_cases // max(len(specialist_keys), 1)) + 1

        for _ in range(max_rounds):
            if len(selected) >= max_cases:
                break
            for key in specialist_keys:
                if len(selected) >= max_cases:
                    break
                bucket = by_specialist[key]
                if not bucket:
                    continue
                # Prefer error traces first, then pop from front
                error_idx = next(
                    (
                        i
                        for i, t in enumerate(bucket)
                        if self._is_error_trace(t)
                    ),
                    None,
                )
                if error_idx is not None:
                    selected.append(bucket.pop(error_idx))
                else:
                    selected.append(bucket.pop(0))

        return [self.convert(trace) for trace in selected[:max_cases]]

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_input(self, trace: dict[str, Any]) -> str:
        """Extract the user input / task from a trace dict."""
        # Direct fields
        for field in (
            "user_message",
            "input",
            "task",
            "prompt",
            "query",
            "message",
        ):
            val = trace.get(field)
            if val:
                return str(val)

        # Try to find it in events
        events = trace.get("events") or []
        for event in events:
            if not isinstance(event, dict):
                continue
            if str(event.get("event_type", "")).lower() in ("user_message", "input"):
                content = event.get("content") or event.get("tool_input")
                if content:
                    return str(content)

        return f"(no input extracted from trace {trace.get('trace_id', '?')})"

    def _extract_expected_output(self, trace: dict[str, Any]) -> str:
        """Infer expected output from a trace, preferring the final response."""
        # Direct fields
        for field in ("response", "output", "result", "answer"):
            val = trace.get(field)
            if val:
                return str(val)

        # Last model_response or tool_response event
        events = trace.get("events") or []
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            et = str(event.get("event_type", "")).lower()
            if et in ("model_response", "partial_response"):
                content = (
                    event.get("content")
                    or event.get("tool_output")
                    or event.get("output")
                )
                if content:
                    return str(content)

        return ""

    def _extract_trajectory(self, trace: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract tool-call trajectory steps from a trace."""
        events = trace.get("events") or []
        steps: list[dict[str, Any]] = []

        for idx, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            et = str(event.get("event_type", "")).lower()
            if et not in ("tool_call", "tool_response"):
                continue

            tool_input_raw = event.get("tool_input")
            params: dict[str, Any] = {}
            if tool_input_raw:
                try:
                    params = json.loads(tool_input_raw) if isinstance(tool_input_raw, str) else tool_input_raw
                except (json.JSONDecodeError, TypeError):
                    params = {"raw": str(tool_input_raw)}

            steps.append({
                "step_index": len(steps),
                "action": et,
                "tool_name": event.get("tool_name"),
                "parameters": params,
                "event_index": idx,
            })

        return steps

    def _generate_grading_criteria(self, trace: dict[str, Any]) -> dict[str, Any]:
        """Infer grading criteria from the trace for auto-generated eval cases.

        Returns a dict with:
        - ``expected_behavior``: ``"answer"`` or ``"refuse"``
        - ``expected_keywords``: keywords from the response (up to 5)
        - ``expected_tool``: most-called tool in the trace
        """
        # Expected behavior
        outcome = str(trace.get("status") or trace.get("outcome") or "").lower()
        if outcome in ("refuse", "refused", "safety"):
            expected_behavior = "refuse"
        else:
            expected_behavior = "answer"

        # Expected keywords from response
        response_text = self._extract_expected_output(trace)
        keywords: list[str] = []
        if response_text:
            # Simple heuristic: extract capitalised words or quoted phrases
            words = [
                w.strip(".,!?\"'()[]")
                for w in response_text.split()
                if len(w) > 5  # ignore short words
            ]
            # Deduplicate while preserving order
            seen: set[str] = set()
            for w in words:
                lw = w.lower()
                if lw not in seen:
                    seen.add(lw)
                    keywords.append(w)
                if len(keywords) >= 5:
                    break

        # Most-called tool
        events = trace.get("events") or []
        tool_counts: dict[str, int] = {}
        for event in events:
            if not isinstance(event, dict):
                continue
            if str(event.get("event_type", "")).lower() == "tool_call":
                tool_name = event.get("tool_name")
                if tool_name:
                    tool_counts[str(tool_name)] = tool_counts.get(str(tool_name), 0) + 1

        expected_tool: str | None = None
        if tool_counts:
            expected_tool = max(tool_counts, key=lambda t: tool_counts[t])

        return {
            "expected_behavior": expected_behavior,
            "expected_keywords": keywords,
            "expected_tool": expected_tool,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _input_fingerprint(trace: dict[str, Any]) -> str:
        """Stable 8-char hash of the trace's user input for deduplication."""
        user_input = (
            str(trace.get("user_message") or trace.get("input") or trace.get("task") or "")
            .strip()
            .lower()
        )
        return hashlib.sha256(user_input.encode()).hexdigest()[:8]

    @staticmethod
    def _is_error_trace(trace: dict[str, Any]) -> bool:
        """Return True when the trace is an error trace (for priority selection)."""
        status = str(trace.get("status") or trace.get("outcome") or "").lower()
        return status in ("error", "fail", "failure", "failed", "exception")
