"""Tests for LLM-driven failure analysis with deterministic fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass

from optimizer.failure_analyzer import (
    FailureAnalysis,
    FailureAnalyzer,
    FailureCluster,
    SurfaceRecommendation,
    _deterministic_analysis,
    _extract_json_payload,
    _parse_llm_analysis,
)
from optimizer.providers import LLMRequest, LLMResponse, LLMRouter, ModelConfig, RetryPolicy


# ---------------------------------------------------------------------------
# Mock LLM provider
# ---------------------------------------------------------------------------


@dataclass
class _MockProvider:
    """Returns a canned JSON response for failure analysis tests."""

    response_text: str = ""
    raise_error: bool = False

    def complete(self, request: LLMRequest, retry_policy: RetryPolicy) -> LLMResponse:
        if self.raise_error:
            raise RuntimeError("Simulated LLM failure")
        return LLMResponse(
            provider="mock",
            model="mock-analyzer",
            text=self.response_text,
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            latency_ms=50.0,
        )


def _make_router(response_text: str = "", raise_error: bool = False) -> LLMRouter:
    """Build an LLMRouter wired to a mock provider."""
    model = ModelConfig(provider="mock", model="mock-analyzer")
    provider = _MockProvider(response_text=response_text, raise_error=raise_error)
    return LLMRouter(
        strategy="single",
        models=[model],
        providers={("mock", "mock-analyzer"): provider},
    )


_SAMPLE_LLM_RESPONSE = json.dumps({
    "clusters": [
        {
            "cluster_id": "clust-routing",
            "description": "Messages about billing routed to wrong specialist",
            "root_cause_hypothesis": "Routing rules lack billing-related keywords",
            "failure_type": "routing_error",
            "sample_ids": ["s1", "s2"],
            "affected_agent": "root",
            "severity": 0.85,
            "count": 5,
        },
        {
            "cluster_id": "clust-tool",
            "description": "Calendar tool returns schema errors",
            "root_cause_hypothesis": "Tool contract date format mismatch",
            "failure_type": "tool_failure",
            "sample_ids": ["s3"],
            "affected_agent": "root/scheduler",
            "severity": 0.6,
            "count": 2,
        },
    ],
    "surface_recommendations": [
        {
            "surface": "routing",
            "agent_path": "root",
            "confidence": 0.9,
            "reasoning": "Routing rules need billing keywords",
            "suggested_approach": "Add billing, invoice, payment to routing keywords",
            "priority": 1,
        },
        {
            "surface": "tool_contract",
            "agent_path": "root/scheduler",
            "confidence": 0.75,
            "reasoning": "Calendar tool expects ISO dates but receives natural language",
            "suggested_approach": "Add date parsing instruction to tool description",
            "priority": 2,
        },
    ],
    "severity_ranking": ["clust-routing", "clust-tool"],
    "cross_cutting_patterns": [
        "Routing and tool failures compound: misrouted messages hit tools with wrong args",
    ],
    "summary": "5 routing errors and 2 tool failures. Routing keywords need expansion; calendar tool contract needs date format fix.",
})

_SAMPLE_AGENT_CARD = """\
# Agent: SupportBot
A customer support agent.

## Instructions
Help customers with billing and scheduling.

## Tools
- calendar: Schedule appointments
- faq: Look up answers
"""

_SAMPLE_EVAL_RESULTS: dict = {
    "failure_buckets": {
        "routing_error": 5,
        "tool_failure": 2,
        "hallucination": 0,
        "safety_violation": 0,
        "timeout": 0,
        "unhelpful_response": 0,
    },
    "failure_samples": [
        {"id": "s1", "failure_type": "routing_error", "failure_buckets": ["routing_error"]},
        {"id": "s2", "failure_type": "routing_error", "failure_buckets": ["routing_error"]},
        {"id": "s3", "failure_type": "tool_failure", "failure_buckets": ["tool_failure"]},
    ],
}


# ---------------------------------------------------------------------------
# Deterministic analysis tests
# ---------------------------------------------------------------------------


def test_deterministic_single_bucket() -> None:
    """Deterministic path should produce one cluster and recommendation for a single non-zero bucket."""
    buckets = {"routing_error": 3, "tool_failure": 0, "hallucination": 0}
    result = _deterministic_analysis(buckets, [])

    assert len(result.clusters) == 1
    assert result.clusters[0].failure_type == "routing_error"
    assert result.clusters[0].count == 3
    assert result.clusters[0].cluster_id == "det-routing_error"

    assert len(result.surface_recommendations) == 1
    assert result.surface_recommendations[0].surface == "routing"
    assert result.surface_recommendations[0].priority == 1


def test_deterministic_multiple_buckets_ordered_by_count() -> None:
    """Clusters and recommendations should be sorted by failure count descending."""
    buckets = {
        "routing_error": 2,
        "tool_failure": 5,
        "hallucination": 1,
        "timeout": 0,
    }
    result = _deterministic_analysis(buckets, [])

    assert len(result.clusters) == 3
    assert result.clusters[0].failure_type == "tool_failure"
    assert result.clusters[1].failure_type == "routing_error"
    assert result.clusters[2].failure_type == "hallucination"

    assert result.surface_recommendations[0].priority == 1
    assert result.surface_recommendations[0].surface == "tool_contract"
    assert result.surface_recommendations[1].priority == 2
    assert result.surface_recommendations[1].surface == "routing"
    assert result.surface_recommendations[2].priority == 3
    assert result.surface_recommendations[2].surface == "instruction"


def test_deterministic_severity_ranking_matches_cluster_order() -> None:
    """severity_ranking should list cluster_ids in the same order as clusters."""
    buckets = {"routing_error": 4, "hallucination": 2}
    result = _deterministic_analysis(buckets, [])

    assert result.severity_ranking == ["det-routing_error", "det-hallucination"]


def test_deterministic_all_zero_buckets() -> None:
    """All-zero buckets should produce an empty analysis."""
    buckets = {"routing_error": 0, "tool_failure": 0}
    result = _deterministic_analysis(buckets, [])

    assert len(result.clusters) == 0
    assert len(result.surface_recommendations) == 0
    assert result.severity_ranking == []


def test_deterministic_surface_mapping_correctness() -> None:
    """Each bucket should map to the expected MutationSurface value."""
    expected_mapping = {
        "routing_error": "routing",
        "tool_failure": "tool_contract",
        "hallucination": "instruction",
        "safety_violation": "policy",
        "timeout": "generation_settings",
        "unhelpful_response": "instruction",
        "invalid_output": "instruction",
    }
    for bucket, expected_surface in expected_mapping.items():
        result = _deterministic_analysis({bucket: 1}, [])
        assert len(result.surface_recommendations) == 1, f"Expected 1 rec for {bucket}"
        assert result.surface_recommendations[0].surface == expected_surface, (
            f"Bucket {bucket} should map to {expected_surface}, "
            f"got {result.surface_recommendations[0].surface}"
        )


def test_deterministic_sample_id_collection() -> None:
    """Deterministic analysis should collect sample IDs matching each bucket."""
    buckets = {"routing_error": 2, "tool_failure": 1}
    samples = [
        {"id": "s1", "failure_buckets": ["routing_error"]},
        {"id": "s2", "failure_buckets": ["routing_error"]},
        {"id": "s3", "failure_buckets": ["tool_failure"]},
    ]
    result = _deterministic_analysis(buckets, samples)

    routing_cluster = next(c for c in result.clusters if c.failure_type == "routing_error")
    tool_cluster = next(c for c in result.clusters if c.failure_type == "tool_failure")

    assert set(routing_cluster.sample_ids) == {"s1", "s2"}
    assert tool_cluster.sample_ids == ["s3"]


def test_deterministic_cross_cutting_routing_unhelpful() -> None:
    """Cross-cutting pattern should fire when routing + unhelpful co-occur."""
    buckets = {"routing_error": 3, "unhelpful_response": 2}
    result = _deterministic_analysis(buckets, [])

    assert len(result.cross_cutting_patterns) >= 1
    assert any("routing" in p.lower() for p in result.cross_cutting_patterns)


def test_deterministic_cross_cutting_tool_timeout() -> None:
    """Cross-cutting pattern should fire when tool_failure + timeout co-occur."""
    buckets = {"tool_failure": 2, "timeout": 3}
    result = _deterministic_analysis(buckets, [])

    assert len(result.cross_cutting_patterns) >= 1
    assert any("tool" in p.lower() and "timeout" in p.lower() for p in result.cross_cutting_patterns)


def test_deterministic_summary_mentions_top_buckets() -> None:
    """Summary should mention the top failure buckets."""
    buckets = {"routing_error": 10, "hallucination": 5, "timeout": 1}
    result = _deterministic_analysis(buckets, [])

    assert "routing_error" in result.summary
    assert "hallucination" in result.summary


# ---------------------------------------------------------------------------
# JSON extraction tests
# ---------------------------------------------------------------------------


def test_extract_json_from_clean_text() -> None:
    """Clean JSON string should parse directly."""
    payload = {"clusters": [], "summary": "ok"}
    result = _extract_json_payload(json.dumps(payload))
    assert result == payload


def test_extract_json_from_wrapped_text() -> None:
    """JSON embedded in prose should be extracted via regex fallback."""
    text = 'Here is the analysis:\n\n{"summary": "found issues"}\n\nHope that helps!'
    result = _extract_json_payload(text)
    assert result is not None
    assert result["summary"] == "found issues"


def test_extract_json_returns_none_on_garbage() -> None:
    """Unparseable text should return None."""
    assert _extract_json_payload("no json here") is None
    assert _extract_json_payload("") is None


# ---------------------------------------------------------------------------
# LLM analysis parse tests
# ---------------------------------------------------------------------------


def test_parse_llm_analysis_full_payload() -> None:
    """Full LLM response should parse into FailureAnalysis with all fields."""
    payload = json.loads(_SAMPLE_LLM_RESPONSE)
    result = _parse_llm_analysis(payload)

    assert len(result.clusters) == 2
    assert result.clusters[0].cluster_id == "clust-routing"
    assert result.clusters[0].severity == 0.85
    assert result.clusters[1].affected_agent == "root/scheduler"

    assert len(result.surface_recommendations) == 2
    assert result.surface_recommendations[0].surface == "routing"
    assert result.surface_recommendations[0].priority == 1
    assert result.surface_recommendations[1].surface == "tool_contract"

    assert result.severity_ranking == ["clust-routing", "clust-tool"]
    assert len(result.cross_cutting_patterns) == 1
    assert "summary" in result.summary.lower() or len(result.summary) > 0


def test_parse_llm_analysis_empty_payload() -> None:
    """Empty payload should produce an empty FailureAnalysis."""
    result = _parse_llm_analysis({})

    assert result.clusters == []
    assert result.surface_recommendations == []
    assert result.severity_ranking == []
    assert result.summary == ""


# ---------------------------------------------------------------------------
# FailureAnalyzer integration tests
# ---------------------------------------------------------------------------


def test_analyzer_uses_llm_when_available() -> None:
    """FailureAnalyzer should use LLM path when a router is provided."""
    router = _make_router(response_text=_SAMPLE_LLM_RESPONSE)
    analyzer = FailureAnalyzer(llm_router=router)

    result = analyzer.analyze(
        eval_results=_SAMPLE_EVAL_RESULTS,
        agent_card_markdown=_SAMPLE_AGENT_CARD,
    )

    assert len(result.clusters) == 2
    assert result.clusters[0].cluster_id == "clust-routing"
    assert result.surface_recommendations[0].surface == "routing"


def test_analyzer_falls_back_on_llm_error() -> None:
    """FailureAnalyzer should fall back to deterministic on LLM failure."""
    router = _make_router(raise_error=True)
    analyzer = FailureAnalyzer(llm_router=router)

    result = analyzer.analyze(
        eval_results=_SAMPLE_EVAL_RESULTS,
        agent_card_markdown=_SAMPLE_AGENT_CARD,
    )

    # Should get deterministic clusters (det-routing_error, det-tool_failure).
    assert len(result.clusters) >= 2
    assert all(c.cluster_id.startswith("det-") for c in result.clusters)


def test_analyzer_falls_back_on_unparseable_response() -> None:
    """Unparseable LLM response should trigger deterministic fallback."""
    router = _make_router(response_text="I don't know how to analyze this.")
    analyzer = FailureAnalyzer(llm_router=router)

    result = analyzer.analyze(
        eval_results=_SAMPLE_EVAL_RESULTS,
        agent_card_markdown=_SAMPLE_AGENT_CARD,
    )

    assert all(c.cluster_id.startswith("det-") for c in result.clusters)


def test_analyzer_deterministic_when_no_router() -> None:
    """FailureAnalyzer without router should always use deterministic path."""
    analyzer = FailureAnalyzer()

    result = analyzer.analyze(
        eval_results=_SAMPLE_EVAL_RESULTS,
        agent_card_markdown=_SAMPLE_AGENT_CARD,
    )

    assert len(result.clusters) == 2  # routing_error + tool_failure
    assert result.clusters[0].cluster_id.startswith("det-")


def test_analyzer_empty_failures() -> None:
    """No failures should return an empty analysis with a summary."""
    analyzer = FailureAnalyzer()
    eval_results: dict = {
        "failure_buckets": {"routing_error": 0, "tool_failure": 0},
        "failure_samples": [],
    }

    result = analyzer.analyze(
        eval_results=eval_results,
        agent_card_markdown=_SAMPLE_AGENT_CARD,
    )

    assert len(result.clusters) == 0
    assert len(result.surface_recommendations) == 0
    assert "no failures" in result.summary.lower()


def test_analyzer_passes_past_attempts_to_llm() -> None:
    """Past attempts should be included in the LLM prompt."""
    captured_prompts: list[str] = []

    @dataclass
    class _CapturingProvider:
        def complete(self, request: LLMRequest, retry_policy: RetryPolicy) -> LLMResponse:
            captured_prompts.append(request.prompt)
            return LLMResponse(
                provider="mock",
                model="mock-analyzer",
                text=_SAMPLE_LLM_RESPONSE,
                prompt_tokens=100,
                completion_tokens=200,
                total_tokens=300,
                latency_ms=50.0,
            )

    model = ModelConfig(provider="mock", model="mock-analyzer")
    provider = _CapturingProvider()
    router = LLMRouter(
        strategy="single",
        models=[model],
        providers={("mock", "mock-analyzer"): provider},
    )

    analyzer = FailureAnalyzer(llm_router=router)
    past = [{"attempt": 1, "surface": "routing", "outcome": "no improvement"}]

    analyzer.analyze(
        eval_results=_SAMPLE_EVAL_RESULTS,
        agent_card_markdown=_SAMPLE_AGENT_CARD,
        past_attempts=past,
    )

    assert len(captured_prompts) == 1
    assert "Past Optimization Attempts" in captured_prompts[0]
    assert "no improvement" in captured_prompts[0]


def test_analyzer_missing_failure_buckets_key() -> None:
    """Missing failure_buckets key should be treated as no failures."""
    analyzer = FailureAnalyzer()
    result = analyzer.analyze(eval_results={}, agent_card_markdown=_SAMPLE_AGENT_CARD)

    assert result.clusters == []
    assert "no failures" in result.summary.lower()


def test_analyzer_llm_response_with_markdown_fences() -> None:
    """LLM response wrapped in markdown code fences should still parse."""
    fenced = f"```json\n{_SAMPLE_LLM_RESPONSE}\n```"
    # _extract_json_payload uses regex fallback which handles this.
    router = _make_router(response_text=fenced)
    analyzer = FailureAnalyzer(llm_router=router)

    result = analyzer.analyze(
        eval_results=_SAMPLE_EVAL_RESULTS,
        agent_card_markdown=_SAMPLE_AGENT_CARD,
    )

    assert len(result.clusters) == 2
    assert result.clusters[0].cluster_id == "clust-routing"
