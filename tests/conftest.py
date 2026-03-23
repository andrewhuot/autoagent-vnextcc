"""Shared pytest fixtures for AutoAgent VNext tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from logger.store import ConversationStore


@pytest.fixture
def base_config() -> dict:
    """Load the baseline config used by tests."""
    root = Path(__file__).resolve().parents[1]
    config_path = root / "configs" / "v001_base.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def conversation_db_path(tmp_path: Path) -> Path:
    """Return a temporary path for conversation SQLite files."""
    return tmp_path / "conversations.db"


@pytest.fixture
def conversation_store(conversation_db_path: Path) -> ConversationStore:
    """Create a conversation store backed by a temp SQLite DB."""
    return ConversationStore(str(conversation_db_path))
