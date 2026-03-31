"""Tests for the connect API route."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import connect as connect_routes


def test_connect_import_route_creates_transcript_workspace(tmp_path: Path) -> None:
    """The connect API should create a transcript-backed workspace."""

    transcript_file = tmp_path / "conversations.jsonl"
    transcript_file.write_text(
        json.dumps(
            {
                "id": "conv-1",
                "messages": [
                    {"role": "user", "content": "Where is my order?"},
                    {"role": "assistant", "content": "Your order shipped yesterday."},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    app = FastAPI()
    app.include_router(connect_routes.router)
    client = TestClient(app)

    response = client.post(
        "/api/connect/import",
        json={
            "adapter": "transcript",
            "file": str(transcript_file),
            "output_dir": str(tmp_path),
            "workspace_name": "api-connect",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["adapter"] == "transcript"
    assert payload["agent_name"] == "transcript-import"
    assert Path(payload["workspace_path"]).exists()
