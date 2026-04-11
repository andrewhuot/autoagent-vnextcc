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
