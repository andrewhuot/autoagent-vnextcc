import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Deploy } from './Deploy';

const apiMocks = vi.hoisted(() => ({
  useDeployStatus: vi.fn(),
  useConfigs: vi.fn(),
  useDeploy: vi.fn(),
  usePromoteCanary: vi.fn(),
  useRollback: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useDeployStatus: apiMocks.useDeployStatus,
  useConfigs: apiMocks.useConfigs,
  useDeploy: apiMocks.useDeploy,
  usePromoteCanary: apiMocks.usePromoteCanary,
  useRollback: apiMocks.useRollback,
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/deploy']}>
      <Deploy />
    </MemoryRouter>
  );
}

describe('Deploy', () => {
  beforeEach(() => {
    apiMocks.useDeployStatus.mockReturnValue({
      data: {
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
          started_at: '2026-03-29T12:00:00Z',
          verdict: 'pending',
        },
        history: [],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    apiMocks.useConfigs.mockReturnValue({
      data: [
        {
          version: 9,
          config_hash: 'cfg-9',
          filename: 'v9.yaml',
          timestamp: '2026-03-29T12:00:00Z',
          status: 'candidate',
          composite_score: 88.1,
        },
      ],
    });
    apiMocks.useDeploy.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.usePromoteCanary.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.useRollback.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
  });

  it('requires confirmation before rolling back a canary', async () => {
    const user = userEvent.setup();
    const rollbackMutate = vi.fn();
    apiMocks.useRollback.mockReturnValue({
      mutate: rollbackMutate,
      isPending: false,
    });

    renderPage();

    await user.click(screen.getByRole('button', { name: 'Rollback' }));

    expect(rollbackMutate).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: 'Confirm rollback' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Confirm rollback' }));

    expect(rollbackMutate).toHaveBeenCalledTimes(1);
  });

  it('requires confirmation before promoting a canary', async () => {
    const user = userEvent.setup();
    const promoteMutate = vi.fn();
    apiMocks.usePromoteCanary.mockReturnValue({
      mutate: promoteMutate,
      isPending: false,
    });

    renderPage();

    await user.click(screen.getByRole('button', { name: 'Promote' }));

    expect(promoteMutate).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: 'Confirm canary promotion' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Confirm promote' }));

    expect(promoteMutate).toHaveBeenCalledWith(
      { version: 8 },
      expect.any(Object)
    );
  });

  it('requires confirmation before an immediate deploy', async () => {
    const user = userEvent.setup();
    const deployMutate = vi.fn();
    apiMocks.useDeploy.mockReturnValue({
      mutate: deployMutate,
      isPending: false,
    });

    renderPage();

    await user.click(screen.getByRole('button', { name: 'Deploy Version' }));
    const comboboxes = screen.getAllByRole('combobox');
    await user.selectOptions(comboboxes[0], '9');
    await user.selectOptions(comboboxes[1], 'immediate');
    await user.click(screen.getByRole('button', { name: 'Deploy' }));

    expect(deployMutate).not.toHaveBeenCalled();
    expect(screen.getByText('Confirm immediate deploy')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Confirm deploy' }));

    expect(deployMutate).toHaveBeenCalledWith(
      { version: 9, strategy: 'immediate' },
      expect.any(Object)
    );
  });
});
