"""Tests for the typed `.mcp.json` pydantic config module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cli.mcp.config import (
    HttpServerConfig,
    McpConfig,
    SseServerConfig,
    StdioServerConfig,
    build_transport,
    load_config,
    save_config,
)
from cli.mcp.transports import (
    HttpStreamableTransport,
    SseTransport,
    StdioTransport,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_parse_modern_mixed_file(tmp_path: Path) -> None:
    """All three transports should parse from an explicit-transport file."""
    cfg_path = tmp_path / ".mcp.json"
    _write(
        cfg_path,
        {
            "mcpServers": {
                "browser": {
                    "transport": "stdio",
                    "command": "python",
                    "args": ["-m", "browser_mcp"],
                    "env": {"FOO": "bar"},
                },
                "remote-sse": {
                    "transport": "sse",
                    "url": "https://mcp.example.com/sse",
                    "headers": {"X-Key": "secret"},
                },
                "remote-http": {
                    "transport": "streamable-http",
                    "url": "https://mcp.example.com/",
                },
            }
        },
    )

    config = load_config(cfg_path)

    assert isinstance(config.mcp_servers["browser"], StdioServerConfig)
    assert isinstance(config.mcp_servers["remote-sse"], SseServerConfig)
    assert isinstance(config.mcp_servers["remote-http"], HttpServerConfig)


def test_parse_legacy_stdio_entries_without_transport(tmp_path: Path) -> None:
    """Entries missing the `transport` key should default to stdio."""
    cfg_path = tmp_path / ".mcp.json"
    _write(
        cfg_path,
        {
            "mcpServers": {
                "browser": {"command": "python", "args": ["-m", "browser_mcp"]},
                "agentlab": {"command": "agentlab", "args": ["mcp-server"]},
            }
        },
    )

    config = load_config(cfg_path)

    browser = config.mcp_servers["browser"]
    agentlab = config.mcp_servers["agentlab"]
    assert isinstance(browser, StdioServerConfig)
    assert browser.transport == "stdio"
    assert browser.command == "python"
    assert browser.args == ["-m", "browser_mcp"]
    assert isinstance(agentlab, StdioServerConfig)


def test_unknown_transport_is_rejected(tmp_path: Path) -> None:
    """An unknown transport string should surface a friendly error naming the server."""
    cfg_path = tmp_path / ".mcp.json"
    _write(
        cfg_path,
        {
            "mcpServers": {
                "weird": {"transport": "telepathy", "command": "python"},
            }
        },
    )

    with pytest.raises(ValueError) as excinfo:
        load_config(cfg_path)

    # The offending server name should appear in the message.
    assert "weird" in str(excinfo.value)


def test_stdio_entry_missing_command_rejected(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".mcp.json"
    _write(
        cfg_path,
        {
            "mcpServers": {
                "broken": {"transport": "stdio", "args": ["-m", "x"]},
            }
        },
    )

    with pytest.raises(ValueError) as excinfo:
        load_config(cfg_path)

    assert "broken" in str(excinfo.value)


def test_sse_entry_missing_url_rejected(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".mcp.json"
    _write(
        cfg_path,
        {"mcpServers": {"remote": {"transport": "sse", "headers": {}}}},
    )

    with pytest.raises(ValueError) as excinfo:
        load_config(cfg_path)

    assert "remote" in str(excinfo.value)


def test_roundtrip_preserves_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".mcp.json"
    original = McpConfig(
        mcp_servers={
            "browser": StdioServerConfig(
                command="python",
                args=["-m", "browser_mcp"],
                env={"FOO": "bar"},
            ),
            "remote-sse": SseServerConfig(
                transport="sse",
                url="https://mcp.example.com/sse",
                headers={"X-Key": "v"},
                ping_interval_seconds=15.0,
            ),
            "remote-http": HttpServerConfig(
                transport="streamable-http",
                url="https://mcp.example.com/",
            ),
        }
    )

    save_config(cfg_path, original)
    roundtrip = load_config(cfg_path)

    assert roundtrip.model_dump() == original.model_dump()


def test_build_transport_stdio() -> None:
    cfg = StdioServerConfig(
        command="python",
        args=["-m", "browser_mcp"],
        env={"FOO": "bar"},
    )

    transport = build_transport(cfg)

    assert isinstance(transport, StdioTransport)
    assert transport.command == ["python"]
    assert transport.args == ["-m", "browser_mcp"]
    assert transport.env == {"FOO": "bar"}


def test_build_transport_sse() -> None:
    cfg = SseServerConfig(
        transport="sse",
        url="https://mcp.example.com/sse",
        headers={"X-Key": "v"},
        ping_interval_seconds=12.5,
    )

    transport = build_transport(cfg)

    assert isinstance(transport, SseTransport)
    assert transport.url == "https://mcp.example.com/sse"
    assert transport.ping_interval_seconds == 12.5


def test_build_transport_streamable_http() -> None:
    cfg = HttpServerConfig(
        transport="streamable-http",
        url="https://mcp.example.com/",
    )

    transport = build_transport(cfg)

    assert isinstance(transport, HttpStreamableTransport)
    assert transport.url == "https://mcp.example.com/"


def test_mixed_transport_workspace(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".mcp.json"
    _write(
        cfg_path,
        {
            "mcpServers": {
                "a": {"command": "x"},
                "b": {"transport": "sse", "url": "https://e/sse"},
                "c": {"transport": "streamable-http", "url": "https://e/"},
            }
        },
    )

    config = load_config(cfg_path)

    assert set(config.mcp_servers) == {"a", "b", "c"}
    assert isinstance(config.mcp_servers["a"], StdioServerConfig)
    assert isinstance(config.mcp_servers["b"], SseServerConfig)
    assert isinstance(config.mcp_servers["c"], HttpServerConfig)


def test_missing_file_yields_empty_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".mcp.json"
    # File does not exist.
    config = load_config(cfg_path)
    assert config.mcp_servers == {}


def test_empty_mcp_servers_key_yields_empty(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".mcp.json"
    _write(cfg_path, {})
    config = load_config(cfg_path)
    assert config.mcp_servers == {}


def test_malformed_json_surfaces_clearly(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".mcp.json"
    cfg_path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        load_config(cfg_path)

    assert str(cfg_path) in str(excinfo.value) or "JSON" in str(excinfo.value)


def test_save_uses_mcpservers_alias(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".mcp.json"
    config = McpConfig(
        mcp_servers={"x": StdioServerConfig(command="python")},
    )
    save_config(cfg_path, config)
    on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "mcpServers" in on_disk
    assert "mcp_servers" not in on_disk


def test_populate_by_name_accepts_mcp_servers_key() -> None:
    """McpConfig should accept either `mcp_servers` or `mcpServers` on construction."""
    cfg = McpConfig.model_validate({"mcp_servers": {"a": {"command": "x"}}})
    assert "a" in cfg.mcp_servers


def test_validation_error_wrapped_is_value_error(tmp_path: Path) -> None:
    """The wrapper error surface should be a plain ValueError (or subclass)."""
    cfg_path = tmp_path / ".mcp.json"
    _write(cfg_path, {"mcpServers": {"nope": {"transport": "nope"}}})
    with pytest.raises(ValueError):
        load_config(cfg_path)


def test_direct_validation_error_on_model() -> None:
    """Direct construction of an invalid StdioServerConfig raises ValidationError."""
    with pytest.raises(ValidationError):
        StdioServerConfig()  # missing `command`
