"""Pydantic request/response models for all API endpoints."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from portability.types import ExportCapabilityMatrix, PortabilityReport


# ---------------------------------------------------------------------------
# Shared / common
# ---------------------------------------------------------------------------

class TaskStatusEnum(str, Enum):
    """Possible states for a background task."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    interrupted = "interrupted"


class TaskStatus(BaseModel):
    """Status of a long-running background task."""
    task_id: str = Field(..., description="Unique task identifier")
    task_type: str = Field(..., description="Type of task (eval, optimize, loop)")
    status: TaskStatusEnum = Field(..., description="Current task status")
    progress: int = Field(0, ge=0, le=100, description="Progress percentage 0-100")
    result: Optional[Any] = Field(None, description="Task result when completed")
    error: Optional[str] = Field(None, description="Error message if failed")
    created_at: datetime = Field(..., description="Task creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    continuity: Optional[dict[str, Any]] = Field(None, description="Live/historical restart context")
    continuity_state: Optional[str] = Field(None, description="Compact continuity state")
    state_label: Optional[str] = Field(None, description="User-facing continuity label")
    state_detail: Optional[str] = Field(None, description="User-facing continuity explanation")


# ---------------------------------------------------------------------------
# Eval models
# ---------------------------------------------------------------------------

class EvalRunRequest(BaseModel):
    """Request to start an eval run."""
    config_path: Optional[str] = Field(None, description="Path to config YAML to evaluate; uses default if omitted")
    category: Optional[str] = Field(None, description="Run only a specific category of test cases")
    dataset_path: Optional[str] = Field(None, description="Dataset file (.jsonl/.csv/.yaml/.yml) for eval runs")
    generated_suite_id: Optional[str] = Field(
        None,
        description="Accepted or generated suite ID to run directly",
    )
    split: str = Field(
        "all",
        pattern="^(train|test|all)$",
        description="Dataset split used with dataset_path",
    )


class EvalCaseResult(BaseModel):
    """Result for a single eval test case."""
    case_id: str
    category: str
    passed: bool
    quality_score: float
    safety_passed: bool
    latency_ms: float
    token_count: int
    details: str = ""


class EvalRunResponse(BaseModel):
    """Response after starting an eval run."""
    task_id: str = Field(..., description="Background task ID to poll for results")
    message: str = Field("Eval run started", description="Human-readable status message")


class EvalResultsResponse(BaseModel):
    """Full results of a completed eval run."""
    run_id: str = Field(..., description="Eval run identifier")
    mode: str = Field(
        ...,
        pattern="^(mock|live|mixed)$",
        description="Whether the run executed in mock, live, or mixed mode",
    )
    quality: float = Field(..., description="Quality score 0-1")
    safety: float = Field(..., description="Safety score 0-1")
    latency: float = Field(..., description="Latency score 0-1 (higher is better)")
    cost: float = Field(..., description="Cost score 0-1 (higher is better)")
    composite: float = Field(..., description="Weighted composite score")
    confidence_intervals: dict[str, tuple[float, float]] = Field(
        default_factory=dict,
        description="95% bootstrap confidence intervals for headline metrics",
    )
    composite_breakdown: dict[str, Any] = Field(
        default_factory=dict,
        description="Weight/metric contribution breakdown for composite transparency",
    )
    safety_failures: int = Field(0, description="Number of safety failures")
    total_cases: int = Field(0, description="Total test cases run")
    passed_cases: int = Field(0, description="Test cases that passed")
    total_tokens: int = Field(0, description="Total output tokens consumed by the run")
    estimated_cost_usd: float = Field(0.0, description="Estimated eval cost in USD")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal eval warnings")
    cases: list[EvalCaseResult] = Field(default_factory=list, description="Per-case results")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")


# ---------------------------------------------------------------------------
# Auto-eval generation models
# ---------------------------------------------------------------------------

class AutoEvalGenerateRequest(BaseModel):
    """Request to generate an eval suite from an agent config."""
    agent_config: dict = Field(..., description="Agent configuration dict (system_prompt, tools, routing_rules, policies)")
    agent_name: str = Field("agent", description="Human-readable agent name")

class AutoEvalGenerateResponse(BaseModel):
    """Response after triggering eval generation."""
    suite_id: str = Field(..., description="Generated suite identifier")
    status: str = Field(..., description="Suite status: generating, ready, accepted")
    total_cases: int = Field(0, description="Total cases generated")
    message: str = Field("", description="Human-readable status message")


# ---------------------------------------------------------------------------
# Pairwise comparison models
# ---------------------------------------------------------------------------

class PairwiseVariantResponse(BaseModel):
    """One side of a pairwise case comparison."""

    response: str = Field("", description="Assistant response text")
    specialist_used: str = Field("", description="Specialist or agent path used")
    passed: bool = Field(False, description="Whether this side passed the case")
    quality_score: float = Field(0.0, description="Quality score for this side")
    safety_passed: bool = Field(False, description="Whether this side passed safety checks")
    latency_ms: float = Field(0.0, description="Latency for this side in milliseconds")
    token_count: int = Field(0, description="Token usage for this side")
    composite_score: float = Field(0.0, description="Per-case composite score")
    details: str = Field("", description="Evaluator notes for this side")
    raw_output: dict[str, Any] = Field(default_factory=dict, description="Raw agent payload")
    custom_scores: dict[str, float] = Field(default_factory=dict, description="Custom metric values")


class HumanPreferenceTaskResponse(BaseModel):
    """Deferred human review task for pairwise evaluation."""

    task_id: str = Field(..., description="Task identifier")
    case_id: str = Field(..., description="Associated case ID")
    label_a: str = Field(..., description="Left variant label")
    label_b: str = Field(..., description="Right variant label")
    prompt: str = Field("", description="Reviewer instructions")
    status: str = Field("pending", description="Task status")


class PairwiseCaseResponse(BaseModel):
    """One pairwise outcome at the case level."""

    case_id: str = Field(..., description="Eval case identifier")
    category: str = Field(..., description="Eval category")
    input_message: str = Field("", description="User message shown to both variants")
    left: PairwiseVariantResponse
    right: PairwiseVariantResponse
    winner: str = Field(..., description="Winning label, tie, or pending_human")
    winner_reason: str = Field("", description="Human-readable winner explanation")
    score_delta: float = Field(0.0, description="Right minus left composite delta")
    human_preference_task: HumanPreferenceTaskResponse | None = Field(
        None,
        description="Human review task when judgment is deferred",
    )


class PairwiseSummaryResponse(BaseModel):
    """Aggregate counts for one pairwise comparison."""

    total_cases: int = Field(0, description="Total pairwise cases evaluated")
    left_wins: int = Field(0, description="Cases won by label_a")
    right_wins: int = Field(0, description="Cases won by label_b")
    ties: int = Field(0, description="Cases that tied")
    pending_human: int = Field(0, description="Cases awaiting human review")


class PairwiseAnalysisResponse(BaseModel):
    """Statistical analysis summary for a pairwise comparison."""

    label_a: str = Field(..., description="Left variant label")
    label_b: str = Field(..., description="Right variant label")
    total_cases: int = Field(0, description="Number of paired cases analyzed")
    mean_score_a: float = Field(0.0, description="Average score for label_a")
    mean_score_b: float = Field(0.0, description="Average score for label_b")
    mean_delta: float = Field(0.0, description="Average score delta, right minus left")
    effect_size: float = Field(0.0, description="Effect size of the score delta")
    p_value: float = Field(1.0, description="Permutation-test p-value")
    is_significant: bool = Field(False, description="Whether the result is statistically significant")
    confidence: float = Field(0.0, description="Confidence assigned to the declared winner")
    winner: str = Field("tie", description="Winning label or tie")
    win_rates: dict[str, float] = Field(default_factory=dict, description="Per-label empirical win rates")
    win_rate_confidence_intervals: dict[str, tuple[float, float]] = Field(
        default_factory=dict,
        description="Confidence intervals for each empirical win rate",
    )
    score_delta_confidence_interval: tuple[float, float] = Field(
        default=(0.0, 0.0),
        description="Confidence interval for the mean score delta",
    )
    recommended_additional_cases: int = Field(0, description="Suggested extra cases when inconclusive")
    target_sample_size: int = Field(0, description="Estimated sample size for significance")
    summary_message: str = Field("", description="User-facing statistical summary")


class CompareRequest(BaseModel):
    """Request to run a pairwise comparison between two configs."""

    config_a_path: Optional[str] = Field(None, description="Path to the left config YAML")
    config_b_path: Optional[str] = Field(None, description="Path to the right config YAML")
    dataset_path: Optional[str] = Field(None, description="Optional dataset file used for the comparison")
    split: str = Field(
        "all",
        pattern="^(train|test|all)$",
        description="Dataset split used with dataset_path",
    )
    label_a: Optional[str] = Field(None, description="Display label for the left variant")
    label_b: Optional[str] = Field(None, description="Display label for the right variant")
    judge_strategy: str = Field(
        "metric_delta",
        pattern="^(metric_delta|llm_judge|human_preference)$",
        description="Winner selection strategy",
    )


class CompareListItem(BaseModel):
    """Compact pairwise comparison summary for list views."""

    comparison_id: str = Field(..., description="Comparison identifier")
    created_at: str = Field(..., description="Creation timestamp")
    dataset_name: str = Field("default", description="Dataset label")
    label_a: str = Field(..., description="Left variant label")
    label_b: str = Field(..., description="Right variant label")
    judge_strategy: str = Field("metric_delta", description="Winner selection strategy")
    winner: str = Field("tie", description="Winning label or tie")
    total_cases: int = Field(0, description="Total cases evaluated")
    left_wins: int = Field(0, description="Cases won by label_a")
    right_wins: int = Field(0, description="Cases won by label_b")
    ties: int = Field(0, description="Cases that tied")
    pending_human: int = Field(0, description="Cases awaiting human review")
    p_value: float = Field(1.0, description="Pairwise p-value")
    is_significant: bool = Field(False, description="Whether the comparison is statistically significant")


class CompareListResponse(BaseModel):
    """List response for stored pairwise comparisons."""

    comparisons: list[CompareListItem] = Field(default_factory=list, description="Recent comparisons")
    count: int = Field(0, description="Number of returned comparisons")


class CompareRunAcceptedResponse(BaseModel):
    """Response after creating a pairwise comparison."""

    comparison_id: str = Field(..., description="Comparison identifier")
    message: str = Field("Pairwise comparison completed", description="Human-readable status")
    summary: CompareListItem


# ---------------------------------------------------------------------------
# Import / export portability models
# ---------------------------------------------------------------------------

class AdkImportResponse(BaseModel):
    """Response returned after importing an ADK agent."""

    config_path: str
    snapshot_path: str
    agent_name: str
    surfaces_mapped: list[str] = Field(default_factory=list)
    tools_imported: int = 0
    portability_report: PortabilityReport | None = None


class AdkExportResponse(BaseModel):
    """Response returned after exporting an AgentLab config back to ADK."""

    output_path: str | None
    changes: list[dict[str, Any]] = Field(default_factory=list)
    files_modified: int = 0
    export_matrix: ExportCapabilityMatrix | None = None


class CxImportResponse(BaseModel):
    """Response returned after importing a CX agent."""

    config_path: str
    eval_path: str | None = None
    snapshot_path: str
    agent_name: str
    surfaces_mapped: list[str] = Field(default_factory=list)
    test_cases_imported: int = 0
    workspace_path: str | None = None
    portability_report: PortabilityReport | None = None


class CxExportResponse(BaseModel):
    """Response returned after diffing or exporting back to CX."""

    changes: list[dict[str, Any]] = Field(default_factory=list)
    pushed: bool = False
    resources_updated: int = 0
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    export_matrix: ExportCapabilityMatrix | None = None


class CompareResponse(BaseModel):
    """Full stored pairwise comparison payload."""

    comparison_id: str = Field(..., description="Comparison identifier")
    created_at: str = Field(..., description="Creation timestamp")
    dataset_name: str = Field("default", description="Dataset label")
    label_a: str = Field(..., description="Left variant label")
    label_b: str = Field(..., description="Right variant label")
    judge_strategy: str = Field("metric_delta", description="Winner selection strategy")
    summary: PairwiseSummaryResponse
    analysis: PairwiseAnalysisResponse
    case_results: list[PairwiseCaseResponse] = Field(default_factory=list, description="Per-case comparison rows")


# ---------------------------------------------------------------------------
# Structured results explorer models
# ---------------------------------------------------------------------------

class ResultAnnotationRequest(BaseModel):
    """Request to append an annotation to a result example."""

    author: str = Field(..., description="Reviewer name")
    type: str = Field(..., description="Annotation type")
    content: str = Field(..., description="Annotation body")
    score_override: Optional[float] = Field(None, description="Optional manual override score")


class ResultAnnotationResponse(BaseModel):
    """Stored annotation on one result example."""

    author: str = Field(..., description="Reviewer name")
    timestamp: str = Field(..., description="Creation timestamp")
    type: str = Field(..., description="Annotation type")
    content: str = Field(..., description="Annotation body")
    score_override: Optional[float] = Field(None, description="Optional manual override score")


class ResultMetricScore(BaseModel):
    """Per-example metric score plus reasoning."""

    value: float = Field(0.0, description="Metric value")
    reasoning: str = Field("", description="Short grader explanation")


class ResultMetricSummary(BaseModel):
    """Aggregate metric summary for one run."""

    mean: float = Field(0.0, description="Arithmetic mean")
    median: float = Field(0.0, description="Median")
    std: float = Field(0.0, description="Standard deviation")
    min: float = Field(0.0, description="Minimum value")
    max: float = Field(0.0, description="Maximum value")
    histogram: list[int] = Field(default_factory=list, description="Ten-bucket histogram counts")


class ResultSummary(BaseModel):
    """Aggregate summary block for a structured eval run."""

    total: int = Field(0, description="Total examples in the run")
    passed: int = Field(0, description="Passed examples")
    failed: int = Field(0, description="Failed examples")
    metrics: dict[str, ResultMetricSummary] = Field(default_factory=dict, description="Metric summaries")


class ResultExampleResponse(BaseModel):
    """One structured example result."""

    example_id: str = Field(..., description="Example identifier")
    input: dict[str, Any] = Field(default_factory=dict, description="Normalized input payload")
    expected: dict[str, Any] | None = Field(None, description="Expected target payload")
    actual: dict[str, Any] = Field(default_factory=dict, description="Actual agent output payload")
    scores: dict[str, ResultMetricScore] = Field(default_factory=dict, description="Per-metric scores")
    passed: bool = Field(False, description="Whether the example passed")
    failure_reasons: list[str] = Field(default_factory=list, description="Structured failure reasons")
    component_attributions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Component-aware failure credit assignments",
    )
    annotations: list[ResultAnnotationResponse] = Field(default_factory=list, description="Human notes")
    category: str = Field("unknown", description="Eval category")


class ResultExamplesResponse(BaseModel):
    """Paginated response for structured example results."""

    run_id: str = Field(..., description="Run identifier")
    page: int = Field(1, description="Current page number")
    page_size: int = Field(50, description="Current page size")
    total: int = Field(0, description="Total matching examples")
    examples: list[ResultExampleResponse] = Field(default_factory=list, description="Example result rows")


class ResultRunListItem(BaseModel):
    """Compact structured eval run summary for list views."""

    run_id: str = Field(..., description="Run identifier")
    timestamp: str = Field(..., description="Run timestamp")
    mode: str = Field(..., description="Eval mode")
    config_snapshot: dict[str, Any] = Field(default_factory=dict, description="Config snapshot used for the run")
    summary: ResultSummary


class ResultRunListResponse(BaseModel):
    """List response for structured eval runs."""

    runs: list[ResultRunListItem] = Field(default_factory=list, description="Recent structured runs")
    count: int = Field(0, description="Number of returned runs")


class ResultRunResponse(BaseModel):
    """Full structured eval run payload."""

    run_id: str = Field(..., description="Run identifier")
    timestamp: str = Field(..., description="Run timestamp")
    mode: str = Field(..., description="Eval mode")
    config_snapshot: dict[str, Any] = Field(default_factory=dict, description="Config snapshot used for the run")
    summary: ResultSummary
    examples: list[ResultExampleResponse] = Field(default_factory=list, description="Structured example rows")


class ResultDiffExampleResponse(BaseModel):
    """One changed example in a run-to-run diff."""

    example_id: str = Field(..., description="Example identifier")
    before_passed: bool = Field(False, description="Whether the baseline passed")
    after_passed: bool = Field(False, description="Whether the candidate passed")
    score_delta: float = Field(0.0, description="Candidate minus baseline composite delta")


class ResultDiffResponse(BaseModel):
    """Run-to-run diff for structured eval results."""

    baseline_run_id: str = Field(..., description="Baseline run identifier")
    candidate_run_id: str = Field(..., description="Candidate run identifier")
    new_failures: int = Field(0, description="Examples that regressed to failure")
    new_passes: int = Field(0, description="Examples that improved to pass")
    changed_examples: list[ResultDiffExampleResponse] = Field(default_factory=list, description="Changed examples")

class GeneratedCaseResponse(BaseModel):
    """A single generated eval case."""
    case_id: str
    category: str
    user_message: str
    expected_behavior: str
    expected_specialist: str = ""
    expected_keywords: list[str] = Field(default_factory=list)
    expected_tool: Optional[str] = None
    safety_probe: bool = False
    difficulty: str = "medium"
    rationale: str = ""
    split: str = "tuning"
    scoring_criteria: list[str] = Field(default_factory=list)

class GeneratedSuiteResponse(BaseModel):
    """Full generated eval suite response."""
    suite_id: str
    agent_name: str
    created_at: str
    status: str
    categories: dict[str, list[GeneratedCaseResponse]] = Field(default_factory=dict)
    cases: list[GeneratedCaseResponse] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)

class UpdateCaseRequest(BaseModel):
    """Request to update a generated eval case."""
    user_message: Optional[str] = None
    expected_behavior: Optional[str] = None
    expected_specialist: Optional[str] = None
    expected_keywords: Optional[list[str]] = None
    expected_tool: Optional[str] = None
    safety_probe: Optional[bool] = None
    difficulty: Optional[str] = None
    rationale: Optional[str] = None

class AcceptSuiteResponse(BaseModel):
    """Response after accepting a generated suite."""
    suite_id: str
    status: str
    total_cases: int
    message: str


# ---------------------------------------------------------------------------
# Generated eval review API models
# ---------------------------------------------------------------------------

class GenerateEvalSuiteRequest(BaseModel):
    """Request to synthesize a generated eval suite from config or transcripts."""

    agent_name: str = Field("agent", description="Human-readable agent name")
    agent_config: Optional[dict[str, Any]] = Field(
        None,
        description="Explicit agent configuration to analyze",
    )
    config_path: Optional[str] = Field(
        None,
        description="Optional path to an agent config file",
    )
    transcripts: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Optional transcript payloads for transcript-informed generation",
    )
    from_transcripts: bool = Field(
        False,
        description="When true, pull recent conversations from the conversation store",
    )
    conversation_limit: int = Field(
        25,
        ge=1,
        le=500,
        description="Maximum number of recent conversations to ingest when from_transcripts is enabled",
    )


class GenerateEvalSuiteResponse(BaseModel):
    """Background-task response for generated eval suite synthesis."""

    task_id: str = Field(..., description="Background task identifier")
    message: str = Field(..., description="Human-readable status message")


class GeneratedEvalSuiteSummary(BaseModel):
    """Compact summary for a generated eval suite list row."""

    suite_id: str
    agent_name: str
    source_kind: str = "config"
    status: str
    mock_mode: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    accepted_at: Optional[str] = None
    accepted_eval_path: Optional[str] = None
    transcript_count: int = 0
    category_counts: dict[str, int] = Field(default_factory=dict)
    case_count: int = 0


class GeneratedEvalListResponse(BaseModel):
    """List response for generated eval suites."""

    suites: list[GeneratedEvalSuiteSummary] = Field(default_factory=list)
    count: int = 0


class GeneratedEvalSuiteResponse(BaseModel):
    """Detailed generated eval suite response."""

    suite_id: str
    agent_name: str
    created_at: str
    status: str
    source_kind: str = "config"
    mock_mode: bool = True
    updated_at: Optional[str] = None
    accepted_at: Optional[str] = None
    accepted_eval_path: Optional[str] = None
    transcript_count: int = 0
    categories: dict[str, list[GeneratedCaseResponse]] = Field(default_factory=dict)
    cases: list[GeneratedCaseResponse] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class GeneratedEvalCasePatchRequest(BaseModel):
    """Inline edit request for one generated eval case."""

    category: Optional[str] = None
    user_message: Optional[str] = None
    expected_behavior: Optional[str] = None
    expected_specialist: Optional[str] = None
    expected_keywords: Optional[list[str]] = None
    expected_tool: Optional[str] = None
    safety_probe: Optional[bool] = None
    difficulty: Optional[str] = None
    rationale: Optional[str] = None
    split: Optional[str] = None
    scoring_criteria: Optional[list[str]] = None


class AcceptGeneratedEvalSuiteRequest(BaseModel):
    """Request to accept a generated eval suite into an eval corpus."""

    eval_cases_dir: Optional[str] = Field(
        None,
        description="Optional directory where accepted eval case files should be written",
    )


# ---------------------------------------------------------------------------
# Optimize models
# ---------------------------------------------------------------------------

class OptimizeRequest(BaseModel):
    """Request to start an optimization cycle."""
    window: int = Field(100, ge=1, le=10000, description="Number of recent conversations to analyze")
    force: bool = Field(False, description="Force optimization even if system appears healthy")
    require_human_approval: bool = Field(
        True,
        description="Require human review before a passing config change is deployed",
    )
    config_path: Optional[str] = Field(
        None,
        description="Optional config path for optimizing a selected agent instead of the active config",
    )
    eval_run_id: Optional[str] = Field(
        None,
        description="Optional eval run ID used to scope optimization context to a specific run",
    )
    mode: str = Field(
        "standard",
        pattern="^(standard|advanced|research)$",
        description="User-facing optimization mode",
    )
    objective: str = Field("", description="Optional optimization objective description")
    guardrails: list[str] = Field(default_factory=list, description="Optional user-defined guardrails")
    research_algorithm: str = Field("", description="Requested research algorithm (preview)")
    budget_cycles: int = Field(10, ge=1, le=1000, description="Requested cycle budget for longer runs")
    budget_dollars: float = Field(50.0, gt=0, description="Maximum dollar budget for the run")


class OptimizeCycleResult(BaseModel):
    """Result of a single optimization cycle."""
    accepted: bool = Field(..., description="Whether the proposed change was accepted")
    pending_review: bool = Field(
        False,
        description="Whether a passing proposal is waiting for human approval before deploy",
    )
    status_message: str = Field(..., description="Detailed status message from optimizer")
    change_description: Optional[str] = Field(None, description="Description of proposed change")
    config_diff: Optional[str] = Field(None, description="Config diff if a change was made")
    score_before: Optional[float] = Field(None, description="Composite score before change")
    score_after: Optional[float] = Field(None, description="Composite score after change")
    deploy_message: Optional[str] = Field(None, description="Deployment result message")
    strategy: str = Field("simple", description="Search strategy used for the cycle")
    search_strategy: str = Field("simple", description="Search strategy used for the cycle")
    selected_operator_family: Optional[str] = Field(
        None,
        description="HSO-selected operator family for adaptive/full modes",
    )
    pareto_front: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Pareto-front detail records (full mode detail view)",
    )
    pareto_recommendation_id: Optional[str] = Field(
        None,
        description="Knee-point recommendation candidate ID",
    )
    governance_notes: list[str] = Field(
        default_factory=list,
        description="Anti-Goodhart governance notes from this cycle",
    )
    global_dimensions: dict[str, Any] = Field(
        default_factory=dict,
        description="9-dimension global scores for the candidate evaluated in this cycle",
    )


class OptimizeResponse(BaseModel):
    """Response after starting an optimization run."""
    task_id: str = Field(..., description="Background task ID to poll for results")
    message: str = Field("Optimization started", description="Human-readable status")


class PendingReview(BaseModel):
    """Durable human-review record for a passing optimization proposal."""

    attempt_id: str = Field(..., description="Optimization attempt identifier")
    proposed_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Candidate config that passed evaluation gates",
    )
    current_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Config used as the evaluation baseline",
    )
    config_diff: str = Field("", description="Unified diff between current and proposed configs")
    score_before: float = Field(0.0, description="Baseline composite score")
    score_after: float = Field(0.0, description="Candidate composite score")
    change_description: str = Field("", description="Human-readable summary of the change")
    reasoning: str = Field("", description="Why the optimizer proposed this change")
    created_at: datetime = Field(..., description="When the review record was created")
    strategy: str = Field("simple", description="Optimization strategy used for the proposal")
    selected_operator_family: Optional[str] = Field(
        None,
        description="Selected operator family when adaptive or full search is used",
    )
    governance_notes: list[str] = Field(
        default_factory=list,
        description="Governance notes captured during evaluation",
    )
    deploy_scores: dict[str, Any] = Field(
        default_factory=dict,
        description="Score payload reused when the review is approved and deployed",
    )
    deploy_strategy: str = Field(
        "immediate",
        description="Deployment strategy to use when the review is approved",
    )
    patch_bundle: Optional[dict[str, Any]] = Field(
        None,
        description="Typed canonical component patch bundle for validation and review",
    )


class PendingReviewActionResponse(BaseModel):
    """Response after approving or rejecting a pending optimization review."""

    status: str = Field(..., description="Action status")
    attempt_id: str = Field(..., description="Optimization attempt identifier")
    message: str = Field(..., description="Human-readable action summary")
    deploy_message: Optional[str] = Field(
        None,
        description="Deployment result for approval actions",
    )


# ---------------------------------------------------------------------------
# Unified review surface
# ---------------------------------------------------------------------------


class UnifiedReviewItem(BaseModel):
    """Normalized review item aggregated from PendingReviewStore or ChangeCardStore.

    The unified review surface reads from both stores and presents a single
    list of actionable items so operators can see all pending decisions in
    one place.
    """

    id: str = Field(..., description="Original store identifier (attempt_id or card_id)")
    source: str = Field(
        ...,
        description="Origin store: 'optimizer' (PendingReviewStore) or 'change_card' (ChangeCardStore)",
    )
    status: str = Field(..., description="Review status: pending, approved/applied, rejected")
    title: str = Field("", description="Human-readable title of the proposed change")
    description: str = Field("", description="Why this change was proposed")
    score_before: float = Field(0.0, description="Baseline composite score (0-1)")
    score_after: float = Field(0.0, description="Candidate composite score (0-1)")
    score_delta: float = Field(0.0, description="score_after minus score_before")
    risk_class: str = Field("medium", description="Risk level: low, medium, high")
    diff_summary: str = Field("", description="Config diff or rendered hunk summary")
    created_at: datetime = Field(..., description="When the review record was created")
    strategy: Optional[str] = Field(None, description="Optimization strategy used")
    operator_family: Optional[str] = Field(None, description="Operator family if applicable")
    has_detailed_audit: bool = Field(
        False,
        description="Whether the source store has a full audit trail (change cards do)",
    )
    patch_bundle: Optional[dict[str, Any]] = Field(
        None,
        description="Typed canonical component patch bundle when the source provides one",
    )


class UnifiedReviewStats(BaseModel):
    """Aggregate counts across both review stores."""

    total_pending: int = Field(0, description="Total pending items across all sources")
    optimizer_pending: int = Field(0, description="Pending items from PendingReviewStore")
    change_card_pending: int = Field(0, description="Pending items from ChangeCardStore")
    total_approved: int = Field(0, description="Total approved/applied items")
    total_rejected: int = Field(0, description="Total rejected items")


class UnifiedReviewActionRequest(BaseModel):
    """Request body for approving or rejecting a unified review item."""

    source: Literal["optimizer", "change_card"] = Field(
        ...,
        description="Origin store: 'optimizer' or 'change_card'",
    )
    reason: str = Field("", description="Rejection reason (used only for rejections)")


class UnifiedReviewActionResponse(BaseModel):
    """Response after approving or rejecting a unified review item."""

    status: str = Field(..., description="Action result: approved, rejected, applied")
    id: str = Field(..., description="Item identifier")
    source: str = Field(..., description="Origin store")
    message: str = Field(..., description="Human-readable action summary")
    deploy_message: Optional[str] = Field(None, description="Deployment result for approvals")


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

class ConfigVersionInfo(BaseModel):
    """Summary info for a single config version."""
    version: int
    config_hash: str
    filename: str
    timestamp: float
    scores: dict[str, Any]
    status: str


class ConfigListResponse(BaseModel):
    """List of all config versions."""
    versions: list[ConfigVersionInfo] = Field(default_factory=list)
    active_version: Optional[int] = None
    canary_version: Optional[int] = None


class ConfigShowResponse(BaseModel):
    """Raw YAML content for a config version."""
    version: int
    yaml_content: str = Field(..., description="Config as YAML string")
    config: dict[str, Any] = Field(..., description="Config as parsed dictionary")


class ConfigDiffResponse(BaseModel):
    """Diff between two config versions."""
    version_a: int
    version_b: int
    diff: str = Field(..., description="Human-readable diff")


# ---------------------------------------------------------------------------
# Health models
# ---------------------------------------------------------------------------

class HealthMetricsData(BaseModel):
    """Core health metrics."""
    success_rate: float = Field(0.0, description="Fraction of successful conversations")
    avg_latency_ms: float = Field(0.0, description="Average response latency in ms")
    error_rate: float = Field(0.0, description="Fraction of error/fail/abandon outcomes")
    safety_violation_rate: float = Field(0.0, description="Fraction with safety flags")
    avg_cost: float = Field(0.0, description="Average cost per conversation (approx)")
    total_conversations: int = Field(0, description="Number of conversations in window")


class WorkspaceStateResponse(BaseModel):
    """Workspace validity resolved at API startup."""

    valid: bool = Field(False, description="Whether the server has a valid AgentLab workspace")
    current_path: str = Field("", description="Process path used for workspace discovery")
    workspace_root: Optional[str] = Field(None, description="Resolved workspace root when available")
    workspace_label: Optional[str] = Field(None, description="Human-readable workspace label")
    active_config_path: Optional[str] = Field(None, description="Resolved active config path")
    active_config_version: Optional[int] = Field(None, description="Resolved active config version")
    source: str = Field("cwd", description="Workspace source: cwd or env")
    message: str = Field("", description="Human-readable workspace state")
    recovery_commands: list[str] = Field(
        default_factory=list,
        description="Suggested commands for recovering from invalid workspace state",
    )


class HealthResponse(BaseModel):
    """Full health report with metrics, anomalies, and failure buckets."""
    metrics: HealthMetricsData
    anomalies: list[str] = Field(default_factory=list, description="Detected anomalies")
    failure_buckets: dict[str, int] = Field(default_factory=dict, description="Failure classification counts")
    needs_optimization: bool = Field(False, description="Whether the observer recommends optimization")
    reason: str = Field("", description="Reason if optimization is recommended")
    mock_mode: bool = Field(False, description="Whether the active server path is currently using simulated components")
    mock_reasons: list[str] = Field(default_factory=list, description="Human-readable reasons mock mode is active")
    real_provider_configured: bool = Field(
        False,
        description="Whether at least one usable non-mock provider credential is configured",
    )
    workspace_valid: bool = Field(False, description="Whether the server has a valid AgentLab workspace")
    workspace: WorkspaceStateResponse = Field(
        default_factory=WorkspaceStateResponse,
        description="Detailed workspace startup state and recovery guidance",
    )


# ---------------------------------------------------------------------------
# Conversation models
# ---------------------------------------------------------------------------

class ConversationRecord(BaseModel):
    """API response model for a single conversation record."""
    conversation_id: str
    session_id: str
    user_message: str
    agent_response: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = 0.0
    token_count: int = 0
    outcome: str = "unknown"
    safety_flags: list[str] = Field(default_factory=list)
    error_message: str = ""
    specialist_used: str = ""
    config_version: str = ""
    timestamp: float = 0.0


class ConversationListResponse(BaseModel):
    """Paginated list of conversations."""
    conversations: list[ConversationRecord]
    total: int = Field(..., description="Total matching records")
    limit: int = Field(..., description="Requested limit")
    offset: int = Field(0, description="Offset used")


class ConversationStatsResponse(BaseModel):
    """Aggregate conversation statistics."""
    total: int = 0
    by_outcome: dict[str, int] = Field(default_factory=dict)
    avg_latency_ms: float = 0.0
    avg_token_count: float = 0.0


# ---------------------------------------------------------------------------
# Deploy models
# ---------------------------------------------------------------------------

class DeployStrategy(str, Enum):
    canary = "canary"
    immediate = "immediate"


class DeployRequest(BaseModel):
    """Request to deploy a config version."""
    config: Optional[dict[str, Any]] = Field(None, description="Config dict to deploy; if omitted, deploys latest canary")
    version: Optional[int] = Field(None, description="Specific version number to promote")
    strategy: DeployStrategy = Field(DeployStrategy.canary, description="Deployment strategy")
    scores: dict[str, Any] = Field(default_factory=dict, description="Score snapshot for this deploy")


class DeployResponse(BaseModel):
    """Response after a deploy action."""
    message: str
    version: Optional[int] = None
    strategy: str = "canary"


class DeployStatusResponse(BaseModel):
    """Current deployment status."""
    active_version: Optional[int] = None
    canary_version: Optional[int] = None
    total_versions: int = 0
    canary_status: Optional[dict[str, Any]] = Field(None, description="Canary health info if active")
    history: list[dict[str, Any]] = Field(default_factory=list, description="Recent version history")


# ---------------------------------------------------------------------------
# Loop models
# ---------------------------------------------------------------------------

class LoopStartRequest(BaseModel):
    """Request to start the continuous optimization loop."""
    cycles: int = Field(5, ge=1, le=1000, description="Number of optimization cycles to run")
    delay: float = Field(1.0, ge=0.0, le=300.0, description="Seconds between cycles")
    window: int = Field(100, ge=1, le=10000, description="Observation window size")
    schedule_mode: Optional[str] = Field(
        None,
        pattern="^(continuous|interval|cron)$",
        description="Loop scheduler mode",
    )
    interval_minutes: Optional[float] = Field(
        None,
        ge=0.0,
        le=1440.0,
        description="Interval length (minutes) for interval scheduling",
    )
    cron_expression: Optional[str] = Field(
        None,
        description="Cron expression (UTC) used when schedule_mode=cron",
    )
    resume_checkpoint: bool = Field(
        True,
        description="Resume from persisted checkpoint when available",
    )


class LoopCycleInfo(BaseModel):
    """Info about a single loop cycle."""
    cycle: int
    health_success_rate: float
    health_error_rate: float
    optimization_run: bool
    optimization_result: Optional[str] = None
    deploy_result: Optional[str] = None
    canary_result: Optional[str] = None


class LoopStatusResponse(BaseModel):
    """Current loop status and cycle history."""
    running: bool = Field(False, description="Whether a loop is currently running")
    task_id: Optional[str] = Field(None, description="Background task ID if running")
    total_cycles: int = Field(0, description="Total cycles configured")
    completed_cycles: int = Field(0, description="Cycles completed so far")
    stalled: bool = Field(False, description="Whether watchdog reports loop stall")
    last_heartbeat: Optional[float] = Field(None, description="Last loop heartbeat unix epoch")
    dead_letter_count: int = Field(0, description="Queued dead-letter items")
    cycle_history: list[LoopCycleInfo] = Field(default_factory=list, description="Recent cycle results")


class SystemHealthResponse(BaseModel):
    """Operational health for long-running backend components."""

    status: str = Field(..., description="ok/degraded")
    loop_running: bool = Field(False, description="Whether optimization loop is running")
    loop_stalled: bool = Field(False, description="Whether loop watchdog is stalled")
    last_heartbeat: Optional[float] = Field(None, description="Last loop heartbeat timestamp")
    dead_letter_count: int = Field(0, description="Dead-letter queue size")
    tasks_running: int = Field(0, description="Count of running background tasks")
    uptime_seconds: float = Field(0.0, description="Process uptime in seconds")
    workspace_valid: bool = Field(False, description="Whether the server has a valid AgentLab workspace")
    workspace: WorkspaceStateResponse = Field(
        default_factory=WorkspaceStateResponse,
        description="Detailed workspace startup state and recovery guidance",
    )


# ---------------------------------------------------------------------------
# Judge subsystem models
# ---------------------------------------------------------------------------

class JudgeVerdictResponse(BaseModel):
    """Structured output from any judge in the grader stack."""
    score: float = Field(..., ge=0.0, le=1.0, description="Judge score 0-1")
    passed: bool = Field(..., description="Whether the case passed this judge")
    judge_id: str = Field(..., description="Identifier of the judge that produced this verdict")
    evidence_spans: list[str] = Field(default_factory=list, description="Quoted evidence from the conversation")
    failure_reasons: list[str] = Field(default_factory=list, description="Reasons for failure if not passed")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Judge confidence 0-1")


class JudgeCalibrationResponse(BaseModel):
    """Judge calibration health metrics."""
    agreement_rate: float = Field(0.0, description="Inter-judge agreement rate")
    drift: float = Field(0.0, description="Score drift over time")
    position_bias: float = Field(0.0, description="Positional bias measurement")
    verbosity_bias: float = Field(0.0, description="Verbosity bias measurement")
    disagreement_rate: float = Field(0.0, description="Rate of judge disagreements")


# ---------------------------------------------------------------------------
# 4-Layer Dimension models
# ---------------------------------------------------------------------------

class LayeredDimensionResponse(BaseModel):
    """All 18 metrics grouped by the 4-layer hierarchy."""
    # Hard Gates
    safety_compliance: float = Field(0.0, description="G3 safety compliance")
    state_integrity: float = Field(0.0, description="State integrity gate")
    authorization_privacy: float = Field(0.0, description="Auth/privacy gate")
    p0_regressions: float = Field(0.0, description="P0 regression count (lower is better)")
    # Outcomes
    task_success_rate: float = Field(0.0, description="G1 task success")
    response_quality: float = Field(0.0, description="G2 response quality")
    user_satisfaction_proxy: float = Field(0.0, description="G9 user satisfaction")
    groundedness: float = Field(0.0, description="Groundedness score")
    # SLOs
    latency_p50: float = Field(0.0, description="G4a latency p50")
    latency_p95: float = Field(0.0, description="G4b latency p95")
    latency_p99: float = Field(0.0, description="G4c latency p99")
    token_cost: float = Field(0.0, description="G5 token cost")
    escalation_rate: float = Field(0.0, description="Escalation rate")
    # Diagnostics
    tool_correctness: float = Field(0.0, description="G6 tool correctness")
    routing_accuracy: float = Field(0.0, description="G7 routing accuracy")
    handoff_fidelity: float = Field(0.0, description="G8 handoff fidelity")
    recovery_rate: float = Field(0.0, description="Recovery rate")
    clarification_quality: float = Field(0.0, description="Clarification quality")
    judge_disagreement_rate: float = Field(0.0, description="Judge disagreement rate")


# ---------------------------------------------------------------------------
# Archive models
# ---------------------------------------------------------------------------

class ArchiveEntryResponse(BaseModel):
    """An entry in the elite Pareto archive with a named role."""
    entry_id: str = Field(..., description="Unique archive entry ID")
    role: str = Field(..., description="Archive role (quality_leader, cost_leader, etc.)")
    candidate_id: str = Field("", description="Candidate variant ID")
    experiment_id: str = Field("", description="Source experiment ID")
    objective_vector: list[float] = Field(default_factory=list, description="Multi-objective vector")
    config_hash: str = Field("", description="Config content hash")
    scores: dict[str, float] = Field(default_factory=dict, description="Named scores")
    created_at: str = Field("", description="ISO timestamp of creation")


# ---------------------------------------------------------------------------
# Training escalation models
# ---------------------------------------------------------------------------

class TrainingRecommendationResponse(BaseModel):
    """Recommendation to escalate a failure family to training."""
    failure_family: str = Field(..., description="Failure family identifier")
    recommended_method: str = Field(..., description="Training method: SFT, DPO, or RFT")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence in recommendation")
    estimated_improvement: float = Field(0.0, description="Expected improvement fraction")
    dataset_size: int = Field(0, description="Recommended dataset size")
    reasoning: str = Field("", description="Explanation for the recommendation")


# ---------------------------------------------------------------------------
# Release manager models
# ---------------------------------------------------------------------------

class PromotionRecordResponse(BaseModel):
    """Tracks a candidate through the promotion pipeline."""
    record_id: str = Field(..., description="Unique promotion record ID")
    candidate_version: str = Field(..., description="Candidate version being promoted")
    current_stage: str = Field("gate_check", description="Current promotion stage")
    stages_completed: list[str] = Field(default_factory=list, description="Stages already completed")
    gate_results: dict[str, bool] = Field(default_factory=dict, description="Gate pass/fail results")
    holdout_score: Optional[float] = Field(None, description="Holdout eval score if completed")
    slice_results: dict[str, float] = Field(default_factory=dict, description="Per-slice scores")
    canary_verdict: Optional[str] = Field(None, description="Canary stage verdict")
    status: str = Field("in_progress", description="Overall promotion status")
    started_at: str = Field("", description="ISO timestamp of start")
    completed_at: Optional[str] = Field(None, description="ISO timestamp of completion")


# ---------------------------------------------------------------------------
# Assistant models
# ---------------------------------------------------------------------------

class AssistantMessageRequest(BaseModel):
    """Request to send a message to the assistant."""
    message: str = Field(..., description="User message text", min_length=1)
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")
    context: dict[str, Any] = Field(default_factory=dict, description="Additional context for the message")


class AssistantHistoryItem(BaseModel):
    """Single turn in conversation history."""
    turn_id: str
    user_message: str
    assistant_response: list[dict[str, Any]]  # List of events (thinking, card, text, etc.)
    timestamp: float
    session_id: str


class AssistantHistoryResponse(BaseModel):
    """Conversation history response."""
    session_id: str
    turns: list[AssistantHistoryItem]
    total: int


class AssistantSuggestionsResponse(BaseModel):
    """Contextual suggestions response."""
    session_id: str
    suggestions: list[str]
    quick_actions: list[dict[str, Any]]
    mock_mode: bool = False
    warning: Optional[str] = None


class AssistantActionRequest(BaseModel):
    """Request to execute a card action."""
    session_id: str = Field(..., description="Session ID for the conversation")
    action_data: dict[str, Any] = Field(default_factory=dict, description="Action-specific data")


class AssistantActionResponse(BaseModel):
    """Response from executing an action."""
    success: bool
    action_id: str
    result: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    mock_mode: bool = False
    warning: Optional[str] = None


# ---------------------------------------------------------------------------
# Skills models (core.skills unified API)
# ---------------------------------------------------------------------------

class SkillCreateRequest(BaseModel):
    """Request to create a new skill."""
    skill: dict[str, Any] = Field(..., description="Skill definition as dict")


class SkillUpdateRequest(BaseModel):
    """Request to update an existing skill."""
    skill: dict[str, Any] = Field(..., description="Updated skill definition as dict")


class SkillComposeRequest(BaseModel):
    """Request to compose a skill set."""
    skill_ids: list[str] = Field(..., description="List of skill IDs to compose")
    name: str = Field(..., description="Name for the composed skill set")
    description: str = Field("", description="Description of the skill set")
    resolve_conflicts: bool = Field(True, description="Attempt to resolve conflicts automatically")


class SkillInstallRequest(BaseModel):
    """Request to install a skill from marketplace."""
    skill_id: Optional[str] = Field(None, description="Marketplace skill ID or URL to install")
    file_path: Optional[str] = Field(None, description="File path to skill pack YAML (backward compat)")

    @property
    def source(self) -> str | None:
        """Get the source (skill_id or file_path)."""
        return self.file_path or self.skill_id


class SkillSearchRequest(BaseModel):
    """Request to search skills."""
    query: str = Field(..., description="Search query text")
    kind: Optional[str] = Field(None, description="Filter by kind: build or runtime")
    domain: Optional[str] = Field(None, description="Filter by domain")
    tags: Optional[str] = Field(None, description="Comma-separated tags filter")


# ---------------------------------------------------------------------------
# Studio Models
# ---------------------------------------------------------------------------

# --- Spec ---

class StudioSpecVersionItem(BaseModel):
    """Compact record for a single spec version in list views."""
    version_id: str = Field(..., description="Version identifier (e.g. 'v003')")
    version_num: int = Field(..., description="Numeric version")
    created_at: float = Field(..., description="Unix timestamp")
    status: str = Field(..., description="active | canary | retired | rolled_back")
    config_hash: str = Field("", description="Short content hash")
    composite_score: float = Field(0.0, description="Composite eval score at deployment")
    label: str = Field("", description="Optional human label")


class StudioSpecVersionListResponse(BaseModel):
    """List of all spec versions."""
    versions: list[StudioSpecVersionItem] = Field(default_factory=list)
    active_version_id: Optional[str] = Field(None)
    total: int = Field(0)


class StudioSpecContentResponse(BaseModel):
    """Full content of a spec version."""
    version_id: str
    version_num: int
    status: str
    created_at: float
    config_hash: str
    composite_score: float
    markdown: str = Field("", description="System prompt / spec rendered as Markdown")
    raw_config: dict[str, Any] = Field(default_factory=dict, description="Full raw config dict")


class StudioSpecParseRequest(BaseModel):
    """Markdown spec text to parse/validate."""
    content: str = Field(..., description="Markdown content to parse", min_length=1)


class StudioSpecParseResponse(BaseModel):
    """Result of parsing/validating a Markdown spec."""
    valid: bool
    word_count: int = 0
    section_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    extracted_sections: dict[str, str] = Field(default_factory=dict)


class StudioSpecDiffResponse(BaseModel):
    """Diff metadata between two spec versions."""
    from_version_id: str
    to_version_id: str
    added_lines: int = 0
    removed_lines: int = 0
    changed_sections: list[str] = Field(default_factory=list)
    diff_text: str = ""


# --- Observe ---

class StudioObsSource(BaseModel):
    """Status of a single observability data source."""
    source_id: str
    name: str
    kind: str = Field("", description="production | staging | sandbox | synthetic")
    status: str = Field("ok", description="ok | degraded | unreachable | no_data")
    last_seen_at: Optional[float] = None
    conversation_count: int = 0
    error_rate: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0


class StudioObsMetricsSummary(BaseModel):
    """Aggregated metrics snapshot for the Observe page."""
    snapshot_at: float = Field(default_factory=lambda: 0.0)
    window_hours: int = 24
    total_conversations: int = 0
    success_rate: float = 0.0
    safety_pass_rate: float = 0.0
    avg_quality_score: float = 0.0
    avg_latency_ms: float = 0.0
    avg_tokens_per_turn: float = 0.0
    error_rate: float = 0.0
    top_failure_categories: list[dict[str, Any]] = Field(default_factory=list)


class StudioObsIssueCluster(BaseModel):
    """A cluster of similar issues surfaced from traces."""
    cluster_id: str
    category: str
    summary: str
    count: int = 0
    severity: str = "medium"
    first_seen_at: Optional[float] = None
    last_seen_at: Optional[float] = None
    example_trace_ids: list[str] = Field(default_factory=list)


class StudioObsIssueListResponse(BaseModel):
    clusters: list[StudioObsIssueCluster] = Field(default_factory=list)
    total: int = 0
    window_hours: int = 24


class StudioObsTraceItem(BaseModel):
    """Compact trace record for the trace list."""
    trace_id: str
    session_id: str = ""
    started_at: Optional[float] = None
    duration_ms: float = 0.0
    outcome: str = "unknown"
    quality_score: float = 0.0
    error: Optional[str] = None
    agent_path: str = ""


class StudioObsTraceListResponse(BaseModel):
    traces: list[StudioObsTraceItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


# --- Optimize ---

class StudioSessionItem(BaseModel):
    """Compact record for an optimization session in list views."""
    session_id: str
    created_at: float
    status: str = Field("active", description="active | completed | failed | promoted")
    attempt_count: int = 0
    accepted_count: int = 0
    best_composite: float = 0.0
    baseline_composite: float = 0.0
    delta: float = 0.0
    label: str = ""


class StudioSessionListResponse(BaseModel):
    sessions: list[StudioSessionItem] = Field(default_factory=list)
    total: int = 0


class StudioSessionCreateRequest(BaseModel):
    """Request body to start a new optimization session."""
    label: str = Field("", description="Human-readable session label")
    baseline_version_id: Optional[str] = Field(None, description="Config version to use as baseline")
    eval_suite_id: Optional[str] = Field(None, description="Eval suite to run against")


class StudioSessionCreateResponse(BaseModel):
    session_id: str
    status: str = "active"
    message: str = ""


class StudioCandidate(BaseModel):
    """A single optimization candidate within a session."""
    candidate_id: str
    attempt_id: str = ""
    status: str = Field("", description="accepted | rejected_* | pending")
    change_description: str = ""
    config_section: str = ""
    score_before: float = 0.0
    score_after: float = 0.0
    delta: float = 0.0
    p_value: float = 1.0
    created_at: float = 0.0


class StudioCandidateListResponse(BaseModel):
    session_id: str
    candidates: list[StudioCandidate] = Field(default_factory=list)
    total: int = 0


class StudioEvalSuiteSummary(BaseModel):
    """Eval suite summary for a session."""
    session_id: str
    eval_run_id: str = ""
    status: str = "no_data"
    total_cases: int = 0
    passed_cases: int = 0
    quality: float = 0.0
    safety: float = 0.0
    latency: float = 0.0
    cost: float = 0.0
    composite: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class StudioBacktestMetrics(BaseModel):
    """Backtest performance comparison for a session."""
    session_id: str
    baseline_composite: float = 0.0
    candidate_composite: float = 0.0
    delta: float = 0.0
    is_significant: bool = False
    p_value: float = 1.0
    effect_size: float = 0.0
    cases_run: int = 0
    safety_regressions: int = 0
    latency_change_pct: float = 0.0


class StudioPromoteRequest(BaseModel):
    candidate_id: str = Field(..., description="Candidate ID to promote")
    strategy: str = Field("canary", description="canary | full | rollback")
    note: str = Field("", description="Optional promotion note")


class StudioPromoteResponse(BaseModel):
    session_id: str
    candidate_id: str
    strategy: str
    status: str
    message: str = ""
    new_version_id: Optional[str] = None
