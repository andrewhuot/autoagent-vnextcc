/**
 * End-to-end golden path test for a Lawn & Garden Store Chat Agent.
 *
 * Mirrors what a new user would actually do:
 *   Build  ->  Workbench  ->  Eval  ->  Optimize / Improve  ->  Deploy
 *
 * Runs against a live backend with a Gemini key so live mode is exercised.
 * Reports findings as console logs + JSON manifest so subagents can fix issues.
 */

import { expect, test, type Page, type ConsoleMessage } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const OUT_DIR = 'test-results/lawn-garden';
const FINDINGS_FILE = path.join(OUT_DIR, 'findings.json');

const AGENT_BRIEF =
  'Build a friendly chat assistant for Greenleaf, a lawn and garden store. ' +
  "It helps customers choose plants suited to their climate, create lawn-care schedules, " +
  'recommend fertilizers and pest solutions, answer warranty and store-pickup questions, ' +
  "and suggest companion plantings. It is cheerful, concise, and grounded in the store's catalog. " +
  'When a customer asks about something outside lawn, garden, or plant care, it politely redirects.';

type Finding = {
  step: string;
  kind: 'gap' | 'bug' | 'friction' | 'success' | 'note';
  severity: 'low' | 'medium' | 'high' | 'critical';
  title: string;
  details?: string;
  evidence?: string;
};

const findings: Finding[] = [];

function record(finding: Finding) {
  findings.push(finding);
  const prefix = `[${finding.kind.toUpperCase()}:${finding.severity}]`;
  console.log(`${prefix} ${finding.step} -> ${finding.title}${finding.details ? ` :: ${finding.details}` : ''}`);
}

fs.mkdirSync(OUT_DIR, { recursive: true });

function trackPageIssues(page: Page, step: string) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: string[] = [];
  const badResponses: string[] = [];

  const ignorable = (entry: string) =>
    entry.includes('/favicon.ico') ||
    entry.includes('WebSocket') ||
    entry.includes('net::ERR_ABORTED') ||
    entry.includes('AbortError') ||
    entry.includes('/@vite/client');

  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('requestfailed', (request) => {
    const failure = request.failure();
    requestFailures.push(`${request.method()} ${request.url()} :: ${failure?.errorText || 'unknown'}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      badResponses.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });

  return {
    report(): Record<string, string[]> {
      return {
        consoleErrors: consoleErrors.filter((e) => !ignorable(e)),
        pageErrors,
        requestFailures: requestFailures.filter((e) => !ignorable(e)),
        badResponses: badResponses.filter((e) => !ignorable(e)),
      };
    },
    commit() {
      const r = this.report();
      for (const msg of r.consoleErrors)
        record({ step, kind: 'bug', severity: 'medium', title: 'Console error', details: msg });
      for (const msg of r.pageErrors)
        record({ step, kind: 'bug', severity: 'high', title: 'Page error', details: msg });
      for (const msg of r.requestFailures)
        record({ step, kind: 'bug', severity: 'high', title: 'Network request failed', details: msg });
      for (const msg of r.badResponses)
        record({ step, kind: 'bug', severity: 'medium', title: 'API returned error status', details: msg });
    },
  };
}

async function shot(page: Page, name: string) {
  const file = path.join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true }).catch(() => {});
}

test.describe('Lawn & Garden Store Agent — Golden Path E2E', () => {
  test.setTimeout(300_000);

  test.afterAll(async () => {
    fs.writeFileSync(FINDINGS_FILE, JSON.stringify(findings, null, 2));
    console.log(`\n======= ${findings.length} findings written to ${FINDINGS_FILE} =======`);
  });

  test('Step 1 — Setup: workspace is ready for live mode', async ({ page }) => {
    const issues = trackPageIssues(page, 'setup');
    await page.goto(`${BASE_URL}/setup`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '01-setup');

    const body = (await page.textContent('body')) ?? '';
    if (/initialization required/i.test(body)) {
      record({
        step: 'setup',
        kind: 'note',
        severity: 'low',
        title: 'Workspace shows Initialization Required',
        details: 'Expected for fresh workspace',
      });
    } else if (/workspace detected/i.test(body) || /workspace ready/i.test(body)) {
      record({
        step: 'setup',
        kind: 'success',
        severity: 'low',
        title: 'Workspace detected',
      });
    } else {
      record({
        step: 'setup',
        kind: 'friction',
        severity: 'medium',
        title: 'Setup page lacks obvious workspace status',
        details: body.substring(0, 200),
      });
    }

    if (/mock mode/i.test(body)) {
      record({
        step: 'setup',
        kind: 'friction',
        severity: 'medium',
        title: 'Setup reports mock mode despite real GOOGLE_API_KEY available',
        details: 'User would expect live mode once keys are present in env.',
      });
    }
    issues.commit();
  });

  test('Step 2 — Build: generate lawn & garden agent from brief', async ({ page }) => {
    const issues = trackPageIssues(page, 'build');
    await page.goto(`${BASE_URL}/build`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
    await shot(page, '02-build-initial');

    const promptTab = page.locator('button, [role="tab"]').filter({ hasText: /^prompt$/i }).first();
    if (await promptTab.count()) await promptTab.click().catch(() => {});

    const textarea = page.locator('textarea').first();
    if (!(await textarea.count())) {
      record({ step: 'build', kind: 'bug', severity: 'critical', title: 'No textarea available on Build page' });
      issues.commit();
      return;
    }
    await textarea.fill(AGENT_BRIEF);
    await shot(page, '02-build-prompt-filled');

    // Capture `generate` button label candidates
    const generateBtn = page
      .locator('button')
      .filter({ hasText: /^generate( agent)?$/i })
      .first();
    if (!(await generateBtn.count())) {
      record({
        step: 'build',
        kind: 'friction',
        severity: 'high',
        title: 'Generate Agent button not found in obvious location',
        details: 'User expected clear call-to-action from the brief examples.',
      });
    } else {
      await generateBtn.click();
      record({ step: 'build', kind: 'note', severity: 'low', title: 'Clicked Generate Agent' });
    }

    // Wait for generation result
    const deadline = Date.now() + 90_000;
    let generated = false;
    while (Date.now() < deadline) {
      await page.waitForTimeout(2000);
      const txt = (await page.textContent('body')) ?? '';
      if (/agent generated/i.test(txt) || /save agent/i.test(txt) || /config preview/i.test(txt)) {
        generated = true;
        break;
      }
      if (/error/i.test(txt) && /generate/i.test(txt)) {
        record({
          step: 'build',
          kind: 'bug',
          severity: 'high',
          title: 'Generate error shown',
          details: txt.slice(0, 400),
        });
        break;
      }
    }

    if (generated) {
      record({ step: 'build', kind: 'success', severity: 'low', title: 'Agent generated within 90s' });
    } else {
      record({
        step: 'build',
        kind: 'bug',
        severity: 'high',
        title: 'Agent generation did not complete in 90s',
      });
    }
    await shot(page, '02-build-generated');

    // Try to save
    const saveBtn = page
      .locator('button')
      .filter({ hasText: /^save( agent| config)?$/i })
      .first();
    if (await saveBtn.count()) {
      await saveBtn.click().catch(() => {});
      await page.waitForTimeout(2500);
      await shot(page, '02-build-saved');
      record({ step: 'build', kind: 'success', severity: 'low', title: 'Clicked save after generation' });
    } else {
      record({
        step: 'build',
        kind: 'friction',
        severity: 'medium',
        title: 'Save button not found after generation',
      });
    }
    issues.commit();
  });

  test('Step 3 — Workbench: inspect candidate build', async ({ page }) => {
    const issues = trackPageIssues(page, 'workbench');
    await page.goto(`${BASE_URL}/workbench`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '03-workbench');

    const body = (await page.textContent('body')) ?? '';
    if (/workbench/i.test(body)) {
      record({ step: 'workbench', kind: 'success', severity: 'low', title: 'Workbench page loaded' });
    } else {
      record({ step: 'workbench', kind: 'bug', severity: 'high', title: 'Workbench heading absent' });
    }

    // Try to start a workbench build from the brief
    const buildBriefTextarea = page.locator('textarea').first();
    if (await buildBriefTextarea.count()) {
      await buildBriefTextarea.fill(AGENT_BRIEF).catch(() => {});
      await shot(page, '03-workbench-brief');
    } else {
      record({
        step: 'workbench',
        kind: 'friction',
        severity: 'medium',
        title: 'No input for brief on Workbench',
      });
    }

    const buildBtn = page
      .locator('button')
      .filter({ hasText: /(build|start|generate|run)/i })
      .first();
    if (await buildBtn.count()) {
      await buildBtn.click().catch(() => {});
      await page.waitForTimeout(5000);
    }

    const planBtn = page.locator('text=/plan|artifact|compatibility|readiness/i').first();
    if (await planBtn.count()) {
      record({ step: 'workbench', kind: 'note', severity: 'low', title: 'Workbench plan/artifact text visible' });
    } else {
      record({
        step: 'workbench',
        kind: 'friction',
        severity: 'medium',
        title: 'Workbench seems empty — no plan/artifacts visible',
      });
    }

    // Save candidate and open eval
    const openEvalBtn = page
      .locator('button, a')
      .filter({ hasText: /(save candidate|open eval|open eval with)/i })
      .first();
    if (await openEvalBtn.count()) {
      await openEvalBtn.click().catch(() => {});
      await page.waitForTimeout(3000);
      record({
        step: 'workbench',
        kind: 'success',
        severity: 'low',
        title: 'Attempted "Open Eval" handoff from workbench',
      });
    } else {
      record({
        step: 'workbench',
        kind: 'friction',
        severity: 'high',
        title: 'No obvious "open eval with candidate" action on workbench',
      });
    }
    await shot(page, '03-workbench-final');
    issues.commit();
  });

  test('Step 4 — Evals: run the test suite against the candidate', async ({ page }) => {
    const issues = trackPageIssues(page, 'evals');
    await page.goto(`${BASE_URL}/evals`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '04-evals-list');

    const body = (await page.textContent('body')) ?? '';
    const hasGenerate = /generate evals/i.test(body);
    const hasNew = /new eval run/i.test(body);
    if (!hasGenerate && !hasNew) {
      record({
        step: 'evals',
        kind: 'bug',
        severity: 'high',
        title: 'Evals page missing expected CTAs (Generate Evals / New Eval Run)',
      });
    } else {
      record({ step: 'evals', kind: 'success', severity: 'low', title: 'Evals page shows expected CTAs' });
    }

    // Try to generate evals first (if no cases yet)
    const genBtn = page.locator('button').filter({ hasText: /^generate evals$/i }).first();
    if (await genBtn.count()) {
      await genBtn.click().catch(() => {});
      await page.waitForTimeout(5000);
      await shot(page, '04-evals-generating');
    }

    // Launch a new eval run
    const newRunBtn = page.locator('button').filter({ hasText: /new eval run/i }).first();
    if (await newRunBtn.count()) {
      await newRunBtn.click().catch(() => {});
      await page.waitForTimeout(1500);
      await shot(page, '04-evals-new-run-dialog');

      const startBtn = page
        .locator('button')
        .filter({ hasText: /^(start|run|launch)( eval| run)?$/i })
        .first();
      if (await startBtn.count()) {
        await startBtn.click().catch(() => {});
        record({ step: 'evals', kind: 'note', severity: 'low', title: 'Eval run started' });
      } else {
        record({
          step: 'evals',
          kind: 'friction',
          severity: 'medium',
          title: 'No obvious Start button in new-eval dialog',
        });
      }
    }

    // Wait up to 60s for any run row to show completed/score
    const evalDeadline = Date.now() + 120_000;
    let gotResult = false;
    while (Date.now() < evalDeadline) {
      await page.waitForTimeout(3000);
      const txt = (await page.textContent('body')) ?? '';
      if (/(score|pass|fail|completed)/i.test(txt)) {
        gotResult = true;
        break;
      }
    }
    if (gotResult) {
      record({ step: 'evals', kind: 'success', severity: 'low', title: 'Eval run produced a score/result' });
    } else {
      record({ step: 'evals', kind: 'bug', severity: 'high', title: 'Eval run never produced a visible result' });
    }
    await shot(page, '04-evals-final');
    issues.commit();
  });

  test('Step 5 — Optimize: launch an optimization cycle', async ({ page }) => {
    const issues = trackPageIssues(page, 'optimize');
    await page.goto(`${BASE_URL}/optimize`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '05-optimize-initial');

    const body = (await page.textContent('body')) ?? '';
    if (!/optimize/i.test(body)) {
      record({ step: 'optimize', kind: 'bug', severity: 'high', title: 'Optimize page failed to render content' });
    }

    const runBtn = page
      .locator('button')
      .filter({ hasText: /^(run|start)( optimization| optimize| cycle)?$/i })
      .first();
    if (await runBtn.count()) {
      await runBtn.click().catch(() => {});
      await page.waitForTimeout(8000);
      await shot(page, '05-optimize-running');
      record({ step: 'optimize', kind: 'note', severity: 'low', title: 'Clicked optimize start' });
    } else {
      record({
        step: 'optimize',
        kind: 'friction',
        severity: 'medium',
        title: 'No obvious Start/Run button on Optimize page',
      });
    }

    // Wait up to 120s for a cycle result / candidate
    const deadline = Date.now() + 120_000;
    let gotResult = false;
    while (Date.now() < deadline) {
      await page.waitForTimeout(3500);
      const txt = (await page.textContent('body')) ?? '';
      if (/candidate|improvement|applied|reviewed|ready to review/i.test(txt)) {
        gotResult = true;
        break;
      }
    }
    if (gotResult) {
      record({ step: 'optimize', kind: 'success', severity: 'low', title: 'Optimize cycle produced candidate/result' });
    } else {
      record({
        step: 'optimize',
        kind: 'bug',
        severity: 'high',
        title: 'Optimize cycle never produced a visible candidate',
      });
    }
    await shot(page, '05-optimize-final');
    issues.commit();
  });

  test('Step 6 — Improvements review', async ({ page }) => {
    const issues = trackPageIssues(page, 'improvements');
    await page.goto(`${BASE_URL}/improvements`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '06-improvements');

    const body = (await page.textContent('body')) ?? '';
    if (!/improvement|review|proposal/i.test(body)) {
      record({
        step: 'improvements',
        kind: 'bug',
        severity: 'medium',
        title: 'Improvements page looks empty or mis-rendered',
      });
    } else {
      record({ step: 'improvements', kind: 'success', severity: 'low', title: 'Improvements page loaded' });
    }

    const acceptBtn = page
      .locator('button')
      .filter({ hasText: /(accept|apply|approve)/i })
      .first();
    if (await acceptBtn.count()) {
      await acceptBtn.click().catch(() => {});
      await page.waitForTimeout(3000);
      record({ step: 'improvements', kind: 'note', severity: 'low', title: 'Clicked accept/apply improvement' });
    } else {
      record({
        step: 'improvements',
        kind: 'friction',
        severity: 'medium',
        title: 'No improvements to accept',
      });
    }
    issues.commit();
  });

  test('Step 7 — Deploy: canary + release', async ({ page }) => {
    const issues = trackPageIssues(page, 'deploy');
    await page.goto(`${BASE_URL}/deploy`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '07-deploy');

    const body = (await page.textContent('body')) ?? '';
    if (!/deploy|canary|release/i.test(body)) {
      record({ step: 'deploy', kind: 'bug', severity: 'high', title: 'Deploy page empty/blank' });
    } else {
      record({ step: 'deploy', kind: 'success', severity: 'low', title: 'Deploy page loaded' });
    }

    // Try to start canary/release
    const canaryBtn = page
      .locator('button')
      .filter({ hasText: /^(canary|release|deploy|promote)( now| release)?$/i })
      .first();
    if (await canaryBtn.count()) {
      await canaryBtn.click().catch(() => {});
      await page.waitForTimeout(4000);
      await shot(page, '07-deploy-clicked');
      record({ step: 'deploy', kind: 'note', severity: 'low', title: 'Clicked deploy/canary' });
    } else {
      record({
        step: 'deploy',
        kind: 'friction',
        severity: 'high',
        title: 'No obvious deploy/canary button',
      });
    }

    // Verify some deployment outcome text appears
    const deadline = Date.now() + 30_000;
    let gotOutcome = false;
    while (Date.now() < deadline) {
      await page.waitForTimeout(2500);
      const txt = (await page.textContent('body')) ?? '';
      if (/released|canary (active|running)|deployed/i.test(txt)) {
        gotOutcome = true;
        break;
      }
    }
    if (gotOutcome) {
      record({ step: 'deploy', kind: 'success', severity: 'low', title: 'Deploy produced visible outcome' });
    } else {
      record({
        step: 'deploy',
        kind: 'friction',
        severity: 'medium',
        title: 'Deploy outcome not visible',
      });
    }
    await shot(page, '07-deploy-final');
    issues.commit();
  });

  test('Step 8 — Nav sanity: every main nav link loads without pageerror', async ({ page }) => {
    const issues = trackPageIssues(page, 'nav');
    const routes = ['/build', '/workbench', '/evals', '/optimize', '/improvements', '/deploy', '/setup', '/configs', '/dashboard'];
    for (const route of routes) {
      await page.goto(`${BASE_URL}${route}`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1200);
      const txt = (await page.textContent('body')) ?? '';
      if (!txt || txt.length < 20) {
        record({
          step: 'nav',
          kind: 'bug',
          severity: 'high',
          title: `Route ${route} rendered empty body`,
        });
      }
    }
    issues.commit();
  });
});
