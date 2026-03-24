"""Pydantic request/response models for all API endpoints."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared / common
# ---------------------------------------------------------------------------

class TaskStatusEnum(str, Enum):
    """Possible states for a background task."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


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


# ---------------------------------------------------------------------------
# Eval models
# ---------------------------------------------------------------------------

class EvalRunRequest(BaseModel):
    """Request to start an eval run."""
    config_path: Optional[str] = Field(None, description="Path to config YAML to evaluate; uses default if omitted")
    category: Optional[str] = Field(None, description="Run only a specific category of test cases")
    dataset_path: Optional[str] = Field(None, description="Dataset file (.jsonl/.csv) for eval runs")
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
    quality: float = Field(..., description="Quality score 0-1")
    safety: float = Field(..., description="Safety score 0-1")
    latency: float = Field(..., description="Latency score 0-1 (higher is better)")
    cost: float = Field(..., description="Cost score 0-1 (higher is better)")
    composite: float = Field(..., description="Weighted composite score")
    safety_failures: int = Field(0, description="Number of safety failures")
    total_cases: int = Field(0, description="Total test cases run")
    passed_cases: int = Field(0, description="Test cases that passed")
    cases: list[EvalCaseResult] = Field(default_factory=list, description="Per-case results")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")


# ---------------------------------------------------------------------------
# Optimize models
# ---------------------------------------------------------------------------

class OptimizeRequest(BaseModel):
    """Request to start an optimization cycle."""
    window: int = Field(100, ge=1, le=10000, description="Number of recent conversations to analyze")
    force: bool = Field(False, description="Force optimization even if system appears healthy")


class OptimizeCycleResult(BaseModel):
    """Result of a single optimization cycle."""
    accepted: bool = Field(..., description="Whether the proposed change was accepted")
    status_message: str = Field(..., description="Detailed status message from optimizer")
    change_description: Optional[str] = Field(None, description="Description of proposed change")
    config_diff: Optional[str] = Field(None, description="Config diff if a change was made")
    score_before: Optional[float] = Field(None, description="Composite score before change")
    score_after: Optional[float] = Field(None, description="Composite score after change")
    deploy_message: Optional[str] = Field(None, description="Deployment result message")
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


class HealthResponse(BaseModel):
    """Full health report with metrics, anomalies, and failure buckets."""
    metrics: HealthMetricsData
    anomalies: list[str] = Field(default_factory=list, description="Detected anomalies")
    failure_buckets: dict[str, int] = Field(default_factory=dict, description="Failure classification counts")
    needs_optimization: bool = Field(False, description="Whether the observer recommends optimization")
    reason: str = Field("", description="Reason if optimization is recommended")


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
