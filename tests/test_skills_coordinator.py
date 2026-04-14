"""Coverage for the V5 coordinator-backed /skills verb.

The /skills slash has three subcommands:

- ``/skills gap`` — route through the coordinator with SKILL_AUTHOR,
  producing an ordered skill_gap_report artifact.
- ``/skills generate <slug>`` — route through the coordinator to persist a
  generated_skill (code + manifest) via AgentSkillStore.
- ``/skills list`` — local-only render of the store (not exercised here;
  covered by existing skills_slash tests).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_skills.coordinator_worker import SkillAuthorWorker
from agent_skills.store import AgentSkillStore
from agent_skills.types import SkillGap
from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.events import EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import CoordinatorExecutionStatus, SpecialistRole
from cli.workbench_app.coordinator_session import CoordinatorSession


@pytest.fixture
def builder_store(tmp_path: Path) -> BuilderStore:
    return BuilderStore(db_path=str(tmp_path / "builder.db"))


def _session_with_skill_worker(
    *,
    builder_store: BuilderStore,
    skills_db: Path,
) -> tuple[CoordinatorSession, AgentSkillStore]:
    skill_store = AgentSkillStore(db_path=str(skills_db))
    orchestrator = BuilderOrchestrator(store=builder_store)
    runtime = CoordinatorWorkerRuntime(
        store=builder_store,
        orchestrator=orchestrator,
        events=EventBroker(),
        worker_adapters={
            SpecialistRole.SKILL_AUTHOR: SkillAuthorWorker(
                store_factory=lambda: skill_store
            ),
        },
    )
    session = CoordinatorSession(
        store=builder_store,
        orchestrator=orchestrator,
        events=EventBroker(),
        runtime=runtime,
    )
    return session, skill_store


def test_skills_gap_returns_ordered_proposals(
    builder_store: BuilderStore, tmp_path: Path
) -> None:
    session, skill_store = _session_with_skill_worker(
        builder_store=builder_store,
        skills_db=tmp_path / "agent_skills.db",
    )
    # Seed two gaps with different impact × frequency products.
    skill_store.save_gap(
        SkillGap(
            gap_id="gap-low",
            gap_type="missing_tool",
            description="Low-impact gap",
            evidence=[],
            failure_family="tool_error",
            frequency=1,
            impact_score=0.1,
            suggested_name="low",
            suggested_platform="adk",
        )
    )
    skill_store.save_gap(
        SkillGap(
            gap_id="gap-high",
            gap_type="missing_tool",
            description="High-impact gap",
            evidence=[],
            failure_family="tool_error",
            frequency=5,
            impact_score=0.9,
            suggested_name="high",
            suggested_platform="adk",
        )
    )

    result = session.process_turn(
        "Surface our biggest skill gaps.",
        command_intent="skills",
        context={"skills": {"subcommand": "gap", "notes": "from test"}},
    )

    assert result.status == CoordinatorExecutionStatus.COMPLETED.value
    runs = builder_store.list_coordinator_runs(session_id=result.session_id)
    assert runs, "coordinator run should be persisted"
    run = runs[0]
    skill_state = next(
        state
        for state in run.worker_states
        if state.worker_role == SpecialistRole.SKILL_AUTHOR
    )
    assert skill_state.result is not None
    report = skill_state.result.artifacts.get("skill_gap_report")
    assert isinstance(report, dict)
    gaps = report["gaps"]
    assert [gap["gap_id"] for gap in gaps[:2]] == ["gap-high", "gap-low"]
    assert report["total_gaps"] == 2
    assert report["notes"] == "from test"


def test_skills_generate_writes_manifest_file(
    builder_store: BuilderStore, tmp_path: Path
) -> None:
    session, skill_store = _session_with_skill_worker(
        builder_store=builder_store,
        skills_db=tmp_path / "agent_skills.db",
    )

    result = session.process_turn(
        "Create the order_lookup helper.",
        command_intent="skills",
        context={
            "skills": {
                "subcommand": "generate",
                "slug": "order_lookup",
                "notes": "Fetch the latest order by id.",
            }
        },
    )

    assert result.status == CoordinatorExecutionStatus.COMPLETED.value
    stored = skill_store.list()
    assert len(stored) == 1
    generated = stored[0]
    # ``name`` stays the requested slug via save_from_coordinator_artifact.
    assert generated.name == "order_lookup"
    assert generated.skill_id.startswith("skill-")
    assert generated.config_yaml is not None
    assert "order_lookup" in generated.config_yaml
    assert generated.source_code is not None
    assert "def order_lookup" in generated.source_code
    # Manifest file paths reflect the slug and are marked new.
    paths = {f.path for f in generated.files}
    assert "agent_skills/generated/order_lookup.yaml" in paths
    assert "agent_skills/generated/order_lookup.py" in paths

    runs = builder_store.list_coordinator_runs(session_id=result.session_id)
    run = runs[0]
    skill_state = next(
        state
        for state in run.worker_states
        if state.worker_role == SpecialistRole.SKILL_AUTHOR
    )
    artifacts = skill_state.result.artifacts
    assert "generated_skill" in artifacts
    assert artifacts["skill_manifest"]["slug"] == "order_lookup"
    assert artifacts["skill_manifest"]["save_record"]["saved"] is True


def test_save_from_coordinator_artifact_requires_skill_id(tmp_path: Path) -> None:
    """Round-trip a coordinator artifact through the store helper."""
    store = AgentSkillStore(db_path=str(tmp_path / "agent_skills.db"))
    with pytest.raises(ValueError, match="missing skill_id"):
        store.save_from_coordinator_artifact(
            {
                "gap_id": "x",
                "platform": "adk",
                "skill_type": "tool",
                "name": "thing",
                "description": "no id",
            }
        )
    saved = store.save_from_coordinator_artifact(
        {
            "skill_id": "skill-42",
            "gap_id": "gap-1",
            "platform": "adk",
            "skill_type": "tool",
            "name": "roundtrip",
            "description": "ok",
            "source_code": "def f(): ...",
            "config_yaml": "skills: []",
            "files": [
                {
                    "path": "agent_skills/generated/roundtrip.yaml",
                    "content": "skills: []",
                    "is_new": True,
                }
            ],
        }
    )
    assert saved.skill_id == "skill-42"
    fetched = store.get("skill-42")
    assert fetched is not None
    assert fetched.name == "roundtrip"
