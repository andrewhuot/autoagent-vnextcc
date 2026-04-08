import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AdkImport } from './AdkImport';
import type { PortabilityReport } from '../lib/types';

const apiMocks = vi.hoisted(() => ({
  useAdkStatus: vi.fn(),
  useAdkImport: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useAdkStatus: apiMocks.useAdkStatus,
  useAdkImport: apiMocks.useAdkImport,
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/adk/import']}>
      <AdkImport />
    </MemoryRouter>
  );
}

const SAMPLE_PORTABILITY: PortabilityReport = {
  platform: 'adk',
  source: 'adk-import',
  summary: {
    total_surfaces: 3,
    imported_surfaces: 3,
    optimizable_surfaces: 2,
    read_only_surfaces: 0,
    unsupported_surfaces: 1,
    supported_parity_surfaces: 1,
    partial_parity_surfaces: 1,
    read_only_parity_surfaces: 0,
    unsupported_parity_surfaces: 1,
    ready_export_surfaces: 1,
    lossy_export_surfaces: 1,
    blocked_export_surfaces: 1,
  },
  surfaces: [
    {
      surface_id: 'instructions',
      label: 'Instructions',
      coverage_status: 'imported',
      parity_status: 'supported',
      portability_status: 'optimizable',
      export_status: 'ready',
      optimization_surface_id: 'instructions',
      rationale: ['System prompt imported'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: { item_count: 1, optimizable_count: 1 },
    },
    {
      surface_id: 'tools',
      label: 'Tools',
      coverage_status: 'partial',
      parity_status: 'partial',
      portability_status: 'optimizable',
      export_status: 'lossy',
      optimization_surface_id: 'tools',
      rationale: ['2 of 3 tools optimizable'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: { item_count: 3, optimizable_count: 2, opaque_code_tool_count: 1 },
    },
    {
      surface_id: 'callbacks',
      label: 'Callbacks',
      coverage_status: 'missing',
      parity_status: 'unsupported',
      portability_status: 'unsupported',
      export_status: 'blocked',
      optimization_surface_id: 'callbacks',
      rationale: ['Custom callbacks not supported'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: {},
    },
  ],
  callbacks: [
    {
      name: 'before_model',
      binding: 'agent.before_model',
      stage: 'before_model',
      source_ref: 'agent.py:12',
      portability_status: 'unsupported',
      export_status: 'blocked',
      rationale: ['Custom callbacks not supported'],
      metadata: {},
    },
  ],
  topology: {
    nodes: [],
    edges: [],
    summary: {
      node_count: 3,
      edge_count: 2,
      max_depth: 2,
      agent_count: 2,
      tool_count: 3,
      callback_count: 1,
      flow_count: 0,
      page_count: 0,
      intent_count: 0,
      webhook_count: 0,
      test_case_count: 0,
      orchestration_modes: ['router'],
    },
  },
  optimization_eligibility: {
    score: 72,
    coverage_score: 75,
    optimizability_score: 72,
    export_score: 55,
    blockers: ['Export may lose callback wiring'],
    rationale: ['Partially portable agent.'],
  },
  export_matrix: {
    status: 'lossy',
    round_trip_ready: false,
    ready_surfaces: ['instructions'],
    lossy_surfaces: ['tools'],
    blocked_surfaces: ['callbacks'],
    surfaces: [],
    rationale: ['Callback wiring blocks full round-trip.'],
  },
  notes: ['One tool has opaque code'],
};

describe('AdkImport', () => {
  beforeEach(() => {
    apiMocks.useAdkStatus.mockReturnValue({
      data: {
        agent: {
          name: 'order_router',
          model: 'gpt-5-mini',
          tools: [{ name: 'lookup_order', description: 'Fetch order details' }],
          sub_agents: [{ name: 'billing', tools: [] }],
        },
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    apiMocks.useAdkImport.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      data: null,
    });
  });

  it('shows next-step actions after a successful ADK import and lets the user reset the flow', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn(
      (
        _payload: { path: string; output_dir?: string },
        options?: { onSuccess?: (value: unknown) => void }
      ) => {
        options?.onSuccess?.({
          agent_name: 'order_router',
          config_path: 'configs/order_router.yaml',
          snapshot_path: '.agentlab/order_router.snapshot.json',
          tools_imported: 3,
          surfaces_mapped: ['instructions', 'tools'],
        });
      }
    );

    apiMocks.useAdkImport.mockReturnValue({
      mutate,
      isPending: false,
      data: {
        agent_name: 'order_router',
        config_path: 'configs/order_router.yaml',
        snapshot_path: '.agentlab/order_router.snapshot.json',
        tools_imported: 3,
        surfaces_mapped: ['instructions', 'tools'],
      },
    });

    renderPage();

    await user.type(screen.getByLabelText('Agent directory'), '/tmp/order_router');
    await user.click(screen.getByRole('button', { name: 'Parse Agent' }));
    await user.click(screen.getByRole('button', { name: 'Import Agent' }));

    expect(screen.getByRole('link', { name: 'Run evaluations' })).toHaveAttribute('href', '/evals');
    expect(screen.getByRole('link', { name: 'Review configs' })).toHaveAttribute('href', '/configs');

    await user.click(screen.getByRole('button', { name: 'Import another agent' }));

    expect(screen.getByRole('button', { name: 'Parse Agent' })).toBeInTheDocument();
  });

  it('renders readiness report when backend portability_report data is present', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn(
      (
        _payload: { path: string; output_dir?: string },
        options?: { onSuccess?: (value: unknown) => void }
      ) => {
        options?.onSuccess?.({
          agent_name: 'order_router',
          config_path: 'configs/order_router.yaml',
          snapshot_path: '.agentlab/order_router.snapshot.json',
          tools_imported: 3,
          surfaces_mapped: ['instructions', 'tools'],
          portability_report: SAMPLE_PORTABILITY,
        });
      }
    );

    apiMocks.useAdkImport.mockReturnValue({
      mutate,
      isPending: false,
      data: {
        agent_name: 'order_router',
        config_path: 'configs/order_router.yaml',
        snapshot_path: '.agentlab/order_router.snapshot.json',
        tools_imported: 3,
        surfaces_mapped: ['instructions', 'tools'],
        portability_report: SAMPLE_PORTABILITY,
      },
    });

    renderPage();

    await user.type(screen.getByLabelText('Agent directory'), '/tmp/order_router');
    await user.click(screen.getByRole('button', { name: 'Parse Agent' }));
    await user.click(screen.getByRole('button', { name: 'Import Agent' }));

    // Readiness report should be visible
    expect(screen.getByTestId('readiness-report')).toBeInTheDocument();
    expect(screen.getByTestId('score-ring')).toBeInTheDocument();
    expect(screen.getAllByText(/72%/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Imported with gaps — review before optimizing')).toBeInTheDocument();

    // Surface table
    expect(screen.getByText('Instructions')).toBeInTheDocument();
    expect(screen.getByText('Callbacks')).toBeInTheDocument();

    // Topology
    expect(screen.getByText('Agent Topology')).toBeInTheDocument();
    expect(screen.getByText('1 callback')).toBeInTheDocument();
    expect(screen.getByText('1 code tool (opaque)')).toBeInTheDocument();

    // Warning
    expect(screen.getByText('One tool has opaque code')).toBeInTheDocument();

    // Readiness report provides its own next-step links
    const evalLinks = screen.getAllByText('Run evaluations');
    expect(evalLinks.length).toBeGreaterThanOrEqual(1);
  });

  it('falls back to the legacy portability alias when the new field is absent', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn(
      (
        _payload: { path: string; output_dir?: string },
        options?: { onSuccess?: (value: unknown) => void }
      ) => {
        options?.onSuccess?.({
          agent_name: 'order_router',
          config_path: 'configs/order_router.yaml',
          snapshot_path: '.agentlab/order_router.snapshot.json',
          tools_imported: 3,
          surfaces_mapped: ['instructions', 'tools'],
          portability: SAMPLE_PORTABILITY,
        });
      }
    );

    apiMocks.useAdkImport.mockReturnValue({
      mutate,
      isPending: false,
      data: {
        agent_name: 'order_router',
        config_path: 'configs/order_router.yaml',
        snapshot_path: '.agentlab/order_router.snapshot.json',
        tools_imported: 3,
        surfaces_mapped: ['instructions', 'tools'],
        portability: SAMPLE_PORTABILITY,
      },
    });

    renderPage();

    await user.type(screen.getByLabelText('Agent directory'), '/tmp/order_router');
    await user.click(screen.getByRole('button', { name: 'Parse Agent' }));
    await user.click(screen.getByRole('button', { name: 'Import Agent' }));

    expect(screen.getByTestId('readiness-report')).toBeInTheDocument();
  });

  it('shows fallback import summary when portability is absent', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn(
      (
        _payload: { path: string; output_dir?: string },
        options?: { onSuccess?: (value: unknown) => void }
      ) => {
        options?.onSuccess?.({
          agent_name: 'order_router',
          config_path: 'configs/order_router.yaml',
          snapshot_path: '.agentlab/order_router.snapshot.json',
          tools_imported: 3,
          surfaces_mapped: ['instructions', 'tools'],
        });
      }
    );

    apiMocks.useAdkImport.mockReturnValue({
      mutate,
      isPending: false,
      data: {
        agent_name: 'order_router',
        config_path: 'configs/order_router.yaml',
        snapshot_path: '.agentlab/order_router.snapshot.json',
        tools_imported: 3,
        surfaces_mapped: ['instructions', 'tools'],
      },
    });

    renderPage();

    await user.type(screen.getByLabelText('Agent directory'), '/tmp/order_router');
    await user.click(screen.getByRole('button', { name: 'Parse Agent' }));
    await user.click(screen.getByRole('button', { name: 'Import Agent' }));

    // Should show fallback
    expect(screen.getByText('Import Summary')).toBeInTheDocument();
    expect(screen.getByText(/Detailed readiness analysis is not yet available/)).toBeInTheDocument();
  });
});
