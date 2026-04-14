// Builder Workspace canonical frontend types.
// Mirrors backend dataclasses from builder/types.py.

export type ExecutionMode = 'ask' | 'draft' | 'apply' | 'delegate';

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type ArtifactType =
  | 'plan'
  | 'source_diff'
  | 'adk_graph_diff'
  | 'skill'
  | 'guardrail'
  | 'eval'
  | 'trace_evidence'
  | 'benchmark'
  | 'release';

export type ApprovalScope = 'once' | 'task' | 'project';

export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export type SpecialistRole =
  | 'orchestrator'
  | 'build_engineer'
  | 'requirements_analyst'
  | 'prompt_engineer'
  | 'adk_architect'
  | 'tool_engineer'
  | 'skill_author'
  | 'guardrail_author'
  | 'eval_author'
  | 'optimization_engineer'
  | 'trace_analyst'
  | 'deployment_engineer'
  | 'release_manager';

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

export type PrivilegedAction =
  | 'source_write'
  | 'external_network'
  | 'secret_access'
  | 'deployment'
  | 'benchmark_spend';

export interface BuilderProject {
  project_id: string;
  name: string;
  description: string;
  root_path: string;
  master_instruction: string;
  folder_instructions: Record<string, string>;
  knowledge_files: string[];
  buildtime_skills: string[];
  runtime_skills: string[];
  eval_defaults: Record<string, unknown>;
  benchmark_defaults: Record<string, unknown>;
  permission_defaults: Record<string, unknown>;
  preferred_models: Record<string, string>;
  deployment_targets: string[];
  created_at: number;
  updated_at: number;
  archived: boolean;
  tags: string[];
  metadata: Record<string, unknown>;
}

export interface BuilderSession {
  session_id: string;
  project_id: string;
  title: string;
  mode: ExecutionMode;
  active_specialist: SpecialistRole;
  status: 'open' | 'closed';
  created_at: number;
  updated_at: number;
  closed_at: number | null;
  message_count: number;
  task_ids: string[];
  metadata: Record<string, unknown>;
}

export interface BuilderTask {
  task_id: string;
  session_id: string;
  project_id: string;
  title: string;
  description: string;
  mode: ExecutionMode;
  status: TaskStatus;
  active_specialist: SpecialistRole;
  created_at: number;
  updated_at: number;
  started_at: number | null;
  paused_at: number | null;
  completed_at: number | null;
  elapsed_seconds: number;
  eta_seconds: number | null;
  progress: number;
  current_step: string;
  tool_in_use: string;
  token_count: number;
  cost_usd: number;
  artifact_ids: string[];
  proposal_ids: string[];
  approval_ids: string[];
  error: string | null;
  parent_task_id: string | null;
  duplicate_of_task_id: string | null;
  forked_from_task_id: string | null;
  worktree_ref: string | null;
  sandbox_run_id: string | null;
  metadata: Record<string, unknown>;
}

export interface BuilderProposal {
  proposal_id: string;
  task_id: string;
  session_id: string;
  project_id: string;
  goal: string;
  assumptions: string[];
  targeted_artifacts: string[];
  targeted_surfaces: string[];
  expected_impact: string;
  risk_level: RiskLevel;
  required_approvals: string[];
  steps: Array<Record<string, unknown>>;
  created_at: number;
  updated_at: number;
  status: 'pending' | 'approved' | 'rejected' | 'revision_requested';
  accepted: boolean;
  rejected: boolean;
  revision_count: number;
  revision_comments: string[];
}

export interface ArtifactRef {
  artifact_id: string;
  task_id: string;
  session_id: string;
  project_id: string;
  artifact_type: ArtifactType;
  title: string;
  summary: string;
  payload: Record<string, unknown>;
  skills_used: string[];
  source_versions: Record<string, string>;
  release_candidate_id: string | null;
  created_at: number;
  updated_at: number;
  selected: boolean;
  comments: Array<Record<string, unknown>>;
}

export interface ApprovalRequest {
  approval_id: string;
  task_id: string;
  session_id: string;
  project_id: string;
  action: PrivilegedAction;
  description: string;
  scope: ApprovalScope;
  status: ApprovalStatus;
  risk_level: RiskLevel;
  details: Record<string, unknown>;
  created_at: number;
  updated_at: number;
  resolved_at: number | null;
  resolved_by: string | null;
  expires_at: number | null;
}

export interface WorktreeRef {
  worktree_id: string;
  task_id: string;
  project_id: string;
  branch_name: string;
  base_sha: string;
  worktree_path: string;
  created_at: number;
  updated_at: number;
  merged_at: number | null;
  abandoned_at: number | null;
  diff_stats: Record<string, unknown>;
}

export interface SandboxRun {
  sandbox_id: string;
  task_id: string;
  project_id: string;
  image: string;
  command: string;
  environment: Record<string, string>;
  status: string;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  created_at: number;
  updated_at: number;
  started_at: number | null;
  completed_at: number | null;
  cost_usd: number;
}

export interface EvalBundle {
  bundle_id: string;
  task_id: string;
  session_id: string;
  project_id: string;
  eval_run_ids: string[];
  baseline_scores: Record<string, number>;
  candidate_scores: Record<string, number>;
  hard_gate_passed: boolean;
  trajectory_quality: number;
  outcome_quality: number;
  eval_coverage_pct: number;
  cost_delta_pct: number;
  latency_delta_pct: number;
  created_at: number;
  updated_at: number;
  notes: string;
}

export interface TraceBookmark {
  bookmark_id: string;
  task_id: string;
  session_id: string;
  project_id: string;
  trace_id: string;
  span_id: string;
  label: string;
  failure_family: string;
  blame_target: string;
  evidence_links: string[];
  promoted_to_eval: boolean;
  created_at: number;
  updated_at: number;
  notes: string;
}

export interface ReleaseCandidate {
  release_id: string;
  task_id: string;
  session_id: string;
  project_id: string;
  version: string;
  artifact_ids: string[];
  eval_bundle_id: string | null;
  status: string;
  deployment_target: string;
  created_at: number;
  updated_at: number;
  approved_at: number | null;
  deployed_at: number | null;
  rolled_back_at: number | null;
  rollback_from_id: string | null;
  changelog: string;
  metadata: Record<string, unknown>;
}

export interface PermissionGrant {
  grant_id: string;
  project_id: string;
  task_id: string | null;
  action: PrivilegedAction;
  scope: ApprovalScope;
  created_at: number;
  updated_at: number;
  expires_at: number | null;
  revoked_at: number | null;
  metadata: Record<string, unknown>;
}

export interface ActionLogEntry {
  log_id: string;
  task_id: string;
  project_id: string;
  action: PrivilegedAction;
  allowed: boolean;
  created_at: number;
  details: Record<string, unknown>;
}

export type BuilderEventType =
  | 'message.delta'
  | 'task.started'
  | 'task.progress'
  | 'plan.ready'
  | 'artifact.updated'
  | 'eval.started'
  | 'eval.completed'
  | 'approval.requested'
  | 'task.completed'
  | 'task.failed'
  | 'execution.started'
  | 'worker.phase_changed'
  | 'execution.completed';

export type WorkerNodePhase =
  | 'pending'
  | 'gathering_context'
  | 'acting'
  | 'verifying'
  | 'completed'
  | 'failed'
  | 'blocked';

export type ExecutionRunStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface WorkerExecutionResult {
  node_id: string;
  worker_role: string;
  phase: WorkerNodePhase;
  context_summary: string;
  outputs: Record<string, unknown>;
  artifacts_produced: string[];
  summary: string;
  error: string | null;
  started_at: number | null;
  completed_at: number | null;
}

export interface CoordinatorExecutionRun {
  run_id: string;
  plan_id: string;
  task_id: string;
  session_id: string;
  project_id: string;
  goal: string;
  status: ExecutionRunStatus;
  worker_states: Record<string, WorkerExecutionResult>;
  synthesis: Record<string, unknown>;
  started_at: number | null;
  completed_at: number | null;
  created_at: number;
  updated_at: number;
}

export interface CoordinatorPlan {
  plan_id: string;
  mode: string;
  root_task_id: string;
  session_id: string;
  project_id: string;
  goal: string;
  tasks: CoordinatorPlanNode[];
  worker_registry: Record<string, unknown>[];
  skill_context: Record<string, unknown>;
  synthesis: Record<string, unknown>;
  created_at: number;
}

export interface CoordinatorPlanNode {
  task_id: string;
  title: string;
  description: string;
  worker_role: string;
  depends_on: string[];
  selected_tools: string[];
  skill_layer: string;
  skill_candidates: string[];
  permission_scope: string[];
  expected_artifacts: string[];
  routing_reason: string;
  status: string;
  provenance: Record<string, unknown>;
  materialized_task_id?: string;
}

export interface BuilderEvent<T = Record<string, unknown>> {
  event_id: string;
  event_type: BuilderEventType;
  session_id: string;
  task_id: string | null;
  payload: T;
  timestamp: number;
}

export interface BuilderMetricsSnapshot {
  project_id: string | null;
  session_count: number;
  task_count: number;
  time_to_first_plan: number;
  acceptance_rate: number;
  revert_rate: number;
  eval_coverage_delta: number;
  unsafe_action_rate: number;
  avg_revisions_per_change: number;
}

export interface SpecialistDefinition {
  role: SpecialistRole;
  display_name: string;
  description: string;
  tools: string[];
  permission_scope: string[];
  context_template: string;
}

// API request payloads
export interface CreateProjectRequest {
  name: string;
  description?: string;
  root_path?: string;
  master_instruction?: string;
}

export interface UpdateProjectRequest {
  name?: string;
  description?: string;
  root_path?: string;
  master_instruction?: string;
  knowledge_files?: string[];
  buildtime_skills?: string[];
  runtime_skills?: string[];
  deployment_targets?: string[];
}

export interface CreateSessionRequest {
  project_id: string;
  title?: string;
  mode?: ExecutionMode;
}

export interface CreateTaskRequest {
  session_id: string;
  project_id: string;
  title: string;
  description: string;
  mode?: ExecutionMode;
}

export interface TaskProgressRequest {
  progress: number;
  current_step: string;
  tool_in_use?: string;
  specialist_message?: string;
}

export interface ProposalRevisionRequest {
  comment: string;
}

export interface ArtifactCommentRequest {
  author?: string;
  body: string;
}

export interface ApprovalResponseRequest {
  approved: boolean;
  responder?: string;
  note?: string;
}

export interface PermissionGrantRequest {
  project_id: string;
  task_id?: string | null;
  action: PrivilegedAction;
  scope: ApprovalScope;
}

export interface SpecialistInvokeRequest {
  task_id: string;
  message: string;
  extra_context?: Record<string, unknown>;
}
