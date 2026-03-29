"""Regression tests for API server boot/import safety."""

from __future__ import annotations


def test_api_server_imports_without_route_model_errors() -> None:
    """Server import should not fail because a route references missing models."""
    __import__("api.server")
