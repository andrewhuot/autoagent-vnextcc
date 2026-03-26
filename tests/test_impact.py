"""Tests for multi-agent impact analyzer."""

from __future__ import annotations

from multi_agent.agent_tree import AgentNode, AgentTree, Dependency, DependencyType
from multi_agent.impact_analyzer import (
    CrossAgentEvalResult,
    ImpactAnalyzer,
    ImpactPrediction,
)


def build_sample_agent_tree() -> AgentTree:
    """Build a sample agent tree for testing."""
    tree = AgentTree()

    # Add root orchestrator
    root = AgentNode(
        agent_id="root",
        agent_name="Main Orchestrator",
        agent_type="orchestrator",
        agent_path="root",
        tools=["router"],
        policies=["safety_policy"],
    )
    tree.add_agent(root)

    # Add support specialist
    support = AgentNode(
        agent_id="support",
        agent_name="Support Agent",
        agent_type="specialist",
        agent_path="root/support",
        tools=["faq", "ticketing"],
        policies=["safety_policy", "escalation_policy"],
        parent_id="root",
    )
    tree.add_agent(support)

    # Add sales specialist
    sales = AgentNode(
        agent_id="sales",
        agent_name="Sales Agent",
        agent_type="specialist",
        agent_path="root/sales",
        tools=["catalog", "pricing"],
        policies=["safety_policy"],
        parent_id="root",
    )
    tree.add_agent(sales)

    # Add orders specialist
    orders = AgentNode(
        agent_id="orders",
        agent_name="Orders Agent",
        agent_type="specialist",
        agent_path="root/support/orders",
        tools=["orders_db", "ticketing"],
        policies=["escalation_policy"],
        parent_id="support",
    )
    tree.add_agent(orders)

    # Add routing dependencies
    tree.add_dependency(
        Dependency(
            from_agent_id="root",
            to_agent_id="support",
            dependency_type=DependencyType.ROUTING,
        )
    )
    tree.add_dependency(
        Dependency(
            from_agent_id="root",
            to_agent_id="sales",
            dependency_type=DependencyType.ROUTING,
        )
    )
    tree.add_dependency(
        Dependency(
            from_agent_id="support",
            to_agent_id="orders",
            dependency_type=DependencyType.ROUTING,
        )
    )

    # Add shared tool dependencies
    tree.add_dependency(
        Dependency(
            from_agent_id="support",
            to_agent_id="orders",
            dependency_type=DependencyType.SHARED_TOOL,
            shared_resource="ticketing",
        )
    )

    # Add shared policy dependencies
    tree.add_dependency(
        Dependency(
            from_agent_id="root",
            to_agent_id="support",
            dependency_type=DependencyType.SHARED_POLICY,
            shared_resource="safety_policy",
        )
    )
    tree.add_dependency(
        Dependency(
            from_agent_id="root",
            to_agent_id="sales",
            dependency_type=DependencyType.SHARED_POLICY,
            shared_resource="safety_policy",
        )
    )

    return tree


# ---------------------------------------------------------------------------
# AgentTree tests
# ---------------------------------------------------------------------------


def test_agent_tree_add_and_get_agent() -> None:
    """AgentTree should store and retrieve agents."""
    tree = AgentTree()
    agent = AgentNode(
        agent_id="test1",
        agent_name="Test Agent",
        agent_type="specialist",
        agent_path="root/test",
    )
    tree.add_agent(agent)

    retrieved = tree.get_agent("test1")
    assert retrieved is not None
    assert retrieved.agent_id == "test1"
    assert retrieved.agent_name == "Test Agent"


def test_agent_tree_get_children() -> None:
    """AgentTree should return children of an agent."""
    tree = build_sample_agent_tree()

    root_children = tree.get_children("root")
    assert len(root_children) == 2
    child_ids = [c.agent_id for c in root_children]
    assert "support" in child_ids
    assert "sales" in child_ids

    support_children = tree.get_children("support")
    assert len(support_children) == 1
    assert support_children[0].agent_id == "orders"


def test_agent_tree_get_parent() -> None:
    """AgentTree should return parent of an agent."""
    tree = build_sample_agent_tree()

    support_parent = tree.get_parent("support")
    assert support_parent is not None
    assert support_parent.agent_id == "root"

    root_parent = tree.get_parent("root")
    assert root_parent is None


def test_agent_tree_get_downstream_dependencies() -> None:
    """AgentTree should find downstream dependencies."""
    tree = build_sample_agent_tree()

    root_downstream = tree.get_downstream_dependencies("root")
    assert "support" in root_downstream
    assert "sales" in root_downstream


def test_agent_tree_get_upstream_dependencies() -> None:
    """AgentTree should find upstream dependencies."""
    tree = build_sample_agent_tree()

    support_upstream = tree.get_upstream_dependencies("support")
    assert "root" in support_upstream


def test_agent_tree_get_shared_tools() -> None:
    """AgentTree should find agents sharing a tool."""
    tree = build_sample_agent_tree()

    agents_with_ticketing = tree.get_shared_tools("ticketing")
    assert len(agents_with_ticketing) == 2
    assert "support" in agents_with_ticketing
    assert "orders" in agents_with_ticketing


def test_agent_tree_get_shared_policies() -> None:
    """AgentTree should find agents sharing a policy."""
    tree = build_sample_agent_tree()

    agents_with_safety = tree.get_shared_policies("safety_policy")
    assert len(agents_with_safety) >= 2
    assert "root" in agents_with_safety
    assert "support" in agents_with_safety


def test_agent_tree_find_affected_agents() -> None:
    """AgentTree should find all agents affected by a change."""
    tree = build_sample_agent_tree()

    affected = tree.find_affected_agents("root")
    # Root change affects support, sales, and potentially orders
    assert "support" in affected
    assert "sales" in affected


def test_agent_tree_from_config() -> None:
    """AgentTree should parse from configuration."""
    config = {
        "agents": [
            {
                "id": "root",
                "name": "Orchestrator",
                "type": "orchestrator",
                "path": "root",
                "tools": ["router"],
                "policies": ["safety"],
                "children": ["agent1"],
            },
            {
                "id": "agent1",
                "name": "Agent 1",
                "type": "specialist",
                "path": "root/agent1",
                "tools": ["tool1"],
                "policies": ["safety"],
                "parent_id": "root",
            },
        ]
    }

    tree = AgentTree.from_config(config)
    assert len(tree.agents) == 2
    assert tree.get_agent("root") is not None
    assert tree.get_agent("agent1") is not None

    # Should have routing dependency
    root_downstream = tree.get_downstream_dependencies("root")
    assert "agent1" in root_downstream


def test_agent_tree_to_dict() -> None:
    """AgentTree should serialize to dictionary."""
    tree = build_sample_agent_tree()
    tree_dict = tree.to_dict()

    assert "agents" in tree_dict
    assert "dependencies" in tree_dict
    assert len(tree_dict["agents"]) == 4
    assert len(tree_dict["dependencies"]) > 0


# ---------------------------------------------------------------------------
# ImpactAnalyzer tests
# ---------------------------------------------------------------------------


def test_impact_analyzer_analyze_dependencies() -> None:
    """ImpactAnalyzer should compute dependency statistics."""
    tree = build_sample_agent_tree()
    analyzer = ImpactAnalyzer(agent_tree=tree)

    analysis = analyzer.analyze_dependencies(tree)

    assert analysis["total_agents"] == 4
    assert analysis["total_dependencies"] > 0
    assert "dependencies_by_type" in analysis
    assert "most_connected_agents" in analysis
    assert "shared_tools" in analysis
    assert "shared_policies" in analysis


def test_impact_analyzer_predict_impact() -> None:
    """ImpactAnalyzer should predict impact of changes."""
    tree = build_sample_agent_tree()
    analyzer = ImpactAnalyzer(agent_tree=tree)

    report = analyzer.predict_impact(
        mutation_id="mut123", target_agent_id="root"
    )

    assert report.report_id.startswith("impact_")
    assert report.mutation_id == "mut123"
    assert report.target_agent_id == "root"
    assert len(report.affected_agents) > 0
    assert len(report.predictions) > 0
    assert report.overall_confidence >= 0
    assert report.overall_confidence <= 1.0
    assert report.recommendation in [
        "SAFE_TO_DEPLOY",
        "PROCEED_WITH_CAUTION",
        "NEEDS_MORE_ANALYSIS",
    ]


def test_impact_analyzer_predict_impact_nonexistent_agent() -> None:
    """ImpactAnalyzer should raise error for non-existent agent."""
    tree = build_sample_agent_tree()
    analyzer = ImpactAnalyzer(agent_tree=tree)

    try:
        analyzer.predict_impact(
            mutation_id="mut123", target_agent_id="nonexistent"
        )
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "not found" in str(e)


def test_impact_analyzer_cross_agent_eval() -> None:
    """ImpactAnalyzer should evaluate mutations across agents."""
    tree = build_sample_agent_tree()
    analyzer = ImpactAnalyzer(agent_tree=tree)

    results = analyzer.cross_agent_eval(
        mutation_id="mut123",
        affected_agents=["support", "sales"],
    )

    assert len(results) == 2
    for result in results:
        assert result.agent_id in ["support", "sales"]
        assert result.baseline_score >= 0
        assert result.mutated_score >= 0
        assert isinstance(result.improved, bool)


def test_impact_analyzer_generate_impact_report() -> None:
    """ImpactAnalyzer should generate structured impact report."""
    predictions = [
        ImpactPrediction(
            agent_id="agent1",
            agent_name="Agent 1",
            impact_level="high",
            impact_reasons=["Routing dependency"],
            predicted_score_delta=0.05,
            confidence=0.9,
        ),
        ImpactPrediction(
            agent_id="agent2",
            agent_name="Agent 2",
            impact_level="low",
            impact_reasons=["Shared tool"],
            predicted_score_delta=0.01,
            confidence=0.6,
        ),
    ]

    eval_results = [
        CrossAgentEvalResult(
            agent_id="agent1",
            agent_name="Agent 1",
            baseline_score=0.75,
            mutated_score=0.80,
            delta_score=0.05,
            conversation_count=50,
            improved=True,
        ),
        CrossAgentEvalResult(
            agent_id="agent2",
            agent_name="Agent 2",
            baseline_score=0.70,
            mutated_score=0.68,
            delta_score=-0.02,
            conversation_count=50,
            improved=False,
        ),
    ]

    tree = build_sample_agent_tree()
    analyzer = ImpactAnalyzer(agent_tree=tree)

    report = analyzer.generate_impact_report(predictions, eval_results)

    assert "summary" in report
    assert report["summary"]["total_affected_agents"] == 2
    assert report["summary"]["high_impact_count"] == 1
    assert report["summary"]["improved_count"] == 1
    assert report["summary"]["degraded_count"] == 1

    assert "predictions" in report
    assert "evaluation_results" in report


def test_impact_prediction_defaults() -> None:
    """ImpactPrediction should have correct structure."""
    prediction = ImpactPrediction(
        agent_id="test",
        agent_name="Test Agent",
        impact_level="medium",
        impact_reasons=["Test reason"],
        predicted_score_delta=0.03,
        confidence=0.8,
    )

    assert prediction.agent_id == "test"
    assert prediction.impact_level == "medium"
    assert len(prediction.impact_reasons) == 1
