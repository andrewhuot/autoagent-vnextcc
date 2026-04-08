import { test, expect } from '@playwright/test';

const BASE_URL = 'http://localhost:5173';

const pages = [
  { name: 'Dashboard', path: '/dashboard' },
  { name: 'EvalRuns', path: '/evals' },
  { name: 'Optimize', path: '/optimize' },
  { name: 'Configs', path: '/configs' },
  { name: 'Conversations', path: '/conversations' },
  { name: 'Deploy', path: '/deploy' },
  { name: 'LoopMonitor', path: '/loop' },
  { name: 'Settings', path: '/settings' },
];

test.describe('Visual QA - All Pages', () => {
  for (const { name, path } of pages) {
    test(`Screenshot: ${name}`, async ({ page }) => {
      await page.goto(`${BASE_URL}${path}`, { waitUntil: 'networkidle' });
      // Wait for any animations to settle
      await page.waitForTimeout(500);
      await page.screenshot({
        path: `screenshots/${name}.png`,
        fullPage: true,
      });
    });
  }
});

test.describe('Visual QA - Special States', () => {
  test('CommandPalette open', async ({ page }) => {
    await page.goto(BASE_URL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    // Trigger Cmd+K
    await page.keyboard.press('Meta+k');
    await page.waitForTimeout(300);
    await page.screenshot({
      path: 'screenshots/CommandPalette.png',
      fullPage: true,
    });
  });

  test('EvalDetail page', async ({ page }) => {
    // Navigate to eval runs first, then try to click into a detail
    await page.goto(`${BASE_URL}/evals`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    // Try clicking the first eval link if one exists
    const firstLink = page.locator('a[href^="/evals/"]').first();
    if (await firstLink.isVisible({ timeout: 2000 }).catch(() => false)) {
      await firstLink.click();
      await page.waitForTimeout(500);
      await page.screenshot({
        path: 'screenshots/EvalDetail.png',
        fullPage: true,
      });
    } else {
      // Screenshot the empty state of eval runs instead
      await page.screenshot({
        path: 'screenshots/EvalDetail-empty.png',
        fullPage: true,
      });
    }
  });

  test('Mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await page.screenshot({
      path: 'screenshots/Mobile-Dashboard.png',
      fullPage: true,
    });

    // Open mobile sidebar
    const menuButton = page.locator('button[aria-label="Open navigation"]');
    if (await menuButton.isVisible({ timeout: 1000 }).catch(() => false)) {
      await menuButton.click();
      await page.waitForTimeout(300);
      await page.screenshot({
        path: 'screenshots/Mobile-Sidebar.png',
        fullPage: true,
      });
    }
  });
});
