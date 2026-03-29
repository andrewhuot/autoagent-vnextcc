from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import quickfix as quickfix_routes


class _RunbookStore:
    """Minimal runbook store for preview-mode quickfix tests."""

    def get(self, name: str):
        return {"name": name}


def test_quickfix_marks_mock_results_as_preview_only() -> None:
    app = FastAPI()
    app.include_router(quickfix_routes.router)
    app.state.runbook_store = _RunbookStore()

    response = TestClient(app).post(
        "/api/quickfix",
        json={"failure_family": "routing_error"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "mock"
    assert payload["applied"] is False
    assert "preview only" in payload["warning"].lower()
