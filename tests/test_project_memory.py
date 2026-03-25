"""Unit tests for core.project_memory — ProjectMemory load/save/parse."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.project_memory import AUTOAGENT_MD_FILENAME, ProjectMemory


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------


class TestGenerateTemplate:
    def test_generate_template(self):
        tmpl = ProjectMemory.generate_template(
            agent_name="TestBot",
            platform="LangGraph",
            use_case="Customer support",
        )
        assert "TestBot" in tmpl
        assert "LangGraph" in tmpl
        assert "Customer support" in tmpl
        assert "## Agent Identity" in tmpl
        assert "## Business Constraints" in tmpl
        assert "## Known Good Patterns" in tmpl
        assert "## Known Bad Patterns" in tmpl
        assert "## Team Preferences" in tmpl
        assert "## Optimization History" in tmpl


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParse:
    def test_parse_empty(self):
        mem = ProjectMemory._parse("")
        assert mem.agent_name == ""
        assert mem.business_constraints == []

    def test_parse_full_template(self):
        tmpl = ProjectMemory.generate_template(
            agent_name="ParseBot", platform="ADK", use_case="Demo"
        )
        mem = ProjectMemory._parse(tmpl)
        assert mem.agent_name == "ParseBot"
        assert mem.platform == "ADK"
        assert mem.use_case == "Demo"
        # Template has default constraint items
        assert any("latency" in c.lower() for c in mem.business_constraints)

    def test_parse_custom_content(self):
        content = """# AUTOAGENT.md \u2014 Project Memory

## Agent Identity
- Name: CustomBot
- Platform: CrewAI
- Primary use case: Sales assistant

## Business Constraints
- Max latency 2s
- Budget $100/day

## Known Good Patterns
- Chain of thought works well

## Known Bad Patterns
- Verbose system prompts cause confusion

## Team Preferences
- Prefer minimal edits

## Optimization History
- 2025-01-01: Initial deployment
"""
        mem = ProjectMemory._parse(content)
        assert mem.agent_name == "CustomBot"
        assert mem.platform == "CrewAI"
        assert len(mem.business_constraints) == 2
        assert len(mem.known_good_patterns) == 1
        assert len(mem.known_bad_patterns) == 1
        assert len(mem.team_preferences) == 1
        assert len(mem.optimization_history) == 1


# ---------------------------------------------------------------------------
# Save / Load
# ---------------------------------------------------------------------------


class TestSaveLoad:
    def test_save_and_load(self, tmp_path: Path):
        mem = ProjectMemory(
            agent_name="SaveBot",
            platform="ADK",
            use_case="Testing",
            business_constraints=["Max cost $50"],
            known_good_patterns=["Pattern A"],
        )
        mem.save(str(tmp_path))
        loaded = ProjectMemory.load(str(tmp_path))
        assert loaded is not None
        assert loaded.agent_name == "SaveBot"
        assert loaded.platform == "ADK"
        assert "Max cost $50" in loaded.business_constraints

    def test_load_not_found(self, tmp_path: Path):
        result = ProjectMemory.load(str(tmp_path / "nonexistent"))
        assert result is None


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------


class TestMutationHelpers:
    def test_add_history_entry(self):
        mem = ProjectMemory()
        mem.add_history_entry("Ran cycle 1")
        assert len(mem.optimization_history) == 1
        assert "Ran cycle 1" in mem.optimization_history[0]
        # Should contain a date stamp
        assert "- 20" in mem.optimization_history[0]

    def test_add_note_good_patterns(self):
        mem = ProjectMemory()
        mem.add_note("good patterns", "CoT helps")
        assert len(mem.known_good_patterns) == 1
        assert "CoT helps" in mem.known_good_patterns[0]

    def test_add_note_bad_patterns(self):
        mem = ProjectMemory()
        mem.add_note("bad patterns", "Long prompts fail")
        assert len(mem.known_bad_patterns) == 1

    def test_add_note_preferences(self):
        mem = ProjectMemory()
        mem.add_note("team preferences", "Minimal changes")
        assert len(mem.team_preferences) == 1

    def test_add_note_constraints(self):
        mem = ProjectMemory()
        mem.add_note("business constraints", "Budget $10/day")
        assert len(mem.business_constraints) == 1


# ---------------------------------------------------------------------------
# Structured accessors
# ---------------------------------------------------------------------------


class TestAccessors:
    def test_get_optimizer_context(self):
        mem = ProjectMemory(
            agent_name="CtxBot",
            platform="ADK",
            use_case="QA",
            business_constraints=["Budget limit"],
            known_bad_patterns=["Avoid verbose"],
            team_preferences=["Minimal edits"],
            known_good_patterns=["CoT"],
        )
        ctx = mem.get_optimizer_context()
        assert "CtxBot" in ctx["agent_identity"]
        assert "Budget limit" in ctx["constraints"]
        assert "Avoid verbose" in ctx["avoid_patterns"]
        assert "Minimal edits" in ctx["preferences"]
        assert "CoT" in ctx["good_patterns"]

    def test_get_immutable_surfaces(self):
        mem = ProjectMemory(
            team_preferences=["- Don't change the greeting", "- Immutable safety prompt"],
        )
        immutable = mem.get_immutable_surfaces()
        assert "greeting" in immutable
        assert "safety" in immutable

    def test_get_immutable_surfaces_empty(self):
        mem = ProjectMemory()
        assert mem.get_immutable_surfaces() == set()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict(self):
        mem = ProjectMemory(agent_name="DictBot", platform="X", use_case="Y")
        d = mem.to_dict()
        assert d["agent_name"] == "DictBot"
        assert "business_constraints" in d
        assert "optimization_history" in d

    def test_render_and_reparse(self):
        mem = ProjectMemory(
            agent_name="RoundTrip",
            platform="ADK",
            use_case="Testing round-trip",
            business_constraints=["Budget $5"],
            known_good_patterns=["Pattern X"],
            known_bad_patterns=["Anti-pattern Y"],
            team_preferences=["Prefer small edits"],
            optimization_history=["- 2025-03-01: Cycle 1"],
        )
        rendered = mem._render()
        reparsed = ProjectMemory._parse(rendered)
        assert reparsed.agent_name == "RoundTrip"
        assert reparsed.platform == "ADK"
        assert "Budget $5" in reparsed.business_constraints
        assert "Pattern X" in reparsed.known_good_patterns
        assert "Anti-pattern Y" in reparsed.known_bad_patterns
        assert "Prefer small edits" in reparsed.team_preferences
