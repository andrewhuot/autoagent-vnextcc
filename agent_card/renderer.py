"""Render Agent Card to/from human-readable markdown.

The markdown format is designed to be:
1. Human-readable and editable in any text editor
2. Machine-parseable for round-trip fidelity
3. Version-controllable with meaningful diffs

Format uses YAML frontmatter for structured metadata and markdown body
for the agent definition. Each section uses consistent heading levels
so parsing is deterministic.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .schema import (
    AgentCardModel,
    CallbackEntry,
    CallbackTiming,
    EnvironmentEntry,
    GuardrailEntry,
    HandoffEntry,
    McpServerEntry,
    PolicyEntry,
    RoutingRuleEntry,
    SubAgentSection,
    ToolEntry,
)


# ---------------------------------------------------------------------------
# Render to markdown
# ---------------------------------------------------------------------------


def render_to_markdown(card: AgentCardModel) -> str:
    """Serialize an AgentCardModel to a human-readable markdown document."""
    sections: list[str] = []

    # YAML frontmatter
    frontmatter = {
        "name": card.name,
        "version": card.version,
        "platform_origin": card.platform_origin,
    }
    if card.description:
        frontmatter["description"] = card.description
    if card.metadata:
        frontmatter["metadata"] = card.metadata

    sections.append("---")
    sections.append(yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip())
    sections.append("---")
    sections.append("")

    # Title
    sections.append(f"# Agent Card: {card.name}")
    sections.append("")

    # Overview
    if card.description:
        sections.append(f"> {card.description}")
        sections.append("")

    # Environment
    if card.environment and (card.environment.model or card.environment.provider):
        sections.append("## Environment")
        sections.append("")
        env = card.environment
        if env.model:
            sections.append(f"- **Model**: {env.model}")
        if env.provider:
            sections.append(f"- **Provider**: {env.provider}")
        if env.temperature is not None:
            sections.append(f"- **Temperature**: {env.temperature}")
        if env.max_tokens is not None:
            sections.append(f"- **Max Tokens**: {env.max_tokens}")
        if env.top_p is not None:
            sections.append(f"- **Top P**: {env.top_p}")
        if env.top_k is not None:
            sections.append(f"- **Top K**: {env.top_k}")
        for key, value in env.settings.items():
            sections.append(f"- **{key}**: {value}")
        sections.append("")

    # Root instructions
    if card.instructions:
        sections.append("## Instructions")
        sections.append("")
        sections.append(card.instructions)
        sections.append("")

    # Tools
    if card.tools:
        sections.append("## Tools")
        sections.append("")
        for tool in card.tools:
            sections.append(_render_tool(tool, heading_level=3))

    # Callbacks
    if card.callbacks:
        sections.append("## Callbacks")
        sections.append("")
        for cb in card.callbacks:
            sections.append(_render_callback(cb, heading_level=3))

    # Routing rules
    if card.routing_rules:
        sections.append("## Routing Rules")
        sections.append("")
        sections.append(_render_routing_table(card.routing_rules))
        sections.append("")

    # Guardrails
    if card.guardrails:
        sections.append("## Guardrails")
        sections.append("")
        sections.append(_render_guardrails_table(card.guardrails))
        sections.append("")

    # Policies
    if card.policies:
        sections.append("## Policies")
        sections.append("")
        sections.append(_render_policies_table(card.policies))
        sections.append("")

    # Handoffs
    if card.handoffs:
        sections.append("## Handoffs")
        sections.append("")
        sections.append(_render_handoffs_table(card.handoffs))
        sections.append("")

    # MCP Servers
    if card.mcp_servers:
        sections.append("## MCP Servers")
        sections.append("")
        for mcp in card.mcp_servers:
            sections.append(_render_mcp_server(mcp, heading_level=3))

    # Sub-agents
    if card.sub_agents:
        sections.append("## Sub-Agents")
        sections.append("")
        for sa in card.sub_agents:
            sections.append(_render_sub_agent(sa, heading_level=3))

    # Example traces
    if card.example_traces:
        sections.append("## Example Traces")
        sections.append("")
        sections.append("```yaml")
        sections.append(yaml.dump(card.example_traces, default_flow_style=False).strip())
        sections.append("```")
        sections.append("")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Parse from markdown
# ---------------------------------------------------------------------------


def parse_from_markdown(text: str) -> AgentCardModel:
    """Parse a markdown Agent Card back into an AgentCardModel.

    This parser uses the heading structure and section conventions to
    reconstruct the model. It is intentionally tolerant of minor formatting
    variations while being strict about section headings.
    """
    frontmatter, body = _split_frontmatter(text)

    fm = yaml.safe_load(frontmatter) if frontmatter else {}
    if not isinstance(fm, dict):
        fm = {}

    sections = _split_sections(body)

    card = AgentCardModel(
        name=fm.get("name", ""),
        version=str(fm.get("version", "1.0")),
        platform_origin=fm.get("platform_origin", ""),
        description=fm.get("description", ""),
        metadata=fm.get("metadata", {}),
    )

    # Parse each section
    for heading, content in sections:
        normalized = heading.strip().lower()

        if normalized == "environment":
            card.environment = _parse_environment(content)
        elif normalized == "instructions":
            card.instructions = content.strip()
        elif normalized == "tools":
            card.tools = _parse_tools(content)
        elif normalized == "callbacks":
            card.callbacks = _parse_callbacks(content)
        elif normalized == "routing rules":
            card.routing_rules = _parse_routing_rules(content)
        elif normalized == "guardrails":
            card.guardrails = _parse_guardrails(content)
        elif normalized == "policies":
            card.policies = _parse_policies(content)
        elif normalized == "handoffs":
            card.handoffs = _parse_handoffs(content)
        elif normalized == "mcp servers":
            card.mcp_servers = _parse_mcp_servers(content)
        elif normalized == "sub-agents":
            card.sub_agents = _parse_sub_agents(content)
        elif normalized == "example traces":
            card.example_traces = _parse_example_traces(content)

    return card


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _render_tool(tool: ToolEntry, heading_level: int = 3) -> str:
    h = "#" * heading_level
    lines = [f"{h} {tool.name}", ""]
    if tool.description:
        lines.append(f"- **Description**: {tool.description}")
    if tool.parameters:
        lines.append("- **Parameters**:")
        for p in tool.parameters:
            name = p.get("name", "?")
            ptype = p.get("type", "string")
            required = "required" if p.get("required") else "optional"
            desc = p.get("description", "")
            param_line = f"  - `{name}` ({ptype}, {required})"
            if desc:
                param_line += f" — {desc}"
            lines.append(param_line)
    if tool.timeout_ms is not None:
        lines.append(f"- **Timeout**: {tool.timeout_ms}ms")
    if tool.invocation_hint != "auto":
        lines.append(f"- **Invocation**: {tool.invocation_hint}")
    lines.append("")
    return "\n".join(lines)


def _render_callback(cb: CallbackEntry, heading_level: int = 3) -> str:
    h = "#" * heading_level
    lines = [f"{h} {cb.timing.value}: {cb.name}", ""]
    if cb.description:
        lines.append(f"- **Description**: {cb.description}")
    if cb.function_name:
        lines.append(f"- **Function**: `{cb.function_name}`")
    if cb.signature:
        lines.append(f"- **Signature**: `{cb.signature}`")
    if cb.body:
        lines.append("- **Body**:")
        lines.append("```python")
        lines.append(cb.body)
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _render_routing_table(rules: list[RoutingRuleEntry]) -> str:
    lines = [
        "| Target | Condition | Keywords | Patterns | Priority | Fallback |",
        "|--------|-----------|----------|----------|----------|----------|",
    ]
    for r in rules:
        kw = ", ".join(r.keywords) if r.keywords else ""
        pat = ", ".join(r.patterns) if r.patterns else ""
        fb = "yes" if r.fallback else "no"
        lines.append(f"| {r.target} | {r.condition_type} | {kw} | {pat} | {r.priority} | {fb} |")
    return "\n".join(lines)


def _render_guardrails_table(guardrails: list[GuardrailEntry]) -> str:
    lines = [
        "| Name | Type | Enforcement | Description |",
        "|------|------|-------------|-------------|",
    ]
    for g in guardrails:
        lines.append(f"| {g.name} | {g.type} | {g.enforcement} | {g.description} |")
    return "\n".join(lines)


def _render_policies_table(policies: list[PolicyEntry]) -> str:
    lines = [
        "| Name | Type | Enforcement | Description |",
        "|------|------|-------------|-------------|",
    ]
    for p in policies:
        lines.append(f"| {p.name} | {p.type} | {p.enforcement} | {p.description} |")
    return "\n".join(lines)


def _render_handoffs_table(handoffs: list[HandoffEntry]) -> str:
    lines = [
        "| Source | Target | Context Transfer | Condition |",
        "|--------|--------|-----------------|-----------|",
    ]
    for h in handoffs:
        lines.append(f"| {h.source} | {h.target} | {h.context_transfer} | {h.condition} |")
    return "\n".join(lines)


def _render_mcp_server(mcp: McpServerEntry, heading_level: int = 3) -> str:
    h = "#" * heading_level
    lines = [f"{h} {mcp.name}", ""]
    if mcp.tools_exposed:
        lines.append(f"- **Tools**: {', '.join(mcp.tools_exposed)}")
    if mcp.config:
        lines.append("- **Config**:")
        lines.append("```yaml")
        lines.append(yaml.dump(mcp.config, default_flow_style=False).strip())
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _render_sub_agent(sa: SubAgentSection, heading_level: int = 3) -> str:
    h = "#" * heading_level
    lines = [f"{h} {sa.name}", ""]
    if sa.description:
        lines.append(f"> {sa.description}")
        lines.append("")
    if sa.agent_type != "llm_agent":
        lines.append(f"- **Type**: {sa.agent_type}")

    # Environment
    if sa.environment and (sa.environment.model or sa.environment.provider):
        env = sa.environment
        if env.model:
            lines.append(f"- **Model**: {env.model}")
        if env.provider:
            lines.append(f"- **Provider**: {env.provider}")
    lines.append("")

    # Instructions
    if sa.instructions:
        hh = "#" * (heading_level + 1)
        lines.append(f"{hh} Instructions")
        lines.append("")
        lines.append(sa.instructions)
        lines.append("")

    # Tools
    if sa.tools:
        hh = "#" * (heading_level + 1)
        lines.append(f"{hh} Tools")
        lines.append("")
        for tool in sa.tools:
            lines.append(_render_tool(tool, heading_level=heading_level + 2))

    # Callbacks
    if sa.callbacks:
        hh = "#" * (heading_level + 1)
        lines.append(f"{hh} Callbacks")
        lines.append("")
        for cb in sa.callbacks:
            lines.append(_render_callback(cb, heading_level=heading_level + 2))

    # Routing rules
    if sa.routing_rules:
        hh = "#" * (heading_level + 1)
        lines.append(f"{hh} Routing Rules")
        lines.append("")
        lines.append(_render_routing_table(sa.routing_rules))
        lines.append("")

    # Guardrails
    if sa.guardrails:
        hh = "#" * (heading_level + 1)
        lines.append(f"{hh} Guardrails")
        lines.append("")
        lines.append(_render_guardrails_table(sa.guardrails))
        lines.append("")

    # Nested sub-agents
    if sa.sub_agents:
        hh = "#" * (heading_level + 1)
        lines.append(f"{hh} Sub-Agents")
        lines.append("")
        for child in sa.sub_agents:
            lines.append(_render_sub_agent(child, heading_level=heading_level + 2))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body."""
    stripped = text.strip()
    if not stripped.startswith("---"):
        return "", stripped

    end = stripped.find("---", 3)
    if end == -1:
        return "", stripped

    frontmatter = stripped[3:end].strip()
    body = stripped[end + 3:].strip()
    return frontmatter, body


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split markdown body into (heading, content) pairs at ## level."""
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in body.split("\n"):
        # Match ## heading but not ### or deeper
        match = re.match(r"^##\s+(.+)$", line)
        if match:
            if current_heading:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = match.group(1).strip()
            current_lines = []
        elif current_heading:
            current_lines.append(line)

    if current_heading:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    return sections


def _parse_list_item(line: str, key: str) -> str | None:
    """Extract value from a markdown list item like '- **Key**: value'."""
    pattern = rf"^-\s+\*\*{re.escape(key)}\*\*:\s*(.+)$"
    match = re.match(pattern, line.strip())
    return match.group(1).strip() if match else None


def _parse_environment(content: str) -> EnvironmentEntry:
    env = EnvironmentEntry()
    for line in content.split("\n"):
        line = line.strip()
        val = _parse_list_item(line, "Model")
        if val:
            env.model = val
            continue
        val = _parse_list_item(line, "Provider")
        if val:
            env.provider = val
            continue
        val = _parse_list_item(line, "Temperature")
        if val:
            env.temperature = float(val)
            continue
        val = _parse_list_item(line, "Max Tokens")
        if val:
            env.max_tokens = int(val)
            continue
        val = _parse_list_item(line, "Top P")
        if val:
            env.top_p = float(val)
            continue
        val = _parse_list_item(line, "Top K")
        if val:
            env.top_k = int(val)
            continue
    return env


def _parse_tools(content: str) -> list[ToolEntry]:
    """Parse tool entries from ### headings within the Tools section."""
    tools: list[ToolEntry] = []
    tool_blocks = re.split(r"^###\s+", content, flags=re.MULTILINE)

    for block in tool_blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        name = lines[0].strip()
        if not name:
            continue

        tool = ToolEntry(name=name)
        body_text = "\n".join(lines[1:])

        desc = _find_field(body_text, "Description")
        if desc:
            tool.description = desc
        timeout = _find_field(body_text, "Timeout")
        if timeout:
            tool.timeout_ms = int(timeout.replace("ms", "").strip())
        invocation = _find_field(body_text, "Invocation")
        if invocation:
            tool.invocation_hint = invocation

        # Parse parameters
        tool.parameters = _parse_tool_parameters(body_text)

        tools.append(tool)

    return tools


def _parse_tool_parameters(text: str) -> list[dict[str, Any]]:
    """Parse parameter entries from indented list items under Parameters."""
    params: list[dict[str, Any]] = []
    in_params = False

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- **Parameters**:"):
            in_params = True
            continue
        if in_params:
            if stripped.startswith("- **"):
                in_params = False
                continue
            match = re.match(r"^\s*-\s+`(\w+)`\s+\(([^)]+)\)", stripped)
            if match:
                pname = match.group(1)
                pinfo = match.group(2)
                parts = [p.strip() for p in pinfo.split(",")]
                ptype = parts[0] if parts else "string"
                required = "required" in pinfo
                desc_match = re.search(r"—\s*(.+)$", stripped)
                desc = desc_match.group(1).strip() if desc_match else ""
                params.append({
                    "name": pname,
                    "type": ptype,
                    "required": required,
                    "description": desc,
                })
    return params


def _parse_callbacks(content: str) -> list[CallbackEntry]:
    """Parse callback entries from ### headings."""
    callbacks: list[CallbackEntry] = []
    cb_blocks = re.split(r"^###\s+", content, flags=re.MULTILINE)

    for block in cb_blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        header = lines[0].strip()

        # Parse "timing: name" format
        match = re.match(r"^(\w+):\s+(.+)$", header)
        if not match:
            continue

        timing_str = match.group(1).strip()
        name = match.group(2).strip()

        try:
            timing = CallbackTiming(timing_str)
        except ValueError:
            continue

        cb = CallbackEntry(name=name, timing=timing)
        body_text = "\n".join(lines[1:])

        desc = _find_field(body_text, "Description")
        if desc:
            cb.description = desc
        func = _find_field(body_text, "Function")
        if func:
            cb.function_name = func.strip("`")
        sig = _find_field(body_text, "Signature")
        if sig:
            cb.signature = sig.strip("`")

        # Extract code body
        code_match = re.search(r"```python\n(.*?)```", body_text, flags=re.DOTALL)
        if code_match:
            cb.body = code_match.group(1).strip()

        callbacks.append(cb)

    return callbacks


def _parse_routing_rules(content: str) -> list[RoutingRuleEntry]:
    """Parse routing rules from markdown table."""
    rules: list[RoutingRuleEntry] = []
    for row in _parse_table_rows(content):
        if len(row) < 4:
            continue
        rules.append(RoutingRuleEntry(
            target=row[0].strip(),
            condition_type=row[1].strip() or "keyword",
            keywords=[k.strip() for k in row[2].split(",") if k.strip()],
            patterns=[p.strip() for p in row[3].split(",") if p.strip()] if len(row) > 3 else [],
            priority=int(row[4].strip()) if len(row) > 4 and row[4].strip().lstrip("-").isdigit() else 0,
            fallback=row[5].strip().lower() == "yes" if len(row) > 5 else False,
        ))
    return rules


def _parse_guardrails(content: str) -> list[GuardrailEntry]:
    """Parse guardrails from markdown table."""
    guardrails: list[GuardrailEntry] = []
    for row in _parse_table_rows(content):
        if len(row) < 3:
            continue
        guardrails.append(GuardrailEntry(
            name=row[0].strip(),
            type=row[1].strip() or "both",
            enforcement=row[2].strip() or "block",
            description=row[3].strip() if len(row) > 3 else "",
        ))
    return guardrails


def _parse_policies(content: str) -> list[PolicyEntry]:
    """Parse policies from markdown table."""
    policies: list[PolicyEntry] = []
    for row in _parse_table_rows(content):
        if len(row) < 3:
            continue
        policies.append(PolicyEntry(
            name=row[0].strip(),
            type=row[1].strip() or "behavioral",
            enforcement=row[2].strip() or "recommended",
            description=row[3].strip() if len(row) > 3 else "",
        ))
    return policies


def _parse_handoffs(content: str) -> list[HandoffEntry]:
    """Parse handoffs from markdown table."""
    handoffs: list[HandoffEntry] = []
    for row in _parse_table_rows(content):
        if len(row) < 3:
            continue
        handoffs.append(HandoffEntry(
            source=row[0].strip(),
            target=row[1].strip(),
            context_transfer=row[2].strip() or "full",
            condition=row[3].strip() if len(row) > 3 else "",
        ))
    return handoffs


def _parse_mcp_servers(content: str) -> list[McpServerEntry]:
    """Parse MCP server entries from ### headings."""
    servers: list[McpServerEntry] = []
    blocks = re.split(r"^###\s+", content, flags=re.MULTILINE)

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        name = lines[0].strip()
        if not name:
            continue

        mcp = McpServerEntry(name=name)
        body_text = "\n".join(lines[1:])

        tools_str = _find_field(body_text, "Tools")
        if tools_str:
            mcp.tools_exposed = [t.strip() for t in tools_str.split(",") if t.strip()]

        # Parse YAML config block
        config_match = re.search(r"```yaml\n(.*?)```", body_text, flags=re.DOTALL)
        if config_match:
            parsed = yaml.safe_load(config_match.group(1).strip())
            if isinstance(parsed, dict):
                mcp.config = parsed

        servers.append(mcp)

    return servers


def _parse_sub_agents(content: str) -> list[SubAgentSection]:
    """Parse sub-agent sections from ### headings."""
    agents: list[SubAgentSection] = []
    # Split on ### but not #### or deeper
    blocks = _split_at_heading(content, level=3)

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        name = lines[0].strip()
        if not name:
            continue

        sa = SubAgentSection(name=name)
        body = "\n".join(lines[1:])

        # Parse description (blockquote)
        desc_match = re.match(r"^\s*>\s*(.+?)$", body.strip(), re.MULTILINE)
        if desc_match:
            sa.description = desc_match.group(1).strip()

        # Parse agent type
        agent_type = _find_field(body, "Type")
        if agent_type:
            sa.agent_type = agent_type

        # Parse model/provider
        model = _find_field(body, "Model")
        if model:
            sa.environment.model = model
        provider = _find_field(body, "Provider")
        if provider:
            sa.environment.provider = provider

        # Parse sub-sections at #### level
        sub_sections = _split_sub_sections(body, level=4)
        for sub_heading, sub_content in sub_sections:
            sub_norm = sub_heading.strip().lower()
            if sub_norm == "instructions":
                sa.instructions = sub_content.strip()
            elif sub_norm == "tools":
                sa.tools = _parse_tools_at_level(sub_content, level=5)
            elif sub_norm == "callbacks":
                sa.callbacks = _parse_callbacks_at_level(sub_content, level=5)
            elif sub_norm == "routing rules":
                sa.routing_rules = _parse_routing_rules(sub_content)
            elif sub_norm == "guardrails":
                sa.guardrails = _parse_guardrails(sub_content)
            elif sub_norm == "sub-agents":
                sa.sub_agents = _parse_nested_sub_agents(sub_content, level=5)

        agents.append(sa)

    return agents


def _parse_example_traces(content: str) -> list[dict[str, Any]]:
    """Parse example traces from YAML code block."""
    match = re.search(r"```yaml\n(.*?)```", content, flags=re.DOTALL)
    if match:
        parsed = yaml.safe_load(match.group(1).strip())
        if isinstance(parsed, list):
            return parsed
    return []


# ---------------------------------------------------------------------------
# Sub-section parsing helpers
# ---------------------------------------------------------------------------


def _split_sub_sections(body: str, level: int = 4) -> list[tuple[str, str]]:
    """Split body into sub-sections at specified heading level."""
    prefix = "#" * level
    pattern = rf"^{prefix}\s+(.+)$"
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in body.split("\n"):
        match = re.match(pattern, line)
        if match:
            if current_heading:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = match.group(1).strip()
            current_lines = []
        elif current_heading:
            current_lines.append(line)

    if current_heading:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    return sections


def _parse_tools_at_level(content: str, level: int = 5) -> list[ToolEntry]:
    """Parse tools from headings at a specific level."""
    prefix = "#" * level
    blocks = re.split(rf"^{prefix}\s+", content, flags=re.MULTILINE)
    tools: list[ToolEntry] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        name = lines[0].strip()
        if not name:
            continue

        tool = ToolEntry(name=name)
        body_text = "\n".join(lines[1:])
        desc = _find_field(body_text, "Description")
        if desc:
            tool.description = desc
        timeout = _find_field(body_text, "Timeout")
        if timeout:
            tool.timeout_ms = int(timeout.replace("ms", "").strip())
        tool.parameters = _parse_tool_parameters(body_text)
        tools.append(tool)

    return tools


def _parse_callbacks_at_level(content: str, level: int = 5) -> list[CallbackEntry]:
    """Parse callbacks from headings at a specific level."""
    prefix = "#" * level
    blocks = re.split(rf"^{prefix}\s+", content, flags=re.MULTILINE)
    callbacks: list[CallbackEntry] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        header = lines[0].strip()
        match = re.match(r"^(\w+):\s+(.+)$", header)
        if not match:
            continue
        try:
            timing = CallbackTiming(match.group(1).strip())
        except ValueError:
            continue
        cb = CallbackEntry(name=match.group(2).strip(), timing=timing)
        body_text = "\n".join(lines[1:])
        desc = _find_field(body_text, "Description")
        if desc:
            cb.description = desc
        func = _find_field(body_text, "Function")
        if func:
            cb.function_name = func.strip("`")
        code_match = re.search(r"```python\n(.*?)```", body_text, flags=re.DOTALL)
        if code_match:
            cb.body = code_match.group(1).strip()
        callbacks.append(cb)

    return callbacks


def _parse_nested_sub_agents(content: str, level: int = 5) -> list[SubAgentSection]:
    """Parse nested sub-agents at a deeper heading level."""
    prefix = "#" * level
    blocks = _split_at_heading(content, level=level)
    agents: list[SubAgentSection] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        name = lines[0].strip()
        if not name:
            continue
        sa = SubAgentSection(name=name)
        body = "\n".join(lines[1:])

        desc_match = re.match(r"^\s*>\s*(.+?)$", body.strip(), re.MULTILINE)
        if desc_match:
            sa.description = desc_match.group(1).strip()

        sub_sections = _split_sub_sections(body, level=level + 1)
        for sub_heading, sub_content in sub_sections:
            if sub_heading.strip().lower() == "instructions":
                sa.instructions = sub_content.strip()

        agents.append(sa)

    return agents


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _split_at_heading(content: str, level: int) -> list[str]:
    """Split content at a specific heading level without matching deeper levels.

    Returns a list of blocks where the first line of each is the heading text
    (without the # prefix). The first block may be empty or contain text
    before the first heading.
    """
    prefix = "#" * level
    blocks: list[str] = []
    current_lines: list[str] = []

    for line in content.split("\n"):
        stripped = line.lstrip()
        # Match exact heading level: N '#' chars followed by space, not N+1
        if stripped.startswith(prefix + " ") and not stripped.startswith(prefix + "#"):
            if current_lines:
                blocks.append("\n".join(current_lines))
            # Start new block with heading text (strip the prefix)
            heading_text = stripped[len(prefix):].strip()
            current_lines = [heading_text]
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append("\n".join(current_lines))

    return blocks


def _find_field(text: str, key: str) -> str | None:
    """Find a markdown list field value by key."""
    pattern = rf"^\s*-\s+\*\*{re.escape(key)}\*\*:\s*(.+)$"
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _parse_table_rows(content: str) -> list[list[str]]:
    """Parse a markdown table into rows (skipping header and separator)."""
    rows: list[list[str]] = []
    lines = content.strip().split("\n")
    for i, line in enumerate(lines):
        line = line.strip()
        if not line.startswith("|"):
            continue
        # Skip separator row
        if re.match(r"^\|[\s\-|]+\|$", line):
            continue
        # Skip header row (first pipe row)
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if i == 0:
            continue  # header
        rows.append(cells)
    return rows
