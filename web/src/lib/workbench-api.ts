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
    | 'harness.metrics'
    | 'reflection.completed'
    | 'iteration.started'
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
}

export interface WorkbenchRunEvent {
  sequence: number;
  event: string;
  phase: string;
  status: string;
  created_at: string;
  data: Record<string, unknown>;
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
 * POST a brief to the Workbench streaming builder and yield one SSE event
 * per chunk. Callers drive the Zustand store from the event stream and can
 * abort mid-stream via the optional ``signal``.
 */
export async function* streamWorkbenchBuild(
  body: {
    project_id?: string | null;
    brief: string;
    target?: WorkbenchTarget;
    environment?: string;
    mock?: boolean;
    /** Let the service autonomously run corrective iterations. */
    auto_iterate?: boolean;
    /** Hard cap on plan passes per turn (initial + corrections). */
    max_iterations?: number;
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
