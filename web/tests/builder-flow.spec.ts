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

test('builder flow updates preview, generates evals, and downloads config', async ({ page }) => {
  const issues = trackPageIssues(page);

  await page.goto(`${BASE_URL}/build`, { waitUntil: 'networkidle' });

  await page.getByTestId('builder-composer').fill(
    'Build me a customer support agent for an airline that handles booking changes, cancellations, and flight status'
  );
  await page.getByTestId('builder-send').click();

  await expect(page.getByTestId('builder-preview-agent-name')).toHaveText(
    'Airline Customer Support Agent'
  );
  await expect(page.getByTestId('builder-stat-routes')).toHaveText('3 routes');
  await expect(page.getByTestId('builder-config-preview')).toContainText('routing_rules');

  await page.getByTestId('builder-composer').fill('Add a tool for checking flight status');
  await page.getByTestId('builder-send').click();

  await expect(page.getByTestId('builder-stat-tools')).toHaveText('1 tools');
  await expect(page.getByTestId('builder-config-preview')).toContainText('flight_status_lookup');

  await page.getByTestId('builder-composer').fill(
    'Add a policy that it should never reveal internal codes'
  );
  await page.getByTestId('builder-send').click();

  await expect(page.getByTestId('builder-stat-policies')).toHaveText('3 policies');
  await expect(page.getByTestId('builder-config-preview')).toContainText('no_internal_codes');

  await page.getByTestId('builder-composer').fill('Make it more empathetic');
  await page.getByTestId('builder-send').click();

  await expect(page.getByTestId('builder-config-preview')).toContainText('empathetic');

  await page.getByTestId('builder-run-eval').click();
  await expect(page.getByTestId('builder-eval-summary')).toHaveText('4 draft evals');

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('builder-download').click(),
  ]);
  expect(download.suggestedFilename()).toBe('airline_customer_support_agent.yaml');

  issues.assertClean();
});

test('legacy builder routes redirect to /build and sidebar nav reaches the page on mobile', async ({
  page,
}) => {
  const issues = trackPageIssues(page);

  await page.goto(`${BASE_URL}/builder`, { waitUntil: 'networkidle' });
  await expect(page).toHaveURL(`${BASE_URL}/build`);

  await page.goto(`${BASE_URL}/builder/demo`, { waitUntil: 'networkidle' });
  await expect(page).toHaveURL(`${BASE_URL}/build`);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('link', { name: 'Builder' }).first().click();
  await expect(page).toHaveURL(`${BASE_URL}/build`);
  await expect(page.getByTestId('builder-page')).toBeVisible();

  issues.assertClean();
});
