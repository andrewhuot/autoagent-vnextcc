import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

const AGENT_BRIEF =
  'Build a Verizon-like phone company billing support agent that explains bills to customers. ' +
  'It should help explain charges, plan details, fees, taxes, surcharges, and common billing confusion. ' +
  'It should be empathetic and clear, avoid jargon, and escalate complex disputes to a human.';

function trackIssues(page: Page) {
  const issues: string[] = [];
  const ignorable = (e: string) =>
    e.includes('/favicon.ico') || e.includes('/ws') || e.includes('WebSocket') || e.includes('AbortError');
  page.on('console', (msg) => { if (msg.type() === 'error' && !ignorable(msg.text())) issues.push(`console: ${msg.text()}`); });
  page.on('pageerror', (e) => issues.push(`pageerror: ${e.message}`));
  page.on('requestfailed', (r) => { if (!ignorable(r.url())) issues.push(`reqfail: ${r.method()} ${r.url()}`); });
  return issues;
}

test.describe('Live Golden Path Deep — Full Flow', () => {
  test.setTimeout(300_000);

  test('Complete flow: Build → Workbench → Eval → Optimize → Improvements → Deploy', async ({ page }) => {
    const issues = trackIssues(page);

    // ============================================================
    // STEP 1: BUILD — Generate and save the billing support agent
    // ============================================================
    console.log('\n=== STEP 1: BUILD ===');
    await page.goto(`${BASE_URL}/build`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/deep-01-build.png' });

    // Click Prompt tab
    const promptTab = page.locator('button').filter({ hasText: 'Prompt' }).first();
    if (await promptTab.isVisible()) await promptTab.click();

    // Fill and generate
    const textarea = page.locator('textarea').first();
    await expect(textarea).toBeVisible({ timeout: 5000 });
    await textarea.fill(AGENT_BRIEF);

    const generateBtn = page.locator('button').filter({ hasText: /generate/i }).first();
    await expect(generateBtn).toBeVisible({ timeout: 5000 });
    await generateBtn.click();
    console.log('[BUILD] Generating agent...');

    // Wait for generation (live API can be slow)
    await page.waitForTimeout(5000);
    await page.screenshot({ path: 'test-results/deep-02-build-generating.png' });

    // Wait for result to appear
    try {
      await page.waitForFunction(() => {
        const body = document.body.textContent || '';
        return body.includes('system_prompt') || body.includes('Save') || body.includes('Generated');
      }, { timeout: 90000 });
      console.log('[BUILD] Generation completed');
    } catch {
      console.log('[BUILD] Generation timeout — checking state...');
    }
    await page.screenshot({ path: 'test-results/deep-03-build-result.png' });

    // Check for generated content
    const bodyText = await page.textContent('body');
    const hasResult = bodyText?.includes('system_prompt') || bodyText?.includes('Agent Details') || bodyText?.includes('model:');
    console.log(`[BUILD] Has generation result: ${hasResult}`);

    // Save the agent
    const saveBtn = page.locator('button').filter({ hasText: /^save/i }).first();
    if (await saveBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await saveBtn.click();
      console.log('[BUILD] Saving agent...');
      await page.waitForTimeout(3000);
      await page.screenshot({ path: 'test-results/deep-04-build-saved.png' });
    } else {
      console.log('[BUILD] No Save button visible — checking alternatives');
      // Try "Save to Agent Library" or similar
      const altSave = page.locator('button').filter({ hasText: /save.*agent|save.*library/i }).first();
      if (await altSave.isVisible({ timeout: 2000 }).catch(() => false)) {
        await altSave.click();
        await page.waitForTimeout(3000);
      }
    }

    // Check journey card
    const journeyText = await page.locator('body').textContent();
    const journeyMatch = journeyText?.match(/Next:?\s*([^.]+)/i);
    console.log(`[BUILD] Journey next step: ${journeyMatch?.[1] || 'not found'}`);

    // Look for "Run eval" link in journey card
    const runEvalLink = page.locator('a[href*="evals"]').first();
    const evalLinkHref = await runEvalLink.getAttribute('href').catch(() => null);
    console.log(`[BUILD] Eval link href: ${evalLinkHref}`);

    // ============================================================
    // STEP 2: WORKBENCH — Inspect the candidate
    // ============================================================
    console.log('\n=== STEP 2: WORKBENCH ===');
    await page.goto(`${BASE_URL}/workbench`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/deep-05-workbench.png' });

    // Document the workbench state
    const wbBody = await page.textContent('body');
    const wbHasProject = wbBody?.includes('Workbench') && (wbBody?.includes('candidate') || wbBody?.includes('Hotel'));
    console.log(`[WORKBENCH] Has existing project: ${wbHasProject}`);

    // Check for chat input and send button
    const chatInput = page.locator('textarea').last();
    const chatInputVisible = await chatInput.isVisible().catch(() => false);
    console.log(`[WORKBENCH] Chat input visible: ${chatInputVisible}`);

    if (chatInputVisible) {
      await chatInput.fill(AGENT_BRIEF);
      // Look for send button (the small icon button)
      const sendBtn = page.locator('button[aria-label="Send"], button[title*="Send"]').first();
      const sendVisible = await sendBtn.isVisible().catch(() => false);
      console.log(`[WORKBENCH] Send button visible: ${sendVisible}`);

      if (sendVisible) {
        const sendDisabled = await sendBtn.isDisabled();
        console.log(`[WORKBENCH] Send button disabled: ${sendDisabled}`);
        if (!sendDisabled) {
          await sendBtn.click();
          console.log('[WORKBENCH] Clicked Send');
          await page.waitForTimeout(5000);
          await page.screenshot({ path: 'test-results/deep-06-workbench-building.png' });

          // Wait for build to complete
          try {
            await page.waitForFunction(() => {
              const body = document.body.textContent || '';
              return body.includes('completed') || body.includes('Save candidate') || body.includes('Ready');
            }, { timeout: 90000 });
            console.log('[WORKBENCH] Build completed');
          } catch {
            console.log('[WORKBENCH] Build still running after 90s');
          }
        }
      } else {
        // Try Enter key submission
        console.log('[WORKBENCH] Trying Enter key submission...');
        await chatInput.press('Enter');
        await page.waitForTimeout(3000);
        await page.screenshot({ path: 'test-results/deep-06-workbench-after-enter.png' });
      }
    }

    // Check for Save candidate / Eval handoff
    const evalHandoff = page.locator('button').filter({ hasText: /save candidate|open eval|run eval/i }).first();
    const evalHandoffVisible = await evalHandoff.isVisible({ timeout: 3000 }).catch(() => false);
    console.log(`[WORKBENCH] Eval handoff button visible: ${evalHandoffVisible}`);
    if (evalHandoffVisible) {
      const evalHandoffText = await evalHandoff.textContent();
      console.log(`[WORKBENCH] Eval handoff button text: ${evalHandoffText}`);
    }
    await page.screenshot({ path: 'test-results/deep-07-workbench-state.png' });

    // ============================================================
    // STEP 3: EVAL RUNS — Select agent and run eval
    // ============================================================
    console.log('\n=== STEP 3: EVAL RUNS ===');

    // First get the agent list to find one to select
    const agentsResponse = await page.request.get('http://localhost:8000/api/agents');
    const agentsData = await agentsResponse.json();
    const agents = agentsData.agents || [];
    console.log(`[EVALS] Available agents: ${agents.length}`);
    agents.slice(0, 3).forEach((a: { name: string; id: string; status: string }) =>
      console.log(`  - ${a.name} (${a.id}, ${a.status})`)
    );

    // Navigate to evals with the latest agent pre-selected
    const latestAgent = agents[0];
    if (latestAgent) {
      await page.goto(`${BASE_URL}/evals?agent=${latestAgent.id}&new=1`, { waitUntil: 'networkidle' });
    } else {
      await page.goto(`${BASE_URL}/evals`, { waitUntil: 'networkidle' });
    }
    await page.screenshot({ path: 'test-results/deep-08-evals.png' });

    // Check if agent is now selected
    const evalBody = await page.textContent('body');
    const agentSelected = evalBody?.includes(latestAgent?.name || 'NONE');
    console.log(`[EVALS] Agent "${latestAgent?.name}" visible on page: ${agentSelected}`);

    // Check Run Eval button state
    const runEvalBtn = page.locator('button').filter({ hasText: /run eval|start eval/i }).first();
    if (await runEvalBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      const disabled = await runEvalBtn.isDisabled();
      console.log(`[EVALS] Run Eval button disabled: ${disabled}`);

      if (!disabled) {
        await runEvalBtn.click();
        console.log('[EVALS] Started eval...');
        await page.waitForTimeout(5000);
        await page.screenshot({ path: 'test-results/deep-09-evals-running.png' });

        // Wait for eval completion
        try {
          await page.waitForFunction(() => {
            const body = document.body.textContent || '';
            return body.includes('completed') || body.includes('passed') || body.includes('%');
          }, { timeout: 120000 });
          console.log('[EVALS] Eval completed');
        } catch {
          console.log('[EVALS] Eval still running after timeout');
        }
        await page.screenshot({ path: 'test-results/deep-10-evals-result.png' });
      } else {
        console.log('[EVALS] ISSUE: Run Eval still disabled even with agent URL param');
        // Try clicking the agent selector to select manually
        const agentSelectorBtn = page.locator('button').filter({ hasText: /select agent|agent/i }).first();
        if (await agentSelectorBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          console.log('[EVALS] Found agent selector button');
        }
      }
    }

    // ============================================================
    // STEP 4: OPTIMIZE
    // ============================================================
    console.log('\n=== STEP 4: OPTIMIZE ===');
    if (latestAgent) {
      await page.goto(`${BASE_URL}/optimize?agent=${latestAgent.id}`, { waitUntil: 'networkidle' });
    } else {
      await page.goto(`${BASE_URL}/optimize`, { waitUntil: 'networkidle' });
    }
    await page.screenshot({ path: 'test-results/deep-11-optimize.png' });

    const optBody = await page.textContent('body');
    const optAgentVisible = optBody?.includes(latestAgent?.name || 'NONE');
    console.log(`[OPTIMIZE] Agent visible: ${optAgentVisible}`);

    // Check for Start Optimize button
    const startOptBtn = page.locator('button').filter({ hasText: /start optim/i }).first();
    if (await startOptBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      const disabled = await startOptBtn.isDisabled();
      console.log(`[OPTIMIZE] Start Optimize disabled: ${disabled}`);
    } else {
      console.log('[OPTIMIZE] No Start Optimize button visible');
    }

    // ============================================================
    // STEP 5: IMPROVEMENTS
    // ============================================================
    console.log('\n=== STEP 5: IMPROVEMENTS ===');
    await page.goto(`${BASE_URL}/improvements`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/deep-12-improvements.png' });

    const impBody = await page.textContent('body');
    const hasTabs = ['Opportunities', 'Experiments', 'Review', 'History'].filter(
      (t) => impBody?.includes(t)
    );
    console.log(`[IMPROVEMENTS] Visible tabs: ${hasTabs.join(', ')}`);

    // ============================================================
    // STEP 6: DEPLOY
    // ============================================================
    console.log('\n=== STEP 6: DEPLOY ===');
    await page.goto(`${BASE_URL}/deploy`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'test-results/deep-13-deploy.png' });

    const depBody = await page.textContent('body');
    const hasVersions = depBody?.includes('Active Version') || depBody?.includes('v7') || depBody?.includes('v9');
    console.log(`[DEPLOY] Has version info: ${hasVersions}`);

    // Check for deploy/promote buttons
    const promoteBtn = page.locator('button').filter({ hasText: /promote/i }).first();
    const deployBtn = page.locator('button').filter({ hasText: /deploy version/i }).first();
    console.log(`[DEPLOY] Promote button visible: ${await promoteBtn.isVisible({ timeout: 2000 }).catch(() => false)}`);
    console.log(`[DEPLOY] Deploy Version button visible: ${await deployBtn.isVisible({ timeout: 2000 }).catch(() => false)}`);

    // ============================================================
    // SUMMARY
    // ============================================================
    console.log('\n=== ISSUE SUMMARY ===');
    console.log(`Total issues captured: ${issues.length}`);
    issues.forEach((i) => console.log(`  - ${i}`));
  });
});
