import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

function trackPageIssues(page: Page) {
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
    const failure = request.failure();
    requestFailures.push(
      `${request.method()} ${request.url()} :: ${failure?.errorText || 'unknown'}`
    );
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      badResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  return {
    assertClean() {
      expect(pageErrors).toEqual([]);
      expect(consoleErrors.filter((entry) => !ignorable(entry))).toEqual([]);
      expect(requestFailures.filter((entry) => !ignorable(entry))).toEqual([]);
      expect(badResponses.filter((entry) => !ignorable(entry))).toEqual([]);
    },
  };
}

test('builder flow clarifies the save-to-eval handoff and downloads config', async ({ page }) => {
  const issues = trackPageIssues(page);

  await page.goto(`${BASE_URL}/builder`, { waitUntil: 'networkidle' });
  await expect(page).toHaveURL(`${BASE_URL}/build?tab=builder-chat`);
  await expect(page.getByRole('heading', { name: 'Builder' }).nth(0)).toBeVisible();

  await page.getByTestId('builder-composer').fill(
    'Build me a customer support agent for an airline that handles booking changes, cancellations, and flight status'
  );
  await page.getByTestId('builder-send').click();

  await expect(page.getByTestId('builder-preview-agent-name')).toContainText('Airline');
  await expect(page.getByTestId('builder-stat-tools')).toHaveText(/\d+ tools/);
  await expect(page.getByTestId('builder-stat-policies')).toHaveText(/\d+ policies/);
  await expect(page.getByTestId('builder-stat-routes')).toHaveText(/\d+ routes/);
  await expect(page.getByRole('button', { name: 'Save & Run Eval' })).toBeVisible();
  await expect(page.getByText('Saves the current draft before opening Eval Runs.')).toBeVisible();

  await page.getByRole('button', { name: 'View Config' }).click();
  const dialog = page.getByRole('dialog', { name: 'Agent Configuration' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId('yaml-preview')).toContainText('routing_rules');

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    dialog.getByRole('button', { name: 'Download Draft' }).click(),
  ]);
  expect(download.suggestedFilename()).toContain('airline');
  expect(download.suggestedFilename()).toMatch(/\.ya?ml$/i);

  await dialog.getByRole('button', { name: 'Close configuration modal' }).click();
  await page.getByRole('button', { name: 'Save & Run Eval' }).click();
  await expect(page).toHaveURL(/\/evals\?agent=.*new=1$/);
  await expect(page.getByRole('heading', { name: 'Start First Evaluation' })).toBeVisible();
  await expect(
    page.getByText(/We carried this saved draft over from Build/i)
  ).toBeVisible();

  issues.assertClean();
});

test('legacy builder routes redirect to builder chat and sidebar nav reaches the shared build page on mobile', async ({
  page,
}) => {
  const issues = trackPageIssues(page);

  await page.goto(`${BASE_URL}/builder`, { waitUntil: 'networkidle' });
  await expect(page).toHaveURL(`${BASE_URL}/build?tab=builder-chat`);
  await expect(page.getByRole('heading', { name: 'Builder' }).nth(0)).toBeVisible();

  await page.goto(`${BASE_URL}/builder/demo`, { waitUntil: 'networkidle' });
  await expect(page).toHaveURL(`${BASE_URL}/build?tab=builder-chat`);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('link', { name: 'Build' }).first().click();
  await expect(page).toHaveURL(`${BASE_URL}/build`);
  await expect(page.getByRole('heading', { name: 'Build' }).nth(0)).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Prompt' })).toHaveAttribute('aria-selected', 'true');

  issues.assertClean();
});
