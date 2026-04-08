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
  overall_score: 72,
  verdict: 'partial',
  surfaces: [
    { name: 'instructions', status: 'full', detail: 'System prompt imported', item_count: 1, optimizable_count: 1 },
    { name: 'tools', status: 'partial', detail: '2 of 3 tools optimizable', item_count: 3, optimizable_count: 2 },
    { name: 'callbacks', status: 'unsupported', detail: 'Custom callbacks not supported' },
  ],
  warnings: [
    { severity: 'warning', category: 'code_tools', message: 'One tool has opaque code', recommendation: 'Review tool code manually' },
  ],
  topology: { node_count: 3, edge_count: 2, max_depth: 2, has_cycles: false, callback_count: 1, code_tool_count: 1 },
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

  it('renders readiness report when portability data is present', async () => {
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

    // Readiness report should be visible
    expect(screen.getByTestId('readiness-report')).toBeInTheDocument();
    expect(screen.getByTestId('score-ring')).toBeInTheDocument();
    expect(screen.getAllByText(/72%/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Imported with gaps — review before optimizing')).toBeInTheDocument();

    // Surface table
    expect(screen.getByText('instructions')).toBeInTheDocument();
    expect(screen.getByText('callbacks')).toBeInTheDocument();

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
