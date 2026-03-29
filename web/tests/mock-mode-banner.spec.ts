import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const BANNER_TEXT = 'Running in mock mode — add API keys for live optimization';

async function stubMockModeApis(
  page: Page,
  options: { realProviderConfigured: boolean }
) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path === '/api/health') {
      await route.fulfill({
        json: {
          metrics: {
            success_rate: 0.82,
            avg_latency_ms: 140,
            error_rate: 0.04,
            safety_violation_rate: 0,
            avg_cost: 0.02,
            total_conversations: 120,
          },
          anomalies: [],
          failure_buckets: {},
          needs_optimization: false,
          reason: '',
          mock_mode: true,
          mock_reasons: ['Eval harness is using mock_agent_response.'],
          real_provider_configured: options.realProviderConfigured,
        },
      });
      return;
    }

    if (path === '/api/demo/status') {
      await route.fulfill({ json: { has_demo_data: false } });
      return;
    }

    if (path === '/api/optimize/history') {
      await route.fulfill({ json: [] });
      return;
    }

    if (path === '/api/control/state') {
      await route.fulfill({
        json: {
          paused: false,
          immutable_surfaces: [],
          rejected_experiments: [],
          last_injected_mutation: null,
          updated_at: null,
        },
      });
      return;
    }

    if (path === '/api/health/cost') {
      await route.fulfill({
        json: {
          summary: {
            total_spend: 0,
            total_improvement: 0,
            cost_per_improvement: 0,
            today_spend: 0,
          },
          budgets: {
            per_cycle_dollars: 1,
            daily_dollars: 10,
            stall_threshold_cycles: 5,
          },
          recent_cycles: [],
          stall_detected: false,
        },
      });
      return;
    }

    if (path === '/api/health/eval-set') {
      await route.fulfill({
        json: {
          analysis: {},
          difficulty_distribution: {},
        },
      });
      return;
    }

    if (path === '/api/events') {
      await route.fulfill({ json: { events: [] } });
      return;
    }

    if (path === '/api/eval/runs') {
      await route.fulfill({ json: [] });
      return;
    }

    if (path === '/api/curriculum/batches') {
      await route.fulfill({
        json: {
          batches: [],
          progression: [],
        },
      });
      return;
    }

    if (path === '/api/config/list') {
      await route.fulfill({ json: { versions: [] } });
      return;
    }

    if (path === '/api/experiments') {
      await route.fulfill({ json: { experiments: [] } });
      return;
    }

    if (path === '/api/experiments/pareto') {
      await route.fulfill({
        json: {
          candidates: [],
          frontier_size: 0,
        },
      });
      return;
    }

    if (path === '/api/experiments/archive') {
      await route.fulfill({ json: { entries: [] } });
      return;
    }

    if (path === '/api/experiments/judge-calibration') {
      await route.fulfill({
        json: {
          agreement_rate: 1,
          drift: 0,
          position_bias: 0,
          verbosity_bias: 0,
          disagreement_rate: 0,
        },
      });
      return;
    }

    if (path === '/api/tasks') {
      await route.fulfill({ json: [] });
      return;
    }

    await route.fulfill({ json: {} });
  });
}

test.describe('Mock Mode Banner', () => {
  test('shows the warning on all optimization-adjacent pages when mock mode is active', async ({ page }) => {
    await stubMockModeApis(page, { realProviderConfigured: false });

    for (const route of ['/dashboard', '/evals', '/optimize', '/live-optimize', '/experiments']) {
      await page.goto(`${BASE_URL}${route}`, { waitUntil: 'networkidle' });
      await expect(page.getByText(BANNER_TEXT)).toBeVisible();
    }
  });

  test('cannot be dismissed until real provider credentials are configured', async ({ page }) => {
    await stubMockModeApis(page, { realProviderConfigured: false });

    await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle' });

    await expect(page.getByText(BANNER_TEXT)).toBeVisible();
    await expect(page.getByRole('button', { name: /dismiss mock mode warning/i })).toHaveCount(0);
  });

  test('can be dismissed after real provider credentials are configured', async ({ page }) => {
    await stubMockModeApis(page, { realProviderConfigured: true });

    await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle' });

    await expect(page.getByText(BANNER_TEXT)).toBeVisible();
    await page.getByRole('button', { name: /dismiss mock mode warning/i }).click();
    await expect(page.getByText(BANNER_TEXT)).toHaveCount(0);

    await page.goto(`${BASE_URL}/experiments`, { waitUntil: 'networkidle' });
    await expect(page.getByText(BANNER_TEXT)).toHaveCount(0);
  });
});
