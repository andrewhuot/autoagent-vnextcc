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

export interface CompositeScore {
  overall: number;
  quality: number;
  safety: number;
  latency: number;
  cost: number;
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
