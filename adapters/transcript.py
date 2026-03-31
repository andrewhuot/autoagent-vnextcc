"""Transcript adapter for importing conversation logs into AutoAgent workspaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentAdapter, ImportedAgentSpec


class TranscriptAdapter(AgentAdapter):
    """Import JSONL conversation exports as traces and starter evals."""

    adapter_name = "transcript"
    platform_name = "Transcript Import"

    def __init__(self, source: str) -> None:
        super().__init__(source)
        self.path = Path(source).resolve()
        self._cached_traces: list[dict[str, Any]] | None = None

    def discover(self) -> ImportedAgentSpec:
        """Normalize transcript files into a starter workspace spec."""

        traces = self.import_traces()
        tools = self.import_tools()
        spec = ImportedAgentSpec(
            adapter=self.adapter_name,
            source=str(self.path),
            agent_name="transcript-import",
            platform=self.platform_name,
            traces=traces,
            tools=tools,
            metadata={"trace_file": str(self.path)},
        )
        spec.ensure_defaults()
        return spec

    def import_traces(self) -> list[dict[str, Any]]:
        """Load JSONL traces from disk."""

        if self._cached_traces is not None:
            return self._cached_traces

        traces: list[dict[str, Any]] = []
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            messages = payload.get("messages") or payload.get("turns") or []
            normalized_messages = [
                {
                    "role": str(item.get("role", "user")),
                    "content": str(item.get("content", "")),
                    "tool_calls": list(item.get("tool_calls", []) or []),
                }
                for item in messages
                if isinstance(item, dict)
            ]
            traces.append(
                {
                    "id": str(payload.get("id", f"trace-{len(traces) + 1}")),
                    "messages": normalized_messages,
                    "metadata": dict(payload.get("metadata", {}) or {}),
                }
            )

        self._cached_traces = traces
        return traces

    def import_tools(self) -> list[dict[str, Any]]:
        """Infer tool usage from transcript tool call metadata."""

        tools: dict[str, dict[str, Any]] = {}
        for trace in self.import_traces():
            for message in trace.get("messages", []):
                for tool_call in message.get("tool_calls", []):
                    if not isinstance(tool_call, dict):
                        continue
                    name = str(tool_call.get("name") or tool_call.get("tool") or "").strip()
                    if not name:
                        continue
                    tools.setdefault(
                        name,
                        {
                            "name": name,
                            "description": "Observed from imported transcript",
                            "source_trace": trace["id"],
                        },
                    )
        return list(tools.values())

    def import_guardrails(self) -> list[dict]:
        """Transcript imports do not infer guardrails automatically."""

        return []
