import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { Connect } from './Connect';

const apiMocks = vi.hoisted(() => ({
  useConnectImport: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useConnectImport: apiMocks.useConnectImport,
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/connect']}>
      <Connect />
    </MemoryRouter>
  );
}

describe('Connect', () => {
  beforeEach(() => {
    apiMocks.useConnectImport.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      data: null,
    });
  });

  it('creates a transcript workspace and shows next-step actions after success', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn(
      (
        _payload: {
          adapter: 'transcript';
          file: string;
          workspace_name?: string;
          runtime_mode: 'mock' | 'live' | 'auto';
        },
        options?: { onSuccess?: (value: unknown) => void }
      ) => {
        options?.onSuccess?.({
          adapter: 'transcript',
          agent_name: 'support-transcript',
          workspace_path: '/tmp/support-transcript',
          config_path: '/tmp/support-transcript/configs/v001.yaml',
          eval_path: '/tmp/support-transcript/evals/cases/imported_connect.yaml',
          adapter_config_path: '/tmp/support-transcript/.autoagent/adapter_config.json',
          spec_path: '/tmp/support-transcript/.autoagent/adapter_spec.json',
          traces_path: '/tmp/support-transcript/.autoagent/imported_traces.jsonl',
          tool_count: 2,
          guardrail_count: 1,
          trace_count: 4,
          eval_case_count: 4,
        });
      }
    );

    apiMocks.useConnectImport.mockReturnValue({
      mutate,
      isPending: false,
      data: {
        adapter: 'transcript',
        agent_name: 'support-transcript',
        workspace_path: '/tmp/support-transcript',
        config_path: '/tmp/support-transcript/configs/v001.yaml',
        eval_path: '/tmp/support-transcript/evals/cases/imported_connect.yaml',
        adapter_config_path: '/tmp/support-transcript/.autoagent/adapter_config.json',
        spec_path: '/tmp/support-transcript/.autoagent/adapter_spec.json',
        traces_path: '/tmp/support-transcript/.autoagent/imported_traces.jsonl',
        tool_count: 2,
        guardrail_count: 1,
        trace_count: 4,
        eval_case_count: 4,
      },
    });

    renderPage();

    await user.click(screen.getByRole('button', { name: /transcript/i }));
    await user.type(screen.getByLabelText('Transcript file'), '/tmp/conversations.jsonl');
    await user.type(screen.getByLabelText('Workspace name'), 'support-transcript');
    await user.selectOptions(screen.getByLabelText('Runtime mode'), 'live');
    await user.click(screen.getByRole('button', { name: 'Create workspace' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        adapter: 'transcript',
        file: '/tmp/conversations.jsonl',
        workspace_name: 'support-transcript',
        runtime_mode: 'live',
      },
      expect.objectContaining({
        onSuccess: expect.any(Function),
      })
    );

    expect(screen.getByRole('link', { name: 'Run evaluations' })).toHaveAttribute('href', '/evals');
    expect(screen.getByRole('link', { name: 'Review configs' })).toHaveAttribute('href', '/configs');

    await user.click(screen.getByRole('button', { name: 'Connect another source' }));

    expect(screen.getByRole('button', { name: 'Create workspace' })).toBeInTheDocument();
  });
});
