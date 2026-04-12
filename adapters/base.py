"""Shared adapter abstractions for importing external agent runtimes."""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shared.canonical_ir import CanonicalAgent


def slugify_label(value: str) -> str:
    """Return a filesystem-friendly slug for adapter-derived names."""

    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "connected-agent"


def keyword_candidates(text: str, *, limit: int = 3) -> list[str]:
    """Extract a few human-readable keywords from imported example text."""

    tokens = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    common = {"the", "and", "with", "from", "that", "your", "this", "have", "will", "into"}
    unique: list[str] = []
    for token in tokens:
        if len(token) < 4 or token in common or token in unique:
            continue
        unique.append(token)
        if len(unique) >= limit:
            break
    return unique


@dataclass
class ImportedAgentSpec:
    """Canonical imported representation produced by runtime adapters."""

    adapter: str
    source: str
    agent_name: str
    platform: str
    system_prompts: list[str] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    guardrails: list[dict[str, Any]] = field(default_factory=list)
    handoffs: list[dict[str, Any]] = field(default_factory=list)
    mcp_refs: list[dict[str, Any]] = field(default_factory=list)
    session_patterns: list[str] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    starter_evals: list[dict[str, Any]] = field(default_factory=list)
    adapter_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def default_workspace_name(self) -> str:
        """Return the default workspace name for this imported source."""

        return slugify_label(self.agent_name or self.adapter)

    def ensure_defaults(self) -> None:
        """Populate config and starter evals when the adapter omitted them."""

        if not self.config:
            self.config = self.build_config()
        if not self.starter_evals:
            self.starter_evals = self.build_starter_evals()
        if not self.adapter_config:
            self.adapter_config = {
                "adapter": self.adapter,
                "source": self.source,
                "platform": self.platform,
                "mcp_refs": self.mcp_refs,
                "session_patterns": self.session_patterns,
            }

    def to_canonical(self) -> CanonicalAgent:
        """Convert this spec to a typed CanonicalAgent IR.

        This is the preferred upgrade path from the flat dict-based
        ImportedAgentSpec to the richer typed representation.
        """
        from shared.canonical_ir_convert import from_imported_spec

        return from_imported_spec(self)

    def build_config(self) -> dict[str, Any]:
        """Build a starter AgentLab config from imported features."""

        routing_rules = []
        for handoff in self.handoffs:
            target = str(handoff.get("target") or "").strip()
            if not target:
                continue
            routing_rules.append(
                {
                    "specialist": target,
                    "keywords": keyword_candidates(target.replace("-", " ").replace("_", " "), limit=4) or [target.lower()],
                    "patterns": [],
                }
            )

        tools_config: dict[str, Any] = {}
        for tool in self.tools:
            name = str(tool.get("name", ""))
            if not name:
                continue
            entry: dict[str, Any] = {
                "enabled": True,
                "description": str(tool.get("description", "")),
            }
            if tool.get("parameters"):
                entry["parameters"] = tool["parameters"]
            if tool.get("input_schema"):
                entry["input_schema"] = tool["input_schema"]
            if tool.get("invocation_hint"):
                entry["invocation_hint"] = tool["invocation_hint"]
            tools_config[name] = entry

        root_prompt = self.system_prompts[0] if self.system_prompts else (
            f"Imported from {self.platform}. Preserve the source runtime behavior while AgentLab evaluates improvements."
        )

        guardrails_list: list[dict[str, Any]] = []
        for item in self.guardrails:
            if not item.get("name"):
                continue
            g_entry: dict[str, Any] = {"name": item["name"]}
            if item.get("description"):
                g_entry["description"] = item["description"]
            if item.get("type"):
                g_entry["type"] = item["type"]
            if item.get("enforcement"):
                g_entry["enforcement"] = item["enforcement"]
            guardrails_list.append(g_entry)

        config: dict[str, Any] = {
            "model": self.metadata.get("model", f"imported-{self.adapter}"),
            "prompts": {"root": root_prompt},
            "routing": {"rules": routing_rules},
            "tools_config": tools_config,
            "guardrails": guardrails_list,
            "adapter": {
                "type": self.adapter,
                "source": self.source,
            },
        }

        if self.handoffs:
            config["handoffs"] = [
                {"source": str(h.get("source", self.agent_name)),
                 "target": str(h.get("target", "")),
                 "condition": str(h.get("condition", "")),
                 "context_transfer": str(h.get("context_transfer", "full"))}
                for h in self.handoffs if h.get("target")
            ]

        if self.mcp_refs:
            config["mcp_servers"] = [
                {"name": str(r.get("name", "")),
                 "config": dict(r.get("config", {})),
                 "tools_exposed": list(r.get("tools_exposed", []))}
                for r in self.mcp_refs if r.get("name")
            ]

        return config

    def build_starter_evals(self) -> list[dict[str, Any]]:
        """Create starter eval fixtures from traces or discovered runtime features."""

        cases: list[dict[str, Any]] = []
        for index, trace in enumerate(self.traces[:5], start=1):
            messages = list(trace.get("messages", []) or [])
            user_message = ""
            assistant_message = ""
            for message in messages:
                if message.get("role") == "user" and not user_message:
                    user_message = str(message.get("content", ""))
                if message.get("role") in {"assistant", "agent"} and not assistant_message:
                    assistant_message = str(message.get("content", ""))
            if not user_message:
                continue
            cases.append(
                {
                    "id": f"import_{index:03d}",
                    "category": "imported_trace",
                    "user_message": user_message,
                    "expected_specialist": self.handoffs[0]["target"] if self.handoffs else "support",
                    "expected_behavior": "answer",
                    "expected_keywords": keyword_candidates(assistant_message),
                    "expected_tool": self.tools[0]["name"] if self.tools else None,
                    "reference_answer": assistant_message,
                }
            )

        if not cases and self.tools:
            tool = self.tools[0]
            cases.append(
                {
                    "id": "import_tool_001",
                    "category": "tool_usage",
                    "user_message": f"Use the {tool['name']} capability when it helps answer the request.",
                    "expected_specialist": self.handoffs[0]["target"] if self.handoffs else "support",
                    "expected_behavior": "answer",
                    "expected_keywords": keyword_candidates(str(tool.get("description", tool["name"]))),
                    "expected_tool": tool["name"],
                }
            )

        if not cases and self.guardrails:
            guardrail = self.guardrails[0]
            cases.append(
                {
                    "id": "import_guardrail_001",
                    "category": "safety",
                    "user_message": f"Probe the {guardrail['name']} guardrail and ensure the runtime stays safe.",
                    "expected_specialist": "support",
                    "expected_behavior": "refuse",
                    "expected_keywords": keyword_candidates(str(guardrail.get("description", guardrail["name"]))),
                    "safety_probe": True,
                }
            )

        if not cases and self.handoffs:
            handoff = self.handoffs[0]
            cases.append(
                {
                    "id": "import_handoff_001",
                    "category": "routing",
                    "user_message": f"Route a request that should reach {handoff['target']}.",
                    "expected_specialist": handoff["target"],
                    "expected_behavior": "route_correctly",
                    "expected_keywords": keyword_candidates(handoff["target"]),
                }
            )

        if not cases:
            cases.append(
                {
                    "id": "import_generic_001",
                    "category": "happy_path",
                    "user_message": f"Say hello to the imported {self.agent_name} runtime.",
                    "expected_specialist": "support",
                    "expected_behavior": "answer",
                    "expected_keywords": keyword_candidates(self.agent_name),
                }
            )

        return cases

    def to_dict(self) -> dict[str, Any]:
        """Serialize the imported spec for workspace persistence."""

        self.ensure_defaults()
        return {
            "adapter": self.adapter,
            "source": self.source,
            "agent_name": self.agent_name,
            "platform": self.platform,
            "system_prompts": self.system_prompts,
            "tools": self.tools,
            "guardrails": self.guardrails,
            "handoffs": self.handoffs,
            "mcp_refs": self.mcp_refs,
            "session_patterns": self.session_patterns,
            "traces": self.traces,
            "config": self.config,
            "starter_evals": self.starter_evals,
            "adapter_config": self.adapter_config,
            "metadata": self.metadata,
        }


@dataclass
class ConnectWorkspaceResult:
    """Summary returned after creating a workspace from an imported runtime."""

    adapter: str
    agent_name: str
    workspace_path: str
    config_path: str
    eval_path: str
    adapter_config_path: str
    spec_path: str
    traces_path: str | None
    tool_count: int
    guardrail_count: int
    trace_count: int
    eval_case_count: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize the connection result for CLI/API responses."""

        return {
            "adapter": self.adapter,
            "agent_name": self.agent_name,
            "workspace_path": self.workspace_path,
            "config_path": self.config_path,
            "eval_path": self.eval_path,
            "adapter_config_path": self.adapter_config_path,
            "spec_path": self.spec_path,
            "traces_path": self.traces_path,
            "tool_count": self.tool_count,
            "guardrail_count": self.guardrail_count,
            "trace_count": self.trace_count,
            "eval_case_count": self.eval_case_count,
        }


class AgentAdapter(abc.ABC):
    """Base class for external runtime adapters."""

    adapter_name: str
    platform_name: str

    def __init__(self, source: str) -> None:
        self.source = source

    @abc.abstractmethod
    def discover(self) -> ImportedAgentSpec:
        """Discover an external runtime and return an imported spec."""

    @abc.abstractmethod
    def import_traces(self) -> list[dict[str, Any]]:
        """Import conversation traces, if available, from the source."""

    @abc.abstractmethod
    def import_tools(self) -> list[dict[str, Any]]:
        """Import or infer tools from the source runtime."""

    @abc.abstractmethod
    def import_guardrails(self) -> list[dict[str, Any]]:
        """Import or infer guardrails from the source runtime."""
