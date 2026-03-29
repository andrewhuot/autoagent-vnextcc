import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

function collectBrowserIssues(page: Page) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: string[] = [];
  const badResponses: string[] = [];

  const ignorable = (entry: string) => entry.includes('/favicon.ico');

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

  test('assistant page advertises preview mode before any action is taken', async ({ page }) => {
    const assertHealthy = collectBrowserIssues(page);

    await page.goto(`${BASE_URL}/assistant`, { waitUntil: 'networkidle' });

    await expect(page.getByText('Preview mode')).toBeVisible();
    await expect(page.getByText(/responses and actions are simulated in this build/i)).toBeVisible();

    assertHealthy();
  });
});
