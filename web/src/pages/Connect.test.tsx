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

function installLocalStorageMock(initial: Record<string, string> = {}) {
  const store = { ...initial };
  const localStorageMock = {
    getItem: vi.fn((key: string) => (key in store ? store[key] : null)),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      Object.keys(store).forEach((key) => delete store[key]);
    }),
    key: vi.fn(),
    get length() {
      return Object.keys(store).length;
    },
  };

  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: localStorageMock,
  });

  return { store, localStorageMock };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/connect']}>
      <Connect />
    </MemoryRouter>
  );
}

describe('Connect', () => {
  beforeEach(() => {
    installLocalStorageMock();
    apiMocks.useConnectImport.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      data: null,
    });
  });

  it('shows CX Agent Studio and Google ADK as the primary simple-mode options', () => {
    renderPage();

    expect(screen.getByRole('link', { name: /import from cx agent studio/i })).toHaveAttribute(
      'href',
      '/cx/studio'
    );
    expect(screen.getByRole('link', { name: /import from google adk/i })).toHaveAttribute(
      'href',
      '/adk/import'
    );
    expect(
      screen.queryByRole('button', { name: /^openai agents$/i })
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /more adapters/i })).toBeInTheDocument();
  });

  it('shows the full adapter grid in pro mode without the simple-mode toggle', () => {
    installLocalStorageMock({ 'agentlab-sidebar-mode': 'pro' });

    renderPage();

    expect(screen.getByRole('link', { name: /import from cx agent studio/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /import from google adk/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^openai agents$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^anthropic claude$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^http webhook$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^transcript import$/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /more adapters/i })).not.toBeInTheDocument();
  });

  it('creates a transcript workspace from the secondary adapters section and shows next-step actions after success', async () => {
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
          adapter_config_path: '/tmp/support-transcript/.agentlab/adapter_config.json',
          spec_path: '/tmp/support-transcript/.agentlab/adapter_spec.json',
          traces_path: '/tmp/support-transcript/.agentlab/imported_traces.jsonl',
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
        adapter_config_path: '/tmp/support-transcript/.agentlab/adapter_config.json',
        spec_path: '/tmp/support-transcript/.agentlab/adapter_spec.json',
        traces_path: '/tmp/support-transcript/.agentlab/imported_traces.jsonl',
        tool_count: 2,
        guardrail_count: 1,
        trace_count: 4,
        eval_case_count: 4,
      },
    });

    renderPage();

    await user.click(screen.getByRole('button', { name: /more adapters/i }));
    await user.click(screen.getByRole('button', { name: /^transcript import$/i }));
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

    expect(screen.getByRole('button', { name: /more adapters/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create workspace' })).not.toBeInTheDocument();
  });
});
