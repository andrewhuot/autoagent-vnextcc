import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

function collectBrowserIssues(page: Page) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: string[] = [];
  const badResponses: string[] = [];

  const ignorable = (entry: string) =>
    entry.includes('/favicon.ico')
    || entry.includes('/ws')
    || entry.includes('WebSocket connection')
    || entry.includes('net::ERR_ABORTED');

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });
  page.on('pageerror', (error) => {
    pageErrors.push(error.message);
  });
  page.on('requestfailed', (request) => {
    requestFailures.push(
      `${request.method()} ${request.url()} :: ${request.failure()?.errorText || 'unknown'}`
    );
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      badResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  return () => {
    expect(pageErrors).toEqual([]);
    expect(consoleErrors.filter((entry) => !ignorable(entry))).toEqual([]);
    expect(requestFailures.filter((entry) => !ignorable(entry))).toEqual([]);
    expect(badResponses.filter((entry) => !ignorable(entry))).toEqual([]);
  };
}

test.describe('Mock Honesty', () => {
  test('dashboard quick fix clearly states preview-only behavior in mock mode', async ({ page }) => {
    await page.route('**/api/quickfix', async (route) => {
      await route.fulfill({
        json: {
          success: true,
          applied: false,
          runbook: 'fix-retrieval-grounding',
          score_before: 0.72,
          score_after: 0.78,
          improvement: 0.06,
          source: 'mock',
          warning: 'Preview only: this quick fix is simulated and does not change the live config yet.',
        },
      });
    });

    const assertHealthy = collectBrowserIssues(page);

    await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'Advanced' }).click();
    await page.getByRole('button', { name: /^Fix$/ }).first().click();
    await page.getByRole('button', { name: /Apply & Optimize/i }).click();

    await expect(page.getByText(/preview only/i)).toBeVisible();
    await expect(
      page.getByText(/Fix applied successfully! Optimization cycle complete\./i)
    ).toHaveCount(0);

    assertHealthy();
  });

  test('legacy assistant route lands on Build with preview-mode guidance', async ({ page }) => {
    const assertHealthy = collectBrowserIssues(page);

    await page.goto(`${BASE_URL}/assistant`, { waitUntil: 'networkidle' });

    await expect(page).toHaveURL(`${BASE_URL}/build?tab=builder-chat`);
    await expect(page.getByText('Preview mode is on')).toBeVisible();
    await expect(page.getByText(/using simulated responses until live providers are ready/i)).toBeVisible();
    await expect(page.getByText(/Live preview is not ready yet/i)).toBeVisible();

    assertHealthy();
  });
});
