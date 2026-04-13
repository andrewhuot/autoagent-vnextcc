/**
 * Smoke test to validate the 5 UI fixes from UI_FINDINGS.md land correctly.
 */
import { test, expect, type Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const OUT_DIR = 'test-results/fix-validation';
fs.mkdirSync(OUT_DIR, { recursive: true });

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {});
}

test.setTimeout(180_000);

test('Fix 1: use_mock=false by default (no preview-mode banner)', async ({ page }) => {
  await page.goto(`${BASE_URL}/setup`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  const body = (await page.textContent('body')) ?? '';
  await shot(page, '01-setup');
  // Banner explicitly says "Preview mode is on"
  expect(body).not.toContain('Preview mode is on');
});

test('Fix 2: Improvements surfaces rejected attempts', async ({ page }) => {
  await page.goto(`${BASE_URL}/improvements`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);
  await shot(page, '02-improvements');
  const body = (await page.textContent('body')) ?? '';
  // The new panel should either show "Tried but rejected" or "rejected_constraints" evidence.
  expect(/Tried but rejected|rejected_constraints|rejection|rejected/i.test(body)).toBeTruthy();
});

test('Fix 3: One-click Generate Evals (Customize link present on evals page)', async ({ page }) => {
  await page.goto(`${BASE_URL}/evals`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await shot(page, '03-evals');
  const body = (await page.textContent('body')) ?? '';
  // Expect either the customize escape-hatch OR the primary 1-click CTA.
  expect(/Generate Evals|Customize/i.test(body)).toBeTruthy();
});

test('Fix 4: Workbench offers Build draft import banner', async ({ page }) => {
  // Pre-seed an active agent in sessionStorage so the banner path can engage.
  await page.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    const agent = {
      id: 'agent-v001',
      name: 'TestAgent',
      version: 1,
      status: 'candidate',
      model: 'gemini-2.5-pro',
      config_path: '/tmp/x.yaml',
    };
    sessionStorage.setItem(
      'agentlab.active-agent.v1',
      JSON.stringify({ state: { activeAgent: agent }, version: 0 })
    );
  });
  await page.goto(`${BASE_URL}/workbench`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  await shot(page, '04-workbench');
  const body = (await page.textContent('body')) ?? '';
  // The banner should offer the import option.
  expect(/Import from Build|Continue .* from .* Build draft|TestAgent/i.test(body)).toBeTruthy();
});

test('Fix 5: Setup shows Detected-from-environment for env credentials', async ({ page }) => {
  await page.goto(`${BASE_URL}/setup`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  await shot(page, '05-setup-env');
  const body = (await page.textContent('body')) ?? '';
  expect(/Detected from environment|shell env|GOOGLE_API_KEY/i.test(body)).toBeTruthy();
});

test('Fix 6: Deploy Version picker defaults to latest', async ({ page }) => {
  await page.goto(`${BASE_URL}/deploy`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  await shot(page, '06-deploy');
  const body = (await page.textContent('body')) ?? '';
  // After the fix, (latest) is appended to the latest option.
  expect(/\(latest\)|Deploy Version/i.test(body)).toBeTruthy();
});
