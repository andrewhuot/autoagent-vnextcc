import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const API_URL = process.env.AGENTLAB_API_URL || 'http://localhost:8000';
const CURRENT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(CURRENT_DIR, '../..');
const SCREENSHOT_DIR = path.resolve(CURRENT_DIR, '../screenshots/live-hotel-agent');
const SUMMARY_PATH = path.resolve(REPO_ROOT, '.tmp/live-hotel-agent-summary.json');
const WORKBENCH_STORE_PATH = path.resolve(
  REPO_ROOT,
  process.env.AGENTLAB_WORKBENCH_STORE_PATH || '.agentlab/workbench_projects.json'
);

const HOTEL_BRIEF = `Build a hotel reservation agent for a luxury hotel group. It must handle room search, rate comparison, booking modification, cancellation policy explanation, loyalty benefits, accessibility requests, payment verification, overbooking recovery, multilingual guest handoff, and safe escalation. It needs tools for availability search, reservation lookup, policy lookup, payment verification, loyalty lookup, and escalation ticket creation. It must never expose payment details or confirm a booking without verified guest identity and explicit guest consent.`;

const FOLLOW_UPS = [
  'Add edge-case handling for overbooked properties and alternate hotel offers.',
  'Tighten identity and payment verification before booking changes or cancellations.',
  'Add eval coverage for accessibility needs, loyalty upgrades, cancellation deadlines, and multilingual escalation.',
];

type JsonRecord = Record<string, unknown>;

interface RunSummary {
  health?: JsonRecord;
  workbench?: {
    projectId?: string;
    initialStatus?: string;
    agentName?: string;
    iterationStatuses: string[];
    provider?: string;
    model?: string;
    mode?: string;
    screenshots: string[];
  };
  eval?: {
    taskId?: string;
    runId?: string;
    mode?: string;
    totalCases?: number;
    passedCases?: number;
    composite?: number;
    warnings?: string[];
  };
  optimize?: {
    taskId?: string;
    status?: string;
    accepted?: boolean;
    pendingReview?: boolean;
    message?: string;
  };
  deploy?: {
    startedCanary?: boolean;
    promotedCanary?: boolean;
    activeVersion?: number | null;
    canaryVersion?: number | null;
  };
  issues: {
    consoleErrors: string[];
    pageErrors: string[];
    requestFailures: string[];
    badResponses: string[];
    flowErrors: string[];
  };
}

function ensureOutputDirs() {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  fs.mkdirSync(path.dirname(SUMMARY_PATH), { recursive: true });
}

function safeJson(value: unknown): JsonRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {};
}

async function readJson(response: { json: () => Promise<unknown> }): Promise<JsonRecord> {
  return safeJson(await response.json());
}

function trackPageIssues(page: Page, summary: RunSummary) {
  const ignorable = (entry: string) =>
    entry.includes('/favicon.ico') ||
    entry.includes('/ws') ||
    entry.includes('WebSocket connection') ||
    entry.includes('net::ERR_ABORTED');

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (!ignorable(text)) summary.issues.consoleErrors.push(text);
    }
  });
  page.on('pageerror', (error) => {
    summary.issues.pageErrors.push(error.message);
  });
  page.on('requestfailed', (request) => {
    const failure = request.failure();
    const text = `${request.method()} ${request.url()} :: ${failure?.errorText || 'unknown'}`;
    if (!ignorable(text)) summary.issues.requestFailures.push(text);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      const text = `${response.status()} ${response.url()}`;
      if (!ignorable(text)) summary.issues.badResponses.push(text);
    }
  });
}

async function screenshot(page: Page, name: string, summary: RunSummary): Promise<void> {
  const filePath = path.join(SCREENSHOT_DIR, `${name}.png`);
  await page.screenshot({ path: filePath, fullPage: true });
  summary.workbench ??= { iterationStatuses: [], screenshots: [] };
  summary.workbench.screenshots.push(filePath);
}

async function poll<T>(
  label: string,
  fn: () => Promise<T>,
  predicate: (value: T) => boolean,
  timeoutMs = 300_000,
  intervalMs = 3_000
): Promise<T> {
  const startedAt = Date.now();
  let latest: T | undefined;
  while (Date.now() - startedAt < timeoutMs) {
    latest = await fn();
    if (predicate(latest)) return latest;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`${label} timed out. Latest: ${JSON.stringify(latest)}`);
}

async function getDefaultWorkbenchProject(request: APIRequestContext): Promise<JsonRecord> {
  const response = await request.get(`${API_URL}/api/workbench/projects/default`);
  expect(response.ok()).toBeTruthy();
  return readJson(response);
}

function projectIdFrom(payload: JsonRecord): string {
  const project = safeJson(payload.project);
  const id = project.project_id;
  if (typeof id !== 'string' || !id) throw new Error('Workbench project id missing');
  return id;
}

function readWorkbenchProject(projectId: string): JsonRecord {
  const raw = fs.readFileSync(WORKBENCH_STORE_PATH, 'utf8');
  const payload = safeJson(JSON.parse(raw));
  const projects = safeJson(payload.projects);
  const project = safeJson(projects[projectId]);
  if (!Object.keys(project).length) {
    throw new Error(`Workbench project ${projectId} was not found in ${WORKBENCH_STORE_PATH}`);
  }
  return project;
}

function latestRunId(project: JsonRecord): string | undefined {
  const activeRunId = project.active_run_id;
  if (typeof activeRunId === 'string' && activeRunId) return activeRunId;
  const runs = safeJson(project.runs);
  return Object.keys(runs).sort().at(-1);
}

function latestRun(project: JsonRecord): JsonRecord {
  const runId = latestRunId(project);
  const runs = safeJson(project.runs);
  return runId ? safeJson(runs[runId]) : {};
}

async function waitForWorkbenchTerminal(projectId: string, previousRunId?: string): Promise<JsonRecord> {
  return poll(
    'Workbench terminal state',
    async () => readWorkbenchProject(projectId),
    (project) => {
      const currentRunId = latestRunId(project);
      const status = String(project.build_status || '');
      const hasExpectedRun = !previousRunId || (currentRunId && currentRunId !== previousRunId);
      return Boolean(hasExpectedRun) && ['completed', 'failed', 'cancelled', 'interrupted', 'error'].includes(status);
    },
    420_000
  );
}

async function submitWorkbenchBrief(page: Page, text: string): Promise<void> {
  await page.getByLabel('Build request').fill(text);
  await page.getByLabel('Send').click();
}

async function runWorkbenchIteration(page: Page, text: string): Promise<void> {
  const controls = page.getByTestId('iteration-controls');
  await expect(controls).toBeVisible({ timeout: 60_000 });
  await controls.getByRole('button', { name: /iterate/i }).click();
  await page.getByLabel('Iteration message').fill(text);
  await page.getByRole('button', { name: /^run$/i }).click();
}

async function waitForTask(request: APIRequestContext, taskId: string, timeoutMs = 300_000): Promise<JsonRecord> {
  return poll(
    `Task ${taskId}`,
    async () => {
      const response = await request.get(`${API_URL}/api/tasks/${encodeURIComponent(taskId)}`);
      expect(response.ok()).toBeTruthy();
      return readJson(response);
    },
    (task) => ['completed', 'failed', 'cancelled', 'error'].includes(String(task.status || '')),
    timeoutMs
  );
}

function taskResult(task: JsonRecord): JsonRecord {
  return safeJson(task.result);
}

async function startEvalFromUi(page: Page): Promise<string> {
  const responsePromise = page.waitForResponse((response) =>
    response.url().includes('/api/eval/run') && response.request().method() === 'POST'
  );
  const runButton = page.getByRole('button', { name: /Run First Eval|Start Eval/i });
  await expect(runButton).toBeVisible({ timeout: 60_000 });
  await runButton.click();
  const response = await responsePromise;
  expect(response.status()).toBe(202);
  const payload = await response.json() as { task_id?: string };
  if (!payload.task_id) throw new Error('Eval task id missing');
  return payload.task_id;
}

async function openEvalFromWorkbench(page: Page): Promise<void> {
  const materializeButton = page.getByRole('button', { name: /Save candidate and open Eval|Open Eval with this candidate/i });
  if (await materializeButton.isVisible().catch(() => false)) {
    await materializeButton.click();
    await expect(page).toHaveURL(/\/evals/, { timeout: 60_000 });
    return;
  }

  const evalLink = page.getByRole('link', { name: /^Run eval$/i });
  await expect(evalLink).toBeVisible({ timeout: 60_000 });
  await evalLink.click();
  await expect(page).toHaveURL(/\/evals/, { timeout: 60_000 });
}

async function startOptimizeFromUi(page: Page): Promise<string> {
  const responsePromise = page.waitForResponse((response) =>
    response.url().includes('/api/optimize/run') && response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: /Advanced settings/i }).click();
  await page.getByLabel('Objective').fill(
    'Improve hotel reservation task success while preserving payment privacy, identity verification, cancellation-policy accuracy, and safe escalation.'
  );
  const approval = page.getByLabel('Require human approval');
  if (!(await approval.isChecked())) {
    await approval.check();
  }
  await page.getByRole('button', { name: 'Start Optimization', exact: true }).last().click();
  const response = await responsePromise;
  expect(response.status()).toBe(202);
  const payload = await response.json() as { task_id?: string };
  if (!payload.task_id) throw new Error('Optimize task id missing');
  return payload.task_id;
}

async function deployLatestCandidate(page: Page, request: APIRequestContext, summary: RunSummary): Promise<void> {
  await page.goto(`${BASE_URL}/deploy?new=1`, { waitUntil: 'networkidle' });
  await screenshot(page, '06-deploy', summary);

  const configsResponse = await request.get(`${API_URL}/api/config/list`);
  expect(configsResponse.ok()).toBeTruthy();
  const configsPayload = await readJson(configsResponse);
  const versions = Array.isArray(configsPayload.versions) ? configsPayload.versions as JsonRecord[] : [];
  const candidate = versions
    .filter((entry) => typeof entry.version === 'number' && String(entry.status || '') !== 'active')
    .sort((a, b) => Number(b.version) - Number(a.version))[0];

  if (!candidate || typeof candidate.version !== 'number') {
    summary.issues.flowErrors.push('No deployable candidate version was available in /api/config/list.');
    return;
  }

  await page.getByLabel('Version').selectOption(String(candidate.version));
  await page.getByLabel('Strategy').selectOption('canary');
  const deployResponsePromise = page.waitForResponse((response) =>
    response.url().includes('/api/deploy') && response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: /^Deploy$/ }).click();
  const deployResponse = await deployResponsePromise;
  summary.deploy = { startedCanary: deployResponse.ok(), promotedCanary: false };

  await page.waitForLoadState('networkidle').catch(() => undefined);
  await page.reload({ waitUntil: 'networkidle' });
  await screenshot(page, '07-deploy-canary', summary);

  const promoteButton = page.getByRole('button', { name: /Promote canary/i });
  if (await promoteButton.isVisible().catch(() => false)) {
    await promoteButton.click();
    await expect(page.getByRole('heading', { name: 'Confirm canary promotion' })).toBeVisible();
    const promoteResponsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/deploy/promote') && response.request().method() === 'POST'
    );
    await page.getByRole('button', { name: 'Confirm canary promotion' }).click();
    const promoteResponse = await promoteResponsePromise;
    summary.deploy.promotedCanary = promoteResponse.ok();
  }

  const statusResponse = await request.get(`${API_URL}/api/deploy/status`);
  if (statusResponse.ok()) {
    const status = await readJson(statusResponse);
    summary.deploy.activeVersion = typeof status.active_version === 'number' ? status.active_version : null;
    summary.deploy.canaryVersion = typeof status.canary_version === 'number' ? status.canary_version : null;
  }
}

test.describe.configure({ mode: 'serial', timeout: 1_200_000 });

test('live hotel reservation agent can move through Workbench, Eval, Optimize, and Deploy', async ({ page, request }) => {
  ensureOutputDirs();
  const summary: RunSummary = {
    issues: {
      consoleErrors: [],
      pageErrors: [],
      requestFailures: [],
      badResponses: [],
      flowErrors: [],
    },
  };
  trackPageIssues(page, summary);

  try {
    const healthResponse = await request.get(`${API_URL}/api/health`);
    expect(healthResponse.ok()).toBeTruthy();
    summary.health = await readJson(healthResponse);
    expect(summary.health.real_provider_configured).toBe(true);

    await page.goto(`${BASE_URL}/workbench`, { waitUntil: 'networkidle' });
    await expect(page.getByLabel('Build request')).toBeVisible({ timeout: 60_000 });
    await screenshot(page, '01-workbench-start', summary);

    await submitWorkbenchBrief(page, HOTEL_BRIEF);
    const initialProject = await getDefaultWorkbenchProject(request);
    const projectId = projectIdFrom(initialProject);
    summary.workbench = { projectId, iterationStatuses: [], screenshots: summary.workbench?.screenshots ?? [] };

    const initialTerminal = await waitForWorkbenchTerminal(projectId);
    summary.workbench.initialStatus = String(initialTerminal.build_status || '');
    const initialRun = latestRun(initialTerminal);
    const model = safeJson(initialTerminal.model);
    const agents = Array.isArray(model.agents) ? model.agents as JsonRecord[] : [];
    const rootAgent = safeJson(agents[0]);
    const agentName = typeof rootAgent.name === 'string' ? rootAgent.name : '';
    const agentRole = typeof rootAgent.role === 'string' ? rootAgent.role : '';
    const agentInstructions = typeof rootAgent.instructions === 'string' ? rootAgent.instructions : '';
    const agentText = `${agentName} ${agentRole} ${agentInstructions}`.toLowerCase();
    summary.workbench.agentName = agentName;
    expect(agentText).toContain('hotel');
    expect(agentText).not.toContain('airline support');
    summary.workbench.provider = typeof initialRun.provider === 'string' ? initialRun.provider : undefined;
    summary.workbench.model = typeof initialRun.model === 'string' ? initialRun.model : undefined;
    summary.workbench.mode = typeof initialRun.mode === 'string' ? initialRun.mode : undefined;
    await screenshot(page, '02-workbench-initial-complete', summary);
    expect(summary.workbench.initialStatus).toBe('completed');

    for (const [index, followUp] of FOLLOW_UPS.entries()) {
      const previousRunId = latestRunId(readWorkbenchProject(projectId));
      await runWorkbenchIteration(page, followUp);
      const terminal = await waitForWorkbenchTerminal(projectId, previousRunId);
      const status = String(terminal.build_status || '');
      summary.workbench.iterationStatuses.push(status);
      await screenshot(page, `03-workbench-iteration-${index + 1}`, summary);
      expect(status).toBe('completed');
    }

    await openEvalFromWorkbench(page);
    await screenshot(page, '04-evals-handoff', summary);

    const evalTaskId = await startEvalFromUi(page);
    const evalTask = await waitForTask(request, evalTaskId, 420_000);
    const evalResult = taskResult(evalTask);
    summary.eval = {
      taskId: evalTaskId,
      runId: typeof evalResult.run_id === 'string' ? evalResult.run_id : evalTaskId,
      mode: typeof evalResult.mode === 'string' ? evalResult.mode : undefined,
      totalCases: typeof evalResult.total_cases === 'number' ? evalResult.total_cases : undefined,
      passedCases: typeof evalResult.passed_cases === 'number' ? evalResult.passed_cases : undefined,
      composite: typeof evalResult.composite === 'number' ? evalResult.composite : undefined,
      warnings: Array.isArray(evalResult.warnings) ? evalResult.warnings.map(String) : [],
    };
    await page.reload({ waitUntil: 'networkidle' });
    await screenshot(page, '05-evals-complete', summary);

    const optimizeLink = page.getByRole('link', { name: /Optimize candidate/i });
    await expect(optimizeLink).toBeVisible({ timeout: 60_000 });
    await optimizeLink.click();
    await expect(page).toHaveURL(/\/optimize/);

    let optimizeTaskId = await startOptimizeFromUi(page);
    let optimizeTask = await waitForTask(request, optimizeTaskId, 420_000);
    let optimizeResult = taskResult(optimizeTask);
    let statusMessage = String(optimizeResult.status_message || '');

    if (statusMessage.toLowerCase().includes('system healthy')) {
      summary.issues.flowErrors.push('Initial optimize run reported system healthy; ran one forced cycle as planned.');
      await page.getByRole('button', { name: /Advanced settings/i }).click();
      const force = page.getByLabel(/Force optimization/i);
      if (!(await force.isChecked())) await force.check();
      optimizeTaskId = await startOptimizeFromUi(page);
      optimizeTask = await waitForTask(request, optimizeTaskId, 420_000);
      optimizeResult = taskResult(optimizeTask);
      statusMessage = String(optimizeResult.status_message || '');
    }

    summary.optimize = {
      taskId: optimizeTaskId,
      status: String(optimizeTask.status || ''),
      accepted: Boolean(optimizeResult.accepted),
      pendingReview: Boolean(optimizeResult.pending_review),
      message: statusMessage,
    };

    await page.reload({ waitUntil: 'networkidle' });
    if (summary.optimize.pendingReview) {
      const approve = page.getByRole('button', { name: 'Approve & Deploy' }).first();
      await expect(approve).toBeVisible({ timeout: 60_000 });
      await approve.click();
    }

    await deployLatestCandidate(page, request, summary);
  } catch (error) {
    summary.issues.flowErrors.push(error instanceof Error ? error.message : String(error));
    throw error;
  } finally {
    fs.writeFileSync(SUMMARY_PATH, `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
  }
});
