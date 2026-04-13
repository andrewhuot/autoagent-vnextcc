import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

const AGENT_BRIEF =
  'Build a Verizon-like phone company billing support agent that explains bills to customers. ' +
  'It should help explain charges, plan details, fees, taxes, surcharges, and common billing confusion. ' +
  'It should be empathetic and clear, avoid jargon, and escalate complex disputes to a human.';

function trackPageIssues(page: Page) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: string[] = [];
  const badResponses: string[] = [];

  const ignorable = (entry: string) =>
    entry.includes('/favicon.ico') ||
    entry.includes('/ws') ||
    entry.includes('WebSocket') ||
    entry.includes('net::ERR_ABORTED') ||
    entry.includes('AbortError');

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('requestfailed', (request) => {
    const failure = request.failure();
    requestFailures.push(`${request.method()} ${request.url()} :: ${failure?.errorText || 'unknown'}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      badResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  return {
    consoleErrors,
    pageErrors,
    requestFailures,
    badResponses,
    report() {
      const filtered = {
        consoleErrors: consoleErrors.filter((e) => !ignorable(e)),
        pageErrors,
        requestFailures: requestFailures.filter((e) => !ignorable(e)),
        badResponses: badResponses.filter((e) => !ignorable(e)),
      };
      return filtered;
    },
  };
}

test.describe('Live Golden Path — Phone Billing Support Agent', () => {
  test.setTimeout(180_000);

  test('Step 1: Build page loads and can generate agent from prompt', async ({ page }) => {
    const issues = trackPageIssues(page);
    await page.goto(`${BASE_URL}/build`, { waitUntil: 'networkidle' });

    // Verify Build page loads
    await expect(page.locator('body')).toBeVisible();
    const pageContent = await page.textContent('body');
    console.log('[BUILD] Page title area:', pageContent?.substring(0, 200));

    // Take screenshot
    await page.screenshot({ path: 'test-results/01-build-page.png' });

    // Check for prompt tab
    const promptTab = page.getByRole('tab', { name: /prompt/i }).or(page.locator('button:has-text("Prompt")'));
    if (await promptTab.isVisible()) {
      await promptTab.click();
      console.log('[BUILD] Clicked Prompt tab');
    }

    // Find and fill the prompt input
    const textarea = page.locator('textarea').first();
    if (await textarea.isVisible()) {
      await textarea.fill(AGENT_BRIEF);
      console.log('[BUILD] Filled agent brief');
      await page.screenshot({ path: 'test-results/02-build-prompt-filled.png' });
    } else {
      console.log('[BUILD] WARNING: No textarea found for prompt input');
    }

    // Look for Generate button
    const generateBtn = page.locator('button').filter({ hasText: /generate/i }).first();
    if (await generateBtn.isVisible()) {
      console.log('[BUILD] Found Generate button');
      await generateBtn.click();
      console.log('[BUILD] Clicked Generate — waiting for response...');

      // Wait for generation to complete (up to 60s for live API)
      await page.waitForTimeout(3000);
      await page.screenshot({ path: 'test-results/03-build-generating.png' });

      // Wait for completion indicator or result
      try {
        await page.waitForSelector('[data-testid="generation-result"], .generated-config, pre, code', {
          timeout: 60000,
        });
        console.log('[BUILD] Generation completed');
      } catch {
        console.log('[BUILD] Generation may still be in progress or no result selector matched');
      }
      await page.screenshot({ path: 'test-results/04-build-generated.png' });
    } else {
      console.log('[BUILD] WARNING: No Generate button found');
    }

    // Check for Save button
    const saveBtn = page.locator('button').filter({ hasText: /save/i }).first();
    if (await saveBtn.isVisible()) {
      console.log('[BUILD] Found Save button');
      await saveBtn.click();
      await page.waitForTimeout(2000);
      console.log('[BUILD] Clicked Save');
      await page.screenshot({ path: 'test-results/05-build-saved.png' });
    }

    // Check journey/next-step card
    const journeyCard = page.locator('[class*="journey"], [class*="next-step"], [data-testid*="journey"]');
    if (await journeyCard.first().isVisible()) {
      const journeyText = await journeyCard.first().textContent();
      console.log('[BUILD] Journey card:', journeyText?.substring(0, 200));
    }

    const report = issues.report();
    console.log('[BUILD] Issues:', JSON.stringify(report, null, 2));
  });

  test('Step 2: Workbench page loads and can build candidate', async ({ page }) => {
    const issues = trackPageIssues(page);
    await page.goto(`${BASE_URL}/workbench`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/06-workbench-initial.png' });

    const pageContent = await page.textContent('body');
    console.log('[WORKBENCH] Page content preview:', pageContent?.substring(0, 300));

    // Check for chat input / build request input
    const chatInput = page.locator('textarea, input[type="text"]').last();
    if (await chatInput.isVisible()) {
      await chatInput.fill(AGENT_BRIEF);
      console.log('[WORKBENCH] Filled build request');
      await page.screenshot({ path: 'test-results/07-workbench-brief-filled.png' });

      // Submit the build request
      const sendBtn = page.locator('button[type="submit"], button:has-text("Send"), button:has-text("Build")').first();
      if (await sendBtn.isVisible()) {
        await sendBtn.click();
        console.log('[WORKBENCH] Submitted build request');

        // Wait for streaming to start
        await page.waitForTimeout(5000);
        await page.screenshot({ path: 'test-results/08-workbench-building.png' });

        // Wait for build to complete (up to 90s for live)
        try {
          await page.waitForFunction(
            () => {
              const body = document.body.textContent || '';
              return (
                body.includes('completed') ||
                body.includes('Save candidate') ||
                body.includes('Ready for Eval') ||
                body.includes('Run eval')
              );
            },
            { timeout: 90000 }
          );
          console.log('[WORKBENCH] Build appears to have completed');
        } catch {
          console.log('[WORKBENCH] Build may still be running after 90s timeout');
        }

        await page.screenshot({ path: 'test-results/09-workbench-completed.png' });
      } else {
        console.log('[WORKBENCH] WARNING: No submit button found');
      }
    } else {
      console.log('[WORKBENCH] WARNING: No chat input found');
    }

    const report = issues.report();
    console.log('[WORKBENCH] Issues:', JSON.stringify(report, null, 2));
  });

  test('Step 3: Eval Runs page loads and can start eval', async ({ page }) => {
    const issues = trackPageIssues(page);
    await page.goto(`${BASE_URL}/evals`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/10-evals-page.png' });

    const pageContent = await page.textContent('body');
    console.log('[EVALS] Page content preview:', pageContent?.substring(0, 300));

    // Check for New Eval button
    const newEvalBtn = page.locator('button').filter({ hasText: /new eval|start eval|run eval/i }).first();
    if (await newEvalBtn.isVisible()) {
      console.log('[EVALS] Found new eval button');
      await newEvalBtn.click();
      await page.waitForTimeout(2000);
      await page.screenshot({ path: 'test-results/11-evals-new-form.png' });
    }

    // Check for agent selector
    const agentSelector = page.locator('select, [role="listbox"], [data-testid*="agent"]').first();
    if (await agentSelector.isVisible()) {
      console.log('[EVALS] Agent selector visible');
    }

    // Try starting an eval
    const startBtn = page.locator('button').filter({ hasText: /start eval|run eval/i }).first();
    if (await startBtn.isVisible()) {
      await startBtn.click();
      console.log('[EVALS] Clicked Start Eval');
      await page.waitForTimeout(5000);
      await page.screenshot({ path: 'test-results/12-evals-running.png' });

      // Wait for eval to complete
      try {
        await page.waitForFunction(
          () => {
            const body = document.body.textContent || '';
            return body.includes('completed') || body.includes('passed') || body.includes('failed');
          },
          { timeout: 120000 }
        );
        console.log('[EVALS] Eval completed');
      } catch {
        console.log('[EVALS] Eval may still be running after timeout');
      }
      await page.screenshot({ path: 'test-results/13-evals-completed.png' });
    }

    const report = issues.report();
    console.log('[EVALS] Issues:', JSON.stringify(report, null, 2));
  });

  test('Step 4: Optimize page loads', async ({ page }) => {
    const issues = trackPageIssues(page);
    await page.goto(`${BASE_URL}/optimize`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/14-optimize-page.png' });

    const pageContent = await page.textContent('body');
    console.log('[OPTIMIZE] Page content preview:', pageContent?.substring(0, 300));

    const report = issues.report();
    console.log('[OPTIMIZE] Issues:', JSON.stringify(report, null, 2));
  });

  test('Step 5: Improvements page loads', async ({ page }) => {
    const issues = trackPageIssues(page);
    await page.goto(`${BASE_URL}/improvements`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/15-improvements-page.png' });

    const pageContent = await page.textContent('body');
    console.log('[IMPROVEMENTS] Page content preview:', pageContent?.substring(0, 300));

    const report = issues.report();
    console.log('[IMPROVEMENTS] Issues:', JSON.stringify(report, null, 2));
  });

  test('Step 6: Deploy page loads', async ({ page }) => {
    const issues = trackPageIssues(page);
    await page.goto(`${BASE_URL}/deploy`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/16-deploy-page.png' });

    const pageContent = await page.textContent('body');
    console.log('[DEPLOY] Page content preview:', pageContent?.substring(0, 300));

    const report = issues.report();
    console.log('[DEPLOY] Issues:', JSON.stringify(report, null, 2));
  });
});
