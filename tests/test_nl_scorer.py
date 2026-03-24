"""Tests for natural language scorer generation (Feature 3).

Covers NLCompiler, ScorerSpec, ScorerDimension, and NLScorer.
"""

from __future__ import annotations

import pytest

from core.types import GraderBundle, GraderSpec, GraderType
from evals.nl_compiler import NLCompiler
from evals.nl_scorer import NLScorer
from evals.scorer import EvalResult
from evals.scorer_spec import ScorerDimension, ScorerSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def compiler() -> NLCompiler:
    return NLCompiler()


@pytest.fixture
def scorer() -> NLScorer:
    return NLScorer()


def _make_result(
    case_id: str = "c1",
    quality: float = 0.8,
    latency: float = 1500.0,
    safety: bool = True,
    passed: bool = True,
    tokens: int = 500,
    tool_acc: float = 0.9,
    satisfaction: float = 0.85,
) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        category="happy_path",
        passed=passed,
        quality_score=quality,
        safety_passed=safety,
        latency_ms=latency,
        token_count=tokens,
        tool_use_accuracy=tool_acc,
        satisfaction_proxy=satisfaction,
    )


# ===================================================================
# NLCompiler._split_criteria tests
# ===================================================================

class TestSplitCriteria:
    def test_comma_separated(self, compiler: NLCompiler) -> None:
        result = compiler._split_criteria("accurate, fast, safe")
        assert len(result) == 3
        assert "accurate" in result
        assert "fast" in result
        assert "safe" in result

    def test_and_separated(self, compiler: NLCompiler) -> None:
        result = compiler._split_criteria("accurate and fast and safe")
        assert len(result) == 3

    def test_newline_separated(self, compiler: NLCompiler) -> None:
        result = compiler._split_criteria("accurate\nfast\nsafe")
        assert len(result) == 3

    def test_bullet_points(self, compiler: NLCompiler) -> None:
        result = compiler._split_criteria("- accurate\n- fast\n- safe")
        assert len(result) == 3

    def test_mixed_separators(self, compiler: NLCompiler) -> None:
        result = compiler._split_criteria(
            "accurate, and not hallucinate"
        )
        assert len(result) == 2

    def test_single_criterion(self, compiler: NLCompiler) -> None:
        result = compiler._split_criteria("respond accurately")
        assert len(result) == 1
        assert result[0] == "respond accurately"

    def test_empty_string(self, compiler: NLCompiler) -> None:
        assert compiler._split_criteria("") == []

    def test_semicolon_separated(self, compiler: NLCompiler) -> None:
        result = compiler._split_criteria("be accurate; be fast; be safe")
        assert len(result) == 3


# ===================================================================
# NLCompiler._match_pattern tests
# ===================================================================

class TestMatchPattern:
    def test_latency_under_3_seconds(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("respond in under 3 seconds")
        assert result is not None
        name, grader_type, config = result
        assert grader_type == "deterministic"
        assert config["type"] == "latency_threshold"
        assert config["threshold_ms"] == 3000

    def test_latency_within_5s(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("respond within 5s")
        assert result is not None
        _, grader_type, config = result
        assert grader_type == "deterministic"
        assert config["threshold_ms"] == 5000

    def test_latency_500ms(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("respond in under 500ms")
        assert result is not None
        _, _, config = result
        assert config["threshold_ms"] == 500

    def test_safety_hallucination(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("don't make up information")
        assert result is not None
        _, grader_type, config = result
        assert grader_type == "llm_judge"
        assert config["type"] == "hallucination_check"

    def test_accuracy_pattern(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("the response must be accurate")
        assert result is not None
        _, grader_type, config = result
        assert grader_type == "llm_judge"
        assert config["type"] == "accuracy_check"

    def test_tone_pattern(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("stay professional at all times")
        assert result is not None
        _, grader_type, config = result
        assert grader_type == "llm_judge"
        assert config["type"] == "tone_check"

    def test_completeness_pattern(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("provide a complete answer")
        assert result is not None
        _, grader_type, config = result
        assert config["type"] == "completeness_check"

    def test_first_contact_resolution(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("resolve on first contact")
        assert result is not None
        _, grader_type, config = result
        assert config["type"] == "resolution_check"

    def test_tool_usage_pattern(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("use the right tool for the job")
        assert result is not None
        _, _, config = result
        assert config["type"] == "tool_usage_check"

    def test_followup_pattern(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("offer follow-up help")
        assert result is not None
        _, _, config = result
        assert config["type"] == "followup_check"

    def test_no_match_fallback(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("do a little dance")
        assert result is None


# ===================================================================
# NLCompiler.compile full pipeline tests
# ===================================================================

class TestCompile:
    def test_basic_compile(self, compiler: NLCompiler) -> None:
        dims = compiler.compile("accurate and fast")
        assert len(dims) == 2
        assert all(isinstance(d, ScorerDimension) for d in dims)

    def test_weight_assignment_sums_to_one(self, compiler: NLCompiler) -> None:
        dims = compiler.compile("accurate, safe, fast, complete")
        total = sum(d.weight for d in dims)
        assert abs(total - 1.0) < 0.01

    def test_layer_classification(self, compiler: NLCompiler) -> None:
        dims = compiler.compile(
            "respond in under 3 seconds, don't hallucinate, be accurate"
        )
        layers = {d.name: d.layer for d in dims}
        # Latency -> slo, hallucination -> hard_gate, accuracy -> outcome
        slo_dims = [d for d in dims if d.layer == "slo"]
        gate_dims = [d for d in dims if d.layer == "hard_gate"]
        outcome_dims = [d for d in dims if d.layer == "outcome"]
        assert len(slo_dims) >= 1
        assert len(gate_dims) >= 1
        assert len(outcome_dims) >= 1

    def test_empty_input(self, compiler: NLCompiler) -> None:
        assert compiler.compile("") == []

    def test_fallback_to_llm_judge(self, compiler: NLCompiler) -> None:
        dims = compiler.compile("do a little dance")
        assert len(dims) == 1
        assert dims[0].grader_type == "llm_judge"
        assert dims[0].grader_config["type"] == "custom_check"
        assert "dance" in dims[0].grader_config["rubric"]


# ===================================================================
# NLCompiler._generate_dimension_name tests
# ===================================================================

class TestGenerateDimensionName:
    def test_basic_name(self, compiler: NLCompiler) -> None:
        name = compiler._generate_dimension_name("respond accurately")
        assert "respond" in name or "accurat" in name
        assert "_" not in name or name.replace("_", "").isalnum()

    def test_strips_stop_words(self, compiler: NLCompiler) -> None:
        name = compiler._generate_dimension_name(
            "the agent should be accurate"
        )
        assert "the" not in name.split("_")
        assert "be" not in name.split("_")

    def test_empty_after_filtering(self, compiler: NLCompiler) -> None:
        name = compiler._generate_dimension_name("a the is")
        assert name == "criterion"


# ===================================================================
# NLCompiler._classify_layer tests
# ===================================================================

class TestClassifyLayer:
    def test_deterministic_latency_is_slo(self, compiler: NLCompiler) -> None:
        assert compiler._classify_layer(
            "deterministic", {"type": "latency_threshold"}
        ) == "slo"

    def test_hallucination_is_hard_gate(self, compiler: NLCompiler) -> None:
        assert compiler._classify_layer(
            "llm_judge", {"type": "hallucination_check"}
        ) == "hard_gate"

    def test_accuracy_is_outcome(self, compiler: NLCompiler) -> None:
        assert compiler._classify_layer(
            "llm_judge", {"type": "accuracy_check"}
        ) == "outcome"

    def test_unknown_is_diagnostic(self, compiler: NLCompiler) -> None:
        assert compiler._classify_layer(
            "llm_judge", {"type": "unknown_thing"}
        ) == "diagnostic"


# ===================================================================
# ScorerDimension tests
# ===================================================================

class TestScorerDimension:
    def test_to_dict_from_dict_roundtrip(self) -> None:
        dim = ScorerDimension(
            name="accuracy",
            description="must be accurate",
            grader_type="llm_judge",
            grader_config={"type": "accuracy_check", "rubric": "be accurate"},
            weight=0.5,
            layer="outcome",
            required=False,
        )
        d = dim.to_dict()
        restored = ScorerDimension.from_dict(d)
        assert restored.name == dim.name
        assert restored.description == dim.description
        assert restored.grader_type == dim.grader_type
        assert restored.grader_config == dim.grader_config
        assert restored.weight == dim.weight
        assert restored.layer == dim.layer
        assert restored.required == dim.required

    def test_to_grader_spec(self) -> None:
        dim = ScorerDimension(
            name="latency_check",
            description="under 3 seconds",
            grader_type="deterministic",
            grader_config={"type": "latency_threshold", "threshold_ms": 3000},
            weight=0.3,
            required=True,
        )
        spec = dim.to_grader_spec()
        assert isinstance(spec, GraderSpec)
        assert spec.grader_type == GraderType.deterministic
        assert spec.grader_id == "latency_check"
        assert spec.weight == 0.3
        assert spec.required is True
        assert spec.config["threshold_ms"] == 3000


# ===================================================================
# ScorerSpec tests
# ===================================================================

class TestScorerSpec:
    def _make_spec(self) -> ScorerSpec:
        return ScorerSpec(
            name="test_scorer",
            version=2,
            dimensions=[
                ScorerDimension(
                    name="accuracy",
                    description="be accurate",
                    grader_type="llm_judge",
                    grader_config={"type": "accuracy_check", "rubric": "accurate"},
                    weight=0.6,
                    layer="outcome",
                ),
                ScorerDimension(
                    name="latency",
                    description="under 3s",
                    grader_type="deterministic",
                    grader_config={"type": "latency_threshold", "threshold_ms": 3000},
                    weight=0.4,
                    layer="slo",
                    required=True,
                ),
            ],
            source_nl="be accurate, under 3s",
        )

    def test_to_dict_from_dict_roundtrip(self) -> None:
        spec = self._make_spec()
        d = spec.to_dict()
        restored = ScorerSpec.from_dict(d)
        assert restored.name == spec.name
        assert restored.version == spec.version
        assert len(restored.dimensions) == 2
        assert restored.source_nl == spec.source_nl

    def test_to_yaml_from_yaml_roundtrip(self) -> None:
        spec = self._make_spec()
        yaml_str = spec.to_yaml()
        restored = ScorerSpec.from_yaml(yaml_str)
        assert restored.name == spec.name
        assert restored.version == spec.version
        assert len(restored.dimensions) == 2

    def test_to_grader_bundle(self) -> None:
        spec = self._make_spec()
        bundle = spec.to_grader_bundle()
        assert isinstance(bundle, GraderBundle)
        assert len(bundle.graders) == 2
        assert bundle.metadata["source_scorer"] == "test_scorer"
        assert bundle.metadata["version"] == 2

    def test_total_weight(self) -> None:
        spec = self._make_spec()
        assert abs(spec.total_weight() - 1.0) < 0.001

    def test_get_dimensions_by_layer(self) -> None:
        spec = self._make_spec()
        outcome_dims = spec.get_dimensions_by_layer("outcome")
        assert len(outcome_dims) == 1
        assert outcome_dims[0].name == "accuracy"
        slo_dims = spec.get_dimensions_by_layer("slo")
        assert len(slo_dims) == 1
        assert slo_dims[0].name == "latency"
        assert spec.get_dimensions_by_layer("hard_gate") == []


# ===================================================================
# NLScorer tests
# ===================================================================

class TestNLScorer:
    def test_create_basic(self, scorer: NLScorer) -> None:
        spec = scorer.create("accurate and fast")
        assert isinstance(spec, ScorerSpec)
        assert len(spec.dimensions) == 2
        assert spec.version == 1
        assert spec.source_nl == "accurate and fast"

    def test_create_with_name(self, scorer: NLScorer) -> None:
        spec = scorer.create("accurate", name="my_scorer")
        assert spec.name == "my_scorer"

    def test_create_auto_generates_name(self, scorer: NLScorer) -> None:
        spec = scorer.create("the agent should be accurate")
        assert spec.name  # non-empty
        assert " " not in spec.name

    def test_create_realistic_description_1(self, scorer: NLScorer) -> None:
        spec = scorer.create(
            "The agent should answer accurately, not hallucinate, "
            "respond in under 3 seconds, and offer follow-up help"
        )
        assert len(spec.dimensions) == 4
        types = {d.grader_config.get("type") for d in spec.dimensions}
        assert "accuracy_check" in types or "hallucination_check" in types
        assert "latency_threshold" in types
        # Weights should sum to ~1.0
        assert abs(spec.total_weight() - 1.0) < 0.01

    def test_create_realistic_description_2(self, scorer: NLScorer) -> None:
        spec = scorer.create(
            "Good means resolves on first contact, stays professional, "
            "uses the right tools"
        )
        assert len(spec.dimensions) == 3
        types = {d.grader_config.get("type") for d in spec.dimensions}
        assert "resolution_check" in types
        assert "tone_check" in types
        assert "tool_usage_check" in types

    def test_create_realistic_description_3(self, scorer: NLScorer) -> None:
        spec = scorer.create(
            "Safety: never share PII. Quality: always cite sources."
        )
        assert len(spec.dimensions) >= 2

    def test_refine_adds_dimensions(self, scorer: NLScorer) -> None:
        spec = scorer.create("be accurate", name="refine_test")
        assert len(spec.dimensions) == 1
        refined = scorer.refine("refine_test", "and be complete")
        assert len(refined.dimensions) == 2
        assert refined.version == 2

    def test_refine_nonexistent_raises(self, scorer: NLScorer) -> None:
        with pytest.raises(KeyError):
            scorer.refine("nonexistent", "be fast")

    def test_get_returns_spec(self, scorer: NLScorer) -> None:
        scorer.create("accurate", name="get_test")
        spec = scorer.get("get_test")
        assert spec is not None
        assert spec.name == "get_test"

    def test_get_returns_none_for_missing(self, scorer: NLScorer) -> None:
        assert scorer.get("nonexistent") is None

    def test_list_returns_all(self, scorer: NLScorer) -> None:
        scorer.create("accurate", name="list_a")
        scorer.create("fast", name="list_b")
        specs = scorer.list()
        names = {s.name for s in specs}
        assert "list_a" in names
        assert "list_b" in names

    def test_test_scores_eval_result(self, scorer: NLScorer) -> None:
        scorer.create("accurate and respond in under 3 seconds", name="test_scorer")
        result = _make_result(quality=0.9, latency=1500)
        scores = scorer.test("test_scorer", result)
        assert "dimensions" in scores
        assert "aggregate_score" in scores
        assert "passed" in scores
        assert scores["aggregate_score"] > 0

    def test_test_latency_pass(self, scorer: NLScorer) -> None:
        scorer.create("respond in under 3 seconds", name="lat_pass")
        result = _make_result(latency=2000)
        scores = scorer.test("lat_pass", result)
        assert scores["passed"] is True

    def test_test_latency_fail(self, scorer: NLScorer) -> None:
        scorer.create("respond in under 3 seconds", name="lat_fail")
        result = _make_result(latency=5000)
        scores = scorer.test("lat_fail", result)
        # Latency dimension should fail
        lat_dims = [
            v for v in scores["dimensions"].values()
            if v.get("layer") == "slo"
        ]
        assert any(not d["passed"] for d in lat_dims)

    def test_test_safety_dimension(self, scorer: NLScorer) -> None:
        scorer.create("don't hallucinate", name="safety_test")
        safe_result = _make_result(safety=True)
        unsafe_result = _make_result(safety=False)
        safe_scores = scorer.test("safety_test", safe_result)
        unsafe_scores = scorer.test("safety_test", unsafe_result)
        assert safe_scores["aggregate_score"] > unsafe_scores["aggregate_score"]

    def test_score_results_multiple(self, scorer: NLScorer) -> None:
        scorer.create("accurate", name="multi_test")
        results = [
            _make_result(case_id="c1", quality=0.9),
            _make_result(case_id="c2", quality=0.3),
            _make_result(case_id="c3", quality=0.7),
        ]
        scores = scorer.score_results("multi_test", results)
        assert scores["total_results"] == 3
        assert scores["average_score"] > 0
        assert scores["passed_count"] + scores["failed_count"] == 3

    def test_score_results_empty(self, scorer: NLScorer) -> None:
        scorer.create("accurate", name="empty_test")
        scores = scorer.score_results("empty_test", [])
        assert scores["total_results"] == 0
        assert scores["average_score"] == 0.0

    def test_test_nonexistent_raises(self, scorer: NLScorer) -> None:
        with pytest.raises(KeyError):
            scorer.test("nonexistent", _make_result())

    def test_generate_name(self) -> None:
        name = NLScorer._generate_name("the agent should be accurate and fast")
        assert " " not in name
        assert len(name) > 0


# ===================================================================
# NLCompiler._build_grader_config tests
# ===================================================================

class TestBuildGraderConfig:
    def test_latency_seconds_conversion(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("respond in under 5 seconds")
        assert result is not None
        _, _, config = result
        assert config["threshold_ms"] == 5000
        assert config["operator"] == "lte"

    def test_llm_judge_includes_rubric(self, compiler: NLCompiler) -> None:
        result = compiler._match_pattern("be accurate in responses")
        assert result is not None
        _, _, config = result
        assert "rubric" in config
        assert "accurate" in config["rubric"]
