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
  platform: 'cx',
  source: 'cx-import',
  summary: {
    total_surfaces: 3,
    imported_surfaces: 3,
    optimizable_surfaces: 2,
    read_only_surfaces: 1,
    unsupported_surfaces: 0,
    supported_parity_surfaces: 2,
    partial_parity_surfaces: 0,
    read_only_parity_surfaces: 1,
    unsupported_parity_surfaces: 0,
    ready_export_surfaces: 2,
    lossy_export_surfaces: 1,
    blocked_export_surfaces: 0,
  },
  surfaces: [
    {
      surface_id: 'playbooks',
      label: 'Playbooks',
      coverage_status: 'imported',
      parity_status: 'supported',
      portability_status: 'optimizable',
      export_status: 'ready',
      optimization_surface_id: 'playbooks',
      rationale: ['All playbooks imported'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: { item_count: 4, optimizable_count: 4 },
    },
    {
      surface_id: 'intents',
      label: 'Intents',
      coverage_status: 'imported',
      parity_status: 'supported',
      portability_status: 'optimizable',
      export_status: 'ready',
      optimization_surface_id: 'intents',
      rationale: ['All intents imported'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: { item_count: 12, optimizable_count: 12 },
    },
    {
      surface_id: 'webhooks',
      label: 'Webhooks',
      coverage_status: 'imported',
      parity_status: 'read_only',
      portability_status: 'read_only',
      export_status: 'lossy',
      optimization_surface_id: 'webhooks',
      rationale: ['Webhook code is external'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: { item_count: 2 },
    },
  ],
  callbacks: [],
  topology: {
    nodes: [],
    edges: [],
    summary: {
      node_count: 8,
      edge_count: 7,
      max_depth: 3,
      agent_count: 1,
      tool_count: 0,
      callback_count: 0,
      flow_count: 2,
      page_count: 8,
      intent_count: 12,
      webhook_count: 2,
      test_case_count: 24,
      orchestration_modes: ['flow'],
    },
  },
  optimization_eligibility: {
    score: 85,
    coverage_score: 88,
    optimizability_score: 85,
    export_score: 78,
    blockers: [],
    rationale: ['Most CX surfaces are portable.'],
  },
  export_matrix: {
    status: 'lossy',
    round_trip_ready: false,
    ready_surfaces: ['playbooks', 'intents'],
    lossy_surfaces: ['webhooks'],
    blocked_surfaces: [],
    surfaces: [],
    rationale: ['Webhook code remains read-only.'],
  },
  notes: [],
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

  it('renders readiness report when CX portability_report data is present', async () => {
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
          portability_report: CX_PORTABILITY,
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
        portability_report: CX_PORTABILITY,
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
    expect(screen.getByText('Playbooks')).toBeInTheDocument();
    expect(screen.getByText('Webhooks')).toBeInTheDocument();

    // Readiness report provides its own next-step links
    const evalLinks = screen.getAllByText('Run evaluations');
    expect(evalLinks.length).toBeGreaterThanOrEqual(1);
  });

  it('falls back to the legacy portability alias when portability_report is absent', async () => {
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

    expect(screen.getByTestId('readiness-report')).toBeInTheDocument();
  });
});
