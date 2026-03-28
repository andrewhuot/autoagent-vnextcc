"""CX Agent Studio compatibility matrix.

Maintains a living matrix of which ADK constructs map to CX Agent Studio,
which are ADK-only, and which are CX-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CompatStatus(str, Enum):
    """Compatibility status between ADK and CX Agent Studio."""

    FULL = "full"
    PARTIAL = "partial"
    ADK_ONLY = "adk_only"
    CX_ONLY = "cx_only"
    NOT_SUPPORTED = "not_supported"


@dataclass
class CompatEntry:
    """Single entry in the compatibility matrix."""

    construct: str
    adk_name: str
    cx_name: str
    status: CompatStatus
    notes: str = ""
    mapping_details: str = ""


# ---------------------------------------------------------------------------
# Hardcoded compatibility matrix entries
# ---------------------------------------------------------------------------

_MATRIX: list[CompatEntry] = [
    # -- Agent types --
    CompatEntry(
        construct="agent_type.llm_agent",
        adk_name="LlmAgent",
        cx_name="CX Agent (Playbook)",
        status=CompatStatus.FULL,
        notes="LlmAgent maps 1-to-1 to a CX Agent with a Playbook. "
              "instruction → playbook steps, tools → CX tools, callbacks → CX generators.",
        mapping_details="agent.instruction → playbook.instruction.steps; "
                        "agent.tools → app-level tools; "
                        "agent.model → generativeSettings.llm.model",
    ),
    CompatEntry(
        construct="agent_type.sequential_agent",
        adk_name="SequentialAgent",
        cx_name="",
        status=CompatStatus.ADK_ONLY,
        notes="SequentialAgent has no direct CX equivalent. "
              "Sub-agents can be flattened to separate CX Playbooks with explicit handoffs.",
        mapping_details="",
    ),
    CompatEntry(
        construct="agent_type.parallel_agent",
        adk_name="ParallelAgent",
        cx_name="",
        status=CompatStatus.ADK_ONLY,
        notes="CX Agent Studio does not support parallel agent execution natively. "
              "Parallel branches must be serialised or handled via external orchestration.",
        mapping_details="",
    ),
    CompatEntry(
        construct="agent_type.loop_agent",
        adk_name="LoopAgent",
        cx_name="",
        status=CompatStatus.ADK_ONLY,
        notes="Looping constructs are ADK-only. CX Playbooks can express iteration "
              "through conditional steps but not a programmatic loop.",
        mapping_details="",
    ),
    # -- Tool types --
    CompatEntry(
        construct="tool_type.function_tool",
        adk_name="FunctionTool",
        cx_name="CX Python code tool",
        status=CompatStatus.FULL,
        notes="Python function tools export to CX Python code tools. "
              "Sandbox restrictions apply — only standard library and approved packages.",
        mapping_details="function body → tool.pythonCode.code; "
                        "function signature → tool input/output schema",
    ),
    CompatEntry(
        construct="tool_type.agent_tool",
        adk_name="AgentTool",
        cx_name="",
        status=CompatStatus.ADK_ONLY,
        notes="AgentTool (sub-agent delegation) has no CX equivalent. "
              "Use sub_agents / childAgents instead for CX-compatible agent delegation.",
        mapping_details="",
    ),
    CompatEntry(
        construct="tool_type.mcp_toolset",
        adk_name="McpToolset",
        cx_name="CX MCP tool",
        status=CompatStatus.PARTIAL,
        notes="Only StreamableHTTP transport is supported in CX Agent Studio. "
              "stdio-only MCP servers cannot be deployed to CX.",
        mapping_details="McpToolset(transport=StreamableHTTP) → CX MCP tool; "
                        "McpToolset(transport=stdio) → NOT_SUPPORTED in CX",
    ),
    CompatEntry(
        construct="tool_type.openapi_tool",
        adk_name="OpenAPITool",
        cx_name="CX OpenAPI tool",
        status=CompatStatus.FULL,
        notes="OpenAPI spec tools map fully to CX OpenAPI tools. "
              "Authentication schemes (bearer, API key) are preserved.",
        mapping_details="openapi_spec → tool.openApiSpec; "
                        "auth_config → tool.authConfig",
    ),
    CompatEntry(
        construct="tool_type.cx_client_function",
        adk_name="",
        cx_name="CX client function",
        status=CompatStatus.CX_ONLY,
        notes="CX client-side functions execute in the browser/channel context. "
              "No ADK equivalent exists.",
        mapping_details="",
    ),
    CompatEntry(
        construct="tool_type.cx_integration_connector",
        adk_name="",
        cx_name="CX integration connector",
        status=CompatStatus.CX_ONLY,
        notes="CX Integration Connectors (Apigee / Cloud Connectors) are CX-only. "
              "ADK uses direct HTTP calls or function tools instead.",
        mapping_details="",
    ),
    CompatEntry(
        construct="tool_type.cx_widget_tools",
        adk_name="",
        cx_name="CX widget tools",
        status=CompatStatus.CX_ONLY,
        notes="Widget tools (rich cards, chips, carousels) are surface-specific to "
              "CX web widget and telephony channels.",
        mapping_details="",
    ),
    CompatEntry(
        construct="tool_type.cx_system_tools",
        adk_name="",
        cx_name="CX system tools",
        status=CompatStatus.CX_ONLY,
        notes="CX system tools (DTMF, live agent handoff, end conversation) are "
              "CX-only built-ins.",
        mapping_details="",
    ),
    # -- Features --
    CompatEntry(
        construct="feature.instruction",
        adk_name="instruction",
        cx_name="playbook.instruction",
        status=CompatStatus.FULL,
        notes="Agent instruction maps directly to CX Playbook instruction steps.",
        mapping_details="agent.instruction (str) → playbook.instruction.steps (list[str])",
    ),
    CompatEntry(
        construct="feature.sub_agents",
        adk_name="sub_agents",
        cx_name="childAgents",
        status=CompatStatus.FULL,
        notes="ADK sub_agents map to CX childAgents with transfer rules generated "
              "for each sub-agent delegation.",
        mapping_details="agent.sub_agents → app.childAgents + transferRules",
    ),
    CompatEntry(
        construct="feature.callbacks",
        adk_name="callbacks",
        cx_name="generators",
        status=CompatStatus.FULL,
        notes="ADK model/agent callbacks map to CX generators (before/after model callbacks "
              "→ input/output processors).",
        mapping_details="before_model_callback → generator.inputProcessor; "
                        "after_model_callback → generator.outputProcessor",
    ),
    CompatEntry(
        construct="feature.guardrails",
        adk_name="guardrails",
        cx_name="safetySettings / bannedPhrases",
        status=CompatStatus.FULL,
        notes="ADK guardrail strings map to CX generativeSettings.safetySettings and "
              "bannedPhrases.",
        mapping_details="guardrails → generativeSettings.safetySettings + bannedPhrases",
    ),
    CompatEntry(
        construct="feature.examples",
        adk_name="examples",
        cx_name="CX examples",
        status=CompatStatus.FULL,
        notes="ADK eval cases / few-shot examples map to CX Playbook examples for "
              "in-context learning.",
        mapping_details="eval_cases → playbook.examples (conversationTurns)",
    ),
    CompatEntry(
        construct="feature.state_session",
        adk_name="state / session",
        cx_name="session parameters",
        status=CompatStatus.PARTIAL,
        notes="CX session parameters cover user: and app: state prefixes. "
              "temp: prefix has no direct equivalent and is dropped on export.",
        mapping_details="state['user:*'] → session.params['user.*']; "
                        "state['app:*'] → session.params['app.*']; "
                        "state['temp:*'] → DROPPED",
    ),
    CompatEntry(
        construct="feature.transfer_rules",
        adk_name="",
        cx_name="transferRules",
        status=CompatStatus.CX_ONLY,
        notes="CX transferRules define explicit conditions for routing to child agents. "
              "In ADK, routing is implicit via LLM decision-making.",
        mapping_details="",
    ),
    CompatEntry(
        construct="feature.versions",
        adk_name="",
        cx_name="CX versions",
        status=CompatStatus.CX_ONLY,
        notes="CX Agent Studio has a formal versioning system with snapshots. "
              "ADK relies on source control (git) for versioning.",
        mapping_details="",
    ),
    CompatEntry(
        construct="feature.deployments",
        adk_name="",
        cx_name="CX deployments",
        status=CompatStatus.CX_ONLY,
        notes="CX deployments (web widget, telephony, CCaaS) are CX-only concepts. "
              "ADK deploys via Cloud Run / Vertex AI Agent Engine.",
        mapping_details="",
    ),
]


class CompatibilityMatrix:
    """Living compatibility matrix between ADK and CX Agent Studio.

    Provides lookup, filtering, and rendering utilities for the matrix.
    """

    def get_matrix(self) -> list[CompatEntry]:
        """Return all compatibility matrix entries.

        Returns:
            Full list of CompatEntry objects covering all constructs.
        """
        return list(_MATRIX)

    def check_construct(self, construct: str) -> Optional[CompatEntry]:
        """Look up a single construct by its canonical key.

        Args:
            construct: Construct identifier, e.g. ``"agent_type.llm_agent"``
                or ``"tool_type.function_tool"``.

        Returns:
            The matching ``CompatEntry``, or ``None`` if not found.
        """
        for entry in _MATRIX:
            if entry.construct == construct:
                return entry
        return None

    def get_cx_portable(self, constructs: list[str]) -> dict[str, bool]:
        """Check CX portability for a list of construct identifiers.

        A construct is considered CX-portable when its status is ``FULL``
        or ``PARTIAL``.

        Args:
            constructs: List of construct identifiers to check.

        Returns:
            Dict mapping each construct name to a bool (True = CX-portable).
        """
        result: dict[str, bool] = {}
        for construct in constructs:
            entry = self.check_construct(construct)
            if entry is None:
                result[construct] = False
            else:
                result[construct] = entry.status in (
                    CompatStatus.FULL,
                    CompatStatus.PARTIAL,
                )
        return result

    def get_adk_only(self) -> list[CompatEntry]:
        """Return all constructs that are ADK-only (no CX equivalent).

        Returns:
            List of entries with status ``ADK_ONLY``.
        """
        return [e for e in _MATRIX if e.status == CompatStatus.ADK_ONLY]

    def get_cx_only(self) -> list[CompatEntry]:
        """Return all constructs that are CX-only (no ADK equivalent).

        Returns:
            List of entries with status ``CX_ONLY``.
        """
        return [e for e in _MATRIX if e.status == CompatStatus.CX_ONLY]

    def to_markdown(self) -> str:
        """Render the compatibility matrix as a Markdown table.

        Returns:
            Multi-line string containing a formatted Markdown table suitable
            for CLI output or documentation.
        """
        header = (
            "| Construct | ADK Name | CX Name | Status | Notes |\n"
            "|-----------|----------|---------|--------|-------|"
        )
        rows = []
        for entry in _MATRIX:
            notes = entry.notes.replace("|", "\\|")[:80]
            if len(entry.notes) > 80:
                notes += "…"
            rows.append(
                f"| `{entry.construct}` "
                f"| {entry.adk_name or '—'} "
                f"| {entry.cx_name or '—'} "
                f"| **{entry.status.value}** "
                f"| {notes} |"
            )
        return header + "\n" + "\n".join(rows)

    def to_dict(self) -> list[dict]:
        """Serialise the matrix to a list of plain dicts for API responses.

        Returns:
            List of dicts, one per entry, with all fields as strings.
        """
        return [
            {
                "construct": e.construct,
                "adk_name": e.adk_name,
                "cx_name": e.cx_name,
                "status": e.status.value,
                "notes": e.notes,
                "mapping_details": e.mapping_details,
            }
            for e in _MATRIX
        ]
