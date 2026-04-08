import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CxImport } from './CxImport';
import type { PortabilityReport } from '../lib/types';

const apiMocks = vi.hoisted(() => ({
  useCxAgents: vi.fn(),
  useCxImport: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useCxAgents: apiMocks.useCxAgents,
  useCxImport: apiMocks.useCxImport,
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cx/import']}>
      <CxImport />
    </MemoryRouter>
  );
}

const CX_PORTABILITY: PortabilityReport = {
  overall_score: 85,
  verdict: 'ready',
  surfaces: [
    { name: 'playbooks', status: 'full', detail: 'All playbooks imported', item_count: 4, optimizable_count: 4 },
    { name: 'intents', status: 'full', detail: 'All intents imported', item_count: 12, optimizable_count: 12 },
    { name: 'webhooks', status: 'read_only', detail: 'Webhook code is external', item_count: 2 },
  ],
  warnings: [],
};

describe('CxImport', () => {
  beforeEach(() => {
    apiMocks.useCxAgents.mockReturnValue({
      data: [
        {
          name: 'projects/demo/agents/support-bot',
          display_name: 'Support Bot',
          description: 'Primary support entry point',
          default_language_code: 'en',
        },
      ],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    apiMocks.useCxImport.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      data: null,
    });
  });

  it('shows next-step actions after a successful import and lets the user start over', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn(
      (
        _payload: { project: string; location: string; agent_id: string },
        options?: { onSuccess?: (value: unknown) => void }
      ) => {
        options?.onSuccess?.({
          agent_name: 'Support Bot',
          config_path: 'configs/support.yaml',
          eval_path: 'evals/support.jsonl',
          test_cases_imported: 24,
          snapshot_path: '.agentlab/support.snapshot.json',
          surfaces_mapped: ['instructions', 'tools'],
        });
      }
    );

    apiMocks.useCxImport.mockReturnValue({
      mutate,
      isPending: false,
      data: {
        agent_name: 'Support Bot',
        config_path: 'configs/support.yaml',
        eval_path: 'evals/support.jsonl',
        test_cases_imported: 24,
        snapshot_path: '.agentlab/support.snapshot.json',
        surfaces_mapped: ['instructions', 'tools'],
      },
    });

    renderPage();

    await user.type(screen.getByLabelText('GCP project ID'), 'demo-project');
    await user.click(screen.getByRole('button', { name: 'List Agents' }));
    await user.click(screen.getByRole('button', { name: /Support Bot/i }));
    await user.click(screen.getByRole('button', { name: 'Import Agent' }));

    expect(screen.getByRole('link', { name: 'Run evaluations' })).toHaveAttribute('href', '/evals');
    expect(screen.getByRole('link', { name: 'Review configs' })).toHaveAttribute('href', '/configs');

    await user.click(screen.getByRole('button', { name: 'Import another agent' }));

    expect(screen.getByRole('button', { name: 'List Agents' })).toBeInTheDocument();
  });

  it('renders readiness report when CX portability data is present', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn(
      (
        _payload: { project: string; location: string; agent_id: string },
        options?: { onSuccess?: (value: unknown) => void }
      ) => {
        options?.onSuccess?.({
          agent_name: 'Support Bot',
          config_path: 'configs/support.yaml',
          eval_path: 'evals/support.jsonl',
          test_cases_imported: 24,
          snapshot_path: '.agentlab/support.snapshot.json',
          surfaces_mapped: ['playbooks', 'intents', 'webhooks'],
          portability: CX_PORTABILITY,
        });
      }
    );

    apiMocks.useCxImport.mockReturnValue({
      mutate,
      isPending: false,
      data: {
        agent_name: 'Support Bot',
        config_path: 'configs/support.yaml',
        eval_path: 'evals/support.jsonl',
        test_cases_imported: 24,
        snapshot_path: '.agentlab/support.snapshot.json',
        surfaces_mapped: ['playbooks', 'intents', 'webhooks'],
        portability: CX_PORTABILITY,
      },
    });

    renderPage();

    await user.type(screen.getByLabelText('GCP project ID'), 'demo-project');
    await user.click(screen.getByRole('button', { name: 'List Agents' }));
    await user.click(screen.getByRole('button', { name: /Support Bot/i }));
    await user.click(screen.getByRole('button', { name: 'Import Agent' }));

    // Readiness report visible
    expect(screen.getByTestId('readiness-report')).toBeInTheDocument();
    expect(screen.getAllByText(/85%/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Ready for optimization')).toBeInTheDocument();

    // Surface details
    expect(screen.getByText('playbooks')).toBeInTheDocument();
    expect(screen.getByText('webhooks')).toBeInTheDocument();

    // Readiness report provides its own next-step links
    const evalLinks = screen.getAllByText('Run evaluations');
    expect(evalLinks.length).toBeGreaterThanOrEqual(1);
  });
});
