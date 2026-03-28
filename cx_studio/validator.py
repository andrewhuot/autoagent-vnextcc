"""Pre-deployment validation for CX Agent Studio compatibility."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .compat import CompatibilityMatrix, CompatStatus

# Packages available in the CX Agent Studio Python code tool sandbox.
# Source: https://cloud.google.com/conversational-agents/docs/tools/python-code-tool
_SANDBOX_SAFE_PACKAGES: frozenset[str] = frozenset(
    {
        # stdlib-only — all are available
        "json",
        "math",
        "re",
        "datetime",
        "collections",
        "itertools",
        "functools",
        "operator",
        "string",
        "textwrap",
        "urllib",
        "hashlib",
        "hmac",
        "base64",
        "uuid",
        "copy",
        "enum",
        "typing",
        "dataclasses",
        # Approved third-party packages in the sandbox
        "requests",
        "httpx",
        "pydantic",
        "google.auth",
        "google.cloud",
    }
)

# ADK agent types that have full or partial CX equivalents
_CX_COMPATIBLE_AGENT_TYPES: frozenset[str] = frozenset({"llm_agent", "LlmAgent"})

# Tool types incompatible with CX deployment
_ADK_ONLY_TOOL_TYPES: frozenset[str] = frozenset({"agent_tool", "AgentTool"})

_MATRIX = CompatibilityMatrix()


@dataclass
class CxValidationResult:
    """Result of a CX compatibility validation pass."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cx_portable_constructs: list[str] = field(default_factory=list)
    adk_only_constructs: list[str] = field(default_factory=list)


class CxValidator:
    """Validate AutoAgent / ADK configs before CX Agent Studio export or deployment.

    All methods are pure functions over their arguments — no I/O, no state.
    Validation operates on the ``AgentConfig``-compatible dict that AutoAgent
    produces internally (same structure used by the mapper layer).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_agent(self, agent_config: dict[str, Any]) -> CxValidationResult:
        """Validate a single agent configuration for CX deployment.

        Checks agent type, tool compatibility, MCP transport, and function
        dependencies in a single pass.

        Args:
            agent_config: AutoAgent config dict (as produced by ``AgentConfig``
                or ``CxMapper.to_autoagent``).

        Returns:
            ``CxValidationResult`` describing validity and any issues.
        """
        errors: list[str] = []
        warnings: list[str] = []
        cx_portable: list[str] = []
        adk_only: list[str] = []

        # --- Agent type ---
        agent_type = agent_config.get("agent_type", "LlmAgent")
        type_ok, type_msg = self.check_agent_type(agent_type)
        if type_ok:
            cx_portable.append(f"agent_type:{agent_type}")
        else:
            errors.append(type_msg)
            adk_only.append(f"agent_type:{agent_type}")

        # --- Tools ---
        tools_raw = agent_config.get("tools", {})
        tools_list: list[dict[str, Any]] = (
            list(tools_raw.values()) if isinstance(tools_raw, dict) else list(tools_raw)
        )

        tool_warnings = self.check_tools(tools_list)
        warnings.extend(tool_warnings)

        # Classify each tool
        for tool in tools_list:
            t_type = tool.get("tool_type", tool.get("_cx_tool_type", "function_tool"))
            if t_type in _ADK_ONLY_TOOL_TYPES:
                adk_only.append(f"tool:{t_type}")
            else:
                cx_portable.append(f"tool:{t_type}")

        # --- MCP transport ---
        mcp_tools = [
            t for t in tools_list if "mcp" in str(t.get("tool_type", "")).lower()
        ]
        mcp_errors = self.check_mcp_transport(mcp_tools)
        errors.extend(mcp_errors)

        # --- Function code dependencies ---
        for tool in tools_list:
            code = tool.get("function_code", tool.get("code", ""))
            if code:
                dep_warnings = self.check_function_dependencies(code)
                warnings.extend(dep_warnings)

        valid = len(errors) == 0
        return CxValidationResult(
            valid=valid,
            errors=errors,
            warnings=warnings,
            cx_portable_constructs=cx_portable,
            adk_only_constructs=adk_only,
        )

    def check_agent_type(self, agent_type: str) -> tuple[bool, str]:
        """Check whether the given agent type is deployable to CX Agent Studio.

        Only ``LlmAgent`` (and its equivalent ``llm_agent`` key) maps to a CX
        Agent.  All other orchestration types (Sequential, Parallel, Loop) are
        ADK-only and cannot be directly represented in CX Agent Studio.

        Args:
            agent_type: The agent type string, e.g. ``"LlmAgent"`` or
                ``"SequentialAgent"``.

        Returns:
            ``(True, "")`` when compatible, or ``(False, <reason>)`` when not.
        """
        if agent_type in _CX_COMPATIBLE_AGENT_TYPES:
            return True, ""
        canonical = f"agent_type.{agent_type.lower()}"
        entry = _MATRIX.check_construct(canonical)
        if entry and entry.status == CompatStatus.ADK_ONLY:
            return (
                False,
                f"Agent type '{agent_type}' is ADK-only and cannot be deployed to "
                f"CX Agent Studio. {entry.notes}",
            )
        # Unknown type — warn rather than hard-fail
        return (
            False,
            f"Unknown agent type '{agent_type}'. Only LlmAgent is supported for CX deployment.",
        )

    def check_tools(self, tools: list[dict[str, Any]]) -> list[str]:
        """Check tool compatibility and return warning strings for any issues.

        Does not generate hard errors — callers decide severity. Checks for:
        - ADK-only tool types (AgentTool)
        - MCP stdio transport (soft warning, also flagged by check_mcp_transport)
        - Unknown tool types

        Args:
            tools: List of tool config dicts, each with at least a ``tool_type``
                or ``_cx_tool_type`` key.

        Returns:
            List of human-readable warning strings (may be empty).
        """
        warnings: list[str] = []
        for tool in tools:
            t_type = str(tool.get("tool_type", tool.get("_cx_tool_type", "function_tool")))
            name = tool.get("name", tool.get("display_name", "<unnamed>"))

            if t_type in _ADK_ONLY_TOOL_TYPES:
                warnings.append(
                    f"Tool '{name}' uses type '{t_type}' which has no CX equivalent. "
                    "Consider converting to a sub-agent transfer or removing for CX export."
                )
            elif "mcp" in t_type.lower():
                transport = tool.get("transport", tool.get("transport_type", ""))
                if transport and "stdio" in transport.lower():
                    warnings.append(
                        f"MCP tool '{name}' uses stdio transport which is not supported "
                        "in CX Agent Studio. Only StreamableHTTP is supported."
                    )
        return warnings

    def check_mcp_transport(self, mcp_tools: list[dict[str, Any]]) -> list[str]:
        """Validate MCP tool transport compatibility with CX Agent Studio.

        CX Agent Studio only supports StreamableHTTP transport for MCP tools.
        stdio-only MCP servers cannot be deployed to CX.

        Args:
            mcp_tools: List of tool dicts that have been identified as MCP tools.

        Returns:
            List of error strings for stdio-only MCP tools (hard errors).
        """
        errors: list[str] = []
        for tool in mcp_tools:
            transport = str(
                tool.get("transport", tool.get("transport_type", "streamable_http"))
            ).lower()
            name = tool.get("name", tool.get("display_name", "<unnamed>"))
            if transport == "stdio" or transport == "std_io":
                errors.append(
                    f"MCP tool '{name}' uses stdio transport which is incompatible with "
                    "CX Agent Studio. Migrate to StreamableHTTP transport or remove "
                    "this tool before exporting to CX."
                )
        return errors

    def check_function_dependencies(self, function_code: str) -> list[str]:
        """Check that a Python function's imports are available in the CX sandbox.

        Parses ``import`` and ``from … import`` statements in the function source
        and flags any top-level package that is not in the known sandbox allowlist.

        Args:
            function_code: Raw Python source code string for the function.

        Returns:
            List of warning strings for each potentially unavailable import.
        """
        warnings: list[str] = []
        for line in function_code.splitlines():
            stripped = line.strip()
            package: str | None = None

            if stripped.startswith("import "):
                # ``import foo`` or ``import foo as bar`` or ``import foo, bar``
                rest = stripped[len("import "):].split("#")[0].strip()
                for part in rest.split(","):
                    pkg = part.strip().split(" ")[0].split(".")[0]
                    if pkg:
                        package = pkg
                        _emit_if_not_safe(package, warnings)
                package = None  # already handled above

            elif stripped.startswith("from "):
                # ``from foo.bar import baz``
                rest = stripped[len("from "):].split(" import ")[0].strip()
                package = rest.split(".")[0]
                _emit_if_not_safe(package, warnings)

        return warnings

    def validate_for_export(self, config: dict[str, Any]) -> CxValidationResult:
        """Full pre-export validation: agent-level + all sub-agents.

        Runs ``validate_agent`` on the root config and recursively on any
        sub-agents stored in ``config["sub_agents"]`` or ``config["agents"]``.

        Args:
            config: AutoAgent config dict, potentially with nested sub-agents.

        Returns:
            Aggregated ``CxValidationResult`` for the entire agent tree.
        """
        root_result = self.validate_agent(config)

        # Recurse into sub-agents
        for sub in config.get("sub_agents", config.get("agents", [])):
            if isinstance(sub, dict):
                child_result = self.validate_for_export(sub)
                root_result.errors.extend(child_result.errors)
                root_result.warnings.extend(child_result.warnings)
                root_result.cx_portable_constructs.extend(child_result.cx_portable_constructs)
                root_result.adk_only_constructs.extend(child_result.adk_only_constructs)

        root_result.valid = len(root_result.errors) == 0
        return root_result

    def flag_mutation_breaks_portability(
        self,
        mutation: dict[str, Any],
        current_config: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Determine whether a proposed mutation would break CX portability.

        Compares the current config's CX validity against what validity would
        look like after the mutation is applied.  Returns a warning dict if
        portability is degraded, or ``None`` if the mutation is safe.

        Args:
            mutation: Partial config update dict (same shape as config).
            current_config: The current agent config dict (before mutation).

        Returns:
            A warning dict with ``"field"``, ``"reason"``, and
            ``"portability_impact"`` keys when portability would be broken,
            or ``None`` when the mutation is safe.
        """
        import copy

        before = self.validate_for_export(current_config)

        # Apply mutation as a shallow merge on a copy
        patched = copy.deepcopy(current_config)
        patched.update(mutation)

        after = self.validate_for_export(patched)

        # If mutation introduces new errors or new adk_only constructs, warn
        new_errors = [e for e in after.errors if e not in before.errors]
        new_adk_only = [
            c for c in after.adk_only_constructs if c not in before.adk_only_constructs
        ]

        if new_errors or new_adk_only:
            return {
                "field": list(mutation.keys()),
                "reason": (
                    f"Mutation introduces {len(new_errors)} new validation error(s) "
                    f"and {len(new_adk_only)} new ADK-only construct(s)."
                ),
                "portability_impact": {
                    "new_errors": new_errors,
                    "new_adk_only_constructs": new_adk_only,
                },
            }
        return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _emit_if_not_safe(package: str, warnings: list[str]) -> None:
    """Append a warning if *package* is not in the CX sandbox allowlist."""
    if not package or package.startswith("_"):
        return
    # Check against allowlist (prefix match so ``google.cloud.foo`` matches ``google.cloud``)
    safe = any(
        package == s or package.startswith(s + ".")
        for s in _SANDBOX_SAFE_PACKAGES
    )
    if not safe:
        warnings.append(
            f"Import '{package}' may not be available in the CX Agent Studio Python "
            "code tool sandbox. Verify availability or remove the dependency before export."
        )
