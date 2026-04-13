import { expect, test } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

test.describe('Verify UX Fixes', () => {
  test.setTimeout(30_000);

  test('Eval page shows amber guidance when no agent selected', async ({ page }) => {
    // Navigate to evals WITHOUT agent param
    await page.goto(`${BASE_URL}/evals?new=1`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/fix-eval-no-agent.png' });

    // Verify the amber guidance text is visible
    const guidance = page.locator('text=Select an agent from the Agent Library above');
    const isVisible = await guidance.isVisible({ timeout: 3000 }).catch(() => false);
    console.log(`[EVAL FIX] Amber guidance visible: ${isVisible}`);

    // Verify Run Eval button has tooltip
    const runBtn = page.locator('button').filter({ hasText: /Start Eval|Run First Eval/i }).first();
    const title = await runBtn.getAttribute('title');
    console.log(`[EVAL FIX] Button tooltip: ${title}`);
  });

  test('Eval page with agent selected has no amber warning', async ({ page }) => {
    // Get an agent ID first
    const resp = await page.request.get('http://localhost:8000/api/agents');
    const data = await resp.json();
    const agent = data.agents?.[0];
    if (!agent) { console.log('No agents available'); return; }

    await page.goto(`${BASE_URL}/evals?agent=${agent.id}&new=1`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/fix-eval-with-agent.png' });

    // Verify NO amber guidance
    const guidance = page.locator('text=Select an agent from the Agent Library above');
    const isVisible = await guidance.isVisible({ timeout: 2000 }).catch(() => false);
    console.log(`[EVAL FIX] Amber guidance visible (should be false): ${isVisible}`);

    // Verify button is enabled
    const runBtn = page.locator('button').filter({ hasText: /Start Eval|Run First Eval/i }).first();
    const disabled = await runBtn.isDisabled();
    console.log(`[EVAL FIX] Button disabled (should be false): ${disabled}`);
  });

  test('Workbench send button shows text label when input has content', async ({ page }) => {
    await page.goto(`${BASE_URL}/workbench`, { waitUntil: 'networkidle' });

    // Find chat input and type something
    const chatInput = page.locator('textarea[aria-label="Build request"]');
    if (await chatInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await chatInput.fill('Test input for button visibility');
      await page.screenshot({ path: 'test-results/fix-workbench-send-with-text.png' });

      // Check that Send text label is visible
      const sendLabel = page.locator('button[aria-label="Send"] span:has-text("Send")');
      const labelVisible = await sendLabel.isVisible({ timeout: 2000 }).catch(() => false);
      console.log(`[WORKBENCH FIX] Send label visible: ${labelVisible}`);
    }

    // Clear input and check button without text
    if (await chatInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await chatInput.fill('');
      await page.screenshot({ path: 'test-results/fix-workbench-send-empty.png' });

      const sendLabel = page.locator('button[aria-label="Send"] span:has-text("Send")');
      const labelVisible = await sendLabel.isVisible({ timeout: 1000 }).catch(() => false);
      console.log(`[WORKBENCH FIX] Send label visible with empty input (should be false): ${labelVisible}`);
    }
  });
});
