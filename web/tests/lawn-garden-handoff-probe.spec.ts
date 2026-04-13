/**
 * Probe: does the Build -> Eval handoff actually carry the agent forward?
 * We simulate the full journey by clicking "Save & Run Eval" in Build and
 * checking whether Eval Runs comes up with the agent pre-selected.
 */

import { test } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const OUT_DIR = 'test-results/lawn-garden-handoff';
fs.mkdirSync(OUT_DIR, { recursive: true });

const BRIEF =
  'Build a Greenleaf lawn-and-garden store chat assistant that helps with plant choice, ' +
  'lawn-care schedules, pest solutions, and companion plantings. Be cheerful and concise.';

type Finding = { severity: 'low' | 'medium' | 'high' | 'critical'; title: string; details?: string };
const findings: Finding[] = [];
function record(f: Finding) {
  findings.push(f);
  console.log(`[${f.severity.toUpperCase()}] ${f.title}${f.details ? ' :: ' + f.details : ''}`);
}

test.setTimeout(300_000);

test('build -> eval handoff carries the active agent', async ({ page }) => {
  const reqs: Array<{ method: string; url: string; status: number }> = [];
  page.on('response', (r) => {
    if (r.url().startsWith('http://127.0.0.1:8000') || r.url().startsWith('http://localhost:8000')) {
      reqs.push({ method: r.request().method(), url: r.url(), status: r.status() });
    }
  });

  // 1) Go to Build, fill brief, generate
  await page.goto(`${BASE_URL}/build`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);

  const ta = page.locator('textarea').first();
  await ta.fill(BRIEF);

  await page.locator('button:has-text("Generate Agent")').first().click();

  // Wait for "Save & Run Eval" button to appear
  const runEvalBtn = page.locator('button', { hasText: /^(save & run eval|run eval)$/i }).first();
  try {
    await runEvalBtn.waitFor({ state: 'visible', timeout: 60_000 });
    record({ severity: 'low', title: 'Save & Run Eval button appeared after generation' });
  } catch {
    record({ severity: 'critical', title: 'Save & Run Eval button never appeared after generation' });
    await page.screenshot({ path: path.join(OUT_DIR, 'no-save-run-eval.png'), fullPage: true });
    fs.writeFileSync(path.join(OUT_DIR, 'findings.json'), JSON.stringify(findings, null, 2));
    return;
  }

  const btnText = await runEvalBtn.textContent();
  await page.screenshot({ path: path.join(OUT_DIR, '01-build-after-generate.png'), fullPage: true });

  // 2) Click Save & Run Eval
  await runEvalBtn.click();
  await page.waitForTimeout(8000);
  await page.screenshot({ path: path.join(OUT_DIR, '02-after-save-and-run.png'), fullPage: true });

  // Where did we land?
  const url = page.url();
  record({ severity: 'low', title: `Post-click URL: ${url}` });

  // 3) Navigate (or should have navigated) to Eval Runs
  if (!/\/evals/.test(url)) {
    record({
      severity: 'high',
      title: `"${btnText?.trim()}" click did not route to /evals`,
      details: `Landed on ${url}`,
    });
    await page.goto(`${BASE_URL}/evals`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
  }

  const body = (await page.textContent('body')) ?? '';
  await page.screenshot({ path: path.join(OUT_DIR, '03-evals-after-handoff.png'), fullPage: true });

  if (/no agent selected|pick an agent/i.test(body)) {
    record({
      severity: 'high',
      title: 'Evals page still says "no agent selected" after Save & Run Eval handoff',
      details: 'Active agent should be carried forward when user uses guided Build->Eval CTA.',
    });
  } else {
    record({ severity: 'low', title: 'Evals page shows an agent context' });
  }

  // 4) Now continue to /optimize
  await page.goto(`${BASE_URL}/optimize`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const optBody = (await page.textContent('body')) ?? '';
  await page.screenshot({ path: path.join(OUT_DIR, '04-optimize-after-handoff.png'), fullPage: true });
  if (/select an agent to begin|pick an agent/i.test(optBody)) {
    record({
      severity: 'high',
      title: 'Optimize page requires manual agent selection after Build handoff',
    });
  }

  // 5) Check Deploy
  await page.goto(`${BASE_URL}/deploy`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const deployBody = (await page.textContent('body')) ?? '';
  await page.screenshot({ path: path.join(OUT_DIR, '05-deploy-after-handoff.png'), fullPage: true });
  if (/no data yet|no deploy history/i.test(deployBody)) {
    record({ severity: 'medium', title: 'Deploy page shows no history — fresh workspace' });
  }

  // 6) Dump captured API calls summary
  const failed = reqs.filter((r) => r.status >= 400);
  if (failed.length) {
    record({
      severity: 'medium',
      title: `Failed API calls observed: ${failed.length}`,
      details: failed.slice(0, 8).map((r) => `${r.status} ${r.method} ${r.url}`).join(' | '),
    });
  }

  fs.writeFileSync(path.join(OUT_DIR, 'findings.json'), JSON.stringify(findings, null, 2));
  fs.writeFileSync(path.join(OUT_DIR, 'api-calls.json'), JSON.stringify(reqs, null, 2));
});
