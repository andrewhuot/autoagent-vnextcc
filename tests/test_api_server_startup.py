"""Regression tests for importing the full API server."""

from __future__ import annotations

import importlib
import sys

import pytest


def test_api_server_imports_cleanly() -> None:
    """`api.server` should import without FastAPI route-construction errors."""
    sys.modules.pop("api.server", None)
    sys.modules.pop("api.routes.eval", None)
    sys.modules.pop("api.routes.compare", None)
    sys.modules.pop("api.routes.results", None)

    module = importlib.import_module("api.server")

    assert hasattr(module, "app")


def test_compare_and_results_routes_import_cleanly() -> None:
    """New compare/results routes should import without missing model errors."""
    sys.modules.pop("api.routes.compare", None)
    sys.modules.pop("api.routes.results", None)

    compare_module = importlib.import_module("api.routes.compare")
    results_module = importlib.import_module("api.routes.results")

    assert hasattr(compare_module, "router")
    assert hasattr(results_module, "router")


def test_api_server_startup_configures_generated_eval_persistence(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server startup should wire one shared generated-eval store into the API.

    WHY: The generated-suite review, acceptance, and browse flows rely on the
    real app exposing both `generated_eval_store` and an `auto_eval_generator`
    that persists into that same store.
    """

    fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
    from fastapi.testclient import TestClient

    monkeypatch.chdir(tmp_path)

    sys.modules.pop("api.server", None)
    module = importlib.import_module("api.server")

    with TestClient(module.app) as client:
        response = client.get("/api/evals/generated")

        assert response.status_code == 200
        assert response.json() == {"suites": [], "count": 0}
        assert hasattr(module.app.state, "generated_eval_store")
        assert module.app.state.generated_eval_store is not None
        assert getattr(module.app.state.auto_eval_generator, "_store", None) is module.app.state.generated_eval_store
