"""Pydantic models for ADK agent structures.

These types represent parsed ADK agent definitions extracted from Python source
code. They are intentionally separate from AutoAgent's internal config schema
so that the mapper layer can evolve each side independently.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class AdkAgentType(str, Enum):
    """Supported ADK agent orchestration types."""

    LLM_AGENT = "llm_agent"
    SEQUENTIAL_AGENT = "sequential_agent"
    PARALLEL_AGENT = "parallel_agent"
    LOOP_AGENT = "loop_agent"


class AdkToolType(str, Enum):
    """Supported ADK tool integration types."""

    FUNCTION_TOOL = "function_tool"
    AGENT_TOOL = "agent_tool"
    MCP_TOOLSET = "mcp_toolset"
    OPENAPI_TOOL = "openapi_tool"


class AdkCallbackSpec(BaseModel):
    """Specification for a named ADK callback function."""

    name: str
    callback_type: str
    function_name: str
    description: str = ""


class AdkSessionConfig(BaseModel):
    """Session-level configuration for ADK runtime execution."""

    state_prefixes: list[str] = Field(default_factory=lambda: ["user:", "app:", "temp:"])
    persistence: str = "memory"
    ttl_seconds: int = 3600


class AdkTemplateVar(BaseModel):
    """A single template variable binding for ADK instruction strings."""

    key: str
    source: str = "state"
    default: str = ""


class AdkAgentRef(BaseModel):
    """Lightweight reference identifying an ADK agent by its local directory path."""

    path: Path

    @property
    def absolute_path(self) -> Path:
        """Return the absolute path to the agent directory."""
        return self.path.resolve()


class AdkTool(BaseModel):
    """Parsed tool function from ADK agent source."""

    name: str
    description: str = ""  # Extracted from docstring
    function_body: str = ""  # Raw function source code for reference
    signature: str = ""  # Function signature (name + params)
    tool_type: AdkToolType = AdkToolType.FUNCTION_TOOL
    cx_portable: bool = True


class AdkAgent(BaseModel):
    """Parsed Agent definition from ADK source."""

    name: str = ""
    model: str = ""
    instruction: str = ""
    tools: list[str] = Field(default_factory=list)  # Tool names referenced
    sub_agents: list[str] = Field(default_factory=list)  # Sub-agent names referenced
    generate_config: dict = Field(default_factory=dict)  # temperature, max_output_tokens, etc.
    before_model_callback: str = ""  # Callback function name (reference only)
    after_model_callback: str = ""  # Callback function name (reference only)
    agent_type: AdkAgentType = AdkAgentType.LLM_AGENT
    before_agent_callback: str = ""  # Callback function name (reference only)
    after_agent_callback: str = ""  # Callback function name (reference only)
    before_tool_callback: str = ""  # Callback function name (reference only)
    after_tool_callback: str = ""  # Callback function name (reference only)
    cx_portable: bool = True


class AdkAgentTree(BaseModel):
    """Hierarchical structure representing a complete ADK agent with sub-agents."""

    agent: AdkAgent = Field(default_factory=AdkAgent)
    tools: list[AdkTool] = Field(default_factory=list)
    sub_agents: list[AdkAgentTree] = Field(default_factory=list)  # Recursive structure
    config: dict = Field(default_factory=dict)  # Merged from config.json if present
    source_path: Path = Path(".")  # Directory path where this agent was parsed from


class ImportResult(BaseModel):
    """Result of a successful ADK-to-AutoAgent import operation."""

    config_path: str
    snapshot_path: str
    agent_name: str
    surfaces_mapped: list[str] = Field(default_factory=list)
    tools_imported: int = 0


class ExportResult(BaseModel):
    """Result of exporting an optimized config back to ADK source."""

    output_path: str
    changes: list[dict] = Field(default_factory=list)
    files_modified: int = 0


class DeployResult(BaseModel):
    """Result of deploying an ADK agent to Cloud Run or Vertex AI."""

    target: str  # "cloud-run" or "vertex-ai"
    url: str = ""
    status: str = ""
    deployment_info: dict = Field(default_factory=dict)
