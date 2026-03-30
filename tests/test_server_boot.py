"""Regression tests for API server boot/import safety."""

from __future__ import annotations

import pytest


def test_api_server_imports_without_route_model_errors() -> None:
    """Server import should not fail because a route references missing models."""
    pytest.importorskip("fastapi", reason="fastapi not installed")
    __import__("api.server")
