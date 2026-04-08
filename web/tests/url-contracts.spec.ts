import { expect, test } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

async function mockCommonPaletteApis(page: import('@playwright/test').Page) {
  await page.route('**/api/evals**', async (route) => {
    await route.fulfill({ json: { runs: [] } });
  });
  await page.route('**/api/config**', async (route) => {
    await route.fulfill({ json: { versions: [] } });
  });
  await page.route('**/api/configs**', async (route) => {
    await route.fulfill({ json: { versions: [] } });
  });
  await page.route('**/api/conversations**', async (route) => {
    await route.fulfill({ json: { conversations: [] } });
  });
}

test.describe('Route Contracts', () => {
  test('command palette routes dashboard queries to /dashboard', async ({ page }) => {
    await mockCommonPaletteApis(page);

    await page.goto(`${BASE_URL}/conversations`, { waitUntil: 'networkidle' });
    await page.evaluate(() => {
      window.dispatchEvent(new Event('open-command-palette'));
    });
    await page.getByPlaceholder('Search...').fill('how is my agent doing');
    await page.getByRole('button', { name: /How is my agent doing\?/i }).click();

    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test('conversations honors the outcome query parameter on first render', async ({ page }) => {
    await page.route('**/api/conversations**', async (route) => {
      await route.fulfill({ json: { conversations: [] } });
    });

    await page.goto(`${BASE_URL}/conversations?outcome=fail`, { waitUntil: 'networkidle' });

    await expect(page.getByRole('combobox').first()).toHaveValue('fail');
  });

  test('runbooks honors shortcut query parameters by expanding and applying the requested runbook', async ({ page }) => {
    let applyCalls = 0;

    await page.route('**/api/runbooks', async (route) => {
      await route.fulfill({
        json: {
          runbooks: [
            {
              name: 'tighten-safety-policy',
              description: 'Guardrail updates for safety-sensitive routes.',
              tags: ['safety'],
            },
          ],
        },
      });
    });
    await page.route('**/api/runbooks/tighten-safety-policy', async (route) => {
      await route.fulfill({
        json: {
          runbook: {
            name: 'tighten-safety-policy',
            description: 'Guardrail updates for safety-sensitive routes.',
            tags: ['safety'],
            skills: ['guardrail-audit'],
            policies: ['tighten-safety-policy'],
            tool_contracts: ['refund_tool'],
          },
        },
      });
    });
    await page.route('**/api/runbooks/tighten-safety-policy/apply', async (route) => {
      applyCalls += 1;
      await route.fulfill({ json: { status: 'ok', message: 'Applied' } });
    });

    await page.goto(
      `${BASE_URL}/runbooks?action=apply&runbook=tighten-safety-policy`,
      { waitUntil: 'networkidle' }
    );

    await expect(page.getByText('Skills (1)')).toBeVisible();
    await expect.poll(() => applyCalls).toBe(1);
  });

  test('blame map filters clusters from the query string', async ({ page }) => {
    await page.route('**/api/traces/blame?window=*', async (route) => {
      await route.fulfill({
        json: [
          {
            id: 'routing',
            grader_name: 'Routing grader',
            agent_path: 'router',
            failure_reason: 'routing_error',
            count: 7,
            impact: 0.9,
            trend: 'up',
            traces: [],
          },
          {
            id: 'timeout',
            grader_name: 'Latency grader',
            agent_path: 'tool',
            failure_reason: 'timeout',
            count: 4,
            impact: 0.6,
            trend: 'flat',
            traces: [],
          },
        ],
      });
    });

    await page.goto(`${BASE_URL}/blame?filter=routing_error`, { waitUntil: 'networkidle' });

    await expect(page.getByText('Routing grader')).toBeVisible();
    await expect(page.getByText('Latency grader')).toHaveCount(0);
  });
});
