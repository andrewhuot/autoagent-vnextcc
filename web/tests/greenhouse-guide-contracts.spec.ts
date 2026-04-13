import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const GREENHOUSE_AGENT_ID = 'agent-v015';
const GREENHOUSE_AGENT_NAME = 'Greenhouse Guide';
const GREENHOUSE_CONFIG_PATH = '/workspace/configs/v015.yaml';
const GREENHOUSE_EVAL_CASES_PATH = '/workspace/evals/cases/generated_build.yaml';
const GREENHOUSE_PROJECT_ID = 'gh-workbench';
const GREENHOUSE_EVAL_RUN_ID = 'eval-run-gh-001';

type JsonRecord = Record<string, unknown>;

function json(payload: unknown, status = 200) {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  };
}

function buildWorkbenchBridgeResponse() {
  return {
    bridge: {
      kind: 'workbench_eval_optimize',
      schema_version: 1,
      candidate: {
        project_id: GREENHOUSE_PROJECT_ID,
        run_id: 'run-gh-001',
        version: 15,
        target: 'portable',
        environment: 'draft',
        agent_name: GREENHOUSE_AGENT_NAME,
        validation_status: 'passed',
        review_gate_status: 'ready',
        generated_config_hash: 'cfg-gh-15',
        config_path: GREENHOUSE_CONFIG_PATH,
        eval_cases_path: GREENHOUSE_EVAL_CASES_PATH,
        export_targets: ['adk', 'cx'],
      },
      evaluation: {
        status: 'ready',
        readiness_state: 'ready',
        label: 'Run eval',
        description: 'Open Eval with the saved Greenhouse Guide candidate.',
        primary_action_label: 'Open Eval with this candidate',
        primary_action_target: 'eval',
        prerequisite_step: null,
        request: {
          config_path: GREENHOUSE_CONFIG_PATH,
          dataset_path: GREENHOUSE_EVAL_CASES_PATH,
          generated_suite_id: 'generated_build',
          split: 'all',
        },
        start_endpoint: '/api/eval/run',
        blocking_reasons: [],
      },
      optimization: {
        status: 'awaiting_eval_run',
        readiness_state: 'awaiting_eval_run',
        label: 'Optimize',
        description: 'Requires a completed eval run first.',
        primary_action_label: 'Run eval first',
        primary_action_target: 'eval',
        prerequisite_step: 'evaluation',
        requires_eval_run: true,
        request_template: {
          window: 100,
          force: false,
          require_human_approval: true,
          config_path: GREENHOUSE_CONFIG_PATH,
          eval_run_id: null,
          mode: 'standard',
          objective: '',
          guardrails: [],
          research_algorithm: 'bayesian',
          budget_cycles: 10,
          budget_dollars: 50,
        },
        start_endpoint: '/api/optimize/run',
        blocking_reasons: ['Awaiting a completed eval run.'],
      },
      review_gate: {
        status: 'ready',
        can_deploy: true,
      },
      validation: {
        status: 'passed',
      },
      created_from: 'workbench',
    },
    save_result: {
      config_path: GREENHOUSE_CONFIG_PATH,
      config_version: 15,
      eval_cases_path: GREENHOUSE_EVAL_CASES_PATH,
    },
    eval_request: {
      config_path: GREENHOUSE_CONFIG_PATH,
      dataset_path: GREENHOUSE_EVAL_CASES_PATH,
      generated_suite_id: 'generated_build',
      split: 'all',
    },
    optimize_request_template: {
      window: 100,
      force: false,
      require_human_approval: true,
      config_path: GREENHOUSE_CONFIG_PATH,
      eval_run_id: GREENHOUSE_EVAL_RUN_ID,
      mode: 'standard',
      objective: '',
      guardrails: [],
      research_algorithm: 'bayesian',
      budget_cycles: 10,
      budget_dollars: 50,
    },
    next: {
      start_eval_endpoint: '/api/eval/run',
      start_optimize_endpoint: '/api/optimize/run',
      optimize_requires_eval_run: true,
    },
  };
}

async function mockGreenhouseApis(
  page: Page,
  options: {
    completedEval?: boolean;
    onEvalRun?: (body: JsonRecord) => void;
    onOptimizeRun?: (body: JsonRecord) => void;
    onDeploy?: (body: JsonRecord) => void;
  }
) {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, '');

    if (path === '/health') {
      await route.fulfill(
        json({
          mock_mode: false,
          mock_reasons: [],
          real_provider_configured: true,
        })
      );
      return;
    }

    if (path === '/agents' && request.method() === 'GET') {
      await route.fulfill(
        json({
          agents: [
            {
              id: GREENHOUSE_AGENT_ID,
              name: GREENHOUSE_AGENT_NAME,
              model: 'gpt-5.4',
              created_at: '2026-04-12T12:00:00.000Z',
              source: 'built',
              config_path: GREENHOUSE_CONFIG_PATH,
              status: 'candidate',
            },
          ],
        })
      );
      return;
    }

    if (path === `/agents/${GREENHOUSE_AGENT_ID}`) {
      await route.fulfill(
        json({
          id: GREENHOUSE_AGENT_ID,
          name: GREENHOUSE_AGENT_NAME,
          model: 'gpt-5.4',
          created_at: '2026-04-12T12:00:00.000Z',
          source: 'built',
          config_path: GREENHOUSE_CONFIG_PATH,
          status: 'candidate',
          config: {
            model: 'gpt-5.4',
            system_prompt: 'You are Greenhouse Guide, a lawn and garden store support agent.',
          },
        })
      );
      return;
    }

    if (path === '/workbench/projects/default') {
      await route.fulfill(
        json({
          project: {
            project_id: GREENHOUSE_PROJECT_ID,
            name: 'Greenhouse Guide Workbench',
            target: 'portable',
            environment: 'draft',
            version: 15,
            draft_badge: 'Draft v15',
            model: {
              project: {
                name: 'Greenhouse Guide Workbench',
                description: 'Lawn and garden support candidate',
              },
              agents: [
                {
                  id: 'root',
                  name: GREENHOUSE_AGENT_NAME,
                  role: 'Answer lawn and garden product-care, planting, delivery, and return questions.',
                  model: 'gpt-5.4',
                  instructions:
                    'Answer lawn and garden product-care, planting, delivery, return, and escalation questions clearly.',
                  sub_agents: [],
                },
              ],
              tools: [],
              callbacks: [],
              guardrails: [],
              eval_suites: [],
              environments: [{ id: 'draft', name: 'Draft', target: 'portable' }],
              deployments: [],
            },
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
            build_status: 'done',
            runs: [],
          },
          exports: { adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
          activity: [],
        })
      );
      return;
    }

    if (path === `/workbench/projects/${GREENHOUSE_PROJECT_ID}/plan`) {
      await route.fulfill(
        json({
          project_id: GREENHOUSE_PROJECT_ID,
          name: 'Greenhouse Guide Workbench',
          target: 'portable',
          environment: 'draft',
          version: 15,
          build_status: 'done',
          plan: null,
          artifacts: [],
          messages: [],
          model: {
            project: {
              name: 'Greenhouse Guide Workbench',
              description: 'Lawn and garden support candidate',
            },
            agents: [
              {
                id: 'root',
                name: GREENHOUSE_AGENT_NAME,
                role: 'Answer lawn and garden product-care, planting, delivery, and return questions.',
                model: 'gpt-5.4',
                instructions:
                  'Answer lawn and garden product-care, planting, delivery, return, and escalation questions clearly.',
                sub_agents: [],
              },
            ],
            tools: [],
            callbacks: [],
            guardrails: [],
            eval_suites: [],
            environments: [{ id: 'draft', name: 'Draft', target: 'portable' }],
            deployments: [],
          },
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
        })
      );
      return;
    }

    if (path === `/workbench/projects/${GREENHOUSE_PROJECT_ID}/bridge/eval` && request.method() === 'POST') {
      await route.fulfill(json(buildWorkbenchBridgeResponse()));
      return;
    }

    if (path === '/eval/runs') {
      await route.fulfill(
        json(
          options.completedEval
            ? [
                {
                  run_id: GREENHOUSE_EVAL_RUN_ID,
                  timestamp: '2026-04-12T12:04:00.000Z',
                  status: 'completed',
                  progress: 100,
                  mode: 'live',
                  composite_score: 91,
                  total_cases: 12,
                  passed_cases: 11,
                  error: null,
                },
              ]
            : []
        )
      );
      return;
    }

    if (path === '/eval/run' && request.method() === 'POST') {
      options.onEvalRun?.(request.postDataJSON() as JsonRecord);
      await route.fulfill(json({ task_id: GREENHOUSE_EVAL_RUN_ID, message: 'Eval run started' }, 202));
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
      await route.fulfill(json([]));
      return;
    }

    if (path === '/optimize/run' && request.method() === 'POST') {
      options.onOptimizeRun?.(request.postDataJSON() as JsonRecord);
      await route.fulfill(json({ task_id: 'opt-task-gh-001', message: 'Optimize started' }, 202));
      return;
    }

    if (path === '/reviews/stats') {
      await route.fulfill(json({ total_pending: 0, optimizer_pending: 0, change_card_pending: 0, total_approved: 0, total_rejected: 0 }));
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

    if (path === '/config/list') {
      await route.fulfill(
        json({
          versions: [
            { version: 15, config_hash: 'cfg-gh-15', filename: 'v15.yaml', timestamp: '2026-04-12T12:00:00.000Z', status: 'candidate', composite_score: 91 },
            { version: 14, config_hash: 'cfg-gh-14', filename: 'v14.yaml', timestamp: '2026-04-12T11:00:00.000Z', status: 'active', composite_score: 88 },
          ],
        })
      );
      return;
    }

    if (path === '/deploy/status') {
      await route.fulfill(
        json({
          active_version: 14,
          canary_version: null,
          total_versions: 15,
          canary_status: null,
          history: [],
        })
      );
      return;
    }

    if (path === '/deploy' && request.method() === 'POST') {
      const body = request.postDataJSON() as JsonRecord;
      options.onDeploy?.(body);
      await route.fulfill(json({ message: `Deployed v${body.version} as canary` }, 201));
      return;
    }

    if (path === '/deploy/promote' && request.method() === 'POST') {
      await route.fulfill(json({ message: 'Promoted canary to active' }, 200));
      return;
    }

    await route.fulfill(json({}));
  });
}

test.describe('Greenhouse Guide golden-path contracts', () => {
  test.setTimeout(180_000);

  test('Workbench handoff carries the saved eval dataset path into Eval', async ({ page }, testInfo) => {
    let evalRunRequestBody: JsonRecord | null = null;
    await mockGreenhouseApis(page, {
      completedEval: false,
      onEvalRun: (body) => {
        evalRunRequestBody = body;
      },
    });

    await page.goto(
      `${BASE_URL}/workbench?agent=${GREENHOUSE_AGENT_ID}&agentName=${encodeURIComponent(GREENHOUSE_AGENT_NAME)}&configPath=${encodeURIComponent(GREENHOUSE_CONFIG_PATH)}`,
      { waitUntil: 'networkidle' }
    );

    await expect(page.getByText(GREENHOUSE_AGENT_NAME)).toBeVisible();
    await expect(page.getByText('lawn and garden support candidate', { exact: false })).toBeVisible();
    await expect(page.getByText('Airline', { exact: false })).toHaveCount(0);
    await expect(page.getByText('Hotel', { exact: false })).toHaveCount(0);

    await page.screenshot({
      path: testInfo.outputPath('greenhouse-guide-workbench.png'),
      fullPage: true,
    });

    const openEvalButton = page.getByRole('button', {
      name: /Save candidate and open Eval|Open Eval with this candidate/i,
    });
    await expect(openEvalButton).toBeVisible();
    await openEvalButton.click();

    await expect(page).toHaveURL(/\/evals\?/);
    const evalUrl = new URL(page.url());
    expect(evalUrl.searchParams.get('agent')).toBe(GREENHOUSE_AGENT_ID);
    expect(evalUrl.searchParams.get('agentName')).toBe(GREENHOUSE_AGENT_NAME);
    expect(evalUrl.searchParams.get('configPath')).toBe(GREENHOUSE_CONFIG_PATH);
    expect(evalUrl.searchParams.get('evalCasesPath')).toBe(GREENHOUSE_EVAL_CASES_PATH);
    expect(evalUrl.searchParams.get('projectId')).toBe(GREENHOUSE_PROJECT_ID);
    expect(evalUrl.searchParams.get('runId')).toBe('run-gh-001');

    await page.screenshot({
      path: testInfo.outputPath('greenhouse-guide-eval-handoff.png'),
      fullPage: true,
    });

    const startEvalButton = page.getByRole('button', {
      name: /Start Eval|Run First Eval/i,
    });
    await expect(startEvalButton).toBeVisible();
    await startEvalButton.click();

    await expect.poll(() => evalRunRequestBody?.dataset_path).toBe(GREENHOUSE_EVAL_CASES_PATH);
    await expect.poll(() => evalRunRequestBody?.config_path).toBe(GREENHOUSE_CONFIG_PATH);
    await expect.poll(() => evalRunRequestBody?.require_live).toBe(true);
  });

  test('Optimize carries evalRunId and Deploy preselects the carried version', async ({
    page,
  }, testInfo) => {
    let optimizeRunRequestBody: JsonRecord | null = null;
    let deployRequestBody: JsonRecord | null = null;

    await mockGreenhouseApis(page, {
      completedEval: true,
      onOptimizeRun: (body) => {
        optimizeRunRequestBody = body;
      },
      onDeploy: (body) => {
        deployRequestBody = body;
      },
    });

    await page.goto(
      `${BASE_URL}/evals?agent=${GREENHOUSE_AGENT_ID}&new=1&configPath=${encodeURIComponent(GREENHOUSE_CONFIG_PATH)}&evalCasesPath=${encodeURIComponent(GREENHOUSE_EVAL_CASES_PATH)}`,
      { waitUntil: 'networkidle' }
    );

    await expect(page.getByText(GREENHOUSE_AGENT_NAME)).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath('greenhouse-guide-evals-complete.png'),
      fullPage: true,
    });

    const optimizeLink = page.getByRole('link', { name: /Optimize candidate/i });
    await expect(optimizeLink).toBeVisible();
    await expect(optimizeLink).toHaveAttribute('href', /evalRunId=eval-run-gh-001/);
    await expect(optimizeLink).toHaveAttribute('href', /configPath=.*v015\.yaml/);

    await optimizeLink.click();
    await expect(page).toHaveURL(/\/optimize\?/);

    const optimizeUrl = new URL(page.url());
    expect(optimizeUrl.searchParams.get('agent')).toBe(GREENHOUSE_AGENT_ID);
    expect(optimizeUrl.searchParams.get('evalRunId')).toBe(GREENHOUSE_EVAL_RUN_ID);
    expect(optimizeUrl.searchParams.get('configPath')).toBe(GREENHOUSE_CONFIG_PATH);

    const reviewLink = page.getByRole('link', { name: /Review proposals/i });
    await expect(reviewLink).toBeVisible();
    await expect(reviewLink).toHaveAttribute('href', '/improvements?tab=review');

    const startOptimizeButton = page.getByRole('button', {
      name: /Start Optimization|Start Optimize/i,
    });
    await expect(startOptimizeButton).toBeVisible();
    await startOptimizeButton.click();

    await expect.poll(() => optimizeRunRequestBody?.eval_run_id).toBe(GREENHOUSE_EVAL_RUN_ID);
    await expect.poll(() => optimizeRunRequestBody?.config_path).toBe(GREENHOUSE_CONFIG_PATH);

    await page.goto(`${BASE_URL}/deploy?new=1&version=v015&from=review`, {
      waitUntil: 'networkidle',
    });

    const versionSelect = page.getByRole('combobox', { name: 'Version' });
    await expect(versionSelect).toHaveValue('15');
    await page.screenshot({
      path: testInfo.outputPath('greenhouse-guide-deploy-preselected.png'),
      fullPage: true,
    });

    await page.getByRole('button', { name: 'Deploy' }).click();

    await expect.poll(() => deployRequestBody?.version).toBe(15);
    await expect.poll(() => deployRequestBody?.strategy).toBe('canary');
  });
});
