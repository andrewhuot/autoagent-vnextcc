import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

const AGENT = {
  id: 'agent-v002',
  name: 'Order Guardian',
  model: 'gpt-5.4',
  created_at: '2026-04-01T12:00:00.000Z',
  source: 'built',
  config_path: '/workspace/configs/v002.yaml',
  status: 'candidate',
  config: {
    model: 'gpt-5.4',
    prompts: { root: 'Resolve support issues safely.' },
  },
};

const PENDING_REVIEW = {
  attempt_id: 'attempt-pending',
  proposed_config: { prompts: { root: 'new' } },
  current_config: { prompts: { root: 'old' } },
  config_diff: '- root: old\n+ root: new',
  score_before: 0.72,
  score_after: 0.84,
  change_description: 'Strengthen root prompt',
  reasoning: 'Improve routing clarity and answer quality',
  created_at: '2026-04-01T12:00:00.000Z',
  strategy: 'simple',
  selected_operator_family: 'prompts',
  governance_notes: ['Protected safety floor at 99%.'],
  deploy_strategy: 'immediate',
  source_eval_run_id: 'eval-run-1234',
  evidence_summary: {
    source: 'eval_run',
    eval_run_id: 'eval-run-1234',
    total_cases: 12,
    failed_cases: 4,
    safety_failures: 1,
    failure_sample_count: 1,
    top_failure_buckets: [{ family: 'routing_error', count: 4 }],
  },
  failure_samples: [
    {
      user_message: 'Route this billing escalation safely.',
      error_message: 'routing: expected=billing got=support',
      safety_flags: [],
      latency_ms: 420,
    },
  ],
};

const CHANGE_CARD = {
  card_id: 'card-001',
  title: 'Strengthen root prompt',
  why: 'Fix routing failures from the latest eval run',
  status: 'pending',
  diff_hunks: [
    {
      hunk_id: 'h1',
      surface: 'prompts.root',
      old_value: 'Resolve support issues safely.',
      new_value: 'Resolve support issues safely. Validate every answer.',
      status: 'pending',
    },
  ],
  metrics_before: { quality: 0.72 },
  metrics_after: { quality: 0.84 },
  confidence: {
    p_value: 0.03,
    effect_size: 0.12,
    judge_agreement: 0.91,
  },
  risk_class: 'low',
  rollout_plan: 'Review diff -> apply locally -> re-run evals -> deploy canary if metrics hold',
  created_at: 1775044800,
  candidate_config_version: 12,
  candidate_config_path: '/workspace/.agentlab/configs/v012.yaml',
  source_eval_path: '/workspace/.agentlab/evals/run-123.json',
  experiment_card_id: 'exp-001',
};

async function mockOptimizeImprovementApis(page: Page) {
  await page.route('**/api/opportunities?*', async (route) => {
    await route.fulfill({
      json: {
        opportunities: [
          {
            opportunity_id: 'opp-routing',
            failure_family: 'routing_failure',
            affected_agent_path: 'agents.root',
            severity: 0.9,
            prevalence: 0.7,
            recency: 0.8,
            business_impact: 0.6,
            priority_score: 0.78,
            status: 'open',
            recommended_operator_families: ['routing_policy'],
            sample_trace_ids: ['trace-1'],
          },
        ],
      },
    });
  });

  await page.route('**/api/agents/agent-v002', async (route) => {
    await route.fulfill({ json: AGENT });
  });

  await page.route('**/api/agents?*', async (route) => {
    await route.fulfill({ json: { agents: [AGENT] } });
  });

  await page.route('**/api/optimize/history', async (route) => {
    await route.fulfill({ json: [] });
  });

  await page.route('**/api/optimize/pending', async (route) => {
    await route.fulfill({ json: [PENDING_REVIEW] });
  });

  await page.route('**/api/changes/audit-summary', async (route) => {
    await route.fulfill({
      json: {
        total_changes: 1,
        accepted: 0,
        rejected: 0,
        pending: 1,
        accept_rate: 0,
        top_rejection_reasons: [],
        avg_improvement_accepted: 0,
        gates_failure_breakdown: {},
      },
    });
  });

  await page.route('**/api/changes?*', async (route) => {
    await route.fulfill({ json: { cards: [CHANGE_CARD], count: 1 } });
  });

  await page.route('**/api/changes/card-001/audit', async (route) => {
    await route.fulfill({
      json: {
        card_id: 'card-001',
        status: 'pending',
        dimension_breakdown: {},
        gate_results: [],
        adversarial_results: {},
        composite_breakdown: {},
        timeline: [],
      },
    });
  });

  await page.route('**/api/experiments?*', async (route) => {
    await route.fulfill({ json: { experiments: [], count: 0 } });
  });

  await page.route('**/api/config/list', async (route) => {
    await route.fulfill({ json: { versions: [], active_version: null, canary_version: null } });
  });

  await page.route('**/api/health', async (route) => {
    await route.fulfill({ json: { mock_mode: false, mock_reasons: [], real_provider_configured: true } });
  });
}

test('operator can carry opportunity context into optimize and inspect review evidence', async ({ page }) => {
  await mockOptimizeImprovementApis(page);

  await page.goto(`${BASE_URL}/improvements`);
  await expect(page.getByRole('heading', { name: 'Improvements', level: 2 })).toBeVisible();

  await page.getByRole('button', { name: 'Optimize this' }).click();
  await expect(page).toHaveURL(/\/optimize\?.*force=1/);
  await expect(page).toHaveURL(/opportunity_id=opp-routing/);
  await expect(page.getByLabel('Objective')).toHaveValue('Improve routing failure for agents.root');

  await expect(page.getByText('Evidence from eval eval-run-1234')).toBeVisible();
  await expect(page.getByText('4 failed of 12 cases')).toBeVisible();
  await expect(page.getByText('routing error (4)')).toBeVisible();
  await expect(page.getByText(/Route this billing escalation safely/)).toBeVisible();

  await page.goto(`${BASE_URL}/improvements?tab=review`);
  await page.getByRole('button', { name: /Strengthen root prompt/ }).click();

  await expect(page.getByText('Candidate handoff')).toBeVisible();
  await expect(page.getByText('Candidate v12')).toBeVisible();
  await expect(page.getByText('/workspace/.agentlab/configs/v012.yaml')).toBeVisible();
  await expect(page.getByText('/workspace/.agentlab/evals/run-123.json')).toBeVisible();
  await expect(page.getByText('Experiment exp-001')).toBeVisible();
});
