import type React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  humanizeHttpStatus,
  useApplyCurriculum,
  useCurriculumBatches,
  useGenerateCurriculum,
  useGeneratedSuites,
  useStartEval,
} from './api';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: init?.status ?? 200,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
}

function renderWithClient(component: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(<QueryClientProvider client={queryClient}>{component}</QueryClientProvider>);
}

function StartEvalHarness() {
  const startEval = useStartEval();

  return (
    <button
      type="button"
      onClick={() =>
        startEval.mutate({
          config_path: '/workspace/configs/v002.yaml',
          category: 'safety',
        })
      }
    >
      Start eval
    </button>
  );
}

function GeneratedSuitesHarness() {
  const { data = [], isLoading } = useGeneratedSuites();

  if (isLoading) {
    return <p>Loading suites…</p>;
  }

  return (
    <div>
      <p>Suite count: {data.length}</p>
      {data.map((suite) => (
        <p key={suite.suite_id}>{suite.agent_name}</p>
      ))}
    </div>
  );
}

function CurriculumBatchesHarness() {
  const { data, isLoading } = useCurriculumBatches();

  if (isLoading) {
    return <p>Loading curriculum…</p>;
  }

  const firstBatch = data?.batches[0];
  const firstPoint = data?.progression[0];

  return (
    <div>
      <p>Batch count: {data?.batches.length ?? 0}</p>
      <p>First prompts: {firstBatch?.prompt_count ?? 0}</p>
      <p>First medium: {firstBatch?.difficulty_distribution.medium ?? 0}</p>
      <p>Progression points: {data?.progression.length ?? 0}</p>
      <p>Average difficulty: {(firstPoint?.average_difficulty ?? 0).toFixed(2)}</p>
    </div>
  );
}

function GenerateCurriculumHarness() {
  const generateCurriculum = useGenerateCurriculum();

  return (
    <div>
      <button type="button" onClick={() => generateCurriculum.mutate({})}>
        Generate curriculum
      </button>
      <p>
        {generateCurriculum.data
          ? `${generateCurriculum.data.batch.batch_id}:${generateCurriculum.data.batch.prompt_count}`
          : 'idle'}
      </p>
    </div>
  );
}

function ApplyCurriculumHarness() {
  const applyCurriculum = useApplyCurriculum();

  return (
    <div>
      <button type="button" onClick={() => applyCurriculum.mutate({ batch_id: 'curriculum_live_001' })}>
        Apply curriculum
      </button>
      <p>
        {applyCurriculum.data
          ? `${applyCurriculum.data.batch_id}:${applyCurriculum.data.applied_count}`
          : 'idle'}
      </p>
    </div>
  );
}

describe('eval API hooks', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('useStartEval posts the selected config path to /api/eval/run', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ task_id: 'task-123', message: 'Eval run started' }, { status: 202 }),
    );

    renderWithClient(<StartEvalHarness />);

    await user.click(screen.getByRole('button', { name: 'Start eval' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/eval/run',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          config_path: '/workspace/configs/v002.yaml',
          category: 'safety',
        }),
      }),
    );
  });

  it('useGeneratedSuites loads persisted generated suites from /api/evals/generated', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        suites: [
          {
            suite_id: 'suite_abc123',
            agent_name: 'Checkout Guard',
            source_kind: 'config',
            status: 'accepted',
            mock_mode: true,
            created_at: '2026-04-01T16:00:00Z',
            updated_at: '2026-04-01T16:00:00Z',
            accepted_at: '2026-04-01T16:05:00Z',
            accepted_eval_path: 'evals/cases/generated_suite_abc123.yaml',
            transcript_count: 0,
            category_counts: { safety: 3, performance: 2 },
            case_count: 5,
          },
        ],
        count: 1,
      }),
    );

    renderWithClient(<GeneratedSuitesHarness />);

    expect(await screen.findByText('Suite count: 1')).toBeInTheDocument();
    expect(screen.getByText('Checkout Guard')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/evals/generated?limit=20',
      expect.objectContaining({
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      }),
    );
  });

  it('useCurriculumBatches normalizes live curriculum payloads for Eval Runs', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        batches: [
          {
            batch_id: 'curriculum_live_001',
            generated_at: 1775712608.780701,
            num_prompts: 12,
            tier_distribution: {
              easy: 0,
              medium: 6,
              hard: 0,
              adversarial: 6,
            },
            source_clusters: ['safety_violation', 'timeout'],
          },
        ],
        count: 1,
      }),
    );

    renderWithClient(<CurriculumBatchesHarness />);

    expect(await screen.findByText('Batch count: 1')).toBeInTheDocument();
    expect(screen.getByText('First prompts: 12')).toBeInTheDocument();
    expect(screen.getByText('First medium: 6')).toBeInTheDocument();
    expect(screen.getByText('Progression points: 1')).toBeInTheDocument();
    expect(screen.getByText('Average difficulty: 0.75')).toBeInTheDocument();
  });

  it('useGenerateCurriculum normalizes the flat backend response for the page callback', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        batch_id: 'curriculum_live_001',
        num_prompts: 12,
        tier_distribution: { medium: 6, adversarial: 6 },
      }),
    );

    renderWithClient(<GenerateCurriculumHarness />);

    await user.click(screen.getByRole('button', { name: 'Generate curriculum' }));

    expect(await screen.findByText('curriculum_live_001:12')).toBeInTheDocument();
  });

  it('useApplyCurriculum normalizes num_prompts to applied_count', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        batch_id: 'curriculum_live_001',
        eval_file: 'evals/cases/curriculum_curriculum_live_001.yaml',
        num_prompts: 12,
      }),
    );

    renderWithClient(<ApplyCurriculumHarness />);

    await user.click(screen.getByRole('button', { name: 'Apply curriculum' }));

    expect(await screen.findByText('curriculum_live_001:12')).toBeInTheDocument();
  });
});

describe('humanizeHttpStatus', () => {
  it('returns auth guidance for 401', () => {
    expect(humanizeHttpStatus(401)).toContain('Authentication');
  });

  it('returns auth guidance for 403', () => {
    expect(humanizeHttpStatus(403)).toContain('Authentication');
  });

  it('returns not-found message for 404', () => {
    expect(humanizeHttpStatus(404)).toContain('not found');
  });

  it('returns timeout message for 408', () => {
    expect(humanizeHttpStatus(408)).toContain('timed out');
  });

  it('returns rate-limit message for 429', () => {
    expect(humanizeHttpStatus(429)).toContain('Rate limited');
  });

  it('returns server-unavailable message for 500-range', () => {
    expect(humanizeHttpStatus(500)).toContain('temporarily unavailable');
    expect(humanizeHttpStatus(502)).toContain('temporarily unavailable');
    expect(humanizeHttpStatus(503)).toContain('temporarily unavailable');
  });

  it('returns generic fallback for unknown codes', () => {
    expect(humanizeHttpStatus(418)).toContain('Something went wrong');
  });
});
