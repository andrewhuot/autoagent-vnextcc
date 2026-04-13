/**
 * Deep probe of the golden path. Records detailed friction evidence
 * rather than just checking that labels appear.
 */

import { expect, test, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const OUT_DIR = 'test-results/lawn-garden-deep';
fs.mkdirSync(OUT_DIR, { recursive: true });

const AGENT_BRIEF =
  'Build a friendly chat assistant for Greenleaf, a lawn and garden store. ' +
  "It helps customers choose plants suited to their climate, create lawn-care schedules, " +
  'recommend fertilizers and pest solutions, answer warranty and store-pickup questions, ' +
  "and suggest companion plantings. It is cheerful, concise, and grounded in the store's catalog. " +
  'When a customer asks about something outside lawn, garden, or plant care, it politely redirects.';

type Finding = { step: string; severity: 'low' | 'medium' | 'high' | 'critical'; title: string; details?: string };
const findings: Finding[] = [];
function record(f: Finding) {
  findings.push(f);
  console.log(`[${f.severity.toUpperCase()}] ${f.step} :: ${f.title}${f.details ? ' — ' + f.details : ''}`);
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {});
}

function extractErrors(page: Page) {
  const errs: string[] = [];
  const bad: string[] = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error') errs.push(m.text());
  });
  page.on('response', (r) => {
    if (r.status() >= 500) bad.push(`${r.status()} ${r.url()}`);
    else if (r.status() >= 400 && !r.url().includes('/ws') && !r.url().includes('/@vite/')) bad.push(`${r.status()} ${r.url()}`);
  });
  return {
    get errs() { return errs; },
    get bad() { return bad; },
  };
}

test.describe('Deep golden path probe — Greenleaf lawn & garden agent', () => {
  test.setTimeout(300_000);

  test.afterAll(async () => {
    fs.writeFileSync(path.join(OUT_DIR, 'findings.json'), JSON.stringify(findings, null, 2));
    console.log(`Findings written: ${path.join(OUT_DIR, 'findings.json')}`);
  });

  test('end to end', async ({ page }) => {
    const tracker = extractErrors(page);

    // --- Setup ---
    await page.goto(`${BASE_URL}/setup`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '00-setup');

    const setupBody = (await page.textContent('body')) ?? '';
    const mockBanner = /preview mode is on|mock mode/i.test(setupBody);
    const hasGoogleKey = /google.*key[\s\S]{0,400}(saved|connected|set|configured)/i.test(setupBody);
    const promptsMockExplicit = /mock mode explicitly enabled by optimizer.use_mock/i.test(setupBody);
    if (mockBanner) {
      record({
        step: 'setup',
        severity: 'high',
        title: 'Mock mode is on by default, blocking live agent generation',
        details: promptsMockExplicit
          ? "agentlab.yaml sets optimizer.use_mock: true. User can't easily discover or toggle this from the UI."
          : 'Banner visible but no clear way to turn mock mode off from Setup.',
      });
    }
    if (!hasGoogleKey) {
      record({
        step: 'setup',
        severity: 'medium',
        title: 'Google/Gemini API key state is not clearly reflected in Setup',
        details: 'Env var GOOGLE_API_KEY is set but Setup still prompts to save/connect.',
      });
    }

    // --- Build page: generate agent ---
    await page.goto(`${BASE_URL}/build`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
    await shot(page, '01-build-initial');

    // Look for an XML instruction / prompt mode selector
    const promptTab = page.locator('button, [role="tab"]').filter({ hasText: /^prompt$/i }).first();
    if (await promptTab.count()) await promptTab.click().catch(() => {});

    const ta = page.locator('textarea').first();
    await expect(ta).toBeVisible({ timeout: 10_000 });
    await ta.fill(AGENT_BRIEF);
    await shot(page, '01-build-filled');

    const genBtn = page.locator('button').filter({ hasText: /^generate agent$/i }).first();
    const hasGenerate = await genBtn.count();
    if (!hasGenerate) {
      record({ step: 'build', severity: 'critical', title: 'No "Generate Agent" CTA found on Build page' });
    } else {
      await genBtn.click();
      await page.waitForTimeout(6000);
      await shot(page, '01-build-generated');
    }

    // Look for save/continue actions
    const saveWB = page.locator('button, a').filter({ hasText: /save to workbench|save & continue|save agent|save to library/i }).first();
    if (await saveWB.count()) {
      await shot(page, '01-build-save-visible');
      await saveWB.click().catch(() => {});
      await page.waitForTimeout(4000);
      await shot(page, '01-build-after-save');
    } else {
      record({
        step: 'build',
        severity: 'high',
        title: 'No obvious Save / Save-to-workbench CTA after agent generation',
      });
    }

    // --- Look at the agent state on the Build page ---
    const bodyAfterSave = (await page.textContent('body')) ?? '';
    const activeAgentShown = /active agent|selected agent|Greenleaf|lawn|garden/i.test(bodyAfterSave);
    if (!activeAgentShown) {
      record({
        step: 'build',
        severity: 'high',
        title: 'Generated agent does not show a clear identity / preview after generation',
      });
    }

    // --- Eval runs: check whether a candidate is auto-selected ---
    await page.goto(`${BASE_URL}/evals`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '02-evals');
    const evalsBody = (await page.textContent('body')) ?? '';
    if (/no agent selected|pick an agent from the library/i.test(evalsBody)) {
      record({
        step: 'evals',
        severity: 'high',
        title: 'Evals page shows "no agent selected" even after generating + saving from Build',
        details: 'User expected the generated agent to become the active candidate for Eval.',
      });
    }

    // Try to open any "New Eval Run" or "Set Up Eval Run"
    const setupEvalBtn = page.locator('button, a').filter({ hasText: /set up eval run|new eval run/i }).first();
    if (await setupEvalBtn.count()) {
      await setupEvalBtn.click().catch(() => {});
      await page.waitForTimeout(2000);
      await shot(page, '02-evals-setup-run');
      const dialog = (await page.textContent('body')) ?? '';
      if (/no agent selected|choose.*agent/i.test(dialog)) {
        record({
          step: 'evals',
          severity: 'high',
          title: 'Set Up Eval Run dialog requires agent selection even when current session has one',
        });
      }
    }

    // --- Optimize page: same check ---
    await page.goto(`${BASE_URL}/optimize`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '03-optimize');
    const optBody = (await page.textContent('body')) ?? '';
    if (/select an agent to begin|no agent selected|pick an agent/i.test(optBody)) {
      record({
        step: 'optimize',
        severity: 'high',
        title: 'Optimize page requires user to pick an agent rather than using current context',
      });
    }

    // --- Improvements page ---
    await page.goto(`${BASE_URL}/improvements`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '04-improvements');

    // --- Deploy page ---
    await page.goto(`${BASE_URL}/deploy`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await shot(page, '05-deploy');
    const deployBody = (await page.textContent('body')) ?? '';
    if (/no deploy history|no releases yet|no canary running/i.test(deployBody)) {
      record({
        step: 'deploy',
        severity: 'medium',
        title: 'Deploy page has no history — normal, but flow needs bridge from optimize candidate',
      });
    }

    // Summary: capture last screenshot + request failures
    await shot(page, '99-final');
    if (tracker.errs.length) {
      record({
        step: 'all',
        severity: 'medium',
        title: `Console / page errors observed (${tracker.errs.length})`,
        details: tracker.errs.slice(0, 6).join(' | '),
      });
    }
    if (tracker.bad.length) {
      record({
        step: 'all',
        severity: 'medium',
        title: `HTTP 4xx/5xx responses (${tracker.bad.length})`,
        details: tracker.bad.slice(0, 6).join(' | '),
      });
    }
  });
});
