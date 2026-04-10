import { expect, test } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

test.describe('Setup Frontend-Only Recovery', () => {
  test('shows a calm recovery plan when setup overview is unavailable', async ({ page }) => {
    await page.route('**/api/setup/overview', async (route) => {
      await route.abort('failed');
    });

    await page.goto(`${BASE_URL}/setup`, { waitUntil: 'networkidle' });

    await expect(page.getByText('Frontend-only mode')).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('Setup is waiting for the AgentLab backend')).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByText('You can still draft in Build while the backend reconnects, then return here for live checks and provider setup.')
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry Setup' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Open Build' })).toBeVisible();
    await expect(page.getByText('agentlab server')).toBeVisible();
  });
});
