// ---------------------------------------------------------------------------
// Harness types (Phase 3 — iteration, reflection, metrics)
// ---------------------------------------------------------------------------

export interface HarnessMetrics {
  stepsCompleted: number;
  totalSteps: number;
  tokensUsed: number;
  costUsd: number;
  elapsedMs: number;
  currentPhase: 'planning' | 'executing' | 'reflecting' | 'presenting' | 'idle';
  contextBudget?: {
    totalTokens: number;
    conversationTokens: number;
    planTokens: number;
    artifactTokens: number;
    modelTokens: number;
    conversationCount: number;
    artifactCount: number;
  };
}

export interface IterationEntry {
  id: string;
  iterationNumber: number;
  message: string;
  timestamp: number;
  artifactCount: number;
}

export interface ReflectionEntry {
  id: string;
  taskId: string;
  qualityScore: number;
  suggestions: string[];
  timestamp: number;
}

export interface RunSummary {
  run_id?: string;
  runId?: string;
  status: string;
  phase: string;
  mode: string;
  provider: string;
  model: string;
  duration_ms?: number;
  durationMs?: number;
  tokens_used?: number;
  tokensUsed?: number;
  cost_usd?: number;
  costUsd?: number;
  artifacts_produced?: number;
  artifactsProduced?: number;
  operations_applied?: number;
  operationsApplied?: number;
  validation_status?: string | null;
  validationStatus?: string | null;
  evidence_summary?: WorkbenchTerminalEvidenceSummary | null;
  evidenceSummary?: WorkbenchTerminalEvidenceSummary | null;
  changes: Array<{
    operation: string;
    category: string;
    name: string;
  }>;
  recommended_action?: string;
  recommendedAction?: string;
}

// ---------------------------------------------------------------------------
// Streaming builder types (Phase 1+2)
// ---------------------------------------------------------------------------

export type PlanTaskStatus =
  | 'pending'
  | 'running'
  | 'done'
  | 'skipped'
  | 'error'
  | 'paused';

export interface PlanTask {
  id: string;
  title: string;
  description?: string;
  status: PlanTaskStatus;
  children: PlanTask[];
  artifact_ids: string[];
  log?: string[];
  parent_id: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export type WorkbenchArtifactCategory =
  | 'agent'
  | 'tool'
  | 'callback'
  | 'guardrail'
  | 'eval'
  | 'environment'
  | 'deployment'
  | 'api_call'
  | 'plan'
  | 'note';

/** Skill layer classification for an artifact. */
export type SkillLayer = 'build' | 'runtime' | 'none';

/** Skill context summary included in build events. */
export interface SkillContext {
  build_skills_available: number;
  runtime_skills_available: number;
  build_skills_relevant?: string[];
  runtime_skills_relevant?: string[];
  skill_store_loaded: boolean;
}

export interface WorkbenchArtifact {
  id: string;
  task_id: string;
  category: WorkbenchArtifactCategory | string;
  name: string;
  summary: string;
  preview: string;
  source: string;
  language: string;
  created_at: string;
  version: number;
  /** Turn id this artifact was generated in (multi-turn builds). */
  turn_id?: string;
  /** Iteration id within the turn (autonomous corrections). */
  iteration_id?: string;
  /** Skill layer this artifact belongs to (build, runtime, or none). */
  skill_layer?: SkillLayer;
}

export interface BuildStreamEvent {
  event:
    | 'turn.started'
    | 'turn.completed'
    | 'iteration.started'
    | 'validation.ready'
    | 'plan.ready'
    | 'task.started'
    | 'task.progress'
    | 'message.delta'
    | 'artifact.updated'
    | 'task.completed'
    | 'build.completed'
    | 'reflect.started'
    | 'reflect.completed'
    | 'present.ready'
    | 'run.completed'
    | 'run.failed'
    | 'run.cancel_requested'
    | 'run.cancelled'
    | 'run.recovered'
    | 'harness.metrics'
    | 'reflection.completed'
    | 'harness.heartbeat'
    | 'progress.stall'
    | 'error'
    | string;
  data: Record<string, unknown>;
}

/** One durable message in the Workbench conversation log. */
export interface WorkbenchConversationMessage {
  id: string;
  role: 'user' | 'assistant' | string;
  content: string;
  turn_id?: string | null;
  task_id?: string | null;
  created_at: string;
  kind?: string;
}

/** Compact validation check result surfaced by the autonomous loop. */
export interface WorkbenchValidationCheck {
  name: string;
  passed: boolean;
  detail: string;
}

/** One autonomous iteration inside a turn. */
export interface WorkbenchIterationRecord {
  iteration_id: string;
  index: number;
  mode: 'initial' | 'follow_up' | 'correction' | string;
  brief: string;
  status: 'running' | 'completed' | 'error' | string;
  operations?: unknown[];
  plan?: PlanTask | null;
  created_at: string;
  completed_at?: string;
}

/** One user-facing turn in the multi-turn log. */
export interface WorkbenchTurnRecord {
  turn_id: string;
  brief: string;
  mode: 'initial' | 'follow_up' | 'correction' | string;
  status: 'running' | 'completed' | 'error' | string;
  created_at: string;
  completed_at?: string;
  plan?: PlanTask | null;
  artifact_ids: string[];
  operations?: unknown[];
  iterations: WorkbenchIterationRecord[];
  validation?: {
    run_id?: string;
    status?: string;
    checks?: WorkbenchValidationCheck[];
  } | null;
}

export interface WorkbenchPlanSnapshot {
  project_id: string;
  name: string;
  target: WorkbenchTarget;
  environment: string;
  version: number;
  build_status: 'idle' | 'running' | 'error' | 'done' | string;
  plan: PlanTask | null;
  artifacts: WorkbenchArtifact[];
  messages: WorkbenchMessage[];
  model: WorkbenchCanonicalModel | null;
  exports: WorkbenchExports | null;
  compatibility: WorkbenchCompatibilityDiagnostic[];
  last_test: WorkbenchTestResult | null;
  activity: WorkbenchActivity[];
  active_run: WorkbenchRun | null;
  runs: WorkbenchRun[];
  last_brief?: string;
  conversation?: WorkbenchConversationMessage[];
  turns?: WorkbenchTurnRecord[];
  harness_state?: WorkbenchHarnessState;
  run_summary?: RunSummary | null;
}

export type WorkbenchTarget = 'portable' | 'adk' | 'cx';
export type CompatibilityStatus = 'portable' | 'adk-only' | 'cx-only' | 'invalid';
export type WorkbenchPlanStatus = 'planned' | 'applied';
export type WorkbenchTestStatus = 'passed' | 'failed';

export interface WorkbenchAgent {
  id: string;
  name: string;
  role: string;
  model: string;
  instructions: string;
  sub_agents: string[];
}

export interface WorkbenchTool {
  id: string;
  name: string;
  description: string;
  type: string;
  parameters?: string[];
}

export interface WorkbenchCallback {
  id: string;
  name: string;
  hook: string;
  description?: string;
}

export interface WorkbenchGuardrail {
  id: string;
  name: string;
  rule: string;
}

export interface WorkbenchEvalCase {
  id: string;
  input: string;
  expected?: string;
}

export interface WorkbenchEvalSuite {
  id: string;
  name: string;
  cases: WorkbenchEvalCase[];
}

export interface WorkbenchEnvironment {
  id: string;
  name: string;
  target: WorkbenchTarget | string;
}

export interface WorkbenchDeployment {
  id: string;
  environment: string;
  status: string;
  version: number;
}

export interface WorkbenchCanonicalModel {
  project: {
    name: string;
    description: string;
  };
  agents: WorkbenchAgent[];
  tools: WorkbenchTool[];
  callbacks: WorkbenchCallback[];
  guardrails: WorkbenchGuardrail[];
  eval_suites: WorkbenchEvalSuite[];
  environments: WorkbenchEnvironment[];
  deployments: WorkbenchDeployment[];
}

export interface WorkbenchCompatibilityDiagnostic {
  object_id: string;
  label: string;
  target: WorkbenchTarget | string;
  status: CompatibilityStatus;
  reason: string;
}

export interface WorkbenchExportPreview {
  target: string;
  label?: string;
  files: Record<string, string>;
}

export interface WorkbenchExports {
  generated_config: Record<string, unknown>;
  adk: WorkbenchExportPreview;
  cx: WorkbenchExportPreview;
}

export interface WorkbenchTestCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface WorkbenchTestResult {
  run_id: string;
  status: WorkbenchTestStatus;
  created_at: string;
  checks: WorkbenchTestCheck[];
  trace: Array<{ event: string; status: string }>;
}

export interface WorkbenchVersion {
  version: number;
  created_at: string;
  summary: string;
}

export interface WorkbenchActivity {
  id: string;
  kind: string;
  created_at: string;
  summary: string;
  diff: Array<{ field: string; before: unknown; after: unknown }>;
}

export interface WorkbenchMessage {
  id: string;
  run_id?: string;
  role: 'user' | 'assistant';
  task_id: string | null;
  text: string;
  created_at: string;
  updated_at?: string;
}

export interface WorkbenchPresentation {
  run_id: string;
  version: number;
  summary: string;
  artifact_ids: string[];
  active_artifact_id: string | null;
  generated_outputs: string[];
  validation_status: WorkbenchTestStatus | string | null;
  next_actions: string[];
  review_gate?: WorkbenchReviewGate;
  handoff?: WorkbenchHandoff;
  improvement_bridge?: WorkbenchImprovementBridge;
}

export interface WorkbenchReviewGateCheck {
  name: string;
  status: 'passed' | 'failed' | 'required' | string;
  required: boolean;
  detail: string;
}

export interface WorkbenchReviewGate {
  status: 'review_required' | 'blocked' | string;
  promotion_status: 'draft' | 'reviewed' | 'candidate' | 'staging' | 'production' | string;
  requires_human_review: boolean;
  checks: WorkbenchReviewGateCheck[];
  blocking_reasons: string[];
}

export interface WorkbenchTerminalEvidenceSummary {
  structural_status?: string;
  validation_status?: string;
  improvement_status?: string;
  correction_status?: string;
  evidence_level?: string;
  operations_applied?: number;
  artifacts_observed?: number;
  task_completions?: number;
  stall_count?: number;
  review_required?: boolean;
}

export interface WorkbenchHandoff {
  project_id: string;
  run_id: string;
  turn_id?: string | null;
  version: number;
  review_gate_status: string;
  evidence_level?: string | null;
  improvement_status?: string | null;
  active_artifact_id?: string | null;
  last_event_sequence: number;
  next_operator_action: string;
  resume_prompt: string;
}

export interface WorkbenchRunEvent {
  sequence: number;
  event: string;
  phase: string;
  status: string;
  created_at: string;
  data: Record<string, unknown>;
  telemetry?: WorkbenchTelemetrySummary;
}

export interface WorkbenchBudget {
  limits: {
    max_iterations?: number | null;
    max_seconds?: number | null;
    max_tokens?: number | null;
    max_cost_usd?: number | null;
  };
  usage: {
    iterations?: number;
    elapsed_ms?: number;
    tokens?: number;
    tokens_used?: number;
    cost_usd?: number;
  };
  breach?: {
    kind?: string;
    limit?: number;
    actual?: number;
    exceeded?: string;
    message?: string;
  } | null;
  exceeded?: string;
  message?: string;
}

export interface WorkbenchTelemetrySummary {
  run_id?: string;
  turn_id?: string | null;
  iteration_id?: string | null;
  event?: string;
  phase?: string;
  status?: string;
  provider?: string;
  model?: string;
  execution_mode?: string;
  duration_ms?: number;
  tokens_used?: number;
  cost_usd?: number;
  event_count?: number;
  failure_reason?: string | null;
  cancel_reason?: string | null;
  budget_breach?: Record<string, unknown> | null;
}

export interface WorkbenchRunHandoff {
  project_id?: string;
  run_id: string;
  turn_id?: string | null;
  iteration_id?: string | null;
  phase?: string;
  status?: string;
  updated_at?: string;
  last_event: {
    sequence?: number;
    event?: string;
    phase?: string;
    status?: string;
    created_at?: string;
  } | null;
  progress: {
    total_tasks: number;
    completed_tasks: number;
    running_tasks?: number;
    blocked_tasks?: number;
    current_task?: {
      task_id?: string;
      title?: string;
      status?: string;
    } | null;
  };
  metrics?: Record<string, unknown> | null;
  verification: {
    status: string;
    passed_checks?: number;
    total_checks?: number;
    blocking?: boolean;
  };
  evidence?: WorkbenchTerminalEvidenceSummary | null;
  latest_artifact?: {
    artifact_id?: string;
    task_id?: string;
    name?: string;
    category?: string;
    summary?: string;
  } | null;
  recent_checkpoints?: Record<string, unknown>[];
  budget?: {
    usage?: Record<string, unknown>;
    breach?: Record<string, unknown> | null;
  };
  failure_reason?: string | null;
  cancel_reason?: string | null;
  recovery?: Record<string, unknown> | null;
  next_action: string;
  improvement_bridge?: WorkbenchImprovementBridge;
}

export interface WorkbenchBridgeEvalRequest {
  config_path?: string | null;
  category?: string | null;
  dataset_path?: string | null;
  generated_suite_id?: string | null;
  split: 'train' | 'test' | 'all' | string;
}

export interface WorkbenchBridgeOptimizeRequest {
  window: number;
  force: boolean;
  require_human_approval: boolean;
  require_eval_evidence?: boolean;
  config_path?: string | null;
  eval_run_id?: string | null;
  mode: 'standard' | 'advanced' | 'research' | string;
  objective: string;
  guardrails: string[];
  research_algorithm: string;
  budget_cycles: number;
  budget_dollars: number;
}

export interface WorkbenchBridgeCandidate {
  project_id: string;
  run_id: string;
  turn_id?: string | null;
  version: number;
  target: WorkbenchTarget | string;
  environment: string;
  agent_name?: string;
  validation_status: string;
  review_gate_status: string;
  active_artifact_id?: string | null;
  generated_config_hash: string;
  config_path?: string | null;
  eval_cases_path?: string | null;
  export_targets: string[];
}

export interface WorkbenchBridgeEvaluationStep {
  status: 'ready' | 'blocked' | 'needs_saved_config' | string;
  readiness_state?: string;
  label?: string;
  description?: string;
  primary_action_label?: string | null;
  primary_action_target?: string | null;
  prerequisite_step?: string | null;
  request?: WorkbenchBridgeEvalRequest | null;
  start_endpoint: string;
  blocking_reasons: string[];
}

export interface WorkbenchBridgeOptimizationStep {
  status: 'ready' | 'blocked' | 'awaiting_eval_run' | string;
  readiness_state?: string;
  label?: string;
  description?: string;
  primary_action_label?: string | null;
  primary_action_target?: string | null;
  prerequisite_step?: string | null;
  requires_eval_run: boolean;
  request_template?: WorkbenchBridgeOptimizeRequest | null;
  start_endpoint: string;
  blocking_reasons: string[];
}

export interface WorkbenchImprovementBridge {
  kind: 'workbench_eval_optimize' | string;
  schema_version: number;
  candidate: WorkbenchBridgeCandidate;
  evaluation: WorkbenchBridgeEvaluationStep;
  optimization: WorkbenchBridgeOptimizationStep;
  review_gate?: WorkbenchReviewGate | Record<string, unknown>;
  validation?: WorkbenchTestResult | Record<string, unknown>;
  created_from?: string;
}

export interface WorkbenchEvalBridgeResponse {
  bridge: WorkbenchImprovementBridge;
  save_result: {
    config_path: string;
    eval_cases_path?: string | null;
    [key: string]: unknown;
  };
  eval_request?: WorkbenchBridgeEvalRequest | null;
  optimize_request_template?: WorkbenchBridgeOptimizeRequest | null;
  next?: {
    start_eval_endpoint?: string;
    start_optimize_endpoint?: string;
    optimize_requires_eval_run?: boolean;
  };
}

export interface WorkbenchHarnessState {
  checkpoint_count: number;
  recent_checkpoints?: Record<string, unknown>[];
  last_metrics?: {
    steps_completed?: number;
    total_steps?: number;
    tokens_used?: number;
    cost_usd?: number;
    elapsed_ms?: number;
    elapsed_seconds?: number;
    current_phase?: HarnessMetrics['currentPhase'] | string;
  } | null;
  latest_handoff?: WorkbenchRunHandoff | null;
}

export interface WorkbenchRun {
  run_id: string;
  project_id?: string;
  brief: string;
  target: WorkbenchTarget | string;
  environment: string;
  status: string;
  phase: string;
  started_version: number;
  completed_version: number | null;
  created_at: string;
  updated_at?: string;
  completed_at: string | null;
  error: string | null;
  execution_mode?: string;
  provider?: string;
  model?: string;
  mode_reason?: string;
  require_live?: boolean;
  budget?: WorkbenchBudget;
  telemetry_summary?: WorkbenchTelemetrySummary;
  summary?: RunSummary | null;
  evidence_summary?: WorkbenchTerminalEvidenceSummary | null;
  failure_reason?: string | null;
  cancel_reason?: string | null;
  review_gate?: WorkbenchReviewGate | null;
  handoff?: WorkbenchRunHandoff | null;
  events: WorkbenchRunEvent[];
  messages: WorkbenchMessage[];
  validation: WorkbenchTestResult | null;
  presentation: WorkbenchPresentation | null;
}

export interface WorkbenchProject {
  project_id: string;
  name: string;
  target: WorkbenchTarget;
  environment: string;
  version: number;
  draft_badge: string;
  model: WorkbenchCanonicalModel;
  compatibility: WorkbenchCompatibilityDiagnostic[];
  exports: WorkbenchExports;
  last_test: WorkbenchTestResult | null;
  artifacts?: WorkbenchArtifact[];
  messages?: WorkbenchMessage[];
  runs?: Record<string, WorkbenchRun> | WorkbenchRun[];
  active_run_id?: string | null;
  active_run?: WorkbenchRun | null;
  build_status?: string;
  versions: WorkbenchVersion[];
  activity: WorkbenchActivity[];
  rolled_back_from_version?: number;
  rolled_back_to_version?: number;
}

export interface WorkbenchOperation {
  operation: string;
  target: string;
  label: string;
  compatibility_status: CompatibilityStatus;
}

export interface WorkbenchPlan {
  plan_id: string;
  status: WorkbenchPlanStatus;
  mode: 'plan' | 'apply' | 'ask';
  target: WorkbenchTarget;
  summary: string;
  requires_approval: boolean;
  operations: WorkbenchOperation[];
  created_at: string;
  test_after_apply: boolean;
  source_version: number;
  applied_version?: number;
}

export interface WorkbenchPayload {
  project: WorkbenchProject;
  plan?: WorkbenchPlan;
  exports?: WorkbenchExports;
  activity?: WorkbenchActivity[];
}

export class WorkbenchApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'WorkbenchApiError';
    this.status = status;
  }
}

async function fetchWorkbench<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    let message = `Workbench request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (payload && typeof payload === 'object' && typeof payload.detail === 'string') {
        message = payload.detail;
      }
    } catch {
      const text = await response.text().catch(() => '');
      if (text.trim()) {
        message = text.trim();
      }
    }
    throw new WorkbenchApiError(message, response.status);
  }

  return response.json() as Promise<T>;
}

export function getDefaultWorkbenchProject(): Promise<WorkbenchPayload> {
  return fetchWorkbench('/api/workbench/projects/default');
}

export function planWorkbenchChange(body: {
  project_id: string;
  message: string;
  target?: WorkbenchTarget;
  mode?: 'plan' | 'apply' | 'ask';
}): Promise<WorkbenchPayload> {
  return fetchWorkbench('/api/workbench/plan', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function applyWorkbenchPlan(body: {
  project_id: string;
  plan_id: string;
}): Promise<WorkbenchPayload> {
  return fetchWorkbench('/api/workbench/apply', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function testWorkbenchProject(body: {
  project_id: string;
  message?: string;
}): Promise<WorkbenchPayload> {
  return fetchWorkbench('/api/workbench/test', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function rollbackWorkbenchProject(body: {
  project_id: string;
  version: number;
}): Promise<WorkbenchPayload> {
  return fetchWorkbench('/api/workbench/rollback', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * Fetch the current plan + artifacts snapshot for a project.
 *
 * Used to hydrate the Workbench UI on page reload so an in-flight or
 * completed build survives a refresh.
 */
export function getWorkbenchPlanSnapshot(projectId: string): Promise<WorkbenchPlanSnapshot> {
  return fetchWorkbench(`/api/workbench/projects/${encodeURIComponent(projectId)}/plan`);
}

/**
 * Request server-side cancellation for an active Workbench run.
 *
 * The project id is optional because operator logs often surface only run ids.
 */
export function cancelWorkbenchRun(
  runId: string,
  reason = 'Cancelled by operator.',
  projectId?: string | null
): Promise<{
  project_id: string;
  run_id: string;
  status: string;
  run?: WorkbenchRun;
  cancel_reason?: string;
}> {
  return fetchWorkbench(`/api/workbench/runs/${encodeURIComponent(runId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({
      ...(projectId ? { project_id: projectId } : {}),
      reason,
    }),
  });
}

/** Materialize a Workbench candidate and return its typed Eval handoff. */
export function createWorkbenchEvalBridge(
  projectId: string,
  body: {
    category?: string | null;
    dataset_path?: string | null;
    generated_suite_id?: string | null;
    split?: string;
  } = {}
): Promise<WorkbenchEvalBridgeResponse> {
  return fetchWorkbench(`/api/workbench/projects/${encodeURIComponent(projectId)}/bridge/eval`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * POST a brief to the Workbench streaming builder and yield one SSE event
 * per chunk. Callers drive the Zustand store from the event stream and can
 * abort mid-stream via the optional ``signal``.
 */
export async function* streamWorkbenchBuild(
  body: {
    project_id?: string | null;
    brief: string;
    config_path?: string | null;
    target?: WorkbenchTarget;
    environment?: string;
    mock?: boolean;
    require_live?: boolean;
    /** Let the service autonomously run corrective iterations. */
    auto_iterate?: boolean;
    /** Hard cap on plan passes per turn (initial + corrections). */
    max_iterations?: number;
    max_seconds?: number;
    max_tokens?: number;
    max_cost_usd?: number;
  },
  options: { signal?: AbortSignal } = {}
): AsyncIterable<BuildStreamEvent> {
  const response = await fetch('/api/workbench/build/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!response.ok) {
    let message = `Workbench stream failed (${response.status})`;
    try {
      const payload = await response.json();
      if (payload && typeof payload === 'object' && typeof payload.detail === 'string') {
        message = payload.detail;
      }
    } catch {
      const text = await response.text().catch(() => '');
      if (text.trim()) message = text.trim();
    }
    throw new WorkbenchApiError(message, response.status);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new WorkbenchApiError('Workbench stream has no body', 500);
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let separatorIndex = buffer.indexOf('\n\n');
    while (separatorIndex !== -1) {
      const rawFrame = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      const parsed = parseSseFrame(rawFrame);
      if (parsed) yield parsed;
      separatorIndex = buffer.indexOf('\n\n');
    }
  }

  // Flush a trailing frame if the server closed without a final blank line.
  const tail = buffer.trim();
  if (tail) {
    const parsed = parseSseFrame(tail);
    if (parsed) yield parsed;
  }
}

/**
 * POST a follow-up message to an existing build and yield SSE events.
 * Hits /api/workbench/build/iterate which continues from the current
 * canonical model rather than starting fresh.
 */
export async function* iterateWorkbenchBuild(
  body: {
    project_id: string;
    message: string;
    target?: WorkbenchTarget;
    environment?: string;
    require_live?: boolean;
    max_iterations?: number;
    max_seconds?: number;
    max_tokens?: number;
    max_cost_usd?: number;
  },
  options: { signal?: AbortSignal } = {}
): AsyncIterable<BuildStreamEvent> {
  const response = await fetch('/api/workbench/build/iterate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      project_id: body.project_id,
      follow_up: body.message,
      target: body.target,
      environment: body.environment,
      require_live: body.require_live,
      max_iterations: body.max_iterations,
      max_seconds: body.max_seconds,
      max_tokens: body.max_tokens,
      max_cost_usd: body.max_cost_usd,
    }),
    signal: options.signal,
  });

  if (!response.ok) {
    let message = `Workbench iterate failed (${response.status})`;
    try {
      const payload = await response.json();
      if (payload && typeof payload === 'object' && typeof payload.detail === 'string') {
        message = payload.detail;
      }
    } catch {
      const text = await response.text().catch(() => '');
      if (text.trim()) message = text.trim();
    }
    throw new WorkbenchApiError(message, response.status);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new WorkbenchApiError('Iterate stream has no body', 500);
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separatorIndex = buffer.indexOf('\n\n');
    while (separatorIndex !== -1) {
      const rawFrame = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      const parsed = parseSseFrame(rawFrame);
      if (parsed) yield parsed;
      separatorIndex = buffer.indexOf('\n\n');
    }
  }

  const tail = buffer.trim();
  if (tail) {
    const parsed = parseSseFrame(tail);
    if (parsed) yield parsed;
  }
}

function parseSseFrame(frame: string): BuildStreamEvent | null {
  let eventName = 'message';
  const dataLines: string[] = [];
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.trimEnd();
    if (!line) continue;
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (dataLines.length === 0) return null;
  try {
    const data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>;
    return { event: eventName, data };
  } catch {
    return { event: eventName, data: { raw: dataLines.join('\n') } };
  }
}
