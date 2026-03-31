import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CXStudio } from './CXStudio';

const apiMocks = vi.hoisted(() => ({
  useConfigs: vi.fn(),
  useConfigShow: vi.fn(),
  useCxAgents: vi.fn(),
  useCxAuth: vi.fn(),
  useCxImport: vi.fn(),
  useCxDiff: vi.fn(),
  useCxExport: vi.fn(),
  useCxSync: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useConfigs: apiMocks.useConfigs,
  useConfigShow: apiMocks.useConfigShow,
  useCxAgents: apiMocks.useCxAgents,
  useCxAuth: apiMocks.useCxAuth,
  useCxImport: apiMocks.useCxImport,
  useCxDiff: apiMocks.useCxDiff,
  useCxExport: apiMocks.useCxExport,
  useCxSync: apiMocks.useCxSync,
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cx/studio']}>
      <CXStudio />
    </MemoryRouter>
  );
}

describe('CXStudio', () => {
  beforeEach(() => {
    apiMocks.useConfigs.mockReturnValue({
      data: [{ version: 4, status: 'active', timestamp: 'now', filename: 'v004.yaml', config_hash: 'abc', composite_score: null }],
    });
    apiMocks.useConfigShow.mockReturnValue({
      data: { version: 4, yaml_content: 'prompts:\n  root: hello', config: { prompts: { root: 'hello' } } },
      isLoading: false,
    });
    apiMocks.useCxAgents.mockReturnValue({
      data: [
        {
          name: 'projects/demo-project/locations/us-central1/agents/support-bot',
          display_name: 'Support Bot',
          description: 'Primary support agent',
          default_language_code: 'en',
        },
      ],
      isLoading: false,
      refetch: vi.fn(),
    });
    apiMocks.useCxAuth.mockReturnValue({
      mutate: vi.fn(),
      data: null,
    });
    apiMocks.useCxExport.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.useCxSync.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
  });

  it('imports a selected agent and renders diff conflicts', async () => {
    const user = userEvent.setup();

    apiMocks.useCxImport.mockReturnValue({
      mutate: vi.fn((_payload, options?: { onSuccess?: (result: unknown) => void }) => {
        options?.onSuccess?.({
          agent_name: 'Support Bot',
          config_path: 'workspace/configs/v001.yaml',
          eval_path: 'workspace/evals/cases/imported_connect.yaml',
          snapshot_path: 'workspace/.autoagent/cx/snapshot.json',
          surfaces_mapped: ['prompts', 'flows', 'intents'],
          test_cases_imported: 3,
          workspace_path: 'workspace',
        });
      }),
      isPending: false,
    });

    apiMocks.useCxDiff.mockReturnValue({
      mutate: vi.fn((_payload, options?: { onSuccess?: (result: unknown) => void }) => {
        options?.onSuccess?.({
          changes: [{ resource: 'playbook', action: 'update', name: 'Escalation', field: 'instruction' }],
          pushed: false,
          resources_updated: 0,
          conflicts: [{ resource: 'playbook', name: 'Escalation', field: 'instruction' }],
        });
      }),
      isPending: false,
    });

    renderPage();

    await user.type(screen.getByLabelText('GCP project ID'), 'demo-project');
    await user.click(screen.getByRole('button', { name: /Support Bot/i }));
    await user.click(screen.getByRole('button', { name: 'Import agent' }));

    expect(screen.getByText('workspace')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Diff vs remote' }));

    expect(screen.getByText('UPDATE playbook')).toBeInTheDocument();
    expect(screen.getByText('playbook · Escalation')).toBeInTheDocument();
  });
});
