"""Typed settings schema for AgentLab."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

_MISSING = object()


def _default_shell_settings() -> dict[str, Any]:
    """Return the legacy shell defaults so empty config stays backward compatible."""
    return {
        "prompt": "agentlab> ",
        "show_status_bar": True,
    }


def _default_output_settings() -> dict[str, Any]:
    """Return the legacy output defaults so old callers keep the same behavior."""
    return {
        "format": "text",
        "color": True,
        "banner": True,
    }


def _dotted_lookup(node: Any, dotted_key: str, default: Any) -> Any:
    """Resolve ``dotted_key`` against a nested model/dict tree."""
    current = node
    for part in dotted_key.split("."):
        if isinstance(current, BaseModel):
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                return default
        elif isinstance(current, dict):
            if part not in current:
                return default
            current = current[part]
        else:
            return default
    if current is None:
        return default
    return current


class PermissionRules(BaseModel):
    """Allow, ask, and deny patterns used by permission checks."""

    model_config = ConfigDict(extra="forbid")

    allow: list[str] = Field(default_factory=list)
    ask: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class Permissions(BaseModel):
    """Permission defaults and explicit rules."""

    model_config = ConfigDict(extra="forbid")

    mode: str = "default"
    strict_live: bool = False
    rules: PermissionRules = Field(default_factory=PermissionRules)


class HookCommand(BaseModel):
    """One executable hook entry or prompt hook."""

    model_config = ConfigDict(extra="forbid")

    type: str = "command"
    command: str = ""
    prompt: str = ""
    timeout_seconds: int | None = None
    timeout: int | None = None
    shell: str = "bash"
    env: dict[str, str] = Field(default_factory=dict)
    id: str = ""


class HookMatcher(BaseModel):
    """Matcher plus nested hooks in the Claude Code settings shape."""

    model_config = ConfigDict(extra="forbid")

    matcher: str = ""
    hooks: list[HookCommand] = Field(default_factory=list)


class Hooks(BaseModel):
    """Lifecycle hooks keyed by Claude-Code-compatible event names."""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = 5
    beforeQuery: list[HookMatcher] = Field(default_factory=list)
    afterQuery: list[HookMatcher] = Field(default_factory=list)
    beforeTool: list[HookMatcher] = Field(default_factory=list)
    afterTool: list[HookMatcher] = Field(default_factory=list)
    PreToolUse: list[HookMatcher] = Field(default_factory=list)
    PostToolUse: list[HookMatcher] = Field(default_factory=list)
    OnPermissionRequest: list[HookMatcher] = Field(default_factory=list)
    SubagentStop: list[HookMatcher] = Field(default_factory=list)
    SessionEnd: list[HookMatcher] = Field(default_factory=list)
    Stop: list[HookMatcher] = Field(default_factory=list)

    def event_map(self) -> dict[str, list[HookMatcher]]:
        """Return only populated hook events for the runtime hook registry."""
        event_names = (
            "beforeQuery",
            "afterQuery",
            "beforeTool",
            "afterTool",
            "PreToolUse",
            "PostToolUse",
            "OnPermissionRequest",
            "SubagentStop",
            "SessionEnd",
            "Stop",
        )
        return {
            name: getattr(self, name)
            for name in event_names
            if getattr(self, name)
        }


class Providers(BaseModel):
    """Provider defaults and API keys loaded from files or env vars."""

    model_config = ConfigDict(extra="forbid")

    default_provider: str | None = None
    default_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None
    gemini_api_key: str | None = None
    models: dict[str, str] = Field(default_factory=dict)


class Sessions(BaseModel):
    """Session storage options."""

    model_config = ConfigDict(extra="forbid")

    root: str | None = None


class Paste(BaseModel):
    """Paste and image-store options reserved for later phases."""

    model_config = ConfigDict(extra="forbid")

    store_root: str | None = None
    inline_threshold_lines: int = 10


class Input(BaseModel):
    """Workbench input and TUI compatibility toggles."""

    model_config = ConfigDict(extra="forbid")

    expose_slash_to_model: bool = False
    no_tui: bool = False


class MCP(BaseModel):
    """MCP configuration placeholder for later transport parity."""

    model_config = ConfigDict(extra="forbid")

    servers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Settings(BaseModel):
    """Fully resolved AgentLab settings."""

    model_config = ConfigDict(extra="forbid")

    permissions: Permissions = Field(default_factory=Permissions)
    hooks: Hooks = Field(default_factory=Hooks)
    providers: Providers = Field(default_factory=Providers)
    sessions: Sessions = Field(default_factory=Sessions)
    paste: Paste = Field(default_factory=Paste)
    input: Input = Field(default_factory=Input)
    mcp: MCP = Field(default_factory=MCP)
    models: dict[str, str] = Field(default_factory=dict)
    theme: dict[str, Any] = Field(default_factory=dict)
    shell: dict[str, Any] = Field(default_factory=_default_shell_settings)
    output: dict[str, Any] = Field(default_factory=_default_output_settings)
    mode: str = "default"
    editor: str | None = None

    _loaded_layers: list[dict[str, str]] = PrivateAttr(default_factory=list)
    _env_overrides: list[str] = PrivateAttr(default_factory=list)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Read dotted settings keys so older call sites keep working."""
        return _dotted_lookup(self, dotted_key, default)
