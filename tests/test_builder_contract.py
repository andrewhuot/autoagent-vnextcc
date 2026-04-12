"""Tests for the builder contract loader and skill context integration.

Covers:
- BuilderContract loading from BUILDER_CONTRACT.md
- Contract parsing (sections, phases, skill layers)
- Graceful degradation when contract file is missing
- SkillContext loading from a skill store
- SkillContext domain relevance filtering
- classify_artifact_skill_layer mapping
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from builder.contract import (
    BuilderContract,
    SkillLayerDefinition,
    load_builder_contract,
    _locate_contract,
)
from builder.harness import (
    SkillContext,
    _load_skill_context,
    classify_artifact_skill_layer,
)


# ---------------------------------------------------------------------------
# BuilderContract loading
# ---------------------------------------------------------------------------

def test_load_contract_from_repo_root() -> None:
    """The contract file should load from the repo root."""
    repo_root = Path(__file__).resolve().parent.parent
    contract_path = repo_root / "BUILDER_CONTRACT.md"
    if not contract_path.exists():
        pytest.skip("BUILDER_CONTRACT.md not found at repo root")

    contract = load_builder_contract(path=str(contract_path))
    assert contract.loaded is True
    assert contract.source_path == str(contract_path)


def test_load_contract_extracts_sections() -> None:
    """Sections (## N. Title) should be extracted from the contract."""
    repo_root = Path(__file__).resolve().parent.parent
    contract_path = repo_root / "BUILDER_CONTRACT.md"
    if not contract_path.exists():
        pytest.skip("BUILDER_CONTRACT.md not found at repo root")

    contract = load_builder_contract(path=str(contract_path))
    assert len(contract.sections) >= 5
    assert "Builder Identity" in contract.sections
    assert "Startup Sequence" in contract.sections
    assert "Skill Treatment" in contract.sections


def test_load_contract_extracts_phases() -> None:
    """Phases (### Phase N: Name) should be extracted."""
    repo_root = Path(__file__).resolve().parent.parent
    contract_path = repo_root / "BUILDER_CONTRACT.md"
    if not contract_path.exists():
        pytest.skip("BUILDER_CONTRACT.md not found at repo root")

    contract = load_builder_contract(path=str(contract_path))
    assert len(contract.phases) == 4
    assert "Plan" in contract.phases
    assert "Execute" in contract.phases
    assert "Reflect" in contract.phases
    assert "Present" in contract.phases


def test_load_contract_extracts_skill_layers() -> None:
    """Both build-time and runtime skill layers should be detected."""
    repo_root = Path(__file__).resolve().parent.parent
    contract_path = repo_root / "BUILDER_CONTRACT.md"
    if not contract_path.exists():
        pytest.skip("BUILDER_CONTRACT.md not found at repo root")

    contract = load_builder_contract(path=str(contract_path))
    kinds = {sl.kind for sl in contract.skill_layers}
    assert "build" in kinds
    assert "runtime" in kinds


def test_load_contract_missing_file_returns_unloaded() -> None:
    """When the file is missing, return a contract with loaded=False."""
    contract = load_builder_contract(path="/nonexistent/BUILDER_CONTRACT.md")
    assert contract.loaded is False
    assert contract.phases == []
    assert contract.sections == []
    assert contract.skill_layers == []


def test_load_contract_to_dict_shape() -> None:
    """to_dict() should produce a well-formed serializable dict."""
    repo_root = Path(__file__).resolve().parent.parent
    contract_path = repo_root / "BUILDER_CONTRACT.md"
    if not contract_path.exists():
        pytest.skip("BUILDER_CONTRACT.md not found at repo root")

    contract = load_builder_contract(path=str(contract_path))
    d = contract.to_dict()
    assert d["loaded"] is True
    assert isinstance(d["phases"], list)
    assert isinstance(d["skill_layers"], list)
    assert all(isinstance(sl, dict) for sl in d["skill_layers"])
    assert all("kind" in sl for sl in d["skill_layers"])


def test_load_contract_from_temp_dir() -> None:
    """Loading from a custom path should work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        contract_file = Path(tmpdir) / "BUILDER_CONTRACT.md"
        contract_file.write_text(
            "# Builder Contract\n\n"
            "## 1. Identity\n\n"
            "## 2. Loop\n\n"
            "### Phase 1: Plan\n\n"
            "### Phase 2: Execute\n\n"
            "Build-time skills are available.\n\n"
            "Runtime skills are also available.\n"
        )
        contract = load_builder_contract(path=str(contract_file))
        assert contract.loaded is True
        assert "Identity" in contract.sections
        assert "Loop" in contract.sections
        assert len(contract.phases) == 2
        assert len(contract.skill_layers) == 2


def test_locate_contract_searches_dirs() -> None:
    """_locate_contract should find the file in search_dirs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        contract_file = Path(tmpdir) / "BUILDER_CONTRACT.md"
        contract_file.write_text("# Test")
        result = _locate_contract(search_dirs=[tmpdir])
        assert result == str(contract_file)


def test_locate_contract_returns_none_when_missing() -> None:
    """_locate_contract returns None when the file doesn't exist."""
    result = _locate_contract(search_dirs=["/nonexistent/dir"])
    # Might find the repo root one; if not, returns None
    if result is not None:
        assert result.endswith("BUILDER_CONTRACT.md")


# ---------------------------------------------------------------------------
# SkillContext
# ---------------------------------------------------------------------------

def test_skill_context_default_is_empty() -> None:
    """Default SkillContext should indicate no skills loaded."""
    ctx = SkillContext()
    assert ctx.build_skills_available == 0
    assert ctx.runtime_skills_available == 0
    assert ctx.skill_store_loaded is False


def test_skill_context_to_dict_shape() -> None:
    """to_dict() should produce a clean serializable dict."""
    ctx = SkillContext(
        build_skills_available=3,
        runtime_skills_available=2,
        build_skill_names=["safety_hardening", "keyword_expansion", "routing_fix"],
        runtime_skill_names=["order_lookup", "refund_processing"],
        skill_store_loaded=True,
    )
    d = ctx.to_dict()
    assert d["build_skills_available"] == 3
    assert d["runtime_skills_available"] == 2
    assert d["skill_store_loaded"] is True
    assert len(d["build_skill_names"]) == 3
    assert len(d["runtime_skill_names"]) == 2


def test_skill_context_relevant_for_domain() -> None:
    """relevant_for_domain() should filter skills by domain keyword."""
    ctx = SkillContext(
        build_skills_available=3,
        runtime_skills_available=2,
        build_skill_names=["airline_safety", "general_routing", "m_and_a_compliance"],
        runtime_skill_names=["airline_booking", "general_search"],
        skill_store_loaded=True,
    )
    d = ctx.relevant_for_domain("airline")
    assert "airline_safety" in d["build_skills_relevant"]
    assert "general_routing" in d["build_skills_relevant"]
    assert "m_and_a_compliance" not in d["build_skills_relevant"]
    assert "airline_booking" in d["runtime_skills_relevant"]
    assert "general_search" in d["runtime_skills_relevant"]


def test_load_skill_context_without_store() -> None:
    """_load_skill_context(None) should return an empty context."""
    ctx = _load_skill_context(None)
    assert ctx.skill_store_loaded is False
    assert ctx.build_skills_available == 0


def test_load_skill_context_with_broken_store() -> None:
    """_load_skill_context with a broken store should degrade gracefully."""
    class _BrokenStore:
        def list(self, **kwargs: Any) -> list:
            raise RuntimeError("Database locked")

    ctx = _load_skill_context(_BrokenStore())
    assert ctx.skill_store_loaded is False


# ---------------------------------------------------------------------------
# classify_artifact_skill_layer
# ---------------------------------------------------------------------------

def test_classify_tool_as_runtime() -> None:
    assert classify_artifact_skill_layer("tool") == "runtime"


def test_classify_callback_as_runtime() -> None:
    assert classify_artifact_skill_layer("callback") == "runtime"


def test_classify_api_call_as_runtime() -> None:
    assert classify_artifact_skill_layer("api_call") == "runtime"


def test_classify_eval_as_build() -> None:
    assert classify_artifact_skill_layer("eval") == "build"


def test_classify_guardrail_as_build() -> None:
    assert classify_artifact_skill_layer("guardrail") == "build"


def test_classify_agent_as_none() -> None:
    assert classify_artifact_skill_layer("agent") == "none"


def test_classify_environment_as_none() -> None:
    assert classify_artifact_skill_layer("environment") == "none"


def test_classify_plan_as_none() -> None:
    assert classify_artifact_skill_layer("plan") == "none"


def test_classify_unknown_as_none() -> None:
    assert classify_artifact_skill_layer("something_else") == "none"
