from __future__ import annotations

from cli.tools.mcp_bridge import McpToolSpec, _build_mcp_tool
from cli.tools.registry import default_registry, reset_default_registry


def test_bundled_tools_have_expected_concurrency_flags() -> None:
    reset_default_registry()
    registry = default_registry()

    expected_flags = {
        "AgentSpawn": False,
        "Bash": False,
        "ConfigEdit": False,
        "ConfigRead": True,
        "ExitPlanMode": False,
        "FileEdit": False,
        "FileRead": True,
        "FileWrite": False,
        "Glob": True,
        "Grep": True,
        "SkillTool": False,
        "TodoWrite": False,
        "WebFetch": True,
        "WebSearch": True,
    }

    actual_flags = {tool.name: tool.is_concurrency_safe for tool in registry.list()}

    assert actual_flags == expected_flags


def test_mcp_bridge_tools_default_to_non_concurrency_safe() -> None:
    tool = _build_mcp_tool(
        McpToolSpec(
            server_name="demo",
            name="lookup",
            description="demo tool",
            input_schema={"type": "object", "properties": {}},
        ),
        lambda server_name: None,
    )

    assert tool.is_concurrency_safe is False
