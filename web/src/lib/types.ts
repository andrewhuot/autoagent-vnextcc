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

export interface EvalResult {
  run_id: string;
  status: TaskState;
  progress: number;
  timestamp: string;
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
  composite_score: number;
  total_cases: number;
  passed_cases: number;
}

export interface OptimizationAttempt {
  attempt_id: string;
  timestamp: string;
  status:
    | 'accepted'
    | 'rejected_invalid'
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
}

export interface OptimizeResult {
  task_id: string;
  message: string;
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

export interface OptimizationOpportunity {
  opportunity_id: string;
  failure_family: string;
  affected_agent_path: string;
  severity: number;
  prevalence: number;
  recency: number;
  business_impact: number;
  priority_score: number;
  status: 'open' | 'in_progress' | 'resolved';
  recommended_operator_families: string[];
  sample_trace_ids: string[];
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
