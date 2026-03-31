"""Compatibility wrapper around the CX agent mapper."""

from __future__ import annotations

from adapters.cx_agent_mapper import CxAgentMapper


class CxMapper(CxAgentMapper):
    """Backward-compatible alias for the shared mapper implementation."""

