import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

const BUILDER_SESSION = {
  session_id: 'workbench-session-1',
  mock_mode: true,
  mock_reason: 'Mocked for workbench flow.',
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
      content: 'Drafted Airline Customer Support Agent.',
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
        when_to_use: 'When traveler asks for status.',
      },
    ],
    routing_rules: [
      { name: 'cancellations', intent: 'cancellation', description: 'Handle cancellations.' },
    ],
    policies: [
      { name: 'no_internal_codes', description: 'Never reveal internal codes.' },
    ],
    eval_criteria: [],
    metadata: {},
  },
  stats: { tool_count: 1, policy_count: 1, routing_rule_count: 1 },
  evals: null,
  updated_at: 3,
};

async function mockApis(page: Page) {
  await page.route('**/api/builder/chat', async (route) => {
    await route.fulfill({ json: BUILDER_SESSION });
  });
  await page.route('**/api/builder/sessions/**', async (route) => {
    await route.fulfill({ json: BUILDER_SESSION });
  });
  await page.route('**/api/builder/sessions*', async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route('**/api/builder/projects*', async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route('**/api/builder/tasks*', async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route('**/api/builder/export/adk', async (route) => {
    await route.fulfill({
      json: {
        filename: 'agent.py',
        content: '# Generated ADK agent\nprint("hello")',
        content_type: 'text/x-python',
        warnings: [],
      },
    });
  });
  await page.route('**/api/builder/export/cx', async (route) => {
    await route.fulfill({
      json: {
        filename: 'agent.json',
        content: '{"name":"airline"}',
        content_type: 'application/json',
        warnings: [],
        diff: null,
      },
    });
  });
  await page.route('**/api/builder/test-live', async (route) => {
    await route.fulfill({
      json: { reply: 'Hello traveler', trace_id: 'trace-1', tool_calls: [] },
    });
  });
  await page.route('**/api/health', async (route) => {
    await route.fulfill({
      json: { mock_mode: true, mock_reasons: [], real_provider_configured: false },
    });
  });
}

test('workbench renders shell, sends message, switches inspector tabs', async ({ page }) => {
  await mockApis(page);

  await page.goto(`${BASE_URL}/workbench`, { waitUntil: 'networkidle' });

  // Composer is present
  const composer = page.getByPlaceholder(/Ask for a plan/i);
  await expect(composer).toBeVisible();

  // 11 inspector tab buttons render
  for (const label of [
    'Preview',
    'Agent Card',
    'Source Code',
    'Tools',
    'Callbacks',
    'Guardrails',
    'Evals',
    'Trace',
    'Test Live',
    'Deploy',
    'Activity',
  ]) {
    await expect(page.getByRole('button', { name: new RegExp(`^${label}$`, 'i') })).toBeVisible();
  }

  // Send a message via composer
  await composer.fill(
    'Build me a customer support agent for an airline that handles booking changes, cancellations, and flight status'
  );
  await composer.press('Enter');

  // Switch to Agent Card tab
  await page.getByRole('button', { name: /^Agent Card$/i }).click();

  // Switch to Deploy tab and trigger ADK export
  await page.getByRole('button', { name: /^Deploy$/i }).click();
  const exportButton = page.getByRole('button', { name: /export adk/i });
  if (await exportButton.isVisible().catch(() => false)) {
    await exportButton.click();
  }
});
