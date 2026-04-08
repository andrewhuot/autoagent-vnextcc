import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

const BUILDER_SESSION = {
  session_id: 'session-123',
  mock_mode: true,
  mock_reason: 'Preview mode is enabled for browser verification.',
  messages: [
    {
      message_id: 'assistant-intro',
      role: 'assistant',
      content: 'Describe the agent you want to build.',
      created_at: 1,
    },
    {
      message_id: 'user-1',
      role: 'user',
      content:
        'Build me a customer support agent for an airline that handles booking changes, cancellations, and flight status',
      created_at: 2,
    },
    {
      message_id: 'assistant-1',
      role: 'assistant',
      content:
        'I drafted `Airline Customer Support Agent` with routing for cancellations, changes, and flight status.',
      created_at: 3,
    },
  ],
  config: {
    agent_name: 'Airline Customer Support Agent',
    model: 'gpt-4o',
    system_prompt: 'You are an airline support agent.',
    tools: [
      {
        name: 'flight_status_lookup',
        description: 'Fetch flight status.',
        when_to_use: 'Use when a traveler asks for flight status.',
      },
    ],
    routing_rules: [
      {
        name: 'booking_changes',
        intent: 'booking_change',
        description: 'Handle booking changes.',
      },
      {
        name: 'cancellations',
        intent: 'cancellation',
        description: 'Handle cancellations.',
      },
      {
        name: 'flight_status',
        intent: 'flight_status',
        description: 'Handle flight status requests.',
      },
    ],
    policies: [
      {
        name: 'no_internal_codes',
        description: 'Never reveal internal codes.',
      },
    ],
    eval_criteria: [
      {
        name: 'correct_routing',
        description: 'Route to the correct workflow.',
      },
    ],
    metadata: {},
  },
  stats: {
    tool_count: 1,
    policy_count: 1,
    routing_rule_count: 3,
  },
  evals: null,
  updated_at: 3,
};

async function mockBuilderApis(page: Page) {
  await page.route('**/api/builder/chat', async (route) => {
    await route.fulfill({ json: BUILDER_SESSION });
  });

  await page.route('**/api/builder/export', async (route) => {
    await route.fulfill({
      json: {
        filename: 'airline-customer-support-agent.yaml',
        content: 'agent_name: Airline Customer Support Agent\nrouting_rules:\n  - name: booking_changes',
        content_type: 'application/x-yaml',
      },
    });
  });

  await page.route('**/api/agents', async (route) => {
    await route.fulfill({
      json: {
        agent: {
          id: 'agent-v002',
          name: 'Airline Customer Support Agent',
          model: 'gpt-4o',
          created_at: '2026-04-08T12:00:00.000Z',
          source: 'built',
          config_path: '/workspace/agents/airline.yaml',
          status: 'ready',
          config: BUILDER_SESSION.config,
        },
        save_result: {
          artifact_id: 'artifact-123',
          config_path: '/workspace/agents/airline.yaml',
          config_version: 2,
          eval_cases_path: '/workspace/evals/airline.yaml',
          runtime_config_path: '/workspace/runtime/airline.yaml',
          workspace_path: '/workspace',
          actual_config_yaml: 'agent_name: Airline Customer Support Agent',
        },
      },
    });
  });
}

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
  await mockBuilderApis(page);
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
