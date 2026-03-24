"""Comprehensive tests for core domain objects in core/types.py and core/handoff.py."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.handoff import HandoffArtifact, HandoffComparator
from core.types import (
    AgentEdge,
    AgentGraphVersion,
    AgentNode,
    AgentNodeType,
    ArchiveEntry,
    ArchiveRole,
    CandidateVariant,
    EdgeType,
    EnvironmentSnapshot,
    EvalCase,
    EvalSuiteType,
    GraderBundle,
    GraderSpec,
    GraderType,
    JudgeVerdict,
    LayeredMetric,
    MetricLayer,
    PolicyPackVersion,
    ReplayMode,
    SkillVersion,
    SnapshotDiff,
    ToolContractVersion,
    get_metrics_by_layer,
    METRIC_REGISTRY,
)


# ---------------------------------------------------------------------------
# AgentGraphVersion Tests
# ---------------------------------------------------------------------------

def test_agent_graph_version_creation():
    """Test basic AgentGraphVersion creation."""
    graph = AgentGraphVersion()
    assert graph.version_id
    assert graph.created_at
    assert len(graph.nodes) == 0
    assert len(graph.edges) == 0
    assert graph.parent_version_id is None


def test_agent_graph_version_content_hash_determinism():
    """Test that content_hash is deterministic and excludes metadata."""
    node1 = AgentNode(
        node_id="n1",
        node_type=AgentNodeType.router,
        name="Main Router",
        config={"model": "claude-3-5-sonnet"},
    )
    edge1 = AgentEdge(
        source_id="n1",
        target_id="n2",
        edge_type=EdgeType.routes_to,
    )

    graph1 = AgentGraphVersion(
        nodes=[node1],
        edges=[edge1],
        metadata={"env": "prod"},
    )
    graph2 = AgentGraphVersion(
        nodes=[node1],
        edges=[edge1],
        metadata={"env": "staging"},  # different metadata
    )

    # Content hash should be identical (metadata excluded)
    assert graph1.content_hash == graph2.content_hash

    # Different version_id and created_at should not affect hash
    assert graph1.version_id != graph2.version_id
    assert graph1.content_hash == graph2.content_hash


def test_agent_graph_version_content_hash_changes_with_content():
    """Test that content_hash changes when nodes/edges change."""
    node1 = AgentNode(node_id="n1", node_type=AgentNodeType.router, name="Router")
    node2 = AgentNode(node_id="n2", node_type=AgentNodeType.specialist, name="Specialist")

    graph1 = AgentGraphVersion(nodes=[node1])
    graph2 = AgentGraphVersion(nodes=[node1, node2])

    assert graph1.content_hash != graph2.content_hash


def test_agent_graph_version_get_nodes_by_type():
    """Test filtering nodes by type."""
    router1 = AgentNode(node_id="r1", node_type=AgentNodeType.router, name="Router1")
    router2 = AgentNode(node_id="r2", node_type=AgentNodeType.router, name="Router2")
    specialist = AgentNode(node_id="s1", node_type=AgentNodeType.specialist, name="Specialist1")
    skill = AgentNode(node_id="sk1", node_type=AgentNodeType.skill, name="Skill1")

    graph = AgentGraphVersion(nodes=[router1, router2, specialist, skill])

    routers = graph.get_nodes_by_type(AgentNodeType.router)
    assert len(routers) == 2
    assert all(n.node_type == AgentNodeType.router for n in routers)

    specialists = graph.get_nodes_by_type(AgentNodeType.specialist)
    assert len(specialists) == 1
    assert specialists[0].node_id == "s1"

    skills = graph.get_nodes_by_type(AgentNodeType.skill)
    assert len(skills) == 1

    guardrails = graph.get_nodes_by_type(AgentNodeType.guardrail)
    assert len(guardrails) == 0


def test_agent_graph_version_get_node():
    """Test retrieving a specific node by ID."""
    node1 = AgentNode(node_id="n1", node_type=AgentNodeType.router, name="Router")
    node2 = AgentNode(node_id="n2", node_type=AgentNodeType.specialist, name="Specialist")

    graph = AgentGraphVersion(nodes=[node1, node2])

    found = graph.get_node("n1")
    assert found is not None
    assert found.node_id == "n1"
    assert found.name == "Router"

    not_found = graph.get_node("n999")
    assert not_found is None


def test_agent_graph_version_get_edges_from():
    """Test getting outgoing edges from a node."""
    edge1 = AgentEdge(source_id="n1", target_id="n2", edge_type=EdgeType.routes_to)
    edge2 = AgentEdge(source_id="n1", target_id="n3", edge_type=EdgeType.delegates_to)
    edge3 = AgentEdge(source_id="n2", target_id="n3", edge_type=EdgeType.uses_tool)

    graph = AgentGraphVersion(edges=[edge1, edge2, edge3])

    from_n1 = graph.get_edges_from("n1")
    assert len(from_n1) == 2
    assert all(e.source_id == "n1" for e in from_n1)

    from_n2 = graph.get_edges_from("n2")
    assert len(from_n2) == 1
    assert from_n2[0].target_id == "n3"

    from_n999 = graph.get_edges_from("n999")
    assert len(from_n999) == 0


def test_agent_graph_version_get_edges_to():
    """Test getting incoming edges to a node."""
    edge1 = AgentEdge(source_id="n1", target_id="n3", edge_type=EdgeType.routes_to)
    edge2 = AgentEdge(source_id="n2", target_id="n3", edge_type=EdgeType.delegates_to)
    edge3 = AgentEdge(source_id="n1", target_id="n2", edge_type=EdgeType.uses_tool)

    graph = AgentGraphVersion(edges=[edge1, edge2, edge3])

    to_n3 = graph.get_edges_to("n3")
    assert len(to_n3) == 2
    assert all(e.target_id == "n3" for e in to_n3)

    to_n2 = graph.get_edges_to("n2")
    assert len(to_n2) == 1
    assert to_n2[0].source_id == "n1"


def test_agent_graph_version_to_dict_from_dict_roundtrip():
    """Test AgentGraphVersion serialization round-trip."""
    node = AgentNode(
        node_id="n1",
        node_type=AgentNodeType.specialist,
        name="SQL Specialist",
        config={"model": "claude-3-5-sonnet", "temperature": 0.3},
        metadata={"domain": "database"},
    )
    edge = AgentEdge(
        source_id="router",
        target_id="n1",
        edge_type=EdgeType.routes_to,
        metadata={"priority": 1},
    )

    original = AgentGraphVersion(
        version_id="test123",
        created_at="2024-01-15T10:00:00+00:00",
        nodes=[node],
        edges=[edge],
        metadata={"env": "production"},
        parent_version_id="parent456",
    )

    serialized = original.to_dict()
    restored = AgentGraphVersion.from_dict(serialized)

    assert restored.version_id == original.version_id
    assert restored.created_at == original.created_at
    assert len(restored.nodes) == 1
    assert restored.nodes[0].node_id == "n1"
    assert restored.nodes[0].config["model"] == "claude-3-5-sonnet"
    assert len(restored.edges) == 1
    assert restored.edges[0].edge_type == EdgeType.routes_to
    assert restored.metadata == original.metadata
    assert restored.parent_version_id == "parent456"


def test_agent_graph_version_parent_version_id():
    """Test that parent_version_id tracks lineage."""
    parent = AgentGraphVersion()
    child = AgentGraphVersion(parent_version_id=parent.version_id)

    assert child.parent_version_id == parent.version_id
    assert parent.parent_version_id is None


# ---------------------------------------------------------------------------
# SkillVersion Tests
# ---------------------------------------------------------------------------

def test_skill_version_creation():
    """Test SkillVersion creation with all fields."""
    skill = SkillVersion(
        skill_id="sql-query",
        version="1.0.0",
        name="SQL Query Executor",
        instructions="Execute SQL queries safely with parameterization.",
        scripts={"query.py": "import sqlite3\n..."},
        assets={"schema.json": {"tables": ["users", "orders"]}},
        validators=["validate_sql_injection", "validate_permissions"],
        metadata={"author": "platform-team"},
    )

    assert skill.skill_id == "sql-query"
    assert skill.version == "1.0.0"
    assert skill.name == "SQL Query Executor"
    assert "parameterization" in skill.instructions
    assert "query.py" in skill.scripts
    assert "schema.json" in skill.assets
    assert len(skill.validators) == 2
    assert skill.created_at


def test_skill_version_content_hash():
    """Test that SkillVersion content_hash is deterministic."""
    skill1 = SkillVersion(
        skill_id="test",
        version="1.0",
        name="Test Skill",
        instructions="Do X",
        scripts={"main.py": "print('hello')"},
    )

    skill2 = SkillVersion(
        skill_id="test",
        version="1.0",
        name="Test Skill",
        instructions="Do X",
        scripts={"main.py": "print('hello')"},
    )

    # Same content should produce same hash (even if created_at differs)
    assert skill1.content_hash == skill2.content_hash

    # Different content should produce different hash
    skill3 = SkillVersion(
        skill_id="test",
        version="1.0",
        name="Test Skill",
        instructions="Do Y",  # different
        scripts={"main.py": "print('hello')"},
    )
    assert skill1.content_hash != skill3.content_hash


def test_skill_version_to_dict():
    """Test SkillVersion serialization."""
    skill = SkillVersion(
        skill_id="test-skill",
        version="2.0",
        name="Test",
        instructions="Test instructions",
        scripts={"main.py": "code"},
        assets={"data.json": {"key": "value"}},
        validators=["check1"],
        metadata={"env": "test"},
    )

    d = skill.to_dict()
    assert d["skill_id"] == "test-skill"
    assert d["version"] == "2.0"
    assert d["name"] == "Test"
    assert d["instructions"] == "Test instructions"
    assert d["scripts"]["main.py"] == "code"
    assert d["assets"]["data.json"]["key"] == "value"
    assert "check1" in d["validators"]
    assert d["metadata"]["env"] == "test"


# ---------------------------------------------------------------------------
# ToolContractVersion Tests
# ---------------------------------------------------------------------------

def test_tool_contract_version_creation():
    """Test ToolContractVersion creation."""
    contract = ToolContractVersion(
        tool_name="read_file",
        version="1",
        schema={"type": "object", "properties": {"path": {"type": "string"}}},
        replay_mode=ReplayMode.deterministic_stub,
        validator="validate_file_path",
        description="Read file contents",
    )

    assert contract.tool_name == "read_file"
    assert contract.replay_mode == ReplayMode.deterministic_stub
    assert contract.can_auto_replay is True


def test_tool_contract_version_can_auto_replay_deterministic_stub():
    """Test can_auto_replay for deterministic_stub mode."""
    contract = ToolContractVersion(
        tool_name="test",
        replay_mode=ReplayMode.deterministic_stub,
    )
    assert contract.can_auto_replay is True


def test_tool_contract_version_can_auto_replay_recorded_stub_with_freshness():
    """Test can_auto_replay for recorded_stub_with_freshness mode."""
    contract = ToolContractVersion(
        tool_name="test",
        replay_mode=ReplayMode.recorded_stub_with_freshness,
        freshness_window_seconds=3600,
    )
    assert contract.can_auto_replay is True


def test_tool_contract_version_can_auto_replay_simulator():
    """Test can_auto_replay for simulator mode."""
    contract = ToolContractVersion(
        tool_name="test",
        replay_mode=ReplayMode.simulator,
    )
    assert contract.can_auto_replay is True


def test_tool_contract_version_can_auto_replay_live_sandbox_clone():
    """Test can_auto_replay for live_sandbox_clone mode (not auto-replayable)."""
    contract = ToolContractVersion(
        tool_name="test",
        replay_mode=ReplayMode.live_sandbox_clone,
    )
    assert contract.can_auto_replay is False


def test_tool_contract_version_can_auto_replay_forbidden():
    """Test can_auto_replay for forbidden mode (not auto-replayable)."""
    contract = ToolContractVersion(
        tool_name="test",
        replay_mode=ReplayMode.forbidden,
    )
    assert contract.can_auto_replay is False


def test_tool_contract_version_to_dict_from_dict_roundtrip():
    """Test ToolContractVersion serialization round-trip."""
    original = ToolContractVersion(
        tool_name="execute_sql",
        version="2",
        schema={"type": "object"},
        side_effect_class="stateful",
        replay_mode=ReplayMode.recorded_stub_with_freshness,
        validator="validate_sql",
        sandbox_policy={"allow_writes": False},
        freshness_window_seconds=1800,
        description="Execute SQL queries",
        metadata={"owner": "db-team"},
    )

    d = original.to_dict()
    restored = ToolContractVersion.from_dict(d)

    assert restored.tool_name == original.tool_name
    assert restored.version == original.version
    assert restored.schema == original.schema
    assert restored.side_effect_class == original.side_effect_class
    assert restored.replay_mode == original.replay_mode
    assert restored.validator == original.validator
    assert restored.sandbox_policy == original.sandbox_policy
    assert restored.freshness_window_seconds == original.freshness_window_seconds
    assert restored.description == original.description
    assert restored.metadata == original.metadata


# ---------------------------------------------------------------------------
# PolicyPackVersion Tests
# ---------------------------------------------------------------------------

def test_policy_pack_version_creation():
    """Test PolicyPackVersion creation."""
    policy = PolicyPackVersion(
        pack_id="prod-safety",
        version="1.0",
        name="Production Safety Pack",
        safety_rules=[
            {"rule": "no_pii_in_logs", "severity": "critical"},
            {"rule": "require_authorization", "severity": "high"},
        ],
        guardrail_thresholds={"pii_detection": 0.95, "prompt_injection": 0.9},
        authorization_policies=[
            {"resource": "database", "action": "write", "role": "admin"},
        ],
        metadata={"env": "production"},
    )

    assert policy.pack_id == "prod-safety"
    assert policy.version == "1.0"
    assert len(policy.safety_rules) == 2
    assert policy.guardrail_thresholds["pii_detection"] == 0.95
    assert len(policy.authorization_policies) == 1


def test_policy_pack_version_to_dict():
    """Test PolicyPackVersion serialization."""
    policy = PolicyPackVersion(
        pack_id="test-pack",
        version="1.0",
        name="Test Pack",
        safety_rules=[{"rule": "test"}],
        guardrail_thresholds={"threshold": 0.8},
        authorization_policies=[{"policy": "test"}],
    )

    d = policy.to_dict()
    assert d["pack_id"] == "test-pack"
    assert d["version"] == "1.0"
    assert len(d["safety_rules"]) == 1
    assert d["guardrail_thresholds"]["threshold"] == 0.8
    assert len(d["authorization_policies"]) == 1


# ---------------------------------------------------------------------------
# EnvironmentSnapshot Tests
# ---------------------------------------------------------------------------

def test_environment_snapshot_creation():
    """Test EnvironmentSnapshot creation."""
    snapshot = EnvironmentSnapshot(
        state={"db_version": "1.0", "user_count": 42, "orders": [1, 2, 3]},
        source="orders_db",
        metadata={"captured_by": "test_runner"},
    )

    assert snapshot.snapshot_id
    assert snapshot.created_at
    assert snapshot.state["user_count"] == 42
    assert snapshot.source == "orders_db"
    assert len(snapshot.state["orders"]) == 3


def test_environment_snapshot_to_dict_from_dict_roundtrip():
    """Test EnvironmentSnapshot serialization round-trip."""
    original = EnvironmentSnapshot(
        snapshot_id="snap123",
        created_at="2024-01-15T10:00:00+00:00",
        state={"key": "value", "count": 10},
        source="test_source",
        metadata={"env": "test"},
    )

    d = original.to_dict()
    restored = EnvironmentSnapshot.from_dict(d)

    assert restored.snapshot_id == original.snapshot_id
    assert restored.created_at == original.created_at
    assert restored.state == original.state
    assert restored.source == original.source
    assert restored.metadata == original.metadata


# ---------------------------------------------------------------------------
# SnapshotDiff Tests
# ---------------------------------------------------------------------------

def test_snapshot_diff_compute_matching_snapshots():
    """Test SnapshotDiff.compute with identical snapshots (score=1.0)."""
    snapshot1 = EnvironmentSnapshot(
        state={"key1": "value1", "key2": "value2", "key3": 42},
        source="test",
    )
    snapshot2 = EnvironmentSnapshot(
        state={"key1": "value1", "key2": "value2", "key3": 42},
        source="test",
    )

    diff = SnapshotDiff.compute(snapshot1, snapshot2)

    assert diff.match_score == 1.0
    assert len(diff.added_keys) == 0
    assert len(diff.removed_keys) == 0
    assert len(diff.changed_keys) == 0


def test_snapshot_diff_compute_completely_different():
    """Test SnapshotDiff.compute with completely different snapshots."""
    snapshot1 = EnvironmentSnapshot(state={"a": 1, "b": 2}, source="test")
    snapshot2 = EnvironmentSnapshot(state={"c": 3, "d": 4}, source="test")

    diff = SnapshotDiff.compute(snapshot1, snapshot2)

    assert diff.match_score == 0.0
    assert set(diff.added_keys) == {"c", "d"}
    assert set(diff.removed_keys) == {"a", "b"}
    assert len(diff.changed_keys) == 0


def test_snapshot_diff_compute_added_keys():
    """Test SnapshotDiff.compute with added keys."""
    snapshot1 = EnvironmentSnapshot(state={"a": 1}, source="test")
    snapshot2 = EnvironmentSnapshot(state={"a": 1, "b": 2}, source="test")

    diff = SnapshotDiff.compute(snapshot1, snapshot2)

    assert "b" in diff.added_keys
    assert len(diff.removed_keys) == 0
    assert diff.match_score == 0.5  # 1 matching out of 2 total keys


def test_snapshot_diff_compute_removed_keys():
    """Test SnapshotDiff.compute with removed keys."""
    snapshot1 = EnvironmentSnapshot(state={"a": 1, "b": 2}, source="test")
    snapshot2 = EnvironmentSnapshot(state={"a": 1}, source="test")

    diff = SnapshotDiff.compute(snapshot1, snapshot2)

    assert "b" in diff.removed_keys
    assert len(diff.added_keys) == 0
    assert diff.match_score == 0.5  # 1 matching out of 2 total keys


def test_snapshot_diff_compute_changed_keys():
    """Test SnapshotDiff.compute with changed values."""
    snapshot1 = EnvironmentSnapshot(state={"a": 1, "b": 2, "c": 3}, source="test")
    snapshot2 = EnvironmentSnapshot(state={"a": 1, "b": 999, "c": 3}, source="test")

    diff = SnapshotDiff.compute(snapshot1, snapshot2)

    assert "b" in diff.changed_keys
    assert diff.changed_keys["b"]["expected"] == 2
    assert diff.changed_keys["b"]["actual"] == 999
    assert len(diff.added_keys) == 0
    assert len(diff.removed_keys) == 0
    assert diff.match_score == pytest.approx(2 / 3)  # 2 out of 3 keys match


# ---------------------------------------------------------------------------
# GraderBundle Tests
# ---------------------------------------------------------------------------

def test_grader_bundle_creation():
    """Test GraderBundle creation with multiple graders."""
    bundle = GraderBundle(
        bundle_id="test-bundle",
        graders=[
            GraderSpec(
                grader_type=GraderType.deterministic,
                grader_id="exact_match",
                weight=1.0,
                required=True,
            ),
            GraderSpec(
                grader_type=GraderType.llm_judge,
                grader_id="claude_judge",
                weight=0.5,
                config={"model": "claude-3-5-sonnet"},
            ),
        ],
        metadata={"suite": "capability"},
    )

    assert bundle.bundle_id == "test-bundle"
    assert len(bundle.graders) == 2
    assert bundle.graders[0].required is True


def test_grader_bundle_get_graders_by_type():
    """Test filtering graders by type."""
    bundle = GraderBundle(
        graders=[
            GraderSpec(grader_type=GraderType.deterministic, grader_id="g1"),
            GraderSpec(grader_type=GraderType.rule_based, grader_id="g2"),
            GraderSpec(grader_type=GraderType.llm_judge, grader_id="g3"),
            GraderSpec(grader_type=GraderType.deterministic, grader_id="g4"),
        ]
    )

    deterministic = bundle.get_graders_by_type(GraderType.deterministic)
    assert len(deterministic) == 2
    assert all(g.grader_type == GraderType.deterministic for g in deterministic)

    llm_judges = bundle.get_graders_by_type(GraderType.llm_judge)
    assert len(llm_judges) == 1

    human = bundle.get_graders_by_type(GraderType.human_review)
    assert len(human) == 0


def test_grader_bundle_has_human_review():
    """Test has_human_review property."""
    bundle_no_human = GraderBundle(
        graders=[
            GraderSpec(grader_type=GraderType.deterministic, grader_id="g1"),
            GraderSpec(grader_type=GraderType.llm_judge, grader_id="g2"),
        ]
    )
    assert bundle_no_human.has_human_review is False

    bundle_with_human = GraderBundle(
        graders=[
            GraderSpec(grader_type=GraderType.deterministic, grader_id="g1"),
            GraderSpec(grader_type=GraderType.human_review, grader_id="human"),
        ]
    )
    assert bundle_with_human.has_human_review is True


# ---------------------------------------------------------------------------
# EvalCase Tests
# ---------------------------------------------------------------------------

def test_eval_case_creation_with_all_fields():
    """Test EvalCase creation with all fields populated."""
    snapshot = EnvironmentSnapshot(state={"db": "init"}, source="test")
    bundle = GraderBundle(graders=[
        GraderSpec(grader_type=GraderType.deterministic, grader_id="exact")
    ])

    case = EvalCase(
        case_id="case-001",
        task="Execute SQL query to count users",
        category="database",
        suite_type=EvalSuiteType.capability,
        environment_snapshot=snapshot,
        grader_bundle=bundle,
        expected_end_state={"user_count": 42},
        diagnostic_trace_features={"tool_calls": 2},
        expected_specialist="sql_specialist",
        expected_behavior="query_execution",
        expected_keywords=["SELECT", "COUNT"],
        expected_tool="execute_sql",
        reference_answer="42 users found",
        safety_probe=False,
        split="tuning",
        business_impact=2.5,
        root_cause_tag="data_quality",
        is_negative_control=False,
        solvability=0.95,
        metadata={"priority": "high"},
    )

    assert case.case_id == "case-001"
    assert case.task == "Execute SQL query to count users"
    assert case.suite_type == EvalSuiteType.capability
    assert case.environment_snapshot is not None
    assert case.grader_bundle is not None
    assert case.expected_end_state["user_count"] == 42
    assert case.business_impact == 2.5
    assert case.solvability == 0.95


def test_eval_case_from_test_case_conversion():
    """Test creating EvalCase from a legacy TestCase."""
    # Mock a legacy TestCase
    class MockTestCase:
        def __init__(self):
            self.id = "legacy-001"
            self.user_message = "Do something"
            self.category = "general"
            self.expected_specialist = "router"
            self.expected_behavior = "route"
            self.expected_keywords = ["route", "delegate"]
            self.expected_tool = "route_tool"
            self.reference_answer = "Routed successfully"
            self.safety_probe = False
            self.split = "test"

    legacy = MockTestCase()
    case = EvalCase.from_test_case(legacy)

    assert case.case_id == "legacy-001"
    assert case.task == "Do something"
    assert case.category == "general"
    assert case.expected_specialist == "router"
    assert case.expected_keywords == ["route", "delegate"]
    assert case.split == "test"


def test_eval_case_to_dict():
    """Test EvalCase serialization."""
    case = EvalCase(
        case_id="test-case",
        task="Test task",
        category="test",
        expected_tool="test_tool",
        metadata={"key": "value"},
    )

    d = case.to_dict()
    assert d["case_id"] == "test-case"
    assert d["task"] == "Test task"
    assert d["category"] == "test"
    assert d["expected_tool"] == "test_tool"
    assert d["metadata"]["key"] == "value"


# ---------------------------------------------------------------------------
# CandidateVariant Tests
# ---------------------------------------------------------------------------

def test_candidate_variant_creation():
    """Test CandidateVariant creation."""
    variant = CandidateVariant(
        variant_id="var123",
        base_graph_version_id="graph-v1",
        description="Improve routing accuracy",
        diff={"nodes": [{"op": "update", "node_id": "router"}]},
        config_patch={"temperature": 0.3},
        mutation_surface="router_config",
        risk_class="medium",
        metadata={"author": "optimizer"},
    )

    assert variant.variant_id == "var123"
    assert variant.base_graph_version_id == "graph-v1"
    assert variant.risk_class == "medium"
    assert "router" in str(variant.diff)


def test_candidate_variant_to_dict():
    """Test CandidateVariant serialization."""
    variant = CandidateVariant(
        description="Test variant",
        diff={"change": "test"},
        risk_class="low",
    )

    d = variant.to_dict()
    assert d["description"] == "Test variant"
    assert d["diff"]["change"] == "test"
    assert d["risk_class"] == "low"
    assert "variant_id" in d
    assert "created_at" in d


# ---------------------------------------------------------------------------
# ArchiveEntry Tests
# ---------------------------------------------------------------------------

def test_archive_entry_creation():
    """Test ArchiveEntry creation."""
    entry = ArchiveEntry(
        entry_id="entry123",
        role=ArchiveRole.quality_leader,
        candidate_id="cand-001",
        experiment_id="exp-001",
        objective_vector=[0.95, 100, 2000],
        config_hash="abc123",
        scores={"task_success_rate": 0.95, "latency_p50": 2000},
        metadata={"notes": "best quality so far"},
    )

    assert entry.entry_id == "entry123"
    assert entry.role == ArchiveRole.quality_leader
    assert entry.objective_vector == [0.95, 100, 2000]
    assert entry.scores["task_success_rate"] == 0.95


def test_archive_entry_to_dict_from_dict_roundtrip():
    """Test ArchiveEntry serialization round-trip."""
    original = ArchiveEntry(
        entry_id="test-entry",
        role=ArchiveRole.cost_leader,
        candidate_id="cand-002",
        experiment_id="exp-002",
        objective_vector=[0.8, 50, 3000],
        config_hash="hash456",
        scores={"cost": 50, "quality": 0.8},
        metadata={"env": "prod"},
    )

    d = original.to_dict()
    restored = ArchiveEntry.from_dict(d)

    assert restored.entry_id == original.entry_id
    assert restored.role == original.role
    assert restored.candidate_id == original.candidate_id
    assert restored.objective_vector == original.objective_vector
    assert restored.scores == original.scores


def test_archive_entry_role_assignment():
    """Test all ArchiveRole assignments."""
    roles = [
        ArchiveRole.quality_leader,
        ArchiveRole.cost_leader,
        ArchiveRole.latency_leader,
        ArchiveRole.safety_leader,
        ArchiveRole.cluster_specialist,
        ArchiveRole.incumbent,
    ]

    for role in roles:
        entry = ArchiveEntry(role=role)
        assert entry.role == role

        # Round-trip test
        d = entry.to_dict()
        restored = ArchiveEntry.from_dict(d)
        assert restored.role == role


# ---------------------------------------------------------------------------
# JudgeVerdict Tests
# ---------------------------------------------------------------------------

def test_judge_verdict_creation():
    """Test JudgeVerdict creation."""
    verdict = JudgeVerdict(
        score=0.85,
        passed=True,
        judge_id="claude_judge_001",
        evidence_spans=["Line 5-10", "Line 20-25"],
        failure_reasons=[],
        confidence=0.9,
        metadata={"model": "claude-3-5-sonnet", "tokens": 1500},
    )

    assert verdict.score == 0.85
    assert verdict.passed is True
    assert verdict.judge_id == "claude_judge_001"
    assert len(verdict.evidence_spans) == 2
    assert verdict.confidence == 0.9


def test_judge_verdict_to_dict():
    """Test JudgeVerdict serialization."""
    verdict = JudgeVerdict(
        score=0.5,
        passed=False,
        judge_id="rule_judge",
        failure_reasons=["Missing required keyword", "Incorrect format"],
        confidence=1.0,
    )

    d = verdict.to_dict()
    assert d["score"] == 0.5
    assert d["passed"] is False
    assert d["judge_id"] == "rule_judge"
    assert len(d["failure_reasons"]) == 2
    assert d["confidence"] == 1.0


# ---------------------------------------------------------------------------
# MetricLayer and METRIC_REGISTRY Tests
# ---------------------------------------------------------------------------

def test_metric_layer_and_registry_hard_gate():
    """Test get_metrics_by_layer returns correct count for HARD_GATE."""
    hard_gates = get_metrics_by_layer(MetricLayer.HARD_GATE)
    assert len(hard_gates) == 4
    assert all(m.layer == MetricLayer.HARD_GATE for m in hard_gates)

    names = {m.name for m in hard_gates}
    assert "safety_compliance" in names
    assert "authorization_privacy" in names
    assert "state_integrity" in names
    assert "p0_regressions" in names


def test_metric_layer_and_registry_outcome():
    """Test get_metrics_by_layer returns correct count for OUTCOME."""
    outcomes = get_metrics_by_layer(MetricLayer.OUTCOME)
    assert len(outcomes) == 3
    assert all(m.layer == MetricLayer.OUTCOME for m in outcomes)

    names = {m.name for m in outcomes}
    assert "task_success_rate" in names
    assert "groundedness" in names
    assert "user_satisfaction_proxy" in names


def test_metric_layer_and_registry_slo():
    """Test get_metrics_by_layer returns correct count for SLO."""
    slos = get_metrics_by_layer(MetricLayer.SLO)
    assert len(slos) == 5
    assert all(m.layer == MetricLayer.SLO for m in slos)

    names = {m.name for m in slos}
    assert "latency_p50" in names
    assert "latency_p95" in names
    assert "latency_p99" in names
    assert "token_cost" in names
    assert "escalation_rate" in names


def test_metric_layer_and_registry_diagnostic():
    """Test get_metrics_by_layer returns correct count for DIAGNOSTIC."""
    diagnostics = get_metrics_by_layer(MetricLayer.DIAGNOSTIC)
    assert len(diagnostics) == 6
    assert all(m.layer == MetricLayer.DIAGNOSTIC for m in diagnostics)

    names = {m.name for m in diagnostics}
    assert "tool_correctness" in names
    assert "routing_accuracy" in names
    assert "handoff_fidelity" in names


def test_metric_registry_total_count():
    """Test that METRIC_REGISTRY has expected total count."""
    assert len(METRIC_REGISTRY) == 18  # 4 + 3 + 5 + 6


# ---------------------------------------------------------------------------
# HandoffArtifact Tests
# ---------------------------------------------------------------------------

def test_handoff_artifact_creation():
    """Test HandoffArtifact creation."""
    artifact = HandoffArtifact(
        goal="Extract customer data from CRM",
        constraints=["No PII in logs", "Read-only access"],
        known_facts={"customer_id": "12345", "region": "US"},
        unresolved_questions=["Which fields to include?"],
        allowed_tools=["read_crm", "format_json"],
        expected_deliverable="JSON formatted customer record",
        evidence_refs=["doc/crm-schema.md"],
        metadata={"priority": "high"},
    )

    assert artifact.goal == "Extract customer data from CRM"
    assert len(artifact.constraints) == 2
    assert artifact.known_facts["customer_id"] == "12345"
    assert len(artifact.unresolved_questions) == 1
    assert "read_crm" in artifact.allowed_tools


def test_handoff_artifact_completeness_calculation():
    """Test HandoffArtifact completeness score."""
    # Empty artifact
    empty = HandoffArtifact()
    assert empty.completeness == 0.0

    # Partially filled
    partial = HandoffArtifact(
        goal="Test goal",
        constraints=["constraint1"],
        known_facts={"key": "value"},
    )
    # 3 out of 7 scored fields filled
    assert partial.completeness == pytest.approx(3 / 7)

    # Fully filled
    full = HandoffArtifact(
        goal="Test goal",
        constraints=["constraint1"],
        known_facts={"key": "value"},
        unresolved_questions=["question"],
        allowed_tools=["tool1"],
        expected_deliverable="deliverable",
        evidence_refs=["ref1"],
    )
    assert full.completeness == 1.0


def test_handoff_artifact_to_dict_from_dict_roundtrip():
    """Test HandoffArtifact serialization round-trip."""
    original = HandoffArtifact(
        goal="Test goal",
        constraints=["c1", "c2"],
        known_facts={"a": 1, "b": 2},
        unresolved_questions=["q1"],
        allowed_tools=["t1", "t2"],
        expected_deliverable="output",
        evidence_refs=["ref1"],
        metadata={"key": "value"},
    )

    d = original.to_dict()
    restored = HandoffArtifact.from_dict(d)

    assert restored.goal == original.goal
    assert restored.constraints == original.constraints
    assert restored.known_facts == original.known_facts
    assert restored.unresolved_questions == original.unresolved_questions
    assert restored.allowed_tools == original.allowed_tools
    assert restored.expected_deliverable == original.expected_deliverable
    assert restored.evidence_refs == original.evidence_refs
    assert restored.metadata == original.metadata


# ---------------------------------------------------------------------------
# HandoffComparator Tests
# ---------------------------------------------------------------------------

def test_handoff_comparator_perfect_match():
    """Test HandoffComparator.compare with perfect match."""
    artifact1 = HandoffArtifact(
        goal="Extract data",
        constraints=["no pii"],
        known_facts={"id": "123"},
    )
    artifact2 = HandoffArtifact(
        goal="Extract data",
        constraints=["no pii"],
        known_facts={"id": "123"},
    )

    result = HandoffComparator.compare(artifact1, artifact2)

    assert result["aggregate_score"] == 1.0
    assert len(result["missing_fields"]) == 0
    assert len(result["extra_fields"]) == 0


def test_handoff_comparator_partial_match():
    """Test HandoffComparator.compare with partial overlap."""
    expected = HandoffArtifact(
        goal="Extract customer data",
        constraints=["no pii", "read-only"],
        known_facts={"id": "123"},
    )
    actual = HandoffArtifact(
        goal="Extract customer information",  # similar but not exact
        constraints=["no pii"],  # missing "read-only"
        known_facts={"id": "123"},
    )

    result = HandoffComparator.compare(expected, actual)

    # Goal should have partial match (word overlap)
    assert 0.0 < result["field_scores"]["goal"] < 1.0

    # Constraints: 1 out of 2 expected items present
    assert result["field_scores"]["constraints"] == 0.5

    # known_facts: exact match
    assert result["field_scores"]["known_facts"] == 1.0

    # Aggregate should be between 0 and 1
    assert 0.0 < result["aggregate_score"] < 1.0


def test_handoff_comparator_missing_fields():
    """Test HandoffComparator.compare identifies missing fields."""
    expected = HandoffArtifact(
        goal="Do task",
        constraints=["constraint"],
        allowed_tools=["tool1"],
    )
    actual = HandoffArtifact(
        goal="Do task",
        # missing constraints and allowed_tools
    )

    result = HandoffComparator.compare(expected, actual)

    assert "constraints" in result["missing_fields"]
    assert "allowed_tools" in result["missing_fields"]
    assert result["field_scores"]["constraints"] == 0.0
    assert result["field_scores"]["allowed_tools"] == 0.0


def test_handoff_comparator_extra_fields():
    """Test HandoffComparator.compare identifies extra fields."""
    expected = HandoffArtifact(
        goal="Do task",
    )
    actual = HandoffArtifact(
        goal="Do task",
        constraints=["extra constraint"],
        allowed_tools=["extra tool"],
    )

    result = HandoffComparator.compare(expected, actual)

    assert "constraints" in result["extra_fields"]
    assert "allowed_tools" in result["extra_fields"]
    # Extra fields are not penalized (score = 1.0)
    assert result["field_scores"]["constraints"] == 1.0
    assert result["field_scores"]["allowed_tools"] == 1.0


def test_handoff_comparator_string_overlap():
    """Test HandoffComparator string field similarity scoring."""
    expected = HandoffArtifact(goal="Extract customer data from database")
    actual = HandoffArtifact(goal="Extract customer information from database")

    result = HandoffComparator.compare(expected, actual)

    # Should have partial overlap (not 0, not 1)
    goal_score = result["field_scores"]["goal"]
    assert 0.0 < goal_score < 1.0


def test_handoff_comparator_list_overlap():
    """Test HandoffComparator list field similarity scoring."""
    expected = HandoffArtifact(constraints=["no pii", "read-only", "audit"])
    actual = HandoffArtifact(constraints=["no pii", "read-only"])

    result = HandoffComparator.compare(expected, actual)

    # 2 out of 3 expected items present
    assert result["field_scores"]["constraints"] == pytest.approx(2 / 3)


def test_handoff_comparator_dict_overlap():
    """Test HandoffComparator dict field similarity scoring."""
    expected = HandoffArtifact(known_facts={"a": 1, "b": 2, "c": 3})
    actual = HandoffArtifact(known_facts={"a": 1, "b": 2, "c": 999})

    result = HandoffComparator.compare(expected, actual)

    # 2 out of 3 keys match values
    assert result["field_scores"]["known_facts"] == pytest.approx(2 / 3)
