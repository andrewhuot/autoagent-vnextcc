/**
 * Full golden-path live test.
 *
 * Goes from a blank Build page all the way through Deploy using the Gemini
 * live key. Captures friction/errors along the way.
 */

import { test, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const OUT_DIR = 'test-results/lawn-garden-live';
fs.mkdirSync(OUT_DIR, { recursive: true });

const BRIEF =
  'Build a Greenleaf lawn-and-garden store chat assistant that helps with plant choice, ' +
  'lawn-care schedules, pest solutions, and companion plantings. Be cheerful and concise.';

type Finding = {
  step: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  kind: 'bug' | 'friction' | 'gap' | 'success' | 'note';
  title: string;
  details?: string;
};
const findings: Finding[] = [];

function record(f: Finding) {
  findings.push(f);
  console.log(`[${f.severity.toUpperCase()}:${f.kind}] ${f.step} :: ${f.title}${f.details ? ' — ' + f.details : ''}`);
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {});
}

test.setTimeout(600_000);

test.afterAll(() => {
  fs.writeFileSync(path.join(OUT_DIR, 'findings.json'), JSON.stringify(findings, null, 2));
  const summary = findings
    .map((f) => `- [${f.severity.toUpperCase()}:${f.kind}] **${f.step}** — ${f.title}${f.details ? `\n  - ${f.details}` : ''}`)
    .join('\n');
  fs.writeFileSync(path.join(OUT_DIR, 'findings.md'), `# Live Golden Path Findings\n\n${summary}\n`);
  console.log(`\n${findings.length} findings written to ${OUT_DIR}\n`);
});

test('Greenleaf lawn-and-garden agent — full live golden path', async ({ page }) => {
  const apiResponses: Array<{ method: string; url: string; status: number }> = [];
  page.on('response', (r) => {
    if (/\/api\//.test(r.url())) apiResponses.push({ method: r.request().method(), url: r.url(), status: r.status() });
  });
  const consoleErrors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('pageerror', (e) => consoleErrors.push(e.message));

  // ── Step 1: Setup ──────────────────────────────────────────────────────
  await page.goto(`${BASE_URL}/setup`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await shot(page, '01-setup');
  const setupBody = (await page.textContent('body')) ?? '';
  const mockOn = /preview mode is on|mock mode/i.test(setupBody);
  if (mockOn) {
    record({ step: 'setup', severity: 'high', kind: 'friction', title: 'Mock mode banner visible even with API keys present' });
  } else {
    record({ step: 'setup', severity: 'low', kind: 'success', title: 'Setup shows live mode (no mock banner)' });
  }

  // ── Step 2: Build ──────────────────────────────────────────────────────
  await page.goto(`${BASE_URL}/build`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  await page.locator('textarea').first().fill(BRIEF);
  await shot(page, '02-build-brief');

  const genStart = Date.now();
  await page.locator('button:has-text("Generate Agent")').first().click();
  await page.locator('button', { hasText: /^(save & run eval|run eval)$/i }).first()
    .waitFor({ state: 'visible', timeout: 120_000 })
    .then(() => record({ step: 'build', severity: 'low', kind: 'success', title: `Agent generated in ${((Date.now()-genStart)/1000).toFixed(1)}s` }))
    .catch(() => record({ step: 'build', severity: 'critical', kind: 'bug', title: 'Generate Agent never produced a Save & Run Eval CTA' }));
  await shot(page, '02-build-after-generate');

  // Observe any agent name / summary
  const buildBodyAfter = (await page.textContent('body')) ?? '';
  if (/Greenleaf|lawn|garden/i.test(buildBodyAfter)) {
    record({ step: 'build', severity: 'low', kind: 'success', title: 'Generated agent references the brief domain (lawn/garden)' });
  } else {
    record({ step: 'build', severity: 'medium', kind: 'bug', title: "Generated agent text doesn't mention lawn/garden domain" });
  }

  // ── Step 3: Save & Run Eval (handoff) ──────────────────────────────────
  await page.locator('button', { hasText: /^save & run eval$/i }).first().click().catch(async () => {
    // Already saved - fall back to Run Eval
    await page.locator('button', { hasText: /^run eval$/i }).first().click();
  });
  await page.waitForTimeout(4000);
  await shot(page, '03-evals-arrived');

  if (!/\/evals/.test(page.url())) {
    record({ step: 'handoff', severity: 'high', kind: 'bug', title: 'Save & Run Eval did not navigate to Evals', details: page.url() });
  } else {
    record({ step: 'handoff', severity: 'low', kind: 'success', title: 'Build -> Eval handoff navigated correctly' });
  }

  // ── Step 4: Ensure an eval set exists; otherwise generate ──────────────
  let evalsBody = (await page.textContent('body')) ?? '';
  if (/no eval sets yet/i.test(evalsBody)) {
    record({ step: 'evals', severity: 'medium', kind: 'friction', title: 'New agent has no eval set — user has to Generate Evals manually' });
    const genEvals = page.locator('button:has-text("Generate Evals")').first();
    if (await genEvals.count()) {
      await genEvals.click();
      await page.waitForTimeout(3000);
      await shot(page, '04-generate-evals-opened');
      // Try to start generation with whatever form is visible
      const startGen = page.locator('button', { hasText: /^(generate|create|start|run)$/i }).first();
      if (await startGen.count()) {
        await startGen.click().catch(() => {});
      }
      await page.waitForTimeout(20_000);
      await shot(page, '04-generate-evals-result');
      evalsBody = (await page.textContent('body')) ?? '';
      if (/no eval sets yet/i.test(evalsBody)) {
        record({ step: 'evals', severity: 'high', kind: 'bug', title: 'Generate Evals ran but no eval set appeared after 20s' });
      } else {
        record({ step: 'evals', severity: 'low', kind: 'success', title: 'Generate Evals produced a set' });
      }
    } else {
      record({ step: 'evals', severity: 'high', kind: 'bug', title: 'No "Generate Evals" button visible on fresh Evals page' });
    }
  }

  // ── Step 5: Run First Eval ─────────────────────────────────────────────
  const runFirstEval = page.locator('button', { hasText: /run first eval|^run eval$/i }).first();
  if (await runFirstEval.count()) {
    await runFirstEval.click();
    record({ step: 'evals', severity: 'low', kind: 'note', title: 'Kicked off run eval' });
  }
  // Wait up to 120s for a run summary
  const evalRunDeadline = Date.now() + 180_000;
  let evalRunComplete = false;
  while (Date.now() < evalRunDeadline) {
    await page.waitForTimeout(5000);
    const txt = (await page.textContent('body')) ?? '';
    if (/composite|passed|score|completed|results/i.test(txt) && /\d/.test(txt)) {
      evalRunComplete = true;
      break;
    }
  }
  await shot(page, '05-evals-after-run');
  if (evalRunComplete) {
    record({ step: 'evals', severity: 'low', kind: 'success', title: 'Eval run finished and shows results' });
  } else {
    record({ step: 'evals', severity: 'high', kind: 'bug', title: 'Eval run never produced visible results within 180s' });
  }

  // ── Step 6: Optimize page ──────────────────────────────────────────────
  await page.goto(`${BASE_URL}/optimize`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  await shot(page, '06-optimize');
  const optBody = (await page.textContent('body')) ?? '';
  if (/select an agent|no agent selected/i.test(optBody)) {
    record({ step: 'optimize', severity: 'high', kind: 'bug', title: 'Optimize page requires manual agent selection (handoff broken)' });
  }
  const startOpt = page.locator('button', { hasText: /start optimization|start optimize|run optimization/i }).first();
  if (await startOpt.count()) {
    await startOpt.click();
    record({ step: 'optimize', severity: 'low', kind: 'note', title: 'Clicked Start Optimization' });
  } else {
    record({ step: 'optimize', severity: 'medium', kind: 'friction', title: 'No obvious "Start Optimization" button' });
  }
  // Wait for a cycle outcome
  const optDeadline = Date.now() + 240_000;
  let optComplete = false;
  while (Date.now() < optDeadline) {
    await page.waitForTimeout(7000);
    const txt = (await page.textContent('body')) ?? '';
    if (/candidate applied|improvement|proposal|cycle complete|ready to review|applied successfully/i.test(txt)) {
      optComplete = true;
      break;
    }
  }
  await shot(page, '06-optimize-result');
  record({
    step: 'optimize',
    severity: optComplete ? 'low' : 'high',
    kind: optComplete ? 'success' : 'bug',
    title: optComplete ? 'Optimize cycle produced a candidate/result' : 'Optimize cycle never produced candidate/result in 240s',
  });

  // ── Step 7: Improvements ───────────────────────────────────────────────
  await page.goto(`${BASE_URL}/improvements`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await shot(page, '07-improvements');
  const impBody = (await page.textContent('body')) ?? '';
  const impCount = (impBody.match(/proposal|change|card/gi) || []).length;
  record({ step: 'improvements', severity: 'low', kind: 'note', title: `Improvements page loaded (${impCount} proposal-ish words)` });
  const accept = page.locator('button', { hasText: /accept|apply|approve/i }).first();
  if (await accept.count()) {
    await accept.click().catch(() => {});
    await page.waitForTimeout(2000);
    record({ step: 'improvements', severity: 'low', kind: 'note', title: 'Attempted to accept an improvement' });
  } else {
    record({ step: 'improvements', severity: 'medium', kind: 'friction', title: 'No accept/apply action on improvements page' });
  }

  // ── Step 8: Deploy ─────────────────────────────────────────────────────
  await page.goto(`${BASE_URL}/deploy`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await shot(page, '08-deploy');
  const deployBody = (await page.textContent('body')) ?? '';
  if (/no deploy|no data yet|no releases/i.test(deployBody)) {
    record({ step: 'deploy', severity: 'medium', kind: 'friction', title: 'Deploy page shows no history' });
  }
  const startCanary = page.locator('button', { hasText: /start canary/i }).first();
  if (await startCanary.count()) {
    await startCanary.click().catch(() => {});
    await page.waitForTimeout(4000);
    await shot(page, '08-deploy-after-canary');
    record({ step: 'deploy', severity: 'low', kind: 'note', title: 'Attempted Start Canary' });
  }
  const deployVer = page.locator('button', { hasText: /deploy version/i }).first();
  if (await deployVer.count()) {
    await deployVer.click().catch(() => {});
    await page.waitForTimeout(4000);
    await shot(page, '08-deploy-after-deploy-version');
    record({ step: 'deploy', severity: 'low', kind: 'note', title: 'Attempted Deploy Version' });
  }

  // ── Summary ────────────────────────────────────────────────────────────
  const failedApi = apiResponses.filter((r) => r.status >= 400 && !r.url().includes('/ws') && !r.url().includes('/@vite/'));
  const uniqueFailures = Array.from(new Set(failedApi.map((r) => `${r.status} ${r.method} ${r.url.split('?')[0]}`)));
  if (uniqueFailures.length) {
    record({ step: 'api', severity: 'medium', kind: 'bug', title: `${uniqueFailures.length} distinct API failures`, details: uniqueFailures.slice(0, 8).join(' | ') });
  }
  if (consoleErrors.length) {
    record({ step: 'console', severity: 'medium', kind: 'bug', title: `${consoleErrors.length} console/page errors`, details: consoleErrors.slice(0, 3).join(' | ') });
  }
});
