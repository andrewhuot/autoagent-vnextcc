"""Tests for Agent Card persistence: save, load, history, diff."""

from __future__ import annotations

import time

import pytest

from agent_card.persistence import (
    card_exists,
    default_card_path,
    diff_with_version,
    generate_and_save_from_config,
    list_history,
    load_card,
    load_card_markdown,
    save_card,
)
from agent_card.schema import (
    AgentCardModel,
    EnvironmentEntry,
    RoutingRuleEntry,
    SubAgentSection,
    ToolEntry,
)


def _make_card() -> AgentCardModel:
    return AgentCardModel(
        name="test_agent",
        description="A test agent",
        version="1.0",
        platform_origin="test",
        instructions="You are a helpful agent.",
        tools=[ToolEntry(name="search", description="Search tool")],
        routing_rules=[
            RoutingRuleEntry(target="support", keywords=["help"]),
        ],
        environment=EnvironmentEntry(model="gpt-4", temperature=0.3),
        sub_agents=[
            SubAgentSection(name="support", instructions="Handle support"),
        ],
    )


def _make_config() -> dict:
    return {
        "name": "config_agent",
        "prompts": {
            "root": "You are an orchestrator.",
            "support": "Handle support queries.",
        },
        "routing": {
            "rules": [{"specialist": "support", "keywords": ["help"]}],
        },
        "tools": {"faq": {"description": "FAQ lookup"}},
        "model": "gemini-2.0-flash",
    }


class TestSaveAndLoad:
    def test_save_creates_file(self, tmp_path):
        card = _make_card()
        path = save_card(card, workspace=tmp_path)
        assert path.is_file()
        assert path.name == "agent_card.md"

    def test_load_returns_card(self, tmp_path):
        card = _make_card()
        save_card(card, workspace=tmp_path)
        loaded = load_card(workspace=tmp_path)
        assert loaded.name == "test_agent"
        assert loaded.description == "A test agent"
        assert len(loaded.tools) == 1
        assert len(loaded.sub_agents) == 1

    def test_load_markdown_returns_string(self, tmp_path):
        card = _make_card()
        save_card(card, workspace=tmp_path)
        md = load_card_markdown(workspace=tmp_path)
        assert "# Agent Card: test_agent" in md
        assert "search" in md

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No Agent Card found"):
            load_card(workspace=tmp_path)

    def test_card_exists_true(self, tmp_path):
        save_card(_make_card(), workspace=tmp_path)
        assert card_exists(workspace=tmp_path) is True

    def test_card_exists_false(self, tmp_path):
        assert card_exists(workspace=tmp_path) is False

    def test_default_card_path(self, tmp_path):
        path = default_card_path(tmp_path)
        assert path.name == "agent_card.md"
        assert ".agentlab" in str(path)

    def test_save_overwrites(self, tmp_path):
        card1 = AgentCardModel(name="v1", instructions="First version")
        card2 = AgentCardModel(name="v2", instructions="Second version")

        save_card(card1, workspace=tmp_path)
        save_card(card2, workspace=tmp_path)

        loaded = load_card(workspace=tmp_path)
        assert loaded.name == "v2"

    def test_round_trip_preserves_fields(self, tmp_path):
        original = _make_card()
        save_card(original, workspace=tmp_path)
        loaded = load_card(workspace=tmp_path)

        assert loaded.name == original.name
        assert loaded.instructions == original.instructions
        assert len(loaded.tools) == len(original.tools)
        assert loaded.tools[0].name == original.tools[0].name
        assert len(loaded.routing_rules) == len(original.routing_rules)
        assert loaded.environment.model == original.environment.model


class TestGenerateAndSave:
    def test_from_config(self, tmp_path):
        config = _make_config()
        card = generate_and_save_from_config(
            config, name="config_agent", workspace=tmp_path,
        )
        assert card.name == "config_agent"
        assert card_exists(workspace=tmp_path)

        loaded = load_card(workspace=tmp_path)
        assert loaded.name == "config_agent"
        assert "orchestrator" in loaded.instructions


class TestHistory:
    def test_save_creates_history(self, tmp_path):
        save_card(_make_card(), workspace=tmp_path, reason="initial")
        history = list_history(workspace=tmp_path)
        assert len(history) == 1
        assert "initial" in history[0]["reason"]

    def test_multiple_saves_create_multiple_history(self, tmp_path):
        save_card(
            AgentCardModel(name="v1"),
            workspace=tmp_path,
            reason="first",
        )
        time.sleep(0.01)  # ensure different timestamps
        save_card(
            AgentCardModel(name="v2"),
            workspace=tmp_path,
            reason="second",
        )

        history = list_history(workspace=tmp_path)
        assert len(history) == 2
        # Newest first
        assert "second" in history[0]["reason"]
        assert "first" in history[1]["reason"]

    def test_no_history_returns_empty(self, tmp_path):
        assert list_history(workspace=tmp_path) == []

    def test_save_without_history(self, tmp_path):
        save_card(_make_card(), workspace=tmp_path, save_history=False)
        assert card_exists(workspace=tmp_path)
        assert list_history(workspace=tmp_path) == []


class TestDiff:
    def test_diff_shows_changes(self, tmp_path):
        save_card(
            AgentCardModel(name="agent", instructions="Original instructions"),
            workspace=tmp_path,
            reason="v1",
        )
        time.sleep(0.01)
        save_card(
            AgentCardModel(name="agent", instructions="Updated instructions with more detail"),
            workspace=tmp_path,
            reason="v2",
        )

        diff = diff_with_version(workspace=tmp_path)
        assert "Original" in diff or "Updated" in diff
        assert diff != "No changes."

    def test_diff_no_previous_version(self, tmp_path):
        save_card(_make_card(), workspace=tmp_path)
        diff = diff_with_version(workspace=tmp_path)
        assert "No previous version" in diff

    def test_diff_no_card(self, tmp_path):
        diff = diff_with_version(workspace=tmp_path)
        assert "No current Agent Card" in diff

    def test_diff_identical(self, tmp_path):
        card = _make_card()
        save_card(card, workspace=tmp_path, reason="v1")
        time.sleep(0.01)
        save_card(card, workspace=tmp_path, reason="v2")

        diff = diff_with_version(workspace=tmp_path)
        assert diff == "No changes."
