import type React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useGeneratedSuites, useStartEval } from './api';

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
});
