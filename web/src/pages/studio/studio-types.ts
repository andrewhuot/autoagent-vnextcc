// ─── Spec Types ─────────────────────────────────────────────────────────────

export interface SpecVersion {
  version_id: string;
  version_number: number;
  created_at: string;
  author: string;
  summary: string;
  status: 'draft' | 'published' | 'archived';
  content: string;
}

// ─── Observe Types ────────────────────────────────────────────────────────────

export type IssueSeverity = 'critical' | 'high' | 'medium' | 'low';
export type IssueCategory =
  | 'task_failure'
  | 'latency'
  | 'policy_violation'
  | 'hallucination'
  | 'tool_error';

export interface ProductionIssue {
  issue_id: string;
  category: IssueCategory;
  severity: IssueSeverity;
  title: string;
  description: string;
  count: number;
  first_seen: string;
  last_seen: string;
  affected_sessions: number;
  example_trace_id: string | null;
  example_conversation_id: string | null;
}

export interface ProductionMetricsSnapshot {
  success_rate: number;
  success_rate_delta: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  latency_delta_pct: number;
  error_rate: number;
  error_rate_delta: number;
  cost_per_session_usd: number;
  cost_delta_pct: number;
  sparkline_success: number[];
  sparkline_latency: number[];
  sparkline_errors: number[];
}

export interface EvidenceTrace {
  trace_id: string;
  session_id: string;
  started_at: string;
  outcome: 'success' | 'failure' | 'partial';
  latency_ms: number;
  issue_category: IssueCategory | null;
  steps: EvidenceTraceStep[];
}

export interface EvidenceTraceStep {
  step_id: string;
  type: 'model_call' | 'tool_call' | 'tool_response' | 'error' | 'agent_transfer';
  label: string;
  latency_ms: number;
  error?: string;
}

export interface EvidenceConversation {
  conversation_id: string;
  session_id: string;
  started_at: string;
  outcome: 'success' | 'failure' | 'partial';
  turns: ConversationTurn[];
  issue_category: IssueCategory | null;
}

export interface ConversationTurn {
  turn_id: string;
  role: 'user' | 'agent';
  content: string;
  timestamp: string;
  flagged?: boolean;
  flag_reason?: string;
}

// ─── Optimize Types ───────────────────────────────────────────────────────────

export type OptimizeMode = 'basic' | 'research' | 'pro';

export interface OptimizeModeConfig {
  mode: OptimizeMode;
  label: string;
  description: string;
  iterations: number;
  uses_research: boolean;
  uses_pareto: boolean;
  estimated_duration: string;
}

export interface EvalSetSummary {
  eval_set_id: string;
  name: string;
  description: string;
  num_cases: number;
  last_run: string | null;
  pass_rate: number | null;
}

export interface StudioCandidate {
  candidate_id: string;
  label: string;
  is_baseline: boolean;
  created_at: string;
  eval_run_id: string | null;
  scores: CandidateScores;
  spec_diff_lines: SpecDiffLine[];
  status: 'pending' | 'running' | 'evaluated' | 'promoted' | 'rejected';
}

export interface CandidateScores {
  overall: number;
  task_success: number;
  response_quality: number;
  safety: number;
  latency_score: number;
  cost_score: number;
}

export interface SpecDiffLine {
  type: 'added' | 'removed' | 'context';
  content: string;
  line_a: number;
  line_b: number;
}

export interface StudioOptimizeRun {
  run_id: string;
  mode: OptimizeMode;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at: string;
  completed_at: string | null;
  candidates: StudioCandidate[];
  recommended_candidate_id: string | null;
  progress: number;
  log_tail: string[];
}

// ─── Studio State ─────────────────────────────────────────────────────────────

export type StudioTab = 'spec' | 'observe' | 'optimize';
