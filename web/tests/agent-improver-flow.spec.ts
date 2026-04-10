import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

const DRAFT_CONFIG = {
  agent_name: 'Escalation Concierge',
  model: 'gpt-5.4-mini',
  system_prompt: 'Help customers, escalate safely, and preserve recent context.',
  tools: [
    {
      name: 'ticket_lookup',
      description: 'Look up the current customer ticket.',
      when_to_use: 'Use when a customer references an existing support issue.',
    },
  ],
  routing_rules: [
    {
      name: 'escalation',
      intent: 'human_help',
      description: 'Escalate when a human review is required.',
    },
  ],
  policies: [
    {
      name: 'Context preservation',
      description: 'Pass recent customer history into escalations.',
    },
  ],
  eval_criteria: [
    {
      name: 'Safe escalation',
      description: 'Escalations retain the correct context and policy guardrails.',
    },
  ],
  metadata: {
    owner: 'agent-improver-playwright',
  },
};

const DRAFT_WITHOUT_EVALS = {
  session_id: 'builder-session-123',
  mock_mode: false,
  messages: [
    {
      message_id: 'user-1',
      role: 'user',
      content: 'Improve the handoff logic for escalations.',
      created_at: 1,
    },
    {
      message_id: 'assistant-1',
      role: 'assistant',
      content: 'I tightened the escalation path and preserved recent ticket context.',
      created_at: 2,
    },
  ],
  config: DRAFT_CONFIG,
  stats: {
    tool_count: 1,
    policy_count: 1,
    routing_rule_count: 1,
  },
  evals: null,
  updated_at: 2,
};

const DRAFT_WITH_EVALS = {
  ...DRAFT_WITHOUT_EVALS,
  updated_at: 3,
  messages: [
    ...DRAFT_WITHOUT_EVALS.messages,
    {
      message_id: 'user-2',
      role: 'user',
      content: 'Generate evals for this draft.',
      created_at: 3,
    },
    {
      message_id: 'assistant-2',
      role: 'assistant',
      content: 'I drafted validation ideas for the escalation path.',
      created_at: 4,
    },
  ],
  evals: {
    case_count: 2,
    scenarios: [
      {
        name: 'Escalation context',
        description: 'Verify human handoff includes recent customer actions.',
      },
      {
        name: 'Policy guardrail',
        description: 'Verify account changes are refused before verification.',
      },
    ],
  },
};

const SAVED_AGENT = {
  id: 'agent-v002',
  name: 'Escalation Concierge',
  model: 'gpt-5.4-mini',
  created_at: '2026-04-10T12:00:00.000Z',
  source: 'built',
  config_path: '/workspace/configs/v002.yaml',
  status: 'candidate',
};

const SAVE_RESULT = {
  artifact_id: 'artifact-123',
  config_path: '/workspace/configs/v002.yaml',
  config_version: 2,
  eval_cases_path: '/workspace/evals/generated_build.yaml',
  runtime_config_path: '/workspace/agentlab.yaml',
  workspace_path: '/workspace',
  actual_config_yaml: 'agent_name: Escalation Concierge',
};

async function mockAgentImproverApis(page: Page) {
  await page.route('**/api/builder/chat', async (route) => {
    const request = route.request().postDataJSON() as { message?: string };
    const hasEvalIntent = request.message?.toLowerCase().includes('generate evals') ?? false;
    await route.fulfill({ json: hasEvalIntent ? DRAFT_WITH_EVALS : DRAFT_WITHOUT_EVALS });
  });

  await page.route('**/api/builder/export', async (route) => {
    await route.fulfill({
      json: {
        filename: 'escalation-concierge.yaml',
        content: 'agent_name: Escalation Concierge\npolicies:\n  - name: Context preservation',
        content_type: 'application/x-yaml',
      },
    });
  });

  await page.route('**/api/agents/agent-v002', async (route) => {
    await route.fulfill({
      json: {
        ...SAVED_AGENT,
        config: DRAFT_CONFIG,
      },
    });
  });

  await page.route('**/api/agents', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        json: {
          agent: {
            ...SAVED_AGENT,
            config: DRAFT_CONFIG,
          },
          save_result: SAVE_RESULT,
        },
      });
      return;
    }

    await route.fulfill({
      json: {
        agents: [SAVED_AGENT],
      },
    });
  });

  await page.route('**/api/eval/runs', async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.route('**/api/evals/generated?*', async (route) => {
    await route.fulfill({
      json: {
        suites: [],
        count: 0,
      },
    });
  });

  await page.route('**/api/curriculum/batches?*', async (route) => {
    await route.fulfill({
      json: {
        batches: [],
        count: 0,
        progression: [],
      },
    });
  });

  await page.route('**/api/health', async (route) => {
    await route.fulfill({
      json: {
        mock_mode: false,
        mock_reasons: [],
        real_provider_configured: true,
      },
    });
  });

  await page.route('**/api/config/list', async (route) => {
    await route.fulfill({ json: { versions: [] } });
  });

  await page.route('**/api/conversations**', async (route) => {
    await route.fulfill({ json: { conversations: [] } });
  });
}

function trackPageIssues(page: Page) {
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
    const failure = request.failure();
    requestFailures.push(`${request.method()} ${request.url()} :: ${failure?.errorText || 'unknown'}`);
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

test('agent improver creates an eval-minded draft and opens the eval generator handoff', async ({
  page,
}) => {
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });
  await mockAgentImproverApis(page);
  const issues = trackPageIssues(page);

  await page.goto(`${BASE_URL}/agent-improver`, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Agent Improver' }).first()).toBeVisible();

  await page
    .getByPlaceholder('Describe how the draft should improve next...')
    .fill('Improve the handoff logic for escalations.');
  await page.getByRole('button', { name: 'Send request' }).click();

  await expect(page.getByRole('heading', { name: 'Escalation Concierge' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate eval plan' })).toBeVisible();

  await page.getByRole('button', { name: 'Generate eval plan' }).click();
  await expect(page.getByText('Escalation context')).toBeVisible();
  await expect(page.getByText('Policy guardrail')).toBeVisible();

  await page.getByRole('tab', { name: 'Config' }).click();
  await expect(page.getByTestId('agent-improver-yaml-preview')).toContainText('Context preservation');

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download draft' }).click(),
  ]);
  expect(download.suggestedFilename()).toContain('escalation');
  expect(download.suggestedFilename()).toMatch(/\.ya?ml$/i);

  await page.getByRole('button', { name: 'Save and open Eval Generator' }).click();
  await expect(page).toHaveURL(/\/evals\?.*generator=1/);
  await expect(page).toHaveURL(/from=agent-improver/);
  await expect(page.getByText('Agent Improver handoff')).toBeVisible();
  await expect(page.getByText(/drafted 2 validation ideas/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Generate Eval Suite' })).toBeVisible();

  issues.assertClean();
});
