import { describe, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Configs } from './Configs';

const apiMocks = vi.hoisted(() => ({
  useActivateConfig: vi.fn(),
  useConfigs: vi.fn(),
  useConfigShow: vi.fn(),
  useConfigDiff: vi.fn(),
  useImportConfig: vi.fn(),
  useMigrateConfig: vi.fn(),
  useNaturalLanguageConfigEdit: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useActivateConfig: apiMocks.useActivateConfig,
  useConfigs: apiMocks.useConfigs,
  useConfigShow: apiMocks.useConfigShow,
  useConfigDiff: apiMocks.useConfigDiff,
  useImportConfig: apiMocks.useImportConfig,
  useMigrateConfig: apiMocks.useMigrateConfig,
  useNaturalLanguageConfigEdit: apiMocks.useNaturalLanguageConfigEdit,
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <Configs />
    </MemoryRouter>
  );
}

describe('Configs', () => {
  beforeEach(() => {
    apiMocks.useConfigs.mockReturnValue({
      data: [
        {
          version: 9,
          config_hash: 'cfg-9',
          filename: 'v9.yaml',
          timestamp: '2026-03-29T12:00:00Z',
          status: 'active',
          composite_score: 88.1,
        },
        {
          version: 8,
          config_hash: 'cfg-8',
          filename: 'v8.yaml',
          timestamp: '2026-03-28T12:00:00Z',
          status: 'archived',
          composite_score: 82.4,
        },
      ],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    apiMocks.useConfigShow.mockReturnValue({ data: null, isLoading: false });
    apiMocks.useConfigDiff.mockReturnValue({ data: null, isLoading: false });
    apiMocks.useActivateConfig.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useImportConfig.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useMigrateConfig.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useNaturalLanguageConfigEdit.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
  });

  it('shows compare guidance before both versions are selected', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Compare Versions' }));

    expect(
      screen.getByText('Select two versions to compare YAML changes side by side.')
    ).toBeInTheDocument();
  });

  it('lets the user preview a natural-language edit before applying it', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((payload: { description: string; dry_run: boolean }, options?: { onSuccess?: (value: unknown) => void }) => {
      if (payload.dry_run) {
        options?.onSuccess?.({
          intent: {
            description: payload.description,
            target_surfaces: ['router.timeout_seconds'],
            change_type: 'config_patch',
            constraints: ['preserve safety gates'],
          },
          diff: '- timeout_seconds: 6\n+ timeout_seconds: 4',
          score_before: 0.62,
          score_after: 0.71,
          applied: false,
          accepted: true,
          dry_run: true,
          scores: {
            quality: 0.71,
            safety: 0.99,
            latency: 0.83,
            cost: 0.9,
            composite: 0.71,
          },
          attempt: null,
        });
        return;
      }

      options?.onSuccess?.({
        intent: {
          description: payload.description,
          target_surfaces: ['router.timeout_seconds'],
          change_type: 'config_patch',
          constraints: ['preserve safety gates'],
        },
        diff: '- timeout_seconds: 6\n+ timeout_seconds: 4',
        score_before: 0.62,
        score_after: 0.71,
        applied: true,
        accepted: true,
        dry_run: false,
        scores: {
          quality: 0.71,
          safety: 0.99,
          latency: 0.83,
          cost: 0.9,
          composite: 0.71,
        },
        attempt: {
          attempt_id: 'abcd1234',
          status: 'accepted',
          score_before: 0.62,
          score_after: 0.71,
        },
      });
    });

    apiMocks.useNaturalLanguageConfigEdit.mockReturnValue({
      mutate,
      isPending: false,
    });

    renderPage();

    await user.type(
      screen.getByLabelText('Describe config change'),
      'Reduce timeout_seconds from six to four for faster retries.'
    );
    await user.click(screen.getByRole('button', { name: 'Preview edit' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        description: 'Reduce timeout_seconds from six to four for faster retries.',
        dry_run: true,
      },
      expect.any(Object)
    );
    expect(screen.getByText('router.timeout_seconds')).toBeInTheDocument();
    expect(screen.getByText(/timeout_seconds: 6/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Apply previewed edit' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        description: 'Reduce timeout_seconds from six to four for faster retries.',
        dry_run: false,
      },
      expect.any(Object)
    );
  });
});
