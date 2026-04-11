export type TaskState = 'pending' | 'running' | 'completed' | 'failed';

export interface TaskStatus {
  task_id: string;
  task_type: string;
  status: TaskState;
  progress: number;
  result: unknown;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface HealthMetrics {
  success_rate: number;
  avg_latency_ms: number;
  error_rate: number;
  safety_violation_rate: number;
  avg_cost: number;
  total_conversations: number;
}

export interface HealthReport {
  metrics: HealthMetrics;
  anomalies: string[];
  failure_buckets: Record<string, number>;
  needs_optimization: boolean;
  reason: string;
  mock_mode?: boolean;
  mock_reasons?: string[];
  real_provider_configured?: boolean;
}

// 9-Dimension Scores (v4 enhanced scoring)
export interface DimensionScores {
  task_success_rate: number;       // G1
  response_quality: number;        // G2
  safety_compliance: number;       // G3
  latency_p50: number;            // G4a
  latency_p95: number;            // G4b
  latency_p99: number;            // G4c
  token_cost: number;             // G5
  tool_correctness: number;       // G6
  routing_accuracy: number;       // G7
  handoff_fidelity: number;       // G8
  user_satisfaction_proxy: number; // G9
}

// Per-Agent Scores
export interface PerAgentScores {
  agent_path: string;
  unit_success: number;
  tool_precision: number;
  tool_recall: number;
  policy_adherence: number;
  avg_latency_ms: number;
  escalation_appropriateness: number;
}

// Pareto Archive
export interface ParetoCandidate {
  candidate_id: string;
  objective_vector: number[];
  constraints_passed: boolean;
  constraint_violations: string[];
  config_hash: string;
  experiment_id: string | null;
  created_at: number;
  dominated: boolean;
  is_recommended: boolean;
}

export interface ParetoFrontier {
  candidates: ParetoCandidate[];
  recommended: ParetoCandidate | null;
  frontier_size: number;
  infeasible_count: number;
}

// Bandit Stats
export interface BanditArmStats {
  arm_id: string;
  operator_name: string;
  failure_family: string;
  attempts: number;
  successes: number;
  mean_reward: number;
  success_rate: number;
}

// Curriculum Status
export interface CurriculumStatus {
  current_tier: 'easy' | 'medium' | 'hard';
  experiments_per_tier: Record<string, number>;
  should_advance: boolean;
}

export interface CurriculumPromptItem {
  prompt_id: string;
  cluster_id: string;
  failure_family: string;
  prompt_text: string;
  difficulty_tier: 'easy' | 'medium' | 'hard' | 'adversarial';
  difficulty_score: number;
  is_adversarial: boolean;
  evidence: string[];
  created_at: number;
}

export interface CurriculumBatchSummary {
  batch_id: string;
  created_at: number;
  prompt_count: number;
  applied_count: number;
  difficulty_distribution: Record<string, number>;
}

export interface CurriculumDifficultyPoint {
  batch_id: string;
  created_at: number;
  average_difficulty: number;
}

// Holdout Status
export interface HoldoutStatus {
  experiment_count: number;
  current_split_id: string | null;
  rotation_epoch: number;
  should_rotate: boolean;
  is_drifting: boolean;
  drift_amount: number;
}

// Search Strategy Config
export interface OptimizerConfig {
  search_strategy: 'simple' | 'adaptive' | 'full';
  bandit_policy: 'ucb1' | 'thompson';
  holdout_rotation: boolean;
  curriculum_enabled: boolean;
}

export interface CompositeScore {
  overall: number;
  quality: number;
  safety: number;
  latency: number;
  cost: number;
  dimensions?: DimensionScores;        // v4: full 9-dimension breakdown
  per_agent_scores?: PerAgentScores[]; // v4: per-agent metrics
}

export interface EvalCase {
  case_id: string;
  category: string;
  passed: boolean;
  quality_score: number;
  safety_passed: boolean;
  latency_ms: number;
  token_count: number;
  details: string;
}

export type EvalMode = 'mock' | 'live' | 'mixed';

export interface EvalResult {
  run_id: string;
  status: TaskState;
  progress: number;
  timestamp: string;
  mode?: EvalMode;
  composite_score: CompositeScore;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  safety_failures: number;
  cases: EvalCase[];
}

export interface EvalRun {
  run_id: string;
  timestamp: string;
  status: TaskState;
  progress: number;
  mode?: EvalMode;
  composite_score: number;
  total_cases: number;
  passed_cases: number;
}

export interface PairwiseVariantResult {
  response: string;
  specialist_used?: string;
  passed?: boolean;
  quality_score: number;
  safety_passed: boolean;
  latency_ms: number;
  token_count: number;
  composite_score: number;
  details: string;
  raw_output?: Record<string, unknown>;
  custom_scores?: Record<string, number>;
}

export interface PairwiseHumanPreferenceTask {
  task_id: string;
  case_id: string;
  label_a: string;
  label_b: string;
  prompt: string;
  status: string;
}

export interface PairwiseCaseResult {
  case_id: string;
  category: string;
  input_message: string;
  left: PairwiseVariantResult;
  right: PairwiseVariantResult;
  winner: string;
  winner_reason: string;
  score_delta: number;
  human_preference_task?: PairwiseHumanPreferenceTask | null;
}

export interface PairwiseSummary {
  total_cases: number;
  left_wins: number;
  right_wins: number;
  ties: number;
  pending_human: number;
}

export interface PairwiseAnalysis {
  label_a: string;
  label_b: string;
  total_cases: number;
  mean_score_a: number;
  mean_score_b: number;
  mean_delta: number;
  effect_size: number;
  p_value: number;
  is_significant: boolean;
  confidence: number;
  winner: string;
  win_rates: Record<string, number>;
  win_rate_confidence_intervals: Record<string, [number, number]>;
  score_delta_confidence_interval: [number, number];
  recommended_additional_cases: number;
  target_sample_size: number;
  summary_message: string;
}

export interface PairwiseComparison {
  comparison_id: string;
  created_at: string;
  dataset_name: string;
  label_a: string;
  label_b: string;
  judge_strategy: string;
  summary: PairwiseSummary;
  analysis: PairwiseAnalysis;
  case_results: PairwiseCaseResult[];
}

export interface PairwiseComparisonListItem {
  comparison_id: string;
  created_at: string;
  dataset_name: string;
  label_a: string;
  label_b: string;
  judge_strategy: string;
  winner: string;
  total_cases: number;
  left_wins: number;
  right_wins: number;
  ties: number;
  pending_human: number;
  p_value: number;
  is_significant: boolean;
}

export interface PairwiseComparisonList {
  comparisons: PairwiseComparisonListItem[];
  count: number;
}

export interface ResultAnnotation {
  author: string;
  timestamp: string;
  type: string;
  content: string;
  score_override: number | null;
}

export interface EvalResultsMetricScore {
  value: number;
  reasoning: string;
}

export interface EvalResultsMetricSummary {
  mean: number;
  median: number;
  std: number;
  min: number;
  max: number;
  histogram: number[];
}

export interface EvalResultExample {
  example_id: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown> | null;
  actual: Record<string, unknown>;
  scores: Record<string, EvalResultsMetricScore>;
  passed: boolean;
  failure_reasons: string[];
  annotations: ResultAnnotation[];
  category: string;
}

export interface EvalResultsSummary {
  total: number;
  passed: number;
  failed: number;
  metrics: Record<string, EvalResultsMetricSummary>;
}

export interface EvalResultsRun {
  run_id: string;
  timestamp: string;
  mode: string;
  config_snapshot: Record<string, unknown>;
  summary: EvalResultsSummary;
  examples: EvalResultExample[];
}

export interface EvalResultsRunListItem {
  run_id: string;
  timestamp: string;
  mode: string;
  config_snapshot: Record<string, unknown>;
  summary: EvalResultsSummary;
}

export interface EvalResultsRunList {
  runs: EvalResultsRunListItem[];
  count: number;
}

export interface EvalResultsDiffChangedExample {
  example_id: string;
  before_passed: boolean;
  after_passed: boolean;
  score_delta: number;
}

export interface EvalResultsDiff {
  baseline_run_id: string;
  candidate_run_id: string;
  new_failures: number;
  new_passes: number;
  changed_examples: EvalResultsDiffChangedExample[];
}

// Auto-generated eval types
export interface GeneratedEvalCase {
  case_id: string;
  category: string;
  user_message: string;
  expected_behavior: string;
  expected_specialist: string;
  expected_keywords: string[];
  expected_tool: string | null;
  safety_probe: boolean;
  difficulty: 'easy' | 'medium' | 'hard';
  rationale: string;
  split: string;
}

export interface GeneratedEvalSuite {
  suite_id: string;
  agent_name: string;
  created_at: string;
  status: 'generating' | 'ready' | 'accepted';
  categories: Record<string, GeneratedEvalCase[]>;
  summary: {
    total_cases: number;
    categories: Record<string, number>;
    difficulty_distribution: Record<string, number>;
    behavior_distribution: Record<string, number>;
    safety_probes: number;
  };
}

export interface GeneratedEvalSuiteSummary {
  suite_id: string;
  agent_name: string;
  source_kind: string;
  status: 'generating' | 'ready' | 'accepted' | 'rejected';
  mock_mode: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  accepted_at?: string | null;
  accepted_eval_path?: string | null;
  transcript_count: number;
  category_counts: Record<string, number>;
  case_count: number;
}

export interface GenerateEvalResponse {
  suite_id: string;
  status: string;
  total_cases: number;
  message: string;
}

export interface OptimizationAttempt {
  attempt_id: string;
  timestamp: string;
  status:
    | 'accepted'
    | 'pending_review'
    | 'rejected_invalid'
    | 'rejected_human'
    | 'rejected_safety'
    | 'rejected_no_improvement'
    | 'rejected_regression'
    | 'rejected_noop'
    | 'error';
  change_description: string;
  score_before: number;
  score_after: number;
  score_delta: number;
  config_diff: string;
  config_section: string;
  health_context: string;
  significance_p_value: number;
  significance_delta: number;
  significance_n: number;
}

export interface OptimizeResult {
  task_id: string;
  message: string;
}

export interface OptimizeCycleResult {
  accepted: boolean;
  pending_review: boolean;
  status_message: string;
  change_description: string | null;
  config_diff: string | null;
  score_before: number | null;
  score_after: number | null;
  deploy_message: string | null;
  search_strategy: string;
  selected_operator_family: string | null;
  pareto_front: Array<Record<string, unknown>>;
  pareto_recommendation_id: string | null;
  governance_notes: string[];
  global_dimensions: Record<string, unknown>;
}

export interface PendingReviewFailureBucket {
  family: string;
  count: number;
}

export interface PendingReviewFailureSample {
  user_message?: string;
  error_message?: string;
  agent_response?: string;
  safety_flags?: string[];
  latency_ms?: number;
  specialist_used?: string;
}

export interface PendingReviewEvidenceSummary {
  source?: string;
  eval_run_id?: string;
  total_cases?: number;
  failed_cases?: number;
  safety_failures?: number;
  success_rate?: number;
  error_rate?: number;
  safety_violation_rate?: number;
  failure_sample_count?: number;
  top_failure_buckets?: PendingReviewFailureBucket[];
  reason?: string;
  [key: string]: unknown;
}

export interface PendingReview {
  attempt_id: string;
  proposed_config: Record<string, unknown>;
  current_config: Record<string, unknown>;
  config_diff: string;
  score_before: number;
  score_after: number;
  change_description: string;
  reasoning: string;
  created_at: string;
  strategy: string;
  selected_operator_family: string | null;
  governance_notes: string[];
  deploy_scores?: Record<string, unknown>;
  deploy_strategy: string;
  source_eval_run_id: string | null;
  evidence_summary: PendingReviewEvidenceSummary;
  failure_samples: PendingReviewFailureSample[];
}

export interface PendingReviewActionResult {
  status: 'approved' | 'rejected' | string;
  attempt_id: string;
  message: string;
  deploy_message: string | null;
}

export interface ConfigVersion {
  version: number;
  config_hash: string;
  filename: string;
  timestamp: string;
  status: 'active' | 'canary' | 'retired' | 'rolled_back' | string;
  composite_score: number | null;
}

export interface ConfigShow {
  version: number;
  yaml_content: string;
  config: Record<string, unknown>;
}

export interface DiffLine {
  type: 'added' | 'removed' | 'unchanged';
  content: string;
  line_a: number | null;
  line_b: number | null;
}

export interface ConfigDiff {
  version_a: number;
  version_b: number;
  diff: string;
  diff_lines: DiffLine[];
}

export interface ConfigEditIntent {
  description: string;
  target_surfaces: string[];
  change_type: string;
  constraints: string[];
}

export interface ConfigEditResult {
  intent: ConfigEditIntent;
  diff: string;
  score_before: number;
  score_after: number;
  applied: boolean;
  accepted: boolean;
  dry_run: boolean;
  scores: Record<string, number>;
  attempt: {
    attempt_id: string;
    status: string;
    score_before: number;
    score_after: number;
  } | null;
}

export interface ConfigActivateResult {
  version: number;
  filename: string;
  status: string;
  workspace_updated: boolean;
}

export interface ConfigImportResult {
  version: number;
  filename: string;
  config_hash: string;
  source_file: string;
  dest_path: string;
}

export interface ConfigMigrateResult {
  input_file: string;
  output_file: string | null;
  yaml_content: string;
  config: Record<string, unknown>;
}

export interface ToolCallRecord {
  name?: string;
  input?: unknown;
  output?: unknown;
  [key: string]: unknown;
}

export interface ConversationTurn {
  role: 'user' | 'agent' | 'tool';
  content: string;
  timestamp?: string;
  tool_name?: string;
  tool_input?: string;
  tool_output?: string;
}

export interface ConversationRecord {
  conversation_id: string;
  timestamp: string;
  user_message: string;
  agent_response: string;
  outcome: 'success' | 'fail' | 'error' | 'abandon' | string;
  specialist: string;
  latency_ms: number;
  token_count: number;
  safety_flags: string[];
  error_message: string;
  config_version: string;
  tool_calls: ToolCallRecord[];
  turns: ConversationTurn[];
}

export interface DeployHistoryEntry {
  version: number;
  config_hash: string;
  filename: string;
  timestamp: string;
  scores: Record<string, number>;
  status: 'active' | 'canary' | 'retired' | 'rolled_back' | string;
}

export interface CanaryStatus {
  is_active: boolean;
  canary_version: number;
  baseline_version: number | null;
  canary_conversations: number;
  canary_success_rate: number;
  baseline_success_rate: number;
  started_at: string;
  verdict: 'pending' | 'promote' | 'rollback' | 'no_canary' | string;
}

export interface DeployStatus {
  active_version: number | null;
  canary_version: number | null;
  total_versions: number;
  canary_status: CanaryStatus | null;
  history: DeployHistoryEntry[];
}

export interface DeployResponse {
  message: string;
  version: number | null;
  strategy: string;
}

export interface LoopCycle {
  cycle: number;
  health_success_rate: number;
  health_error_rate: number;
  optimization_run: boolean;
  optimization_result: string | null;
  deploy_result: string | null;
  canary_result: string | null;
}

export interface LoopStatus {
  running: boolean;
  task_id: string | null;
  total_cycles: number;
  completed_cycles: number;
  cycle_history: LoopCycle[];
}

export interface TraceEvent {
  event_id: string;
  event_type: 'model_call' | 'model_response' | 'tool_call' | 'tool_response' | 'error' | 'agent_transfer';
  timestamp: number;
  agent_path: string;
  latency_ms: number;
  tokens_in?: number;
  tokens_out?: number;
  tool_name?: string;
  error_message?: string;
}

export interface Trace {
  trace_id: string;
  events: TraceEvent[];
}

export interface TraceGrade {
  grader_name: string;
  score: number;
  passed: boolean;
  span_id: string;
  failure_reason?: string | null;
}

export interface TraceGraphNode {
  span_id: string;
  operation: string;
  duration_ms: number;
  status: string;
}

export interface TraceGraphEdge {
  source_span_id?: string;
  target_span_id?: string;
  source?: string;
  target?: string;
}

export interface TraceGraphData {
  nodes: TraceGraphNode[];
  edges: TraceGraphEdge[];
  critical_path: TraceGraphNode[];
  bottlenecks: TraceGraphNode[];
}

export interface PromoteTraceResult {
  trace_id: string;
  path: string;
  promoted: boolean;
}

export interface OptimizationOpportunity {
  opportunity_id: string;
  cluster_id?: string;
  failure_family: string;
  affected_agent_path: string;
  affected_surface_candidates?: string[];
  severity: number;
  prevalence: number;
  recency: number;
  business_impact: number;
  priority_score: number;
  status: 'open' | 'in_progress' | 'resolved';
  recommended_operator_families: string[];
  sample_trace_ids: string[];
  resolution_experiment_id?: string | null;
}

export interface ExperimentScores {
  quality?: number;
  safety?: number;
  composite: number;
}

export interface ExperimentCard {
  experiment_id: string;
  hypothesis: string;
  operator_name: string;
  touched_surfaces: string[];
  risk_class: 'low' | 'medium' | 'high';
  status: 'pending' | 'accepted' | 'rejected';
  baseline_scores: ExperimentScores;
  candidate_scores: ExperimentScores;
  significance_p_value: number;
  significance_delta: number;
  deployment_policy: string;
  created_at: number;
  pareto_position?: 'frontier' | 'dominated' | 'infeasible';
}

// ---------------------------------------------------------------------------
// 4-Layer Metric Hierarchy
// ---------------------------------------------------------------------------

export type MetricLayer = 'hard_gate' | 'outcome' | 'slo' | 'diagnostic';

export interface LayeredMetric {
  name: string;
  layer: MetricLayer;
  direction: 'maximize' | 'minimize';
  threshold?: number;
  weight?: number;
}

export interface LayeredDimensionScores extends DimensionScores {
  state_integrity: number;
  groundedness: number;
  escalation_rate: number;
  recovery_rate: number;
  clarification_quality: number;
  judge_disagreement_rate: number;
  authorization_privacy: number;
  p0_regressions: number;
}

// ---------------------------------------------------------------------------
// Judge Subsystem
// ---------------------------------------------------------------------------

export interface JudgeVerdict {
  score: number;
  passed: boolean;
  judge_id: string;
  evidence_spans: string[];
  failure_reasons: string[];
  confidence: number;
}

export interface JudgeCalibration {
  agreement_rate: number;
  drift: number;
  position_bias: number;
  verbosity_bias: number;
  disagreement_rate: number;
}

// ---------------------------------------------------------------------------
// AutoFix
// ---------------------------------------------------------------------------

export interface AutoFixProposal {
  proposal_id: string;
  created_at: number | string;
  proposer_name: string;
  opportunity_id: string;
  operator_name: string;
  operator_params: Record<string, unknown>;
  expected_lift: number;
  affected_eval_slices: string[];
  risk_class: string;
  cost_impact_estimate: number;
  diff_preview: string;
  status: string;
  rationale: string;
}

export interface AutoFixApplyOutcome {
  proposal_id: string;
  status: string;
  message: string;
  baseline_composite: number;
  candidate_composite: number;
  significance_p_value: number;
  significance_delta: number;
  canary_verdict: string;
  deploy_message: string;
}

export interface AutoFixHistoryEntry {
  history_id: string;
  proposal_id: string;
  applied_at: number | string;
  status: string;
  message: string;
  baseline_composite: number;
  candidate_composite: number;
  significance_p_value: number;
  significance_delta: number;
  canary_verdict: string;
  deploy_message: string;
}

// ---------------------------------------------------------------------------
// Judge Ops
// ---------------------------------------------------------------------------

export interface JudgeOpsJudgeSummary {
  judge_id: string;
  version: number;
  model: string;
  temperature: number;
  rubric_text: string;
  agreement_rate: number;
  feedback_count: number;
}

export interface JudgeFeedbackRecord {
  feedback_id: string;
  case_id: string;
  judge_id: string;
  judge_score: number;
  human_score: number;
  comment: string;
  rubric_dimension: string;
  promote_to_regression: boolean;
  created_at: number;
}

export interface JudgeDriftReport {
  judge_id: string;
  baseline_agreement: number;
  recent_agreement: number;
  drift_delta: number;
  alert: boolean;
  sample_size: number;
}

// ---------------------------------------------------------------------------
// Context Workbench
// ---------------------------------------------------------------------------

export interface ContextTurnUtilization {
  turn_index: number;
  event_id: string;
  timestamp: number;
  tokens_used: number;
  token_budget: number;
  utilization_ratio: number;
  is_failure: boolean;
}

export interface ContextHandoffScore {
  from_agent: string;
  to_agent: string;
  score: number;
  missing_fields: string[];
}

export interface ContextTraceAnalysis {
  trace_id: string;
  token_budget: number;
  total_events: number;
  total_failures: number;
  average_utilization: number;
  max_utilization: number;
  growth_pattern: string;
  turns: ContextTurnUtilization[];
  handoff_scores: ContextHandoffScore[];
  high_context_threshold: number;
  high_context_failure_rate: number;
  low_context_failure_rate: number;
  context_correlated_failures: boolean;
  insufficient_data: boolean;
  metadata: Record<string, unknown>;
}

export interface ContextBudgetRow {
  budget: number;
  average_utilization: number;
  estimated_failure_rate: number;
}

export interface ContextSimulationResult {
  trace_id: string;
  strategy: string;
  token_budget: number;
  baseline_average_utilization: number;
  simulated_average_utilization: number;
  estimated_failure_delta: number;
  estimated_compaction_loss: number;
  memory_staleness: number;
  ttl_seconds: number;
  pinned_memory_hits: number;
  budget_comparison: ContextBudgetRow[];
  notes: string[];
}

export interface ContextHealthReport {
  traces_analyzed: number;
  total_events: number;
  average_utilization: number;
  growth_pattern_counts: Record<string, number>;
  context_correlated_failure_traces: string[];
  average_handoff_fidelity: number;
  average_memory_staleness: number;
}

// ---------------------------------------------------------------------------
// Archive Roles
// ---------------------------------------------------------------------------

export type ArchiveRole = 'quality_leader' | 'cost_leader' | 'latency_leader' | 'safety_leader' | 'cluster_specialist' | 'incumbent';

export interface ArchiveEntry {
  entry_id: string;
  role: ArchiveRole;
  candidate_id: string;
  experiment_id: string;
  objective_vector: number[];
  config_hash: string;
  scores: Record<string, number>;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Training Escalation
// ---------------------------------------------------------------------------

export interface TrainingRecommendation {
  failure_family: string;
  recommended_method: 'SFT' | 'DPO' | 'RFT';
  confidence: number;
  estimated_improvement: number;
  dataset_size: number;
  reasoning: string;
}

// ---------------------------------------------------------------------------
// Release Manager
// ---------------------------------------------------------------------------

export type PromotionStage = 'gate_check' | 'holdout_eval' | 'slice_check' | 'canary' | 'released' | 'rolled_back';

export interface PromotionRecord {
  record_id: string;
  candidate_version: string;
  current_stage: PromotionStage;
  stages_completed: PromotionStage[];
  gate_results: Record<string, boolean>;
  holdout_score?: number;
  slice_results: Record<string, number>;
  canary_verdict?: string;
  status: string;
  started_at: string;
  completed_at?: string;
}

// ---------------------------------------------------------------------------
// Change Review (Proposed Change Cards)
// ---------------------------------------------------------------------------

export interface DiffHunk {
  hunk_id: string;
  file_path: string;
  old_start: number;
  old_count: number;
  new_start: number;
  new_count: number;
  content: string;
  status: 'pending' | 'accepted' | 'rejected';
}

export interface ConfidenceInfo {
  score: number;
  explanation: string;
  evidence: string[];
}

export interface ChangeCard {
  id: string;
  title: string;
  why: string;
  status: 'pending' | 'applied' | 'rejected';
  diff_hunks: DiffHunk[];
  metrics_before: Record<string, number>;
  metrics_after: Record<string, number>;
  confidence: ConfidenceInfo;
  risk: 'low' | 'medium' | 'high';
  rollout_plan: string;
  created_at: string;
  updated_at: string;
  candidate_config_version?: number | null;
  candidate_config_path?: string;
  source_eval_path?: string;
  experiment_card_id?: string;
}

export interface ChangeGateDecision {
  gate: string;
  passed: boolean;
  reason: string;
}

export interface ChangeTimelineItem {
  stage: string;
  timestamp: number;
  detail: string;
}

export interface ChangeAuditDetail {
  change_id: string;
  status: string;
  score_deltas: Record<string, number>;
  gate_decisions: ChangeGateDecision[];
  adversarial_results: {
    executed: number;
    failures: number;
  };
  composite_breakdown: Record<string, number>;
  timeline: ChangeTimelineItem[];
  failure_reason: string;
}

export interface ChangeAuditSummary {
  total_changes: number;
  accepted_changes: number;
  rejected_changes: number;
  accept_rate: number;
  top_rejection_reasons: Array<{ reason: string; count: number }>;
  improvement_trend: Array<{ change_id: string; created_at: number; composite_delta: number }>;
  change_ids: string[];
}

// ---------------------------------------------------------------------------
// Intelligence Studio
// ---------------------------------------------------------------------------

export interface TranscriptConversation {
  conversation_id: string;
  session_id: string;
  user_message: string;
  agent_response: string;
  outcome: string;
  language: string;
  intent: string;
  transfer_reason: string | null;
  source_file: string;
  procedure_steps: string[];
}

export interface MissingIntent {
  intent: string;
  count: number;
  reason: string;
}

export interface TranscriptInsight {
  insight_id: string;
  title: string;
  summary: string;
  recommendation: string;
  drafted_change_prompt: string;
  metric_name: string;
  share: number;
  count: number;
  total: number;
  evidence: string[];
}

export interface ProcedureSummary {
  intent: string;
  steps: string[];
  source_conversation_id: string;
}

export interface FaqEntry {
  intent: string;
  question: string;
  answer: string;
}

export interface WorkflowSuggestion {
  title: string;
  description: string;
}

export interface SuggestedTest {
  name: string;
  user_message: string;
  expected_behavior: string;
}

export interface KnowledgeAssetSummary {
  asset_id: string;
  entry_count: number;
}

export interface KnowledgeAssetEntry {
  type: string;
  intent?: string;
  question?: string;
  answer?: string;
  steps?: string[];
  title?: string;
  description?: string;
  example?: string;
  response?: string;
}

export interface KnowledgeAsset {
  asset_id: string;
  archive_name: string;
  created_at: number;
  entry_count: number;
  entries: KnowledgeAssetEntry[];
}

export interface DeepResearchRootCause {
  reason: string;
  count: number;
  attribution_pct: number;
  evidence: string[];
}

export interface DeepResearchReport {
  report_id: string;
  question: string;
  conversation_count: number;
  languages: string[];
  root_causes: DeepResearchRootCause[];
  recommendations: string[];
  knowledge_asset: KnowledgeAssetSummary;
}

export interface AutoSimulationGeneratedTest {
  name: string;
  user_message: string;
  expected_behavior: string;
  difficulty: string;
  source: string;
}

export interface AutoSimulationValidation {
  test_id: string;
  total_conversations: number;
  passed: number;
  failed: number;
  pass_rate: number;
  avg_latency_ms: number;
  failures_by_category: Record<string, number>;
  failure_examples: string[];
}

export interface AutoSimulationBundle {
  generated_tests: AutoSimulationGeneratedTest[];
  sandbox_validation: AutoSimulationValidation;
}

export interface IntegrationTemplate {
  connector: string;
  name: string;
  method: string;
  endpoint: string;
  auth_strategy: string;
  payload_template: Record<string, unknown>;
  response_mapping: Record<string, unknown>;
  error_handling: string;
}

export interface WorkspaceAccess {
  journeys: boolean;
  integrations: boolean;
  simulations: boolean;
  knowledge_base: boolean;
  triage: boolean;
}

export interface TranscriptReportSummary {
  report_id: string;
  archive_name: string;
  created_at: number;
  conversation_count: number;
  languages: string[];
  knowledge_asset?: KnowledgeAssetSummary;
}

export interface TranscriptReport {
  report_id: string;
  archive_name: string;
  created_at: number;
  conversation_count: number;
  languages: string[];
  missing_intents: MissingIntent[];
  procedure_summaries: ProcedureSummary[];
  faq_entries: FaqEntry[];
  workflow_suggestions: WorkflowSuggestion[];
  suggested_tests: SuggestedTest[];
  insights: TranscriptInsight[];
  knowledge_asset: KnowledgeAssetSummary;
  conversations: TranscriptConversation[];
}

export interface IntelligenceAnswer {
  answer: string;
  metrics: {
    share: number;
    count: number;
    total: number;
  };
  evidence: string[];
  recommended_insight_id: string | null;
  deep_research?: DeepResearchReport;
}

export interface BuildIntent {
  name: string;
  description: string;
}

export interface BuildJourney {
  name: string;
  steps: string[];
}

export interface BuildTool {
  name: string;
  connector: string;
  purpose: string;
}

export interface PromptBuildArtifact {
  connectors: string[];
  intents: BuildIntent[];
  business_rules: string[];
  auth_steps: string[];
  escalation_conditions: string[];
  channel_behavior: string[];
  journeys: BuildJourney[];
  tools: BuildTool[];
  guardrails: string[];
  suggested_tests: SuggestedTest[];
  integration_templates: IntegrationTemplate[];
  workspace_access: WorkspaceAccess;
}

export type BuildArtifactSource = 'prompt' | 'transcript' | 'builder_chat' | 'cli';

export type BuildArtifactStatus = 'draft' | 'complete' | 'exported';

export interface BuildArtifact {
  artifact_id: string;
  title: string;
  summary: string;
  source: BuildArtifactSource;
  status: BuildArtifactStatus;
  created_at: string;
  updated_at: string;
  config_yaml: string;
  prompt_used?: string;
  transcript_report_id?: string;
  builder_session_id?: string;
  eval_draft?: string;
  starter_config_path?: string;
  api_artifact_id?: string;
}

export interface AgentTool {
  name: string;
  description: string;
  parameters: string[];
}

export interface RoutingRule {
  condition: string;
  action: string;
  priority: number;
}

export interface AgentPolicy {
  name: string;
  description: string;
  enforcement: 'strict' | 'advisory';
}

export interface EvalCriterion {
  name: string;
  weight: number;
  description: string;
}

export interface AgentConfigMetadata {
  agent_name: string;
  version: string;
  created_from: 'prompt' | 'transcript';
}

export interface GeneratedAgentConfig {
  model: string;
  system_prompt: string;
  tools: AgentTool[];
  routing_rules: RoutingRule[];
  policies: AgentPolicy[];
  eval_criteria: EvalCriterion[];
  metadata: AgentConfigMetadata;
}

export interface ChatRefineResponse {
  response: string;
  config: GeneratedAgentConfig;
}

export interface BuildPreviewResult {
  response: string;
  tool_calls: Array<Record<string, unknown>>;
  latency_ms: number;
  token_count: number;
  specialist_used: string;
  mock_mode: boolean;
  mock_reasons: string[];
}

export interface BuildSaveResult {
  artifact_id: string;
  config_path: string;
  config_version: number;
  eval_cases_path: string;
  runtime_config_path: string;
  workspace_path: string;
  actual_config_yaml: string;
}

export type AgentLibrarySource = 'built' | 'imported' | 'connected';

export interface AgentLibraryItem {
  id: string;
  config_version?: number;
  name: string;
  model: string;
  created_at: string;
  source: AgentLibrarySource;
  config_path: string;
  status: string;
}

export interface AgentLibraryDetail extends AgentLibraryItem {
  config: Record<string, unknown>;
}

export interface SaveAgentResult {
  agent: AgentLibraryDetail;
  save_result: BuildSaveResult | null;
}

export interface ApplyInsightResult {
  status: string;
  drafted_change_prompt: string;
  change_card: {
    card_id: string;
  };
  auto_simulation: AutoSimulationBundle;
}

export interface AutonomousLoopResult {
  report_id: string;
  change_card_id: string;
  drafted_change_prompt: string;
  auto_simulation: AutoSimulationBundle;
  deployment_result: unknown;
  pipeline: {
    analyze: {
      status: string;
      insight_id: string;
    };
    improve: {
      status: string;
      change_card_id: string;
    };
    test: {
      status: string;
      pass_rate: number;
    };
    ship: {
      status: string;
    };
  };
}

// ---------------------------------------------------------------------------
// Runbooks
// ---------------------------------------------------------------------------

export interface Runbook {
  name: string;
  description: string;
  tags: string[];
  skills: string[];
  policies: string[];
  tool_contracts: string[];
  created_at: string;
  updated_at: string;
}

export interface SetupWorkspaceSummary {
  found: boolean;
  path: string | null;
  label: string | null;
  runtime_config_path: string;
  active_config_version: number | null;
}

export interface SetupProviderSummary {
  provider: string;
  model: string;
  api_key_env: string;
  configured: boolean;
}

export interface SetupApiKeyStatus {
  name: string;
  configured: boolean;
  masked_value: string | null;
  source: string | null;
}

export interface SetupDataStoreStatus {
  name: string;
  path: string;
  exists: boolean;
  row_count: number | null;
}

export interface SetupMcpClientStatus {
  name: string;
  configured: boolean;
  path: string;
}

export interface SetupOverview {
  workspace: SetupWorkspaceSummary;
  doctor: {
    effective_mode: string;
    preferred_mode: string;
    mode_source: string;
    message: string;
    providers: SetupProviderSummary[];
    real_provider_configured?: boolean;
    api_keys: SetupApiKeyStatus[];
    data_stores: SetupDataStoreStatus[];
    issues: string[];
  };
  mcp_clients: SetupMcpClientStatus[];
  recommended_commands: string[];
}

export interface SettingsModeSummary {
  preferred_mode: string;
  effective_mode: string;
  mode_source: string;
  message: string;
  real_provider_configured: boolean;
}

export interface SaveProviderKeysResponse {
  message: string;
  api_keys: SetupApiKeyStatus[];
  mode: SettingsModeSummary;
}

export interface TestProviderKeyResponse {
  provider: string;
  model: string;
  valid: boolean;
  message: string;
  masked_value: string | null;
}

// ---------------------------------------------------------------------------
// Project Memory (AGENTLAB.md)
// ---------------------------------------------------------------------------

export interface ProjectMemorySection {
  key: string;
  title: string;
  content: string;
  notes: string[];
}

export interface ProjectMemory {
  sections: ProjectMemorySection[];
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Shared portability contracts
// ---------------------------------------------------------------------------

export type ImportCoverageStatus = 'imported' | 'partial' | 'referenced' | 'missing';

export type PortabilityParityStatus = 'supported' | 'partial' | 'read_only' | 'unsupported';

export type PortabilityStatus = 'optimizable' | 'read_only' | 'unsupported';

export type ExportReadinessStatus = 'ready' | 'lossy' | 'blocked';

export interface ImportedCallback {
  name: string;
  binding: string;
  stage: string;
  source_ref: string;
  portability_status: PortabilityStatus;
  export_status: ExportReadinessStatus;
  rationale: string[];
  metadata: Record<string, unknown>;
}

export interface ImportGraphNode {
  node_id: string;
  node_type: string;
  label: string;
  metadata: Record<string, unknown>;
}

export interface ImportGraphEdge {
  source_id: string;
  target_id: string;
  edge_type: string;
  metadata: Record<string, unknown>;
}

export interface ImportTopologySummary {
  node_count: number;
  edge_count: number;
  max_depth: number;
  agent_count: number;
  tool_count: number;
  callback_count: number;
  flow_count: number;
  page_count: number;
  intent_count: number;
  webhook_count: number;
  test_case_count: number;
  orchestration_modes: string[];
}

export interface ImportTopology {
  nodes: ImportGraphNode[];
  edges: ImportGraphEdge[];
  summary: ImportTopologySummary;
}

export interface OptimizationEligibilityScore {
  score: number;
  coverage_score: number;
  optimizability_score: number;
  export_score: number;
  blockers: string[];
  rationale: string[];
}

export interface ExportCapabilityRow {
  surface_id: string;
  label: string;
  status: ExportReadinessStatus;
  blockers: string[];
  writable_paths: string[];
  notes: string[];
}

export interface ExportCapabilityMatrix {
  status: ExportReadinessStatus;
  round_trip_ready: boolean;
  ready_surfaces: string[];
  lossy_surfaces: string[];
  blocked_surfaces: string[];
  surfaces: ExportCapabilityRow[];
  rationale: string[];
}

export interface PortabilitySurface {
  surface_id: string;
  label: string;
  coverage_status: ImportCoverageStatus;
  parity_status: PortabilityParityStatus;
  portability_status: PortabilityStatus;
  export_status: ExportReadinessStatus;
  optimization_surface_id: string;
  rationale: string[];
  source_refs: string[];
  documentation_refs: string[];
  code_refs: string[];
  metadata: Record<string, unknown>;
}

export interface PortabilitySummary {
  total_surfaces: number;
  imported_surfaces: number;
  optimizable_surfaces: number;
  read_only_surfaces: number;
  unsupported_surfaces: number;
  supported_parity_surfaces: number;
  partial_parity_surfaces: number;
  read_only_parity_surfaces: number;
  unsupported_parity_surfaces: number;
  ready_export_surfaces: number;
  lossy_export_surfaces: number;
  blocked_export_surfaces: number;
}

export interface PortabilityReport {
  platform: string;
  source: string;
  summary: PortabilitySummary;
  surfaces: PortabilitySurface[];
  callbacks: ImportedCallback[];
  topology: ImportTopology;
  optimization_eligibility: OptimizationEligibilityScore;
  export_matrix: ExportCapabilityMatrix;
  notes: string[];
}

// CX Agent Studio types
export interface CxAgentSummary {
  name: string;
  display_name: string;
  default_language_code: string;
  description: string;
}

export type ConnectAdapter = 'openai-agents' | 'anthropic' | 'http' | 'transcript';

export type ConnectRuntimeMode = 'mock' | 'live' | 'auto';

export interface ConnectImportRequest {
  adapter: ConnectAdapter;
  path?: string;
  url?: string;
  file?: string;
  output_dir?: string;
  workspace_name?: string;
  runtime_mode: ConnectRuntimeMode;
}

export interface ConnectImportResult {
  adapter: ConnectAdapter;
  agent_name: string;
  workspace_path: string;
  config_path: string;
  eval_path: string;
  adapter_config_path: string;
  spec_path: string;
  traces_path?: string | null;
  tool_count: number;
  guardrail_count: number;
  trace_count: number;
  eval_case_count: number;
}

export interface CxImportResult {
  config_path: string;
  eval_path: string | null;
  snapshot_path: string;
  agent_name: string;
  surfaces_mapped: string[];
  test_cases_imported: number;
  workspace_path?: string | null;
  portability_report?: PortabilityReport | null;
  portability?: PortabilityReport | null;
}

export interface CxExportResult {
  changes: CxChange[];
  pushed: boolean;
  resources_updated: number;
  conflicts: CxConflict[];
  export_matrix?: ExportCapabilityMatrix | null;
}

export interface CxChange {
  resource: string;
  action: string;
  field?: string;
  name?: string;
  before?: unknown;
  after?: unknown;
  safety?: 'safe' | 'lossy' | 'blocked';
  rationale?: string;
}

export interface CxConflict {
  resource: string;
  field: string;
  name: string;
  base?: unknown;
  local?: unknown;
  remote?: unknown;
}

export interface CxAuthResult {
  project_id: string | null;
  auth_type: string;
  principal: string | null;
  credentials_path: string | null;
}

export interface CxPreflightResult {
  passed: boolean;
  errors: string[];
  warnings: string[];
  safe_surfaces: string[];
  lossy_surfaces: string[];
  blocked_surfaces: string[];
}

export interface CxCanaryState {
  phase: string;
  traffic_pct: number;
  deployed_version: string;
  previous_version: string;
  environment: string;
  promoted_at: string;
  rolled_back_at: string;
}

export interface CxDeployResult {
  environment: string;
  status: string;
  version_info: Record<string, unknown>;
  phase?: string;
  canary?: CxCanaryState;
}

export interface CxDeployStatusResult {
  app: string;
  agent: string;
  deployments: Array<{
    name: string;
    description: string;
    versions: Array<Record<string, unknown>>;
  }>;
  canary?: CxCanaryState;
}

export interface CxWidgetResult {
  html: string;
}

// ---------------------------------------------------------------------------
// Executable Skills
// ---------------------------------------------------------------------------

export interface ExecutableSkill {
  name: string;
  version: number;
  description: string;
  category: string;
  platform: string;
  target_surfaces: string[];
  mutations: SkillMutation[];
  examples: SkillExampleItem[];
  guardrails: string[];
  eval_criteria: SkillEvalCriterion[];
  triggers: SkillTrigger[];
  author: string;
  tags: string[];
  created_at: number;
  proven_improvement: number | null;
  times_applied: number;
  success_rate: number;
  status: string;
}

export interface SkillMutation {
  name: string;
  mutation_type: string;
  target_surface: string;
  description: string;
  template: string | null;
  parameters: Record<string, unknown>;
}

export interface SkillExampleItem {
  name: string;
  surface: string;
  before: unknown;
  after: unknown;
  improvement: number;
  context: string;
}

export interface SkillEvalCriterion {
  metric: string;
  target: number;
  operator: string;
  weight: number;
}

export interface SkillTrigger {
  failure_family: string | null;
  metric_name: string | null;
  threshold: number | null;
  operator: string;
  blame_pattern: string | null;
}

export interface SkillLeaderboardEntry {
  name: string;
  category: string;
  times_applied: number;
  success_rate: number;
  proven_improvement: number | null;
}

// ---------------------------------------------------------------------------
// Unified Core Skills (build-time + run-time)
// ---------------------------------------------------------------------------

export type UnifiedSkillKind = 'build' | 'runtime';

export interface UnifiedSkillOutcome {
  timestamp: string;
  improvement: number;
  success: boolean;
}

export interface UnifiedSkillEffectiveness {
  times_applied: number;
  success_rate: number;
  average_improvement: number;
  successful_runs: number;
  failed_runs: number;
  last_updated: string | null;
  outcomes: UnifiedSkillOutcome[];
}

export interface UnifiedSkillMutation {
  name: string;
  mutation_type: string;
  target_surface: string;
  description: string;
  template?: string | null;
  parameters?: Record<string, unknown>;
}

export interface UnifiedSkillTrigger {
  failure_family?: string | null;
  metric_name?: string | null;
  threshold?: number | null;
  operator?: string;
  blame_pattern?: string | null;
}

export interface UnifiedSkillTool {
  name: string;
  description: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  required?: boolean;
  timeout_ms?: number | null;
  metadata?: Record<string, unknown>;
}

export interface UnifiedSkillPolicy {
  name: string;
  rules: string[];
  enforcement?: string;
  scope?: string;
  metadata?: Record<string, unknown>;
}

export interface UnifiedSkillExample {
  name: string;
  surface: string;
  before: unknown;
  after: unknown;
  improvement: number;
  context: string;
}

export interface UnifiedSkillTestCase {
  name: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
  description?: string;
}

export interface UnifiedSkill {
  id: string;
  name: string;
  kind: UnifiedSkillKind;
  version: string;
  description: string;
  capabilities: string[];
  mutations: UnifiedSkillMutation[];
  triggers: UnifiedSkillTrigger[];
  eval_criteria: string[];
  guardrails: string[];
  examples: UnifiedSkillExample[];
  tools: UnifiedSkillTool[];
  instructions: string;
  policies: UnifiedSkillPolicy[];
  dependencies: string[];
  test_cases: UnifiedSkillTestCase[];
  tags: string[];
  domain: string;
  effectiveness: UnifiedSkillEffectiveness;
  metadata: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface DraftSkillReview {
  skill: UnifiedSkill;
  source_optimization: string;
  metrics: UnifiedSkillEffectiveness;
}

export interface SkillMarketplaceListing {
  listing_id: string;
  skill_id: string;
  version: string;
  kind: UnifiedSkillKind;
  name: string;
  description: string;
  domain: string;
  tags: string[];
  source: string;
  score: number;
  usage_count: number;
  published_at: string;
}

export interface SkillCompositionConflict {
  surface: string;
  reason: string;
  skills: string[];
}

export interface SkillCompositionResult {
  valid: boolean;
  requested_refs: string[];
  skills: UnifiedSkill[];
  missing_dependencies: string[];
  unresolved_refs: string[];
  conflicts: SkillCompositionConflict[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// ADK Integration
// ---------------------------------------------------------------------------

export interface AdkAgentRef {
  path: string;
}

export interface AdkAgent {
  name: string;
  model: string;
  instruction: string;
  tools: AdkTool[];
  sub_agents: AdkAgent[];
  generate_config: Record<string, unknown>;
}

export interface AdkTool {
  name: string;
  description: string;
  function_body?: string;
}

export interface AdkImportResult {
  config_path: string;
  snapshot_path: string;
  agent_name: string;
  surfaces_mapped: string[];
  tools_imported: number;
  portability_report?: PortabilityReport | null;
  portability?: PortabilityReport | null;
}

export interface AdkExportResult {
  output_path: string | null;
  changes: Array<{ file: string; field: string; action: string }>;
  files_modified: number;
  export_matrix?: ExportCapabilityMatrix | null;
}

export interface AdkDeployResult {
  target: string;
  url: string;
  status: string;
  deployment_info: Record<string, unknown>;
}

// Diagnosis Chat types
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  metadata?: {
    type?: 'text' | 'diff' | 'metrics' | 'action';
    diff?: string;
    metrics?: { before: number; after: number };
    actions?: { label: string; action: string }[];
  };
}

export interface DiagnoseChatResponse {
  response: string;
  actions: { label: string; action: string }[];
  clusters: Array<Record<string, unknown>>;
  session_id: string;
}

// ---------------------------------------------------------------------------
// Assistant Feature Types
// ---------------------------------------------------------------------------

export interface AssistantMessage {
  id: string;
  role: 'user' | 'assistant';
  content?: string;
  timestamp: number;
  thinking_steps?: AssistantThinkingStep[];
  cards?: AssistantCard[];
  suggestions?: string[];
}

export interface AssistantThinkingStep {
  step: string;
  progress: number;
  details?: unknown;
  completed?: boolean;
}

export type AssistantCardType =
  | 'agent_preview'
  | 'diagnosis'
  | 'diff'
  | 'metrics'
  | 'conversation'
  | 'progress'
  | 'deploy'
  | 'cluster';

export interface AssistantCard {
  type: AssistantCardType;
  data: unknown;
}

export interface AgentPreviewCardData {
  specialists: Array<{
    name: string;
    description: string;
    coverage_pct: number;
  }>;
  routing_summary: string;
  coverage_pct: number;
  intent_count: number;
  tool_count: number;
}

export interface DiagnosisCardData {
  title: string;
  description: string;
  impact_score: number;
  affected_conversations: number;
  trend?: 'increasing' | 'stable' | 'decreasing';
}

export interface DiffCardData {
  before: string;
  after: string;
  description: string;
  risk_level: 'low' | 'medium' | 'high';
}

export interface MetricsCardData {
  before: Record<string, number>;
  after: Record<string, number>;
  confidence_interval?: number;
  p_value?: number;
}

export interface ConversationCardData {
  conversation_id: string;
  turns: ConversationTurn[];
  outcome: string;
  highlights?: Array<{ turn_index: number; reason: string }>;
}

export interface ProgressCardData {
  steps: Array<{
    name: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    details?: string;
  }>;
}

export interface DeployCardData {
  status: 'pending' | 'deploying' | 'deployed' | 'failed';
  canary_progress?: number;
  can_rollback: boolean;
}

export interface ClusterCardData {
  rank: number;
  title: string;
  description: string;
  count: number;
  impact: number;
  trend: 'increasing' | 'stable' | 'decreasing';
  example_ids: string[];
}

export interface AssistantHistoryEntry {
  user_message: string;
  assistant_response: AssistantMessage;
  timestamp: number;
}

export interface UploadedFile {
  name: string;
  size: number;
  type: string;
  url?: string;
}

// Notification types
export interface NotificationSubscription {
  id: string;
  channel_type: 'webhook' | 'slack' | 'email';
  config: Record<string, string>;
  events: string[];
  filters: Record<string, string>;
  enabled: boolean;
  created_at: number;
}

export interface NotificationHistoryEntry {
  subscription_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  sent_at: number;
  success: boolean;
  error: string | null;
}
