import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

const SAVED_AGENT = {
  id: 'agent-v002',
  name: 'Order Guardian',
  model: 'gpt-5.4',
  created_at: '2026-04-12T12:00:00.000Z',
  source: 'built',
  config_path: '/workspace/configs/order-guardian.yaml',
  status: 'candidate',
};

const EVAL_RUN = {
  task_id: 'eval-run-1234',
  task_type: 'eval',
  status: 'completed',
  progress: 100,
  result: {
    run_id: 'eval-run-1234',
    mode: 'mixed',
    quality: 0.92,
    safety: 0.98,
    latency: 0.87,
    cost: 0.91,
    composite: 0.91,
    safety_failures: 0,
    total_cases: 12,
    passed_cases: 11,
    cases: [],
    completed_at: '2026-04-12T12:04:00.000Z',
  },
  error: null,
  created_at: '2026-04-12T12:00:00.000Z',
  updated_at: '2026-04-12T12:04:00.000Z',
};

const PENDING_REVIEW = {
  attempt_id: 'attempt-review-1',
  proposed_config: { prompts: { root: 'new' } },
  current_config: { prompts: { root: 'old' } },
  config_diff: '- root: old\n+ root: new',
  score_before: 0.72,
  score_after: 0.84,
  change_description: 'Strengthen root prompt',
  reasoning: 'Improve routing clarity and answer quality',
  created_at: '2026-04-12T12:08:00.000Z',
  strategy: 'simple',
  selected_operator_family: 'prompts',
  governance_notes: ['Protected safety floor at 99%.'],
  deploy_strategy: 'canary',
};

const WORKBENCH_MODEL = {
  project: { name: 'Order Guardian Workbench', description: 'Order support candidate' },
  agents: [
    {
      id: 'root',
      name: 'Order Guardian',
      role: 'Resolve order issues',
      model: 'gpt-5.4',
      instructions: 'Resolve order support issues safely.',
      sub_agents: [],
    },
  ],
  tools: [],
  callbacks: [],
  guardrails: [],
  eval_suites: [],
  environments: [{ id: 'draft', name: 'Draft', target: 'portable' }],
  deployments: [],
};

function json(payload: unknown, status = 200) {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  };
}

async function mockJourneyApis(page: Page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, '');

    if (path === '/health') {
      await route.fulfill(json({
        mock_mode: true,
        mock_reasons: ['Browser journey validation uses mocked API state.'],
        real_provider_configured: false,
      }));
      return;
    }

    if (path === '/agents') {
      await route.fulfill(json({ agents: [SAVED_AGENT] }));
      return;
    }

    if (path === `/agents/${SAVED_AGENT.id}`) {
      await route.fulfill(json({
        ...SAVED_AGENT,
        config: {
          model: 'gpt-5.4',
          system_prompt: 'Resolve order support issues safely.',
        },
      }));
      return;
    }

    if (path === '/workbench/projects/default') {
      await route.fulfill(json({
        project: {
          project_id: 'wb-journey',
          name: 'Order Guardian Workbench',
          target: 'portable',
          environment: 'draft',
          version: 2,
          draft_badge: 'Draft v2',
          model: WORKBENCH_MODEL,
          compatibility: [],
          exports: { adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
          last_test: {
            run_id: 'wb-test',
            status: 'passed',
            created_at: '2026-04-12T12:00:00.000Z',
            checks: [],
            trace: [],
          },
          versions: [],
          activity: [],
          messages: [],
        },
        exports: { adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
        activity: [],
      }));
      return;
    }

    if (path === '/workbench/projects/wb-journey/plan') {
      await route.fulfill(json({
        project_id: 'wb-journey',
        name: 'Order Guardian Workbench',
        target: 'portable',
        environment: 'draft',
        version: 2,
        build_status: 'done',
        plan: null,
        artifacts: [],
        messages: [],
        model: WORKBENCH_MODEL,
        exports: { adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
        compatibility: [],
        last_test: {
          run_id: 'wb-test',
          status: 'passed',
          created_at: '2026-04-12T12:00:00.000Z',
          checks: [],
          trace: [],
        },
        activity: [],
        active_run: null,
        runs: [],
        run_summary: {
          run_id: 'wb-run',
          status: 'completed',
          phase: 'presenting',
          mode: 'initial',
          provider: 'mock',
          model: 'gpt-5.4',
          changes: [],
          recommended_action: 'Run eval before optimizing.',
        },
      }));
      return;
    }

    if (path === '/eval/runs') {
      await route.fulfill(json([EVAL_RUN]));
      return;
    }

    if (path === '/eval/run' && request.method() === 'POST') {
      await route.fulfill(json({ task_id: EVAL_RUN.task_id, message: 'Eval run started' }, 202));
      return;
    }

    if (path === '/evals/generated') {
      await route.fulfill(json({ suites: [], count: 0 }));
      return;
    }

    if (path === '/curriculum/batches') {
      await route.fulfill(json({ batches: [], count: 0, progression: [] }));
      return;
    }

    if (path === '/optimize/history') {
      await route.fulfill(json([]));
      return;
    }

    if (path === '/optimize/pending') {
      await route.fulfill(json([PENDING_REVIEW]));
      return;
    }

    if (path === '/reviews/stats') {
      await route.fulfill(json({
        total_pending: 0,
        optimizer_pending: 0,
        change_card_pending: 0,
        total_approved: 1,
        total_rejected: 0,
      }));
      return;
    }

    if (path === '/reviews/pending') {
      await route.fulfill(json([]));
      return;
    }

    if (path === '/experiments') {
      await route.fulfill(json([]));
      return;
    }

    if (path === '/deploy/status') {
      await route.fulfill(json({
        active_version: 7,
        canary_version: 8,
        total_versions: 9,
        canary_status: {
          is_active: true,
          canary_version: 8,
          baseline_version: 7,
          canary_conversations: 120,
          canary_success_rate: 0.71,
          baseline_success_rate: 0.76,
          started_at: 1775995200,
          verdict: 'pending',
        },
        history: [],
      }));
      return;
    }

    if (path === '/config/list') {
      await route.fulfill(json({
        versions: [
          {
            version: 8,
            config_hash: 'cfg-8',
            filename: 'v8.yaml',
            timestamp: 1775995200,
            status: 'candidate',
            composite_score: 91,
          },
        ],
      }));
      return;
    }

    await route.fulfill(json({}));
  });
}

function trackPageIssues(page: Page) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: string[] = [];
  const badResponses: string[] = [];

  const ignorable = (entry: string) =>
    entry.includes('/favicon.ico') ||
    entry.includes('/ws') ||
    entry.includes('WebSocket connection') ||
    entry.includes(':: net::ERR_ABORTED') ||
    entry.includes('/api/health :: net::ERR_ABORTED');

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

async function expectJourney(page: Page, currentStep: string, nextAction: string) {
  const journey = page.getByRole('region', { name: 'Operator journey' });
  await expect(journey.getByText(`Current step: ${currentStep}`)).toBeVisible();
  await expect(journey.getByText(`Next: ${nextAction}`)).toBeVisible();
  return journey;
}

test('main operator journey is explicit from build through deploy', async ({ page }) => {
  await mockJourneyApis(page);
  const issues = trackPageIssues(page);

  await page.addInitScript((agent) => {
    window.localStorage.setItem(
      'agentlab.build-artifacts.v1',
      JSON.stringify([
        {
          artifact_id: 'artifact-journey',
          agent_id: agent.id,
          title: agent.name,
          summary: 'Saved from Build',
          source: 'prompt',
          status: 'complete',
          created_at: '2026-04-12T12:00:00.000Z',
          updated_at: '2026-04-12T12:00:00.000Z',
          config_yaml: 'model: gpt-5.4\n',
        },
      ])
    );
  }, SAVED_AGENT);

  await page.goto(`${BASE_URL}/build`, { waitUntil: 'networkidle' });
  let journey = await expectJourney(page, 'Build', 'run eval');
  await expect(journey.getByRole('link', { name: 'Run eval' })).toHaveAttribute(
    'href',
    '/evals?agent=agent-v002&new=1'
  );

  await page.goto(`${BASE_URL}/workbench`, { waitUntil: 'networkidle' });
  journey = await expectJourney(page, 'Workbench', 'run eval');
  await expect(journey.getByRole('link', { name: 'Run eval' })).toHaveAttribute('href', '/evals?new=1');

  await page.goto(`${BASE_URL}/evals?agent=agent-v002&new=1`, { waitUntil: 'networkidle' });
  journey = await expectJourney(page, 'Eval', 'optimize candidate');
  await journey.getByRole('link', { name: 'Optimize candidate' }).click();
  await expect(page).toHaveURL(`${BASE_URL}/optimize?agent=agent-v002&evalRunId=eval-run-1234`);

  journey = await expectJourney(page, 'Optimize', 'review proposals');
  await journey.getByRole('link', { name: 'Review proposals' }).click();
  await expect(page).toHaveURL(`${BASE_URL}/improvements?tab=review`);

  journey = await expectJourney(page, 'Review', 'deploy approved improvements');
  await journey.getByRole('link', { name: 'Deploy approved improvements' }).click();
  await expect(page).toHaveURL(`${BASE_URL}/deploy`);

  journey = await expectJourney(page, 'Deploy', 'promote canary');
  await expect(journey.getByRole('button', { name: 'Promote canary' })).toBeVisible();

  issues.assertClean();
});
