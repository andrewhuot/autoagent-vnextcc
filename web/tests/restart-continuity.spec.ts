import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

const BUILDER_CONTINUITY = {
  state: 'historical',
  label: 'Historical session',
  detail: 'This builder chat was restored from durable storage after restart. Resume it to continue editing.',
  is_live: false,
};

const BUILDER_SESSION = {
  session_id: 'builder-session-restart',
  mock_mode: false,
  mock_reason: '',
  continuity: BUILDER_CONTINUITY,
  messages: [
    {
      message_id: 'user-1',
      role: 'user',
      content: 'Build a refund rescue agent',
      created_at: 1776000000,
    },
    {
      message_id: 'assistant-1',
      role: 'assistant',
      content: 'I drafted Refund Rescue with refund lookup and escalation policy.',
      created_at: 1776000001,
    },
  ],
  config: {
    agent_name: 'Refund Rescue',
    model: 'gpt-5.4-mini',
    system_prompt: 'Help customers with refunds safely.',
    tools: [{ name: 'refund_lookup', description: 'Look up refund status.', when_to_use: 'Refund questions.' }],
    routing_rules: [{ name: 'refund_request', intent: 'refund', description: 'Route refund requests.' }],
    policies: [{ name: 'Protect data', description: 'Do not reveal private customer data.' }],
    eval_criteria: [{ name: 'Correct routing', description: 'Refund cases route correctly.' }],
    metadata: {},
  },
  stats: {
    tool_count: 1,
    policy_count: 1,
    routing_rule_count: 1,
  },
  evals: null,
  updated_at: 1776000001,
};

const SAVED_AGENT = {
  id: 'agent-v002',
  name: 'Refund Rescue',
  model: 'gpt-5.4-mini',
  created_at: '2026-04-12T14:00:00.000Z',
  source: 'built',
  config_path: '/workspace/configs/refund-rescue.yaml',
  status: 'candidate',
};

async function mockRestartContinuityApis(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path === '/api/health') {
      await route.fulfill({
        json: {
          metrics: {
            success_rate: 0.9,
            avg_latency_ms: 100,
            error_rate: 0.01,
            safety_violation_rate: 0,
            avg_cost: 0.01,
            total_conversations: 12,
          },
          anomalies: [],
          failure_buckets: {},
          needs_optimization: false,
          reason: '',
          mock_mode: false,
          mock_reasons: [],
          real_provider_configured: true,
        },
      });
      return;
    }

    if (path === '/api/builder/chat/sessions') {
      await route.fulfill({
        json: [
          {
            session_id: BUILDER_SESSION.session_id,
            agent_name: 'Refund Rescue',
            message_count: 2,
            mock_mode: false,
            created_at: 1776000000,
            updated_at: 1776000001,
            continuity: BUILDER_CONTINUITY,
          },
        ],
      });
      return;
    }

    if (path === `/api/builder/session/${BUILDER_SESSION.session_id}`) {
      await route.fulfill({ json: BUILDER_SESSION });
      return;
    }

    if (path === '/api/agents') {
      await route.fulfill({ json: { agents: [SAVED_AGENT] } });
      return;
    }

    if (path === `/api/agents/${SAVED_AGENT.id}`) {
      await route.fulfill({ json: { ...SAVED_AGENT, config: BUILDER_SESSION.config } });
      return;
    }

    if (path === '/api/eval/runs') {
      await route.fulfill({
        json: [
          {
            task_id: 'eval-live-1',
            task_type: 'eval',
            status: 'running',
            progress: 62,
            result: null,
            error: null,
            created_at: '2026-04-12T14:08:00Z',
            updated_at: '2026-04-12T14:09:00Z',
            continuity: {
              state: 'live',
              label: 'Live run',
              detail: 'This eval is active in the current server process.',
              is_live: true,
              is_historical: false,
              can_rerun: false,
            },
          },
          {
            task_id: 'eval-interrupted-1',
            task_type: 'eval',
            status: 'interrupted',
            progress: 42,
            result: null,
            error: null,
            created_at: '2026-04-12T14:00:00Z',
            updated_at: '2026-04-12T14:05:00Z',
            continuity: {
              state: 'interrupted',
              label: 'Interrupted by restart',
              detail: 'This task was pending or running when the server restarted. It did not finish; rerun it to continue.',
              is_live: false,
              is_historical: true,
              can_rerun: true,
            },
          },
          {
            task_id: 'eval-historical-1',
            task_type: 'eval',
            status: 'completed',
            progress: 100,
            result: {
              composite: 0.91,
              total_cases: 12,
              passed_cases: 11,
              mode: 'live',
            },
            error: null,
            created_at: '2026-04-12T13:00:00Z',
            updated_at: '2026-04-12T13:10:00Z',
            continuity: {
              state: 'historical',
              label: 'Historical run',
              detail: 'This eval is saved history and remains visible after restart.',
              is_live: false,
              is_historical: true,
              can_rerun: false,
            },
          },
        ],
      });
      return;
    }

    if (path === '/api/evals/generated') {
      await route.fulfill({ json: { suites: [], count: 0 } });
      return;
    }

    if (path === '/api/curriculum/batches') {
      await route.fulfill({ json: { batches: [], progression: [] } });
      return;
    }

    if (path === '/api/events/unified' || path === '/api/events') {
      await route.fulfill({
        json: {
          events: [
            {
              id: 'sys-1',
              timestamp: 1776000002,
              event_type: 'eval_started',
              source: 'system',
              source_label: 'System event log',
              continuity_state: 'historical',
              session_id: null,
              payload: { run_id: 'eval-interrupted-1' },
            },
            {
              id: 'bld-1',
              timestamp: 1776000001,
              event_type: 'task.started',
              source: 'builder',
              source_label: 'Builder event history',
              continuity_state: 'historical',
              session_id: BUILDER_SESSION.session_id,
              payload: { phase: 'plan' },
            },
          ],
          count: 2,
          sources: {
            system: { included: true, durable: true, label: 'System event log' },
            builder: { included: true, durable: true, label: 'Builder event history' },
          },
          continuity: {
            state: 'historical',
            label: 'Durable event history',
            detail: 'This timeline merges persisted system events and builder events so history remains visible after restart.',
          },
        },
      });
      return;
    }

    if (path === '/api/workbench/projects/default') {
      await route.fulfill({
        json: {
          project: {
            project_id: 'wb-restart',
            name: 'Restart Workbench',
            target: 'portable',
            environment: 'draft',
            version: 2,
            model: null,
            compatibility: [],
            exports: { generated_config: {}, adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
            last_test: null,
            activity: [],
          },
          exports: { generated_config: {}, adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
          activity: [],
        },
      });
      return;
    }

    if (path === '/api/workbench/projects/wb-restart/plan') {
      await route.fulfill({
        json: {
          project_id: 'wb-restart',
          name: 'Restart Workbench',
          target: 'portable',
          environment: 'draft',
          version: 2,
          build_status: 'interrupted',
          plan: null,
          artifacts: [],
          messages: [],
          model: null,
          exports: { generated_config: {}, adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
          compatibility: [],
          last_test: null,
          activity: [],
          active_run: {
            run_id: 'run-interrupted',
            project_id: 'wb-restart',
            brief: 'Build restart-safe agent',
            target: 'portable',
            environment: 'draft',
            status: 'interrupted',
            phase: 'executing',
            started_version: 1,
            completed_version: null,
            created_at: '2026-04-12T13:00:00Z',
            updated_at: '2026-04-12T13:05:00Z',
            completed_at: null,
            error: 'Recovered after restart before the run completed.',
            failure_reason: 'stale_interrupted',
            events: [],
            messages: [],
            validation: null,
            presentation: null,
          },
          runs: [],
          last_brief: 'Build restart-safe agent',
          conversation: [],
          turns: [
            {
              turn_id: 'turn-1',
              brief: 'Build restart-safe agent',
              mode: 'initial',
              status: 'interrupted',
              created_at: '2026-04-12T13:00:00Z',
              artifact_ids: [],
              iterations: [],
              plan: null,
            },
          ],
        },
      });
      return;
    }

    await route.fulfill({ json: {} });
  });
}

test('restart continuity is clear across builder, eval history, events, and workbench', async ({ page }) => {
  await mockRestartContinuityApis(page);

  await page.goto(`${BASE_URL}/build?tab=builder-chat`, { waitUntil: 'networkidle' });
  await expect(page.getByText('Restart recovery')).toBeVisible();
  await expect(page.getByText('Historical session')).toBeVisible();
  await page.getByRole('button', { name: /Refund Rescue/ }).click();
  await expect(page.getByText('Restored historical session')).toBeVisible();

  await page.goto(`${BASE_URL}/evals?agent=agent-v002`, { waitUntil: 'networkidle' });
  await expect(page.getByText('Live: 1')).toBeVisible();
  await expect(page.getByText('Interrupted: 1')).toBeVisible();
  await expect(page.getByText('Historical: 1')).toBeVisible();
  await expect(page.getByText('Interrupted by restart')).toBeVisible();
  await expect(page.getByText('Durable history')).toBeVisible();

  await page.goto(`${BASE_URL}/events`, { waitUntil: 'networkidle' });
  await expect(page.getByText('Unified durable timeline', { exact: true })).toBeVisible();
  await expect(page.getByText('Durable event history')).toBeVisible();
  await expect(page.getByText('System event log', { exact: true })).toBeVisible();
  await expect(page.getByText('Builder event history', { exact: true })).toBeVisible();
  await expect(page.getByText('system', { exact: true })).toBeVisible();
  await expect(page.getByText('builder', { exact: true })).toBeVisible();

  await page.goto(`${BASE_URL}/workbench`, { waitUntil: 'networkidle' });
  await expect(page.getByText('Historical snapshot')).toBeVisible();
  await expect(page.getByText('Interrupted run restored after restart')).toBeVisible();
});
